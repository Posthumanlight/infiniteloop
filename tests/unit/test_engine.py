"""Tests for the combat engine public API."""

import pytest

from game.combat.engine import get_available_actions, skip_turn, start_combat, submit_action
from game.combat.models import ActionRequest
from game.core.data_loader import clear_cache
from game.core.enums import ActionType, CombatPhase

from tests.unit.conftest import make_goblin, make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_start_combat_creates_valid_state():
    warrior = make_warrior()
    goblin = make_goblin()
    state = start_combat("sess1", [warrior], [goblin], seed=42)

    assert state.session_id == "sess1"
    assert state.round_number == 1
    assert state.phase == CombatPhase.ACTING
    assert set(state.turn_order) == {"p1", "e1"}
    assert len(state.entities) == 2
    assert state.rng_state is not None


def test_start_combat_deterministic():
    warrior = make_warrior()
    goblin = make_goblin()
    s1 = start_combat("s", [warrior], [goblin], seed=42)
    s2 = start_combat("s", [warrior], [goblin], seed=42)

    assert s1.turn_order == s2.turn_order
    assert s1.rng_state == s2.rng_state


def test_submit_action_slash():
    warrior = make_warrior()
    goblin = make_goblin()
    state = start_combat("s", [warrior], [goblin], seed=42)

    current_id = state.turn_order[state.current_turn_index]
    if current_id == "p1":
        action = ActionRequest(
            actor_id="p1",
            action_type=ActionType.ACTION,
            skill_id="slash",
            target_id="e1",
        )
    else:
        action = ActionRequest(
            actor_id="e1",
            action_type=ActionType.ACTION,
            skill_id="slash",
            target_id="p1",
        )

    new_state, result = submit_action(state, action)
    assert result.actor_id == current_id
    assert not result.skipped
    assert len(result.hits) > 0
    assert new_state.current_turn_index != state.current_turn_index or new_state.round_number > state.round_number


def test_submit_action_wrong_turn_raises():
    warrior = make_warrior()
    goblin = make_goblin()
    state = start_combat("s", [warrior], [goblin], seed=42)

    current_id = state.turn_order[state.current_turn_index]
    wrong_id = "e1" if current_id == "p1" else "p1"

    action = ActionRequest(
        actor_id=wrong_id,
        action_type=ActionType.ACTION,
        skill_id="slash",
        target_id=current_id,
    )
    with pytest.raises(ValueError, match="Not .* turn"):
        submit_action(state, action)


def test_submit_action_ended_raises():
    from dataclasses import replace

    warrior = make_warrior()
    goblin = make_goblin()
    state = start_combat("s", [warrior], [goblin], seed=42)
    state = replace(state, phase=CombatPhase.ENDED)

    action = ActionRequest(
        actor_id="p1",
        action_type=ActionType.ACTION,
        skill_id="slash",
        target_id="e1",
    )
    with pytest.raises(ValueError, match="Combat has ended"):
        submit_action(state, action)


def test_skip_turn():
    warrior = make_warrior()
    goblin = make_goblin()
    state = start_combat("s", [warrior], [goblin], seed=42)

    current_id = state.turn_order[state.current_turn_index]
    new_state, result = skip_turn(state, current_id)

    assert result.skipped is True
    assert result.actor_id == current_id


def test_get_available_actions():
    warrior = make_warrior()
    goblin = make_goblin()
    state = start_combat("s", [warrior], [goblin], seed=42)

    skills = get_available_actions(state, "p1")
    assert len(skills) == 1
    skill, cd = skills[0]
    assert skill.skill_id == "slash"
    assert cd == 0


def test_full_combat_to_end():
    """Run a full combat: warrior vs goblin, keep attacking until one side dies."""
    warrior = make_warrior()
    goblin = make_goblin()
    state = start_combat("s", [warrior], [goblin], seed=42)

    max_turns = 50
    for _ in range(max_turns):
        if state.phase == CombatPhase.ENDED:
            break

        current_id = state.turn_order[state.current_turn_index]
        entity = state.entities[current_id]

        if entity.entity_type.value == "player":
            target = "e1"
        else:
            target = "p1"

        action = ActionRequest(
            actor_id=current_id,
            action_type=ActionType.ACTION,
            skill_id="slash",
            target_id=target,
        )
        state, result = submit_action(state, action)
    else:
        pytest.fail(f"Combat didn't end within {max_turns} turns")

    assert state.phase == CombatPhase.ENDED

    # One side should be dead
    p1_alive = state.entities["p1"].current_hp > 0
    e1_alive = state.entities["e1"].current_hp > 0
    assert not (p1_alive and e1_alive), "Both sides still alive after combat ended"
