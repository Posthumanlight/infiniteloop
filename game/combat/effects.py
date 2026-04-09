from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from game.character.base_entity import BaseEntity
from game.combat.models import CombatState, DamageResult, HitResult
from game.core.data_loader import load_effect
from game.core.dice import SeededRNG
from game.core.enums import DamageType, EffectActionType, TriggerType
from game.core.formula_eval import ExprContext, evaluate_expr


# ---------------------------------------------------------------------------
# StatusEffectInstance — lives on BaseEntity.active_effects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusEffectInstance:
    effect_id: str
    source_id: str
    remaining_duration: int
    stack_count: int = 1


# ---------------------------------------------------------------------------
# Expression context builder
# ---------------------------------------------------------------------------

def build_expr_context(entity: BaseEntity) -> ExprContext:
    return ExprContext(
        attack=entity.major_stats.attack,
        hp=entity.major_stats.hp,
        current_hp=entity.current_hp,
        speed=entity.major_stats.speed,
        crit_chance=entity.major_stats.crit_chance,
        crit_dmg=entity.major_stats.crit_dmg,
        resistance=entity.major_stats.resistance,
        energy=entity.major_stats.energy,
        mastery=entity.major_stats.mastery,
    )


# ---------------------------------------------------------------------------
# Damage type numeric helpers (for condition expressions)
# ---------------------------------------------------------------------------

_DAMAGE_TYPE_NUMERIC: dict[DamageType, int] = {
    DamageType.SLASHING: 1,
    DamageType.PIERCING: 2,
    DamageType.ARCANE: 3,
    DamageType.FIRE: 4,
    DamageType.ICE: 5,
}


def _damage_type_to_numeric(dt: DamageType | None) -> int:
    if dt is None:
        return 0
    return _DAMAGE_TYPE_NUMERIC[dt]


def _build_damage_type_constants() -> dict[str, int]:
    return {dt.name: _damage_type_to_numeric(dt) for dt in DamageType}


# ---------------------------------------------------------------------------
# Condition evaluation
# ---------------------------------------------------------------------------

def _check_condition(
    condition: str | None,
    entity: BaseEntity,
    extra_ctx: dict[str, Any] | None = None,
) -> bool:
    if not condition:
        return True
    ctx: dict[str, Any] = {
        "target": build_expr_context(entity),
        **_build_damage_type_constants(),
        **(extra_ctx or {}),
    }
    return bool(evaluate_expr(condition, ctx))


# ---------------------------------------------------------------------------
# Entity update helper
# ---------------------------------------------------------------------------

def _update_entity(state: CombatState, entity_id: str, **kwargs: Any) -> CombatState:
    entity = state.entities[entity_id]
    new_entity = replace(entity, **kwargs)
    new_entities = {**state.entities, entity_id: new_entity}
    return replace(state, entities=new_entities)


# ---------------------------------------------------------------------------
# Non-ticking action types (checked on-demand, not via tick_effects)
# ---------------------------------------------------------------------------

_NON_TICKING_ACTIONS = frozenset({
    EffectActionType.SKIP_TURN,
    EffectActionType.DAMAGE_DEALT_MULT,
    EffectActionType.DAMAGE_TAKEN_MULT,
    EffectActionType.STAT_MODIFY,
})


# ---------------------------------------------------------------------------
# apply_effect
# ---------------------------------------------------------------------------

def apply_effect(
    state: CombatState,
    target_id: str,
    effect_id: str,
    source_id: str,
    context: dict[str, Any] | None = None,
) -> CombatState:
    effect_def = load_effect(effect_id)
    entity = state.entities[target_id]

    # Check apply condition
    if not _check_condition(effect_def.apply_condition, entity, context):
        return state

    existing = list(entity.active_effects)
    for i, inst in enumerate(existing):
        if inst.effect_id == effect_id:
            if effect_def.stackable:
                at_max = (
                    effect_def.max_stacks is not None
                    and inst.stack_count >= effect_def.max_stacks
                )
                new_stacks = inst.stack_count if at_max else inst.stack_count + 1
                existing[i] = replace(
                    inst,
                    stack_count=new_stacks,
                    remaining_duration=effect_def.duration,
                )
            else:
                existing[i] = replace(inst, remaining_duration=effect_def.duration)
            return _update_entity(state, target_id, active_effects=tuple(existing))

    new_inst = StatusEffectInstance(
        effect_id=effect_id,
        source_id=source_id,
        remaining_duration=effect_def.duration,
    )
    return _update_entity(
        state, target_id,
        active_effects=entity.active_effects + (new_inst,),
    )


# ---------------------------------------------------------------------------
# tick_effects
# ---------------------------------------------------------------------------

def tick_effects(
    state: CombatState,
    entity_id: str,
    trigger: TriggerType,
    rng: SeededRNG,
) -> tuple[CombatState, list[HitResult]]:
    entity = state.entities[entity_id]
    results: list[HitResult] = []

    for inst in entity.active_effects:
        effect_def = load_effect(inst.effect_id)
        if effect_def.trigger != trigger:
            continue

        current_entity = state.entities[entity_id]
        if not _check_condition(effect_def.tick_condition, current_entity):
            continue

        target_ctx = build_expr_context(current_entity)
        source = state.entities.get(inst.source_id)
        attacker_ctx = build_expr_context(source) if source else target_ctx
        ctx: dict[str, Any] = {"target": target_ctx, "attacker": attacker_ctx}

        for action in effect_def.actions:
            if action.action_type in _NON_TICKING_ACTIONS:
                continue

            value = evaluate_expr(action.expr, ctx)
            stack_mult = inst.stack_count if action.scales_with_stacks else 1

            match action.action_type:
                case EffectActionType.DAMAGE:
                    dmg = int(abs(value) * stack_mult)
                    current_entity = state.entities[entity_id]
                    new_hp = max(0, current_entity.current_hp - dmg)
                    state = _update_entity(state, entity_id, current_hp=new_hp)
                    results.append(HitResult(
                        target_id=entity_id,
                        damage=DamageResult(
                            amount=dmg,
                            damage_type=action.damage_type,
                            is_crit=False,
                            formula_id=inst.effect_id,
                        ),
                    ))

                case EffectActionType.HEAL:
                    heal = int(abs(value) * stack_mult)
                    current_entity = state.entities[entity_id]
                    max_hp = current_entity.major_stats.hp
                    new_hp = min(max_hp, current_entity.current_hp + heal)
                    state = _update_entity(state, entity_id, current_hp=new_hp)
                    results.append(HitResult(
                        target_id=entity_id,
                        heal_amount=heal,
                    ))

                case EffectActionType.GRANT_ENERGY:
                    amount = int(abs(value) * stack_mult)
                    current_entity = state.entities[entity_id]
                    max_energy = current_entity.major_stats.energy
                    new_energy = min(max_energy, current_entity.current_energy + amount)
                    state = _update_entity(state, entity_id, current_energy=new_energy)

    return state, results


# ---------------------------------------------------------------------------
# expire_effects
# ---------------------------------------------------------------------------

def reset_effect_stacks(state: CombatState, entity_id: str, effect_id: str) -> CombatState:
    """Remove all stacks of an effect (consume it entirely)."""
    entity = state.entities[entity_id]
    new_effects = tuple(inst for inst in entity.active_effects if inst.effect_id != effect_id)
    return _update_entity(state, entity_id, active_effects=new_effects)


def expire_effects(state: CombatState, entity_id: str) -> CombatState:
    entity = state.entities[entity_id]
    new_effects: list[StatusEffectInstance] = []
    for inst in entity.active_effects:
        remaining = inst.remaining_duration - 1
        if remaining > 0:
            new_effects.append(replace(inst, remaining_duration=remaining))
    return _update_entity(state, entity_id, active_effects=tuple(new_effects))


# ---------------------------------------------------------------------------
# get_damage_multiplier
# ---------------------------------------------------------------------------

def get_damage_multiplier(
    state: CombatState,
    attacker_id: str,
    defender_id: str,
    damage_type: DamageType | None = None,
) -> float:
    multiplier = 1.0
    dt_ctx: dict[str, Any] = {
        "damage_type": _damage_type_to_numeric(damage_type),
        **_build_damage_type_constants(),
    }

    # Attacker: DAMAGE_DEALT_MULT effects
    attacker = state.entities[attacker_id]
    for inst in attacker.active_effects:
        effect_def = load_effect(inst.effect_id)
        if effect_def.trigger != TriggerType.ON_DAMAGE_CALC:
            continue
        if not _check_condition(effect_def.tick_condition, attacker, dt_ctx):
            continue
        for action in effect_def.actions:
            if action.action_type != EffectActionType.DAMAGE_DEALT_MULT:
                continue
            ctx: dict[str, Any] = {"target": build_expr_context(attacker)}
            stack_mult = inst.stack_count if action.scales_with_stacks else 1
            val = evaluate_expr(action.expr, ctx)
            multiplier *= val ** stack_mult if val != 0 else 1

    # Defender: DAMAGE_TAKEN_MULT effects
    defender = state.entities[defender_id]
    for inst in defender.active_effects:
        effect_def = load_effect(inst.effect_id)
        if effect_def.trigger != TriggerType.ON_DAMAGE_CALC:
            continue
        if not _check_condition(effect_def.tick_condition, defender, dt_ctx):
            continue
        for action in effect_def.actions:
            if action.action_type != EffectActionType.DAMAGE_TAKEN_MULT:
                continue
            ctx = {"target": build_expr_context(defender)}
            stack_mult = inst.stack_count if action.scales_with_stacks else 1
            val = evaluate_expr(action.expr, ctx)
            multiplier *= val ** stack_mult if val != 0 else 1

    return multiplier


# ---------------------------------------------------------------------------
# is_skipped
# ---------------------------------------------------------------------------

def is_skipped(state: CombatState, entity_id: str) -> bool:
    entity = state.entities[entity_id]
    for inst in entity.active_effects:
        effect_def = load_effect(inst.effect_id)
        for action in effect_def.actions:
            if action.action_type == EffectActionType.SKIP_TURN:
                return True
    return False


# ---------------------------------------------------------------------------
# Effective stat helpers (on-demand, for STAT_MODIFY effects)
# ---------------------------------------------------------------------------

def get_effective_major_stat(
    state: CombatState,
    entity_id: str,
    stat_name: str,
) -> float:
    """Get a major stat value with all active STAT_MODIFY effects applied."""
    entity = state.entities[entity_id]
    base_value = float(getattr(entity.major_stats, stat_name))

    for inst in entity.active_effects:
        effect_def = load_effect(inst.effect_id)
        for action in effect_def.actions:
            if action.action_type != EffectActionType.STAT_MODIFY:
                continue
            if action.stat != stat_name:
                continue
            if not _check_condition(effect_def.tick_condition, entity):
                continue
            ctx: dict[str, Any] = {"target": build_expr_context(entity)}
            modifier = evaluate_expr(action.expr, ctx)
            stack_mult = inst.stack_count if action.scales_with_stacks else 1
            base_value += modifier * stack_mult

    return base_value


def get_effective_minor_stat(
    state: CombatState,
    entity_id: str,
    stat_key: str,
) -> float:
    """Get a minor stat value with all active STAT_MODIFY effects applied.

    stat_key is the full key, e.g. "arcane_dmg_pct", "slashing_def_pct".
    """
    entity = state.entities[entity_id]
    base_value = entity.minor_stats.values.get(stat_key, 0.0)

    for inst in entity.active_effects:
        effect_def = load_effect(inst.effect_id)
        for action in effect_def.actions:
            if action.action_type != EffectActionType.STAT_MODIFY:
                continue
            if action.stat != stat_key:
                continue
            if not _check_condition(effect_def.tick_condition, entity):
                continue
            ctx: dict[str, Any] = {"target": build_expr_context(entity)}
            modifier = evaluate_expr(action.expr, ctx)
            stack_mult = inst.stack_count if action.scales_with_stacks else 1
            base_value += modifier * stack_mult

    return base_value
