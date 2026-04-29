from __future__ import annotations

from dataclasses import dataclass, field
from typing import TypeAlias

from agents.observation import difficulty_modifier
from game.combat.models import ActionResult, CombatState, TriggeredActionResult
from game.combat.summons import SummonEntity
from game.core.enums import SessionEndReason, SessionPhase
from game.session.models import CompletedCombat, SessionState


CombatLike: TypeAlias = CombatState | CompletedCombat


@dataclass(frozen=True)
class RewardWeights:
    alive_step: float = 0.05
    death_penalty: float = -10.0
    actor_damage: float = 0.40
    average_dpr_delta: float = 0.20
    combat_victory: float = 0.50
    room_progress: float = 0.10
    max_depth_success: float = 2.0
    party_wipe: float = -10.0
    retreat: float = -10.0


@dataclass(frozen=True)
class RewardConfig:
    weights: RewardWeights = field(default_factory=RewardWeights)
    damage_normalizer: float = 500.0
    dpr_normalizer: float = 250.0


@dataclass(frozen=True)
class RewardBreakdown:
    total: float
    is_alive: bool
    average_damage_per_round: float
    difficulty_modifier: float
    components: dict[str, float] = field(default_factory=dict)


def actor_is_alive(state: SessionState, actor_id: str) -> bool:
    if state.combat is not None and actor_id in state.combat.entities:
        return state.combat.entities[actor_id].current_hp > 0

    for player in state.players:
        if player.entity_id == actor_id:
            return player.current_hp > 0

    if state.last_combat is not None and actor_id in state.last_combat.entities:
        return state.last_combat.entities[actor_id].current_hp > 0

    return False


def transition_difficulty_modifier(
    before: SessionState,
    after: SessionState,
) -> float:
    if after.combat is not None:
        return difficulty_modifier(after.combat)
    if before.combat is not None:
        return difficulty_modifier(before.combat)
    return 1.0


def scale_positive(value: float, diff: float) -> float:
    return value * diff if value > 0 else value


def controlled_actor_ids(combat: CombatLike, actor_id: str) -> set[str]:
    ids = {actor_id}
    for entity in combat.entities.values():
        if isinstance(entity, SummonEntity) and entity.owner_id == actor_id:
            ids.add(entity.entity_id)
    return ids


def damage_from_result(
    result: ActionResult | TriggeredActionResult,
    controlled_ids: set[str],
) -> int:
    total = 0

    if result.actor_id in controlled_ids:
        total += sum(
            hit.damage.amount
            for hit in result.hits
            if hit.damage is not None
        )

    for nested in result.triggered_actions:
        total += damage_from_result(nested, controlled_ids)

    return total


def controlled_damage_total(combat: CombatLike, actor_id: str) -> int:
    controlled_ids = controlled_actor_ids(combat, actor_id)
    return sum(
        damage_from_result(result, controlled_ids)
        for result in combat.action_log
    )


def combat_round_number(combat: CombatLike) -> int:
    if isinstance(combat, CompletedCombat):
        return combat.final_round_number
    return combat.round_number


def average_damage_per_round_for_reward(
    combat: CombatLike,
    actor_id: str,
) -> float:
    return controlled_damage_total(combat, actor_id) / max(
        1,
        combat_round_number(combat),
    )


def reward_combat_snapshot(state: SessionState) -> CombatLike | None:
    if state.combat is not None:
        return state.combat
    return state.last_combat


def same_combat(left: CombatLike | None, right: CombatLike | None) -> bool:
    return (
        left is not None
        and right is not None
        and left.combat_id == right.combat_id
    )


def _combat_components(
    before: SessionState,
    after: SessionState,
    actor_id: str,
    config: RewardConfig,
    diff: float,
) -> tuple[dict[str, float], float]:
    components: dict[str, float] = {}
    before_combat = reward_combat_snapshot(before)
    after_combat = reward_combat_snapshot(after)
    after_dpr = (
        average_damage_per_round_for_reward(after_combat, actor_id)
        if after_combat is not None
        else 0.0
    )

    if not same_combat(before_combat, after_combat):
        return components, after_dpr

    before_damage = controlled_damage_total(before_combat, actor_id)
    after_damage = controlled_damage_total(after_combat, actor_id)
    damage_delta = max(0, after_damage - before_damage)

    before_dpr = average_damage_per_round_for_reward(before_combat, actor_id)
    dpr_delta = max(0.0, after_dpr - before_dpr)

    if damage_delta > 0:
        components["actor_damage"] = scale_positive(
            config.weights.actor_damage
            * (damage_delta / config.damage_normalizer),
            diff,
        )
    if dpr_delta > 0:
        components["average_dpr_delta"] = scale_positive(
            config.weights.average_dpr_delta
            * (dpr_delta / config.dpr_normalizer),
            diff,
        )

    return components, after_dpr


def calculate_reward(
    before: SessionState,
    after: SessionState,
    actor_id: str,
    config: RewardConfig = RewardConfig(),
) -> RewardBreakdown:
    weights = config.weights
    diff = transition_difficulty_modifier(before, after)
    components: dict[str, float] = {}

    was_alive = actor_is_alive(before, actor_id)
    is_alive = actor_is_alive(after, actor_id)

    if is_alive:
        components["alive_step"] = weights.alive_step
    if was_alive and not is_alive:
        components["death_penalty"] = weights.death_penalty

    combat_components, after_dpr = _combat_components(
        before,
        after,
        actor_id,
        config,
        diff,
    )
    components.update(combat_components)

    rooms_delta = after.run_stats.rooms_explored - before.run_stats.rooms_explored
    combats_delta = (
        after.run_stats.combats_completed - before.run_stats.combats_completed
    )

    if rooms_delta > 0:
        components["room_progress"] = scale_positive(
            weights.room_progress * rooms_delta,
            diff,
        )

    if combats_delta > 0 and is_alive:
        components["combat_victory"] = scale_positive(
            weights.combat_victory * combats_delta,
            diff,
        )

    if after.phase == SessionPhase.ENDED and before.phase != SessionPhase.ENDED:
        if after.end_reason == SessionEndReason.MAX_DEPTH:
            components["max_depth_success"] = scale_positive(
                weights.max_depth_success,
                diff,
            )
        elif after.end_reason == SessionEndReason.PARTY_WIPED:
            components["party_wipe"] = weights.party_wipe
        elif after.end_reason == SessionEndReason.RETREAT:
            components["retreat"] = weights.retreat

    total = float(sum(components.values()))
    return RewardBreakdown(
        total=total,
        is_alive=is_alive,
        average_damage_per_round=after_dpr,
        difficulty_modifier=diff,
        components=components,
    )
