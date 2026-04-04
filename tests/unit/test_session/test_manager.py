import pytest

from game.combat.models import ActionRequest
from game.core.data_loader import clear_cache
from game.core.enums import (
    ActionType,
    CombatPhase,
    EntityType,
    SessionEndReason,
    SessionPhase,
)
from game.session.factories import build_player
from game.session.session_manager import SessionManager
from game.world.models import GenerationConfig

from tests.unit.conftest import make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


PREDETERMINED_CONFIG = GenerationConfig(predetermined_set_id="dark_cave_intro")

# dark_cave_intro locations:
#   [0] Goblin Ambush   (combat: 2x goblin)
#   [1] Underground Fountain (event: mysterious_fountain)
#   [2] Skeleton Guard   (combat: 1x skeleton)


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------

def test_start_run():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])

    assert state.phase == SessionPhase.EXPLORING
    assert len(state.players) == 1
    assert state.exploration is not None
    assert state.run_stats.rooms_explored == 0


def test_start_run_no_players():
    mgr = SessionManager(seed=42)
    with pytest.raises(ValueError, match="At least one player"):
        mgr.start_run("test-session", [])


def test_generate_and_vote():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)

    assert len(state.exploration.current_options) == 3

    state = mgr.submit_location_vote(state, "p1", 0)
    assert len(state.exploration.votes) == 1


def test_retreat():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])

    state = mgr.retreat(state)
    assert state.phase == SessionPhase.ENDED
    assert state.end_reason == SessionEndReason.RETREAT


# ---------------------------------------------------------------------------
# Phase validation
# ---------------------------------------------------------------------------

def test_wrong_phase_combat_action_raises():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])

    action = ActionRequest(actor_id="p1", action_type=ActionType.ACTION, skill_id="slash")
    with pytest.raises(ValueError, match="Expected phase in_combat"):
        mgr.submit_combat_action(state, action)


def test_wrong_phase_event_vote_raises():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])

    with pytest.raises(ValueError, match="Expected phase in_event"):
        mgr.submit_event_vote(state, "p1", 0)


# ---------------------------------------------------------------------------
# Full combat loop
# ---------------------------------------------------------------------------

def _run_combat_to_end(mgr, state):
    """Auto-play combat: players slash first enemy, enemies slash player."""
    while state.phase == SessionPhase.IN_COMBAT:
        current_id = state.combat.turn_order[state.combat.current_turn_index]
        entity = state.combat.entities[current_id]

        if entity.entity_type == EntityType.PLAYER:
            enemies_alive = [
                eid for eid in state.combat.turn_order
                if state.combat.entities[eid].entity_type == EntityType.ENEMY
                and state.combat.entities[eid].current_hp > 0
            ]
            target = enemies_alive[0] if enemies_alive else None
            action = ActionRequest(
                actor_id=current_id,
                action_type=ActionType.ACTION,
                skill_id="slash",
                target_id=target,
            )
            state = mgr.submit_combat_action(state, action)
        else:
            players_alive = [
                eid for eid in state.combat.turn_order
                if state.combat.entities[eid].entity_type == EntityType.PLAYER
                and state.combat.entities[eid].current_hp > 0
            ]
            target = players_alive[0] if players_alive else None
            action = ActionRequest(
                actor_id=current_id,
                action_type=ActionType.ACTION,
                skill_id="slash",
                target_id=target,
            )
            state = mgr.submit_combat_action(state, action)
    return state


def test_full_combat_loop():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)

    # Pick index 0: Goblin Ambush (combat)
    state = mgr.submit_location_vote(state, "p1", 0)
    state = mgr.resolve_location_choice(state)
    assert state.phase == SessionPhase.IN_COMBAT
    assert state.combat is not None

    state = _run_combat_to_end(mgr, state)

    # After combat, should be EXPLORING or ENDED
    assert state.phase in (SessionPhase.EXPLORING, SessionPhase.ENDED)
    assert state.combat is None
    assert state.run_stats.combats_completed == 1
    assert state.run_stats.rooms_explored == 1


def test_hp_carries_over():
    """Damage from combat persists between encounters."""
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    initial_hp = player.current_hp
    state = mgr.start_run("test-session", [player])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)

    # Enter combat
    state = mgr.submit_location_vote(state, "p1", 0)
    state = mgr.resolve_location_choice(state)
    state = _run_combat_to_end(mgr, state)

    if state.phase == SessionPhase.EXPLORING:
        # Player should have taken some damage
        assert state.players[0].current_hp <= initial_hp
        # HP is carried — not reset to full
        carried_hp = state.players[0].current_hp

        # Enter another combat
        state = mgr.generate_choices(state, PREDETERMINED_CONFIG)
        state = mgr.submit_location_vote(state, "p1", 2)  # Skeleton Guard
        state = mgr.resolve_location_choice(state)

        # Player enters with carried HP, not full
        player_in_combat = state.combat.entities["p1"]
        assert player_in_combat.current_hp == carried_hp


def test_combat_stats_tracked():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)

    state = mgr.submit_location_vote(state, "p1", 0)
    state = mgr.resolve_location_choice(state)
    state = _run_combat_to_end(mgr, state)

    if state.phase == SessionPhase.EXPLORING:
        assert state.run_stats.enemies_defeated > 0
        assert state.run_stats.total_damage_dealt > 0


# ---------------------------------------------------------------------------
# Full event loop
# ---------------------------------------------------------------------------

def test_full_event_loop():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)

    # Pick index 1: Underground Fountain (event: mysterious_fountain)
    state = mgr.submit_location_vote(state, "p1", 1)
    state = mgr.resolve_location_choice(state)
    assert state.phase == SessionPhase.IN_EVENT
    assert state.event is not None

    # Vote for choice 0: "Drink from the fountain" (heals)
    state = mgr.submit_event_vote(state, "p1", 0)
    state = mgr.resolve_event(state)

    assert state.phase in (SessionPhase.EXPLORING, SessionPhase.ENDED)
    assert state.event is None
    assert state.run_stats.events_completed == 1
    assert state.run_stats.rooms_explored == 1


# ---------------------------------------------------------------------------
# Max depth
# ---------------------------------------------------------------------------

def test_max_depth_ends_run():
    mgr = SessionManager(seed=42, max_depth=1)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)

    # Pick event (won't kill the player), resolve quickly
    state = mgr.submit_location_vote(state, "p1", 1)
    state = mgr.resolve_location_choice(state)

    # Resolve the event with "Walk away" (no outcomes)
    state = mgr.submit_event_vote(state, "p1", 3)
    state = mgr.resolve_event(state)

    assert state.phase == SessionPhase.ENDED
    assert state.end_reason == SessionEndReason.MAX_DEPTH


# ---------------------------------------------------------------------------
# Deterministic with same seed
# ---------------------------------------------------------------------------

def test_deterministic_with_seed():
    def run_one(seed):
        mgr = SessionManager(seed=seed)
        player = make_warrior("p1")
        state = mgr.start_run("test-session", [player])
        state = mgr.generate_choices(state, PREDETERMINED_CONFIG)
        state = mgr.submit_location_vote(state, "p1", 1)
        state = mgr.resolve_location_choice(state)
        state = mgr.submit_event_vote(state, "p1", 0)
        state = mgr.resolve_event(state)
        return state

    s1 = run_one(99)
    s2 = run_one(99)

    assert s1.players[0].current_hp == s2.players[0].current_hp
    assert s1.run_stats == s2.run_stats
    assert s1.phase == s2.phase
