from dataclasses import replace

import pytest

from game.core.data_loader import LocationOption, clear_cache, load_enemy
from game.core.enums import EntityType, LocationType, SessionPhase
from game.session.session_manager import SessionManager
from game.world.models import GenerationConfig

from tests.unit.conftest import make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_resolve_location_choice_preserves_room_difficulty_and_scales_enemies():
    mgr = SessionManager(seed=42)
    players = [
        replace(make_warrior("p1"), level=3),
        replace(make_warrior("p2"), level=5),
    ]
    state = mgr.start_run("test-session", players)
    state = mgr.generate_choices(
        state,
        GenerationConfig(predetermined_set_id="dark_cave_intro"),
    )

    room = state.exploration.current_options[0]
    assert room.room_difficulty is not None

    state = mgr.submit_location_vote(state, "p1", 0)
    state = mgr.submit_location_vote(state, "p2", 0)
    state = mgr.resolve_location_choice(state)

    assert state.phase == SessionPhase.IN_COMBAT
    assert state.combat is not None
    assert state.combat.room_difficulty == room.room_difficulty

    goblin_data = load_enemy("goblin")
    enemy_entities = [
        entity for entity in state.combat.entities.values()
        if entity.entity_type == EntityType.ENEMY
    ]
    assert enemy_entities

    expected = room.room_difficulty
    assert expected is not None
    for enemy in enemy_entities:
        assert enemy.major_stats.hp == round(goblin_data.major_stats["hp"] * expected.hp_mult)
        assert enemy.major_stats.attack == round(
            goblin_data.major_stats["attack"] * expected.attack_mult,
        )
        assert enemy.current_hp == enemy.major_stats.hp
        assert enemy.major_stats.energy == goblin_data.major_stats["energy"]


def test_event_triggered_combat_keeps_room_difficulty_none():
    mgr = SessionManager(seed=42)
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])
    event_option = LocationOption(
        location_id="event_1",
        name="Shrine",
        location_type=LocationType.EVENT,
        tags=(),
        event_id="cursed_shrine",
    )
    state = replace(
        state,
        exploration=replace(
            state.exploration,
            current_options=(event_option,),
            votes=(),
        ),
    )

    state = mgr.submit_location_vote(state, "p1", 0)
    state = mgr.resolve_location_choice(state)
    state = mgr.submit_event_vote(state, "p1", 0)
    state = mgr.resolve_event(state)

    assert state.phase == SessionPhase.IN_COMBAT
    assert state.combat is not None
    assert state.combat.room_difficulty is None
