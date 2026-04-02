import pytest

from game.core.data_loader import clear_cache, load_event, load_events, load_event_constants
from game.core.enums import EventType, OutcomeAction, OutcomeTarget


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_load_events_returns_all():
    events = load_events()
    assert len(events) >= 5
    assert "mysterious_fountain" in events
    assert "trapped_chest" in events


def test_load_event_by_id():
    event = load_event("mysterious_fountain")
    assert event.event_id == "mysterious_fountain"
    assert event.name == "Mysterious Fountain"
    assert event.event_type == EventType.MULTIPLAYER


def test_load_event_unknown_raises():
    with pytest.raises(KeyError, match="Unknown event"):
        load_event("nonexistent_event")


def test_event_choices_parsed():
    event = load_event("mysterious_fountain")
    assert len(event.choices) == 4
    assert event.choices[0].label == "Drink from the fountain"
    assert event.choices[0].index == 0
    assert event.choices[3].index == 3


def test_outcome_enums_parsed():
    event = load_event("mysterious_fountain")
    heal_outcome = event.choices[0].outcomes[0]
    assert heal_outcome.action == OutcomeAction.HEAL
    assert heal_outcome.target == OutcomeTarget.ALL
    assert heal_outcome.expr == "target.hp * 0.25"


def test_solo_event_type():
    event = load_event("trapped_chest")
    assert event.event_type == EventType.SOLO


def test_requirements_parsed():
    event = load_event("trapped_chest")
    assert event.requirements.min_level == 2


def test_enemy_group_parsed():
    event = load_event("mysterious_fountain")
    combat_choice = event.choices[2]  # "Smash the fountain"
    assert len(combat_choice.outcomes) == 1
    assert combat_choice.outcomes[0].action == OutcomeAction.START_COMBAT
    assert "water_elemental" in combat_choice.outcomes[0].enemy_group


def test_empty_outcomes():
    event = load_event("mysterious_fountain")
    walk_away = event.choices[3]  # "Walk away"
    assert len(walk_away.outcomes) == 0


def test_depth_range():
    event = load_event("trapped_chest")
    assert event.min_depth == 2
    assert event.max_depth == 8


def test_weight():
    event = load_event("mysterious_fountain")
    assert event.weight == 10


def test_event_constants():
    constants = load_event_constants()
    assert constants["vote_timer_seconds"] == 30
    assert constants["max_choices"] == 4
    assert constants["min_choices"] == 2
