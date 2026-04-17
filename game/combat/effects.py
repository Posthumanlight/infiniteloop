from dataclasses import dataclass, replace
from typing import Any

from game.character.base_entity import BaseEntity
from game.character.player_character import PlayerCharacter
from game.combat.models import CombatState, DamageResult, HitResult
from game.combat.summons import handle_owner_death
from game.core.data_loader import load_effect, load_modifier
from game.core.dice import SeededRNG
from game.core.enums import DamageType, EffectActionType, TriggerType
from game.core.formula_eval import ExprContext, evaluate_expr
from game.items.equipment_effects import collect_equipped_item_effects


# ---------------------------------------------------------------------------
# StatusEffectInstance — lives on BaseEntity.active_effects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusEffectInstance:
    effect_id: str
    source_id: str
    remaining_duration: int
    stack_count: int = 1


@dataclass(frozen=True)
class SkillAccessSnapshot:
    base: tuple[str, ...]
    granted: tuple[str, ...]
    blocked: tuple[str, ...]
    available: tuple[str, ...]

    @property
    def available_set(self) -> frozenset[str]:
        return frozenset(self.available)

    @property
    def blocked_set(self) -> frozenset[str]:
        return frozenset(self.blocked)


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


def build_effective_expr_context(
    state: CombatState,
    entity_id: str,
) -> ExprContext:
    entity = state.entities[entity_id]
    return ExprContext(
        attack=get_effective_major_stat(state, entity_id, "attack"),
        hp=get_effective_major_stat(state, entity_id, "hp"),
        current_hp=entity.current_hp,
        speed=get_effective_major_stat(state, entity_id, "speed"),
        crit_chance=get_effective_major_stat(state, entity_id, "crit_chance"),
        crit_dmg=get_effective_major_stat(state, entity_id, "crit_dmg"),
        resistance=get_effective_major_stat(state, entity_id, "resistance"),
        energy=get_effective_major_stat(state, entity_id, "energy"),
        mastery=get_effective_major_stat(state, entity_id, "mastery"),
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
    target_ctx: ExprContext | None = None,
    attacker_ctx: ExprContext | None = None,
) -> bool:
    if not condition:
        return True
    resolved_target = target_ctx or build_expr_context(entity)
    resolved_attacker = attacker_ctx or resolved_target
    ctx: dict[str, Any] = {
        "target": resolved_target,
        "attacker": resolved_attacker,
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
    EffectActionType.GRANT_SKILL,
    EffectActionType.BLOCK_SKILL,
})


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def _build_effect_context(
    state: CombatState,
    target_id: str,
    source_id: str | None = None,
    *,
    use_effective_stats: bool,
    extra_ctx: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_entity = state.entities[target_id]
    target_ctx = (
        build_effective_expr_context(state, target_id)
        if use_effective_stats
        else build_expr_context(target_entity)
    )

    if source_id and source_id in state.entities:
        attacker_ctx = (
            build_effective_expr_context(state, source_id)
            if use_effective_stats
            else build_expr_context(state.entities[source_id])
        )
    else:
        attacker_ctx = target_ctx

    return {
        "target": target_ctx,
        "attacker": attacker_ctx,
        **_build_damage_type_constants(),
        **(extra_ctx or {}),
    }


def _get_effect_damage_modifier(
    state: CombatState,
    effect_inst: StatusEffectInstance,
    ctx: dict[str, Any],
) -> float:
    if effect_inst.source_id not in state.entities:
        return 1.0

    source = state.entities[effect_inst.source_id]
    multiplier = 1.0

    for mod_inst in source.skill_modifiers:
        mod_data = load_modifier(mod_inst.modifier_id)
        if mod_data.action != "effect_damage_mult":
            continue
        if mod_data.effect_id != effect_inst.effect_id:
            continue

        value = evaluate_expr(mod_data.expr, ctx)
        if mod_data.stackable:
            multiplier *= 1.0 + ((value - 1.0) * mod_inst.stack_count)
        else:
            multiplier *= value

    return multiplier


def _apply_heal_or_energy_gain(
    state: CombatState,
    entity_id: str,
    action_type: EffectActionType,
    amount: int,
) -> tuple[CombatState, int]:
    entity = state.entities[entity_id]

    if action_type == EffectActionType.HEAL:
        max_hp = int(get_effective_major_stat(state, entity_id, "hp"))
        new_hp = min(max_hp, entity.current_hp + amount)
        applied = max(0, new_hp - entity.current_hp)
        return _update_entity(state, entity_id, current_hp=new_hp), applied

    max_energy = int(get_effective_major_stat(state, entity_id, "energy"))
    new_energy = min(max_energy, entity.current_energy + amount)
    applied = max(0, new_energy - entity.current_energy)
    return _update_entity(state, entity_id, current_energy=new_energy), applied


def _apply_on_apply_actions(
    state: CombatState,
    target_id: str,
    inst: StatusEffectInstance,
) -> CombatState:
    effect_def = load_effect(inst.effect_id)
    if effect_def.trigger != TriggerType.ON_APPLY:
        return state

    current_entity = state.entities[target_id]
    effective_ctx = _build_effect_context(
        state,
        target_id,
        inst.source_id,
        use_effective_stats=True,
    )
    if not _check_condition(
        effect_def.tick_condition,
        current_entity,
        target_ctx=effective_ctx["target"],
        attacker_ctx=effective_ctx["attacker"],
    ):
        return state

    for action in effect_def.actions:
        if action.action_type not in {
            EffectActionType.HEAL,
            EffectActionType.GRANT_ENERGY,
        }:
            continue

        value = evaluate_expr(action.expr, effective_ctx)
        stack_mult = inst.stack_count if action.scales_with_stacks else 1
        amount = int(abs(value) * stack_mult)
        state, _ = _apply_heal_or_energy_gain(
            state,
            target_id,
            action.action_type,
            amount,
        )

    return state


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
            updated_state = _update_entity(
                state,
                target_id,
                active_effects=tuple(existing),
            )
            return _apply_on_apply_actions(updated_state, target_id, existing[i])

    new_inst = StatusEffectInstance(
        effect_id=effect_id,
        source_id=source_id,
        remaining_duration=effect_def.duration,
    )
    updated_state = _update_entity(
        state, target_id,
        active_effects=entity.active_effects + (new_inst,),
    )
    return _apply_on_apply_actions(updated_state, target_id, new_inst)


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
        ctx = _build_effect_context(
            state,
            entity_id,
            inst.source_id,
            use_effective_stats=True,
        )
        if not _check_condition(
            effect_def.tick_condition,
            current_entity,
            target_ctx=ctx["target"],
            attacker_ctx=ctx["attacker"],
        ):
            continue

        for action in effect_def.actions:
            if action.action_type in _NON_TICKING_ACTIONS:
                continue

            value = evaluate_expr(action.expr, ctx)
            stack_mult = inst.stack_count if action.scales_with_stacks else 1

            match action.action_type:
                case EffectActionType.DAMAGE:
                    effect_damage_mult = _get_effect_damage_modifier(state, inst, ctx)
                    dmg = int(abs(value) * stack_mult * effect_damage_mult)
                    current_entity = state.entities[entity_id]
                    new_hp = max(0, current_entity.current_hp - dmg)
                    state = _update_entity(state, entity_id, current_hp=new_hp)
                    if new_hp <= 0:
                        state = handle_owner_death(state, entity_id)
                        from game.combat.passives import PassiveEvent, check_passives
                        from game.combat.targeting import get_allies

                        if inst.source_id in state.entities:
                            state, kill_results = check_passives(
                                state,
                                inst.source_id,
                                PassiveEvent(
                                    trigger=TriggerType.ON_KILL,
                                    payload={
                                        "killed": build_effective_expr_context(
                                            state,
                                            entity_id,
                                        ),
                                    },
                                ),
                                rng=rng,
                            )
                            results.extend(kill_results)

                        for ally_id in get_allies(state, entity_id):
                            if ally_id == entity_id:
                                continue
                            state, ally_results = check_passives(
                                state,
                                ally_id,
                                PassiveEvent(trigger=TriggerType.ON_ALLY_DEATH),
                                rng=rng,
                            )
                            results.extend(ally_results)
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
                    state, applied = _apply_heal_or_energy_gain(
                        state,
                        entity_id,
                        EffectActionType.HEAL,
                        heal,
                    )
                    results.append(HitResult(
                        target_id=entity_id,
                        heal_amount=applied,
                    ))

                case EffectActionType.GRANT_ENERGY:
                    amount = int(abs(value) * stack_mult)
                    state, _ = _apply_heal_or_energy_gain(
                        state,
                        entity_id,
                        EffectActionType.GRANT_ENERGY,
                        amount,
                    )

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
        ctx = _build_effect_context(
            state,
            attacker_id,
            inst.source_id,
            use_effective_stats=True,
            extra_ctx=dt_ctx,
        )
        if not _check_condition(
            effect_def.tick_condition,
            attacker,
            dt_ctx,
            target_ctx=ctx["target"],
            attacker_ctx=ctx["attacker"],
        ):
            continue
        for action in effect_def.actions:
            if action.action_type != EffectActionType.DAMAGE_DEALT_MULT:
                continue
            stack_mult = inst.stack_count if action.scales_with_stacks else 1
            val = evaluate_expr(action.expr, ctx)
            multiplier *= val ** stack_mult if val != 0 else 1

    # Defender: DAMAGE_TAKEN_MULT effects
    defender = state.entities[defender_id]
    for inst in defender.active_effects:
        effect_def = load_effect(inst.effect_id)
        if effect_def.trigger != TriggerType.ON_DAMAGE_CALC:
            continue
        ctx = _build_effect_context(
            state,
            defender_id,
            inst.source_id,
            use_effective_stats=True,
            extra_ctx=dt_ctx,
        )
        if not _check_condition(
            effect_def.tick_condition,
            defender,
            dt_ctx,
            target_ctx=ctx["target"],
            attacker_ctx=ctx["attacker"],
        ):
            continue
        for action in effect_def.actions:
            if action.action_type != EffectActionType.DAMAGE_TAKEN_MULT:
                continue
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


def get_effective_skill_access(
    entity: BaseEntity,
    state: CombatState | None = None,
) -> SkillAccessSnapshot:
    base = tuple(getattr(entity, "skills", ()))
    grants: list[str] = []
    blocks: list[str] = []

    if isinstance(entity, PlayerCharacter) and entity.inventory is not None:
        item_effects = collect_equipped_item_effects(entity.inventory)
        grants.extend(item_effects.granted_skills)
        blocks.extend(item_effects.blocked_skills)

    for inst in entity.active_effects:
        effect_def = load_effect(inst.effect_id)
        if state is not None:
            ctx = _build_effect_context(
                state,
                entity.entity_id,
                inst.source_id,
                use_effective_stats=True,
            )
            if not _check_condition(
                effect_def.tick_condition,
                entity,
                target_ctx=ctx["target"],
                attacker_ctx=ctx["attacker"],
            ):
                continue

        for action in effect_def.actions:
            if action.action_type == EffectActionType.GRANT_SKILL and action.skill_id:
                grants.append(action.skill_id)
            elif action.action_type == EffectActionType.BLOCK_SKILL and action.skill_id:
                blocks.append(action.skill_id)

    ordered_grants = _ordered_unique(grants)
    ordered_blocks = _ordered_unique(blocks)
    blocked_set = set(ordered_blocks)

    available = tuple(
        skill_id
        for skill_id in _ordered_unique([*base, *ordered_grants])
        if skill_id not in blocked_set
    )
    visible_grants = tuple(
        skill_id for skill_id in ordered_grants
        if skill_id not in blocked_set
    )

    return SkillAccessSnapshot(
        base=base,
        granted=visible_grants,
        blocked=ordered_blocks,
        available=available,
    )


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

    if isinstance(entity, PlayerCharacter) and entity.inventory is not None:
        item_effects = collect_equipped_item_effects(entity.inventory)
        base_value += item_effects.stat_modifiers.get(stat_name, 0.0)

    for inst in entity.active_effects:
        effect_def = load_effect(inst.effect_id)
        for action in effect_def.actions:
            if action.action_type != EffectActionType.STAT_MODIFY:
                continue
            if action.stat != stat_name:
                continue
            ctx = _build_effect_context(
                state,
                entity_id,
                inst.source_id,
                use_effective_stats=False,
            )
            if not _check_condition(
                effect_def.tick_condition,
                entity,
                target_ctx=ctx["target"],
                attacker_ctx=ctx["attacker"],
            ):
                continue
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

    if isinstance(entity, PlayerCharacter) and entity.inventory is not None:
        item_effects = collect_equipped_item_effects(entity.inventory)
        base_value += item_effects.stat_modifiers.get(stat_key, 0.0)

    for inst in entity.active_effects:
        effect_def = load_effect(inst.effect_id)
        for action in effect_def.actions:
            if action.action_type != EffectActionType.STAT_MODIFY:
                continue
            if action.stat != stat_key:
                continue
            ctx = _build_effect_context(
                state,
                entity_id,
                inst.source_id,
                use_effective_stats=False,
            )
            if not _check_condition(
                effect_def.tick_condition,
                entity,
                target_ctx=ctx["target"],
                attacker_ctx=ctx["attacker"],
            ):
                continue
            modifier = evaluate_expr(action.expr, ctx)
            stack_mult = inst.stack_count if action.scales_with_stacks else 1
            base_value += modifier * stack_mult

    return base_value
