from __future__ import annotations
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Iterable


from game.combat.cooldowns import is_on_cooldown, put_on_cooldown
from game.combat.effects import (
    apply_effect,
    build_effective_expr_context,
    get_effective_major_stat,
    reset_effect_stacks,
)
from game.combat.models import CombatState, DamageResult, HitResult
from game.combat.targeting import get_enemies
from game.core.data_loader import PassiveSkillData, load_passive, load_skill
from game.core.dice import SeededRNG
from game.core.enums import DamageType, PassiveAction, TriggerType, UsageLimit
from game.core.formula_eval import ZeroDefaultNamespace, evaluate_expr
from game.items.equipment_effects import get_effective_passive_ids


@dataclass(frozen=True)
class PassiveEvent:
    trigger: TriggerType
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PassiveTracker:
    """Tracks usage counts for passive skills during a combat."""

    usage_counts: dict[str, int]
    turn_usage: dict[str, int]

    def can_use(self, passive: PassiveSkillData) -> bool:
        combat_count = self.usage_counts.get(passive.skill_id, 0)
        turn_count = self.turn_usage.get(passive.skill_id, 0)
        match passive.usage_limit:
            case UsageLimit.UNLIMITED:
                return True
            case UsageLimit.N_PER_TURN:
                return turn_count < (passive.max_uses or 0)
            case UsageLimit.N_PER_COMBAT:
                return combat_count < (passive.max_uses or 0)

    def record_use(self, passive_id: str) -> PassiveTracker:
        new_combat = {
            **self.usage_counts,
            passive_id: self.usage_counts.get(passive_id, 0) + 1,
        }
        new_turn = {
            **self.turn_usage,
            passive_id: self.turn_usage.get(passive_id, 0) + 1,
        }
        return PassiveTracker(usage_counts=new_combat, turn_usage=new_turn)

    def reset_turn(self) -> PassiveTracker:
        return replace(self, turn_usage={})


def _empty_tracker() -> PassiveTracker:
    return PassiveTracker(usage_counts={}, turn_usage={})


_DAMAGE_TYPE_NUMERIC: dict[DamageType, int] = {
    DamageType.SLASHING: 1,
    DamageType.PIERCING: 2,
    DamageType.ARCANE: 3,
    DamageType.FIRE: 4,
    DamageType.ICE: 5,
}


def _damage_type_to_numeric(value: DamageType | None) -> int:
    if value is None:
        return 0
    return _DAMAGE_TYPE_NUMERIC[value]


def _normalize_damage_type(value: Any) -> int:
    if isinstance(value, DamageType) or value is None:
        return _damage_type_to_numeric(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return _damage_type_to_numeric(DamageType(value))
        except ValueError:
            return 0
    return 0


def _build_damage_type_constants() -> dict[str, int]:
    return {dt.name: _damage_type_to_numeric(dt) for dt in DamageType}


def _update_entity(state: CombatState, entity_id: str, **kwargs: object) -> CombatState:
    entity = state.entities[entity_id]
    new_entity = replace(entity, **kwargs)
    new_entities = {**state.entities, entity_id: new_entity}
    return replace(state, entities=new_entities)


PassiveExecutor = Callable[
    [CombatState, str, PassiveSkillData, dict[str, Any], SeededRNG | None, dict | None],
    tuple[CombatState, list[HitResult]],
]


def _exec_apply_effect(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    if passive.effect_id is not None:
        state = apply_effect(state, entity_id, passive.effect_id, entity_id)
    return state, []


def _exec_damage(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    value = int(abs(evaluate_expr(passive.expr, ctx)))
    entity = state.entities[entity_id]
    new_hp = max(0, entity.current_hp - value)
    state = _update_entity(state, entity_id, current_hp=new_hp)
    return state, [HitResult(
        target_id=entity_id,
        damage=DamageResult(
            amount=value,
            damage_type=None,
            is_crit=False,
            formula_id=passive.skill_id,
        ),
    )]


def _exec_heal(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    value = int(abs(evaluate_expr(passive.expr, ctx)))
    entity = state.entities[entity_id]
    max_hp = int(get_effective_major_stat(state, entity_id, 'hp'))
    new_hp = min(entity.current_hp + value, max_hp)
    applied = max(0, new_hp - entity.current_hp)
    state = _update_entity(state, entity_id, current_hp=new_hp)
    return state, [HitResult(target_id=entity_id, heal_amount=applied)]


def _exec_grant_energy(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    value = int(abs(evaluate_expr(passive.expr, ctx)))
    entity = state.entities[entity_id]
    max_energy = int(get_effective_major_stat(state, entity_id, 'energy'))
    new_energy = min(max_energy, entity.current_energy + value)
    state = _update_entity(state, entity_id, current_energy=new_energy)
    return state, []


def _exec_cast_skill(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    if passive.cast_skill_id is None or rng is None or constants is None:
        return state, []
    from game.combat.skill_resolver import resolve_skill

    skill = load_skill(passive.cast_skill_id)
    target_ids = get_enemies(state, entity_id)
    if not target_ids:
        return state, []
    selected_targets = {
        hit_index: target_ids[0]
        for hit_index, hit in enumerate(skill.hits)
        if hit.target_type.value in {'single_enemy', 'single_ally'}
    }
    return resolve_skill(state, entity_id, skill, selected_targets, rng, constants)


def _exec_consume_effect(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    if passive.consume_effect_id is not None:
        state = reset_effect_stacks(state, entity_id, passive.consume_effect_id)
    return state, []


def _exec_noop(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    return state, []


PASSIVE_ACTION_EXECUTORS: dict[PassiveAction, PassiveExecutor] = {
    PassiveAction.APPLY_EFFECT: _exec_apply_effect,
    PassiveAction.DAMAGE: _exec_damage,
    PassiveAction.HEAL: _exec_heal,
    PassiveAction.GRANT_ENERGY: _exec_grant_energy,
    PassiveAction.CAST_SKILL: _exec_cast_skill,
    PassiveAction.CONSUME_EFFECT: _exec_consume_effect,
    PassiveAction.MODIFY_STAT: _exec_noop,
}


def _execute_passive_action(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    executor = PASSIVE_ACTION_EXECUTORS.get(passive.action)
    if executor is None:
        raise ValueError(f'Unsupported passive action: {passive.action.value}')
    return executor(state, entity_id, passive, ctx, rng, constants)


def _iter_matching_passives(entity, trigger: TriggerType) -> Iterable[PassiveSkillData]:
    for passive_id in get_effective_passive_ids(entity):
        passive = load_passive(passive_id)
        if trigger in passive.triggers:
            yield passive


def _can_fire_passive(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
) -> bool:
    tracker = state.passive_trackers.get(entity_id, _empty_tracker())
    if not tracker.can_use(passive):
        return False
    if is_on_cooldown(state, entity_id, passive.skill_id):
        return False
    return True


def _build_passive_context(
    state: CombatState,
    entity_id: str,
    event: PassiveEvent,
) -> dict[str, Any]:
    entity = state.entities[entity_id]
    owner_ctx = build_effective_expr_context(state, entity_id)
    stack_ctx = ZeroDefaultNamespace({
        eff.effect_id: eff.stack_count
        for eff in entity.active_effects
    })

    event_scalars: dict[str, int | float] = {}
    event_subjects: dict[str, Any] = {}
    for key, value in dict(event.payload).items():
        if key == 'damage_type':
            event_scalars[key] = _normalize_damage_type(value)
        elif isinstance(value, (int, float)):
            event_scalars[key] = value
        elif value is None:
            event_scalars[key] = 0
        else:
            event_subjects[key] = value

    return {
        'owner': owner_ctx,
        'attacker': owner_ctx,
        'stacks': stack_ctx,
        'event': ZeroDefaultNamespace(event_scalars),
        'damage_type': event_scalars.get('damage_type', 0),
        'damage_taken': event_scalars.get('damage_taken', 0),
        'damage_dealt': event_scalars.get('damage_dealt', 0),
        **event_subjects,
        **_build_damage_type_constants(),
    }


def _record_passive_fire(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
) -> CombatState:
    state = put_on_cooldown(state, entity_id, passive.skill_id, passive.cooldown)
    tracker = state.passive_trackers.get(entity_id, _empty_tracker()).record_use(passive.skill_id)
    new_trackers = {**state.passive_trackers, entity_id: tracker}
    return replace(state, passive_trackers=new_trackers)


def check_passives(
    state: CombatState,
    entity_id: str,
    event: PassiveEvent,
    rng: SeededRNG | None = None,
    constants: dict | None = None,
) -> tuple[CombatState, list[HitResult]]:
    """Check and fire all matching passives for an entity at a trigger point."""
    entity = state.entities.get(entity_id)
    if entity is None or entity.current_hp <= 0:
        return state, []

    results: list[HitResult] = []
    for passive in _iter_matching_passives(entity, event.trigger):
        if not _can_fire_passive(state, entity_id, passive):
            continue

        ctx = _build_passive_context(state, entity_id, event)
        if passive.condition and not evaluate_expr(passive.condition, ctx):
            continue

        state, hits = _execute_passive_action(
            state, entity_id, passive, ctx, rng, constants,
        )
        results.extend(hits)

        if passive.consume_effect_id and passive.action != PassiveAction.CONSUME_EFFECT:
            state = reset_effect_stacks(state, entity_id, passive.consume_effect_id)

        state = _record_passive_fire(state, entity_id, passive)

    return state, results
