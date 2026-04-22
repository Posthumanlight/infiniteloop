import pytest

from game.core.dice import SeededRNG
from game.core.enums import EventPhase, EventType, OutcomeAction, OutcomeTarget
from game.events.engine import (
    get_current_stage,
    resolve_event,
    select_event,
    start_event,
    submit_vote,
)
from game.events.models import (
    ChoiceDef,
    EventDef,
    EventRequirements,
    EventStageDef,
    OutcomeDef,
)

from tests.unit.conftest import make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    yield


def _choice(
    index: int,
    label: str,
    outcomes: tuple[OutcomeDef, ...] = (),
    *,
    next_stage: str | None = None,
) -> ChoiceDef:
    return ChoiceDef(
        index=index,
        label=label,
        description=f"{label}.",
        outcomes=outcomes,
        next_stage=next_stage,
    )


def _stage(
    stage_id: str,
    choices: tuple[ChoiceDef, ...],
    *,
    title: str | None = None,
) -> EventStageDef:
    return EventStageDef(
        stage_id=stage_id,
        title=title or stage_id.title(),
        description=f"{stage_id} description.",
        choices=choices,
    )


def _event(
    event_id: str,
    stages: dict[str, EventStageDef],
    *,
    name: str = "Test Event",
    event_type: EventType = EventType.MULTIPLAYER,
    initial_stage_id: str = "start",
    min_depth: int = 0,
    max_depth: int = 999,
    weight: int = 10,
    requirements: EventRequirements = EventRequirements(),
) -> EventDef:
    return EventDef(
        event_id=event_id,
        name=name,
        event_type=event_type,
        stages=stages,
        initial_stage_id=initial_stage_id,
        min_depth=min_depth,
        max_depth=max_depth,
        weight=weight,
        requirements=requirements,
    )


@pytest.fixture
def fountain_event() -> EventDef:
    choices = (
        _choice(0, "Drink from the fountain", (
            OutcomeDef(
                action=OutcomeAction.HEAL,
                target=OutcomeTarget.ALL,
                expr="target.hp * 0.25",
            ),
        )),
        _choice(1, "Toss a coin", (
            OutcomeDef(
                action=OutcomeAction.GIVE_XP,
                target=OutcomeTarget.ALL,
                value=5,
            ),
        )),
        _choice(2, "Smash the fountain", (
            OutcomeDef(
                action=OutcomeAction.START_COMBAT,
                target=OutcomeTarget.ALL,
                enemy_group=("water_elemental",),
            ),
        )),
        _choice(3, "Walk away"),
    )
    return _event(
        "mysterious_fountain",
        {"start": _stage("start", choices, title="Mysterious Fountain")},
        name="Mysterious Fountain",
    )


@pytest.fixture
def chest_event() -> EventDef:
    return _event(
        "trapped_chest",
        {"start": _stage("start", (
            _choice(0, "Force it open", (
                OutcomeDef(
                    action=OutcomeAction.DAMAGE,
                    target=OutcomeTarget.ALL,
                    value=5,
                ),
            )),
            _choice(1, "Leave it"),
        ))},
        name="Trapped Chest",
        event_type=EventType.SOLO,
        min_depth=2,
        max_depth=8,
        requirements=EventRequirements(min_level=2),
    )


@pytest.fixture
def multistage_event() -> EventDef:
    return _event(
        "demon_bargain",
        {
            "start": _stage("start", (
                _choice(0, "Ask the price", (
                    OutcomeDef(
                        action=OutcomeAction.GIVE_XP,
                        target=OutcomeTarget.ALL,
                        value=7,
                    ),
                ), next_stage="price"),
                _choice(1, "Refuse"),
            ), title="The Offer"),
            "price": _stage("price", (
                _choice(0, "Accept", (
                    OutcomeDef(
                        action=OutcomeAction.RESTORE_ENERGY,
                        target=OutcomeTarget.ALL,
                        value=3,
                    ),
                )),
            ), title="The Price"),
        },
        name="Demon Bargain",
    )


# ---------------------------------------------------------------------------
# start_event
# ---------------------------------------------------------------------------


def test_start_event_multiplayer(fountain_event: EventDef):
    state = start_event("sess1", fountain_event, ["p1", "p2", "p3"], seed=42)
    assert state.phase == EventPhase.PRESENTING
    assert state.player_ids == ("p1", "p2", "p3")
    assert state.current_stage_id == "start"
    assert get_current_stage(state).title == "Mysterious Fountain"
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
    assert new_state.votes == ()
    assert new_state.history == (resolution,)
    assert resolution.stage_id == "start"
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


def test_resolve_nonterminal_stage_advances_and_resets_votes(
    multistage_event: EventDef,
):
    players = [make_warrior("p1"), make_warrior("p2")]
    state = start_event("sess1", multistage_event, ["p1", "p2"], seed=42)
    state = submit_vote(state, "p1", 0)
    state = submit_vote(state, "p2", 0)

    new_state, resolution = resolve_event(state, players)

    assert new_state.phase == EventPhase.PRESENTING
    assert new_state.current_stage_id == "price"
    assert new_state.votes == ()
    assert new_state.resolution is None
    assert new_state.history == (resolution,)
    assert resolution.stage_id == "start"
    assert resolution.next_stage == "price"
    assert len(resolution.outcomes) == 2


def test_submit_vote_uses_current_stage_choices(multistage_event: EventDef):
    players = [make_warrior("p1")]
    state = start_event("sess1", multistage_event, ["p1"], seed=42)
    state = submit_vote(state, "p1", 0)
    state, _ = resolve_event(state, players)

    with pytest.raises(ValueError, match="Invalid choice index"):
        submit_vote(state, "p1", 1)

    state = submit_vote(state, "p1", 0)
    resolved_state, resolution = resolve_event(state, players)
    assert resolved_state.phase == EventPhase.RESOLVED
    assert resolution.stage_id == "price"
    assert resolved_state.history[-1] == resolution


# ---------------------------------------------------------------------------
# select_event
# ---------------------------------------------------------------------------


def test_select_event_filters_by_depth(
    fountain_event: EventDef,
    chest_event: EventDef,
):
    all_events = [fountain_event, chest_event]
    rng = SeededRNG(42)
    party = [make_warrior("p1")]

    # Depth 0 should exclude trapped_chest (min_depth=2)
    selected_ids: set[str] = set()
    for _ in range(50):
        ev = select_event(all_events, depth=0, party=party, rng=rng)
        if ev:
            selected_ids.add(ev.event_id)
    assert "trapped_chest" not in selected_ids


def test_select_event_filters_by_level(
    fountain_event: EventDef,
    chest_event: EventDef,
):
    from dataclasses import replace as dc_replace

    all_events = [fountain_event, chest_event]
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
    low_weight = _event(
        "low",
        {"start": _stage("start", (_choice(0, "Done"),))},
        weight=1,
    )
    high_weight = _event(
        "high",
        {"start": _stage("start", (_choice(0, "Done"),))},
        weight=50,
    )
    all_events = [low_weight, high_weight]
    rng = SeededRNG(42)
    party = [make_warrior("p1")]

    counts: dict[str, int] = {}
    for _ in range(200):
        ev = select_event(all_events, depth=5, party=party, rng=rng)
        if ev:
            counts[ev.event_id] = counts.get(ev.event_id, 0) + 1

    assert counts.get("high", 0) > counts.get("low", 0)
