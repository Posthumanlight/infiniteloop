import pytest

from game.core.data_loader import clear_cache, load_event
from game.core.dice import SeededRNG
from game.core.enums import EventPhase, EventType, OutcomeAction
from game.events.engine import resolve_event, select_event, start_event, submit_vote
from game.events.models import EventDef, EventRequirements

from tests.unit.conftest import make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.fixture
def fountain_event() -> EventDef:
    return load_event("mysterious_fountain")


@pytest.fixture
def chest_event() -> EventDef:
    return load_event("trapped_chest")


# ---------------------------------------------------------------------------
# start_event
# ---------------------------------------------------------------------------


def test_start_event_multiplayer(fountain_event: EventDef):
    state = start_event("sess1", fountain_event, ["p1", "p2", "p3"], seed=42)
    assert state.phase == EventPhase.PRESENTING
    assert state.player_ids == ("p1", "p2", "p3")
    assert state.votes == ()
    assert state.resolution is None
    assert state.rng_state is not None


def test_start_event_solo(chest_event: EventDef):
    state = start_event("sess1", chest_event, ["p1"], seed=42)
    assert state.phase == EventPhase.PRESENTING
    assert state.player_ids == ("p1",)


def test_start_event_solo_rejects_multiple_players(chest_event: EventDef):
    with pytest.raises(ValueError, match="Solo events require exactly 1 player"):
        start_event("sess1", chest_event, ["p1", "p2"], seed=42)


def test_start_event_rejects_empty_players(fountain_event: EventDef):
    with pytest.raises(ValueError, match="At least one player"):
        start_event("sess1", fountain_event, [], seed=42)


# ---------------------------------------------------------------------------
# submit_vote
# ---------------------------------------------------------------------------


def test_submit_vote(fountain_event: EventDef):
    state = start_event("sess1", fountain_event, ["p1", "p2"], seed=42)
    state = submit_vote(state, "p1", 0)
    assert len(state.votes) == 1
    assert state.votes[0].player_id == "p1"
    assert state.votes[0].choice_index == 0


def test_submit_vote_rejects_duplicate(fountain_event: EventDef):
    state = start_event("sess1", fountain_event, ["p1", "p2"], seed=42)
    state = submit_vote(state, "p1", 0)
    with pytest.raises(ValueError, match="already voted"):
        submit_vote(state, "p1", 1)


def test_submit_vote_rejects_unknown_player(fountain_event: EventDef):
    state = start_event("sess1", fountain_event, ["p1"], seed=42)
    with pytest.raises(ValueError, match="not part of this event"):
        submit_vote(state, "p99", 0)


def test_submit_vote_rejects_invalid_choice(fountain_event: EventDef):
    state = start_event("sess1", fountain_event, ["p1"], seed=42)
    with pytest.raises(ValueError, match="Invalid choice index"):
        submit_vote(state, "p1", 99)


def test_submit_vote_rejects_negative_choice(fountain_event: EventDef):
    state = start_event("sess1", fountain_event, ["p1"], seed=42)
    with pytest.raises(ValueError, match="Invalid choice index"):
        submit_vote(state, "p1", -1)


# ---------------------------------------------------------------------------
# resolve_event
# ---------------------------------------------------------------------------


def test_resolve_solo(chest_event: EventDef):
    player = make_warrior("p1")
    state = start_event("sess1", chest_event, ["p1"], seed=42)
    state = submit_vote(state, "p1", 0)  # "Force it open"
    new_state, resolution = resolve_event(state, [player])

    assert new_state.phase == EventPhase.RESOLVED
    assert resolution.winning_choice_index == 0
    assert resolution.winning_choice_label == "Force it open"
    assert resolution.was_tie is False
    assert resolution.vote_counts == {0: 1}
    assert len(resolution.outcomes) > 0


def test_resolve_multiplayer_majority(fountain_event: EventDef):
    players = [make_warrior(f"p{i}") for i in range(3)]
    state = start_event("sess1", fountain_event, ["p0", "p1", "p2"], seed=42)
    state = submit_vote(state, "p0", 0)  # Drink
    state = submit_vote(state, "p1", 0)  # Drink
    state = submit_vote(state, "p2", 1)  # Toss coin

    _, resolution = resolve_event(state, players)
    assert resolution.winning_choice_index == 0
    assert resolution.was_tie is False
    assert resolution.vote_counts == {0: 2, 1: 1}


def test_resolve_tie_breaking_deterministic(fountain_event: EventDef):
    """With a fixed seed, tie-breaking should be deterministic."""
    players = [make_warrior(f"p{i}") for i in range(4)]
    state = start_event("sess1", fountain_event, ["p0", "p1", "p2", "p3"], seed=42)
    state = submit_vote(state, "p0", 0)
    state = submit_vote(state, "p1", 1)
    state = submit_vote(state, "p2", 0)
    state = submit_vote(state, "p3", 1)

    _, resolution = resolve_event(state, players)
    assert resolution.was_tie is True
    # Run again with same seed — should pick same winner
    state2 = start_event("sess1", fountain_event, ["p0", "p1", "p2", "p3"], seed=42)
    state2 = submit_vote(state2, "p0", 0)
    state2 = submit_vote(state2, "p1", 1)
    state2 = submit_vote(state2, "p2", 0)
    state2 = submit_vote(state2, "p3", 1)
    _, resolution2 = resolve_event(state2, players)
    assert resolution.winning_choice_index == resolution2.winning_choice_index


def test_resolve_party_of_one_multiplayer(fountain_event: EventDef):
    """Party of 1 in a multiplayer event works fine."""
    player = make_warrior("p1")
    # Multiplayer event but only one player — should work
    state = start_event("sess1", fountain_event, ["p1"], seed=42)
    state = submit_vote(state, "p1", 0)
    new_state, resolution = resolve_event(state, [player])
    assert new_state.phase == EventPhase.RESOLVED
    assert resolution.winning_choice_index == 0


def test_resolve_rejects_no_votes(fountain_event: EventDef):
    state = start_event("sess1", fountain_event, ["p1"], seed=42)
    with pytest.raises(ValueError, match="no votes"):
        resolve_event(state, [make_warrior("p1")])


def test_resolve_rejects_already_resolved(fountain_event: EventDef):
    player = make_warrior("p1")
    state = start_event("sess1", fountain_event, ["p1"], seed=42)
    state = submit_vote(state, "p1", 0)
    resolved_state, _ = resolve_event(state, [player])
    with pytest.raises(ValueError, match="not in PRESENTING phase"):
        resolve_event(resolved_state, [player])


def test_resolve_partial_votes(fountain_event: EventDef):
    """Resolve with only some players having voted."""
    players = [make_warrior(f"p{i}") for i in range(3)]
    state = start_event("sess1", fountain_event, ["p0", "p1", "p2"], seed=42)
    state = submit_vote(state, "p0", 1)
    # p1 and p2 haven't voted (timeout scenario)
    _, resolution = resolve_event(state, players)
    assert resolution.winning_choice_index == 1


# ---------------------------------------------------------------------------
# select_event
# ---------------------------------------------------------------------------


def test_select_event_filters_by_depth():
    from game.core.data_loader import load_events

    all_events = list(load_events().values())
    rng = SeededRNG(42)
    party = [make_warrior("p1")]

    # Depth 0 should exclude trapped_chest (min_depth=2)
    selected_ids: set[str] = set()
    for _ in range(50):
        ev = select_event(all_events, depth=0, party=party, rng=rng)
        if ev:
            selected_ids.add(ev.event_id)
    assert "trapped_chest" not in selected_ids


def test_select_event_filters_by_level():
    from game.core.data_loader import load_events
    from dataclasses import replace as dc_replace

    all_events = list(load_events().values())
    rng = SeededRNG(42)
    # Level 1 player — trapped_chest requires min_level=2
    low_level_player = dc_replace(make_warrior("p1"), level=1)
    party = [low_level_player]

    selected_ids: set[str] = set()
    for _ in range(50):
        ev = select_event(all_events, depth=5, party=party, rng=rng)
        if ev:
            selected_ids.add(ev.event_id)
    assert "trapped_chest" not in selected_ids


def test_select_event_returns_none_when_nothing_eligible():
    rng = SeededRNG(42)
    party = [make_warrior("p1")]
    result = select_event([], depth=5, party=party, rng=rng)
    assert result is None


def test_select_event_respects_weight():
    """Higher weight events should be selected more often."""
    from game.core.data_loader import load_events

    all_events = list(load_events().values())
    rng = SeededRNG(42)
    party = [make_warrior("p1")]

    counts: dict[str, int] = {}
    for _ in range(200):
        ev = select_event(all_events, depth=5, party=party, rng=rng)
        if ev:
            counts[ev.event_id] = counts.get(ev.event_id, 0) + 1

    # mysterious_fountain (weight=10) should appear more than cursed_shrine (weight=5)
    assert counts.get("mysterious_fountain", 0) > counts.get("cursed_shrine", 0)
