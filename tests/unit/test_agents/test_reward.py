from dataclasses import replace

import pytest

from agents.reward import (
    RewardConfig,
    RewardWeights,
    actor_is_alive,
    average_damage_per_round_for_reward,
    calculate_reward,
    controlled_damage_total,
    transition_difficulty_modifier,
)
from game.combat.models import (
    ActionRequest,
    ActionResult,
    DamageResult,
    HitResult,
    TriggeredActionResult,
)
from game.combat.summons import SummonEntity
from game.core.enums import (
    ActionType,
    DamageType,
    EntityType,
    SessionEndReason,
    SessionPhase,
)
from game.session.models import CompletedCombat, RunStats, SessionState
from game.world.difficulty import RoomDifficultyModifier

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


def _session(**kwargs) -> SessionState:
    defaults = {
        "session_id": "test-session",
        "players": (make_warrior("p1"),),
        "phase": SessionPhase.EXPLORING,
    }
    defaults.update(kwargs)
    return SessionState(**defaults)


def _action(
    actor_id: str,
    amount: int,
    *,
    target_id: str = "e1",
    nested: tuple[TriggeredActionResult, ...] = (),
) -> ActionResult:
    return ActionResult(
        actor_id=actor_id,
        action=ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id="slash",
        ),
        hits=(
            HitResult(
                target_id=target_id,
                damage=DamageResult(
                    amount=amount,
                    damage_type=DamageType.SLASHING,
                    is_crit=False,
                    formula_id="slash",
                ),
            ),
        ),
        triggered_actions=nested,
        round_number=1,
    )


def _triggered(actor_id: str, amount: int) -> TriggeredActionResult:
    return TriggeredActionResult(
        actor_id=actor_id,
        skill_id="slash",
        hits=(
            HitResult(
                target_id="e1",
                damage=DamageResult(
                    amount=amount,
                    damage_type=DamageType.SLASHING,
                    is_crit=False,
                    formula_id="slash",
                ),
            ),
        ),
    )


def _combat(*, round_number=1, action_log=(), room_difficulty=None, entities=None):
    if entities is None:
        entities = {
            "p1": make_warrior("p1"),
            "e1": make_goblin("e1"),
        }
    return replace(
        make_combat_state(
            players=[
                entity for entity in entities.values()
                if entity.entity_type == EntityType.PLAYER
            ],
            enemies=[
                entity for entity in entities.values()
                if entity.entity_type == EntityType.ENEMY
            ],
            turn_order=tuple(entities),
        ),
        entities=entities,
        round_number=round_number,
        action_log=action_log,
        room_difficulty=room_difficulty,
    )


def _difficulty(scalar: float) -> RoomDifficultyModifier:
    return RoomDifficultyModifier(
        scalar=scalar,
        average_level=1.0,
        party_size=1,
        power=1,
    )


def test_alive_step_and_death_penalty():
    alive = _session(players=(make_warrior("p1"),))
    dead = _session(players=(replace(make_warrior("p1"), current_hp=0),))

    alive_reward = calculate_reward(alive, alive, "p1")
    dead_reward = calculate_reward(alive, dead, "p1")

    assert actor_is_alive(alive, "p1") is True
    assert alive_reward.components["alive_step"] == pytest.approx(0.01)
    assert dead_reward.is_alive is False
    assert dead_reward.components["death_penalty"] == pytest.approx(-1.0)
    assert "alive_step" not in dead_reward.components


def test_actor_and_owned_summon_damage_count_but_enemy_and_other_summon_do_not():
    player = make_warrior("p1")
    enemy = make_goblin("e1")
    owned = SummonEntity(
        entity_id="ally_familiar_1",
        entity_name="Familiar",
        entity_type=EntityType.ALLY,
        major_stats=player.major_stats,
        minor_stats=player.minor_stats,
        current_hp=20,
        current_energy=20,
        summon_template_id="familiar",
        owner_id="p1",
        skills=("slash",),
    )
    other = replace(owned, entity_id="ally_familiar_2", owner_id="p2")
    combat = _combat(
        round_number=2,
        entities={
            "p1": player,
            "ally_familiar_1": owned,
            "ally_familiar_2": other,
            "e1": enemy,
        },
        action_log=(
            _action("p1", 20, nested=(_triggered("ally_familiar_1", 10),)),
            _action("e1", 100, target_id="p1"),
            _action("ally_familiar_2", 50),
        ),
    )

    assert controlled_damage_total(combat, "p1") == 30
    assert average_damage_per_round_for_reward(combat, "p1") == 15


def test_damage_and_dpr_delta_rewards_scale_with_difficulty():
    difficulty = _difficulty(2.0)
    before_combat = _combat(round_number=1, room_difficulty=difficulty)
    after_combat = _combat(
        round_number=1,
        room_difficulty=difficulty,
        action_log=(_action("p1", 50),),
    )
    before = _session(phase=SessionPhase.IN_COMBAT, combat=before_combat)
    after = _session(phase=SessionPhase.IN_COMBAT, combat=after_combat)

    reward = calculate_reward(before, after, "p1")

    assert reward.difficulty_modifier == 2.0
    assert reward.average_damage_per_round == 50
    assert reward.components["actor_damage"] == pytest.approx(0.08)
    assert reward.components["average_dpr_delta"] == pytest.approx(0.08)


def test_ended_combat_transition_uses_before_combat_difficulty():
    difficulty = _difficulty(3.0)
    before_combat = _combat(round_number=1, room_difficulty=difficulty)
    after_combat = replace(
        before_combat,
        action_log=(_action("p1", 100),),
    )
    completed = CompletedCombat(
        combat_id=after_combat.combat_id,
        final_round_number=after_combat.round_number,
        action_log=after_combat.action_log,
        entities=after_combat.entities,
        location=after_combat.location,
    )
    before = _session(phase=SessionPhase.IN_COMBAT, combat=before_combat)
    after = _session(
        phase=SessionPhase.EXPLORING,
        combat=None,
        last_combat=completed,
        run_stats=RunStats(combats_completed=1),
    )

    reward = calculate_reward(before, after, "p1")

    assert transition_difficulty_modifier(before, after) == 3.0
    assert reward.components["actor_damage"] == pytest.approx(0.24)
    assert reward.components["combat_victory"] == pytest.approx(1.5)


def test_penalties_do_not_scale_with_difficulty():
    before = _session(
        phase=SessionPhase.IN_COMBAT,
        combat=_combat(room_difficulty=_difficulty(9.0)),
    )
    after = _session(
        players=(replace(make_warrior("p1"), current_hp=0),),
        phase=SessionPhase.ENDED,
        end_reason=SessionEndReason.PARTY_WIPED,
    )

    reward = calculate_reward(before, after, "p1")

    assert reward.difficulty_modifier == 9.0
    assert reward.components["death_penalty"] == pytest.approx(-1.0)
    assert reward.components["party_wipe"] == pytest.approx(-2.0)


def test_room_progress_and_terminal_rewards():
    before = _session(run_stats=RunStats(rooms_explored=2))
    after = _session(run_stats=RunStats(rooms_explored=4))
    progress = calculate_reward(before, after, "p1")

    success = calculate_reward(
        before,
        _session(
            phase=SessionPhase.ENDED,
            end_reason=SessionEndReason.MAX_DEPTH,
        ),
        "p1",
    )
    retreat = calculate_reward(
        before,
        _session(
            phase=SessionPhase.ENDED,
            end_reason=SessionEndReason.RETREAT,
        ),
        "p1",
    )

    assert progress.components["room_progress"] == pytest.approx(0.2)
    assert success.components["max_depth_success"] == pytest.approx(2.0)
    assert retreat.components["retreat"] == pytest.approx(-1.0)


def test_reward_breakdown_total_matches_components_and_handles_no_combat():
    before = _session()
    after = _session()

    reward = calculate_reward(before, after, "p1")

    assert reward.total == pytest.approx(sum(reward.components.values()))
    assert reward.is_alive is True
    assert reward.average_damage_per_round == 0.0
    assert reward.difficulty_modifier == 1.0
