from dataclasses import dataclass, replace

from game.character.base_entity import BaseEntity
from game.combat.models import CombatState, HitResult, DamageResult
from game.core.data_loader import load_effect
from game.core.dice import SeededRNG
from game.core.enums import EffectAction, TriggerType
from game.core.formula_eval import ExprContext, evaluate_expr


@dataclass(frozen=True)
class StatusEffectInstance:
    effect_id: str
    source_id: str
    remaining_duration: int
    stack_count: int = 1


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


def _update_entity(state: CombatState, entity_id: str, **kwargs) -> CombatState:
    entity = state.entities[entity_id]
    new_entity = replace(entity, **kwargs)
    new_entities = {**state.entities, entity_id: new_entity}
    return replace(state, entities=new_entities)


def apply_effect(
    state: CombatState,
    target_id: str,
    effect_id: str,
    source_id: str,
) -> CombatState:
    effect_def = load_effect(effect_id)
    entity = state.entities[target_id]

    existing = list(entity.active_effects)
    for i, inst in enumerate(existing):
        if inst.effect_id == effect_id:
            if effect_def.stackable:
                existing[i] = replace(
                    inst,
                    stack_count=inst.stack_count + 1,
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

        target_ctx = build_expr_context(state.entities[entity_id])
        source = state.entities.get(inst.source_id)
        attacker_ctx = build_expr_context(source) if source else target_ctx

        ctx = {"target": target_ctx, "attacker": attacker_ctx}
        value = evaluate_expr(effect_def.expr, ctx)

        if effect_def.action == EffectAction.DAMAGE:
            dmg = int(abs(value) * inst.stack_count)
            current_entity = state.entities[entity_id]
            new_hp = max(0, current_entity.current_hp - dmg)
            state = _update_entity(state, entity_id, current_hp=new_hp)
            results.append(HitResult(
                target_id=entity_id,
                damage=DamageResult(
                    amount=dmg,
                    damage_type=effect_def.damage_type,
                    is_crit=False,
                    formula_id=inst.effect_id,
                ),
            ))

        elif effect_def.action == EffectAction.HEAL:
            heal = int(abs(value) * inst.stack_count)
            current_entity = state.entities[entity_id]
            max_hp = current_entity.major_stats.hp
            new_hp = min(max_hp, current_entity.current_hp + heal)
            state = _update_entity(state, entity_id, current_hp=new_hp)
            results.append(HitResult(
                target_id=entity_id,
                heal_amount=heal,
            ))

    return state, results


def expire_effects(state: CombatState, entity_id: str) -> CombatState:
    entity = state.entities[entity_id]
    new_effects: list[StatusEffectInstance] = []
    for inst in entity.active_effects:
        remaining = inst.remaining_duration - 1
        if remaining > 0:
            new_effects.append(replace(inst, remaining_duration=remaining))
    return _update_entity(state, entity_id, active_effects=tuple(new_effects))


def get_damage_multiplier(
    state: CombatState,
    attacker_id: str,
    defender_id: str,
) -> float:
    multiplier = 1.0

    attacker = state.entities[attacker_id]
    for inst in attacker.active_effects:
        effect_def = load_effect(inst.effect_id)
        if effect_def.trigger != TriggerType.ON_DAMAGE_CALC:
            continue
        if effect_def.action == EffectAction.BUFF:
            ctx = {"target": build_expr_context(attacker)}
            multiplier *= evaluate_expr(effect_def.expr, ctx)

    defender = state.entities[defender_id]
    for inst in defender.active_effects:
        effect_def = load_effect(inst.effect_id)
        if effect_def.trigger != TriggerType.ON_DAMAGE_CALC:
            continue
        if effect_def.action in (EffectAction.BUFF, EffectAction.DEBUFF):
            ctx = {"target": build_expr_context(defender)}
            multiplier *= evaluate_expr(effect_def.expr, ctx)

    return multiplier


def is_stunned(state: CombatState, entity_id: str) -> bool:
    entity = state.entities[entity_id]
    for inst in entity.active_effects:
        effect_def = load_effect(inst.effect_id)
        if (
            effect_def.action == EffectAction.DEBUFF
            and effect_def.trigger == TriggerType.ON_TURN_START
            and inst.effect_id == "stun"
        ):
            return True
    return False
