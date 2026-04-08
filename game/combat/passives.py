from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from game.combat.effects import apply_effect, build_expr_context
from game.combat.models import CombatState, DamageResult, HitResult
from game.core.data_loader import PassiveSkillData, load_passive
from game.core.enums import DamageType, PassiveAction, TriggerType, UsageLimit
from game.core.formula_eval import evaluate_expr


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


def _execute_passive_action(
    state: CombatState,
    entity_id: str,
    passive: PassiveSkillData,
    ctx: dict[str, Any],
) -> tuple[CombatState, HitResult | None]:
    """Execute a passive's action and return updated state + optional hit result."""
    match passive.action:
        case PassiveAction.APPLY_EFFECT:
            if passive.effect_id is not None:
                state = apply_effect(state, entity_id, passive.effect_id, entity_id)
            return state, None

        case PassiveAction.DAMAGE:
            value = int(abs(evaluate_expr(passive.expr, ctx)))
            entity = state.entities[entity_id]
            new_hp = max(0, entity.current_hp - value)
            state = _update_entity(state, entity_id, current_hp=new_hp)
            return state, HitResult(
                target_id=entity_id,
                damage=DamageResult(
                    amount=value,
                    damage_type=None,
                    is_crit=False,
                    formula_id=passive.skill_id,
                ),
            )

        case PassiveAction.HEAL:
            value = int(abs(evaluate_expr(passive.expr, ctx)))
            entity = state.entities[entity_id]
            new_hp = min(entity.current_hp + value, entity.major_stats.hp)
            state = _update_entity(state, entity_id, current_hp=new_hp)
            return state, HitResult(target_id=entity_id, heal_amount=value)

        case PassiveAction.MODIFY_STAT | PassiveAction.BONUS_DAMAGE:
            return state, None  # future expansion

        case _:
            return state, None


def check_passives(
    state: CombatState,
    entity_id: str,
    trigger: TriggerType,
    trigger_context: dict[str, Any] | None = None,
) -> tuple[CombatState, list[HitResult]]:
    """Check and fire all matching passives for an entity at a trigger point."""
    entity = state.entities.get(entity_id)
    if entity is None or entity.current_hp <= 0:
        return state, []

    results: list[HitResult] = []
    ctx_extra = dict(trigger_context or {})
    if "damage_type" in ctx_extra:
        ctx_extra["damage_type"] = _normalize_damage_type(ctx_extra["damage_type"])

    for passive_id in entity.passive_skills:
        passive = load_passive(passive_id)
        if passive.trigger != trigger:
            continue

        tracker = state.passive_trackers.get(entity_id, _empty_tracker())
        if not tracker.can_use(passive):
            continue

        ctx: dict[str, Any] = {
            "attacker": build_expr_context(entity),
            **_build_damage_type_constants(),
            **ctx_extra,
        }
        if passive.condition and not evaluate_expr(passive.condition, ctx):
            continue

        state, hit = _execute_passive_action(state, entity_id, passive, ctx)
        if hit is not None:
            results.append(hit)

        tracker = tracker.record_use(passive_id)
        new_trackers = {**state.passive_trackers, entity_id: tracker}
        state = replace(state, passive_trackers=new_trackers)

    return state, results
