import pytest

import game.core.data_loader as data_loader
from game.core.data_loader import clear_cache, load_event, load_events, load_event_constants
from game.core.enums import EventType, OutcomeAction, OutcomeTarget


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_load_events_returns_all():
    events = load_events()
    assert len(events) >= 2
    assert "cursed_shrine" in events
    assert "river_with_surprise" in events


def test_load_event_by_id():
    event = load_event("cursed_shrine")
    assert event.event_id == "cursed_shrine"
    assert event.name == "Cursed Shrine"
    assert event.event_type == EventType.MULTIPLAYER
    assert event.initial_stage_id == "start"


def test_load_event_unknown_raises():
    with pytest.raises(KeyError, match="Unknown event"):
        load_event("nonexistent_event")


def test_event_stages_and_choices_parsed():
    event = load_event("cursed_shrine")
    stage = event.stages["start"]
    assert stage.title == "Cursed Shrine"
    assert len(stage.choices) == 2
    assert stage.choices[0].label == "Desecrate the shrine"
    assert stage.choices[0].index == 0
    assert stage.choices[1].index == 1


def test_outcome_enums_parsed():
    event = load_event("cursed_shrine")
    combat_outcome = event.stages["start"].choices[0].outcomes[0]
    assert combat_outcome.action == OutcomeAction.START_COMBAT
    assert combat_outcome.target == OutcomeTarget.ALL


def test_enemy_group_parsed():
    event = load_event("cursed_shrine")
    combat_choice = event.stages["start"].choices[0]
    assert len(combat_choice.outcomes) == 1
    assert combat_choice.outcomes[0].action == OutcomeAction.START_COMBAT
    assert "fire_imp" in combat_choice.outcomes[0].enemy_group


def test_empty_outcomes():
    event = load_event("cursed_shrine")
    walk_away = event.stages["start"].choices[1]
    assert len(walk_away.outcomes) == 0


def test_depth_range():
    event = load_event("cursed_shrine")
    assert event.min_depth == 2
    assert event.max_depth == 100


def test_weight():
    event = load_event("cursed_shrine")
    assert event.weight == 5


def test_multistage_next_stage_parsed(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(data_loader, "_load_toml", lambda _: {
        "events": {
            "test_event": {
                "name": "Test Event",
                "event_type": "multiplayer",
                "initial_stage_id": "start",
                "stages": {
                    "start": {
                        "title": "Start",
                        "description": "Begin.",
                        "choices": [{
                            "label": "Continue",
                            "description": "Move on.",
                            "next_stage": "finish",
                            "outcomes": [{
                                "action": "give_xp",
                                "target": "all",
                                "value": 1,
                            }],
                        }],
                    },
                    "finish": {
                        "title": "Finish",
                        "description": "End.",
                        "choices": [{
                            "label": "Done",
                            "description": "End event.",
                            "outcomes": [],
                        }],
                    },
                },
            },
        },
    })

    event = data_loader.load_event("test_event")
    choice = event.stages["start"].choices[0]
    assert choice.next_stage == "finish"
    assert choice.outcomes[0].action == OutcomeAction.GIVE_XP


def test_loader_rejects_legacy_top_level_choices(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(data_loader, "_load_toml", lambda _: {
        "events": {
            "legacy": {
                "name": "Legacy",
                "event_type": "multiplayer",
                "description": "Old shape.",
                "choices": [],
            },
        },
    })

    with pytest.raises(ValueError, match="top-level choices"):
        data_loader.load_events()


def test_loader_rejects_missing_initial_stage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(data_loader, "_load_toml", lambda _: {
        "events": {
            "bad": {
                "name": "Bad",
                "event_type": "multiplayer",
                "initial_stage_id": "missing",
                "stages": {
                    "start": {
                        "title": "Start",
                        "description": "Begin.",
                        "choices": [{
                            "label": "Done",
                            "description": "End event.",
                            "outcomes": [],
                        }],
                    },
                },
            },
        },
    })

    with pytest.raises(ValueError, match="initial_stage_id"):
        data_loader.load_events()


def test_loader_rejects_unknown_next_stage(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(data_loader, "_load_toml", lambda _: {
        "events": {
            "bad": {
                "name": "Bad",
                "event_type": "multiplayer",
                "stages": {
                    "start": {
                        "title": "Start",
                        "description": "Begin.",
                        "choices": [{
                            "label": "Continue",
                            "description": "Move on.",
                            "next_stage": "missing",
                            "outcomes": [],
                        }],
                    },
                },
            },
        },
    })

    with pytest.raises(ValueError, match="unknown next_stage"):
        data_loader.load_events()


def test_loader_rejects_next_stage_with_start_combat(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(data_loader, "_load_toml", lambda _: {
        "events": {
            "bad": {
                "name": "Bad",
                "event_type": "multiplayer",
                "stages": {
                    "start": {
                        "title": "Start",
                        "description": "Begin.",
                        "choices": [{
                            "label": "Fight later",
                            "description": "Invalid mix.",
                            "next_stage": "finish",
                            "outcomes": [{
                                "action": "start_combat",
                                "target": "all",
                                "enemy_group": ["goblin"],
                            }],
                        }],
                    },
                    "finish": {
                        "title": "Finish",
                        "description": "End.",
                        "choices": [{
                            "label": "Done",
                            "description": "End event.",
                            "outcomes": [],
                        }],
                    },
                },
            },
        },
    })

    with pytest.raises(ValueError, match="next_stage and start_combat"):
        data_loader.load_events()


def test_loader_rejects_stage_cycles(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(data_loader, "_load_toml", lambda _: {
        "events": {
            "bad": {
                "name": "Bad",
                "event_type": "multiplayer",
                "stages": {
                    "start": {
                        "title": "Start",
                        "description": "Begin.",
                        "choices": [{
                            "label": "Loop",
                            "description": "Loop.",
                            "next_stage": "start",
                            "outcomes": [],
                        }],
                    },
                },
            },
        },
    })

    with pytest.raises(ValueError, match="cycle"):
        data_loader.load_events()


def test_event_constants():
    constants = load_event_constants()
    assert constants["vote_timer_seconds"] == 30
    assert constants["max_choices"] == 4
    assert constants["min_choices"] == 2
