import pytest
from dataclasses import replace as dc_replace

from game.core.data_loader import clear_cache
from game.core.enums import ExplorationPhase, LocationType
from game.world.world_run import (
    compute_power,
    generate_choices,
    resolve_location_choice,
    start_run,
    submit_location_vote,
)
from game.world.models import GenerationConfig

from tests.unit.conftest import make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# start_run
# ---------------------------------------------------------------------------

def test_start_run():
    state = start_run("sess1", ["p1", "p2"], seed=42)
    assert state.session_id == "sess1"
    assert state.depth == 0
    assert state.phase == ExplorationPhase.CHOOSING
    assert state.player_ids == ("p1", "p2")
    assert state.current_options == ()
    assert state.votes == ()
    assert state.rng_state is not None


def test_start_run_rejects_empty():
    with pytest.raises(ValueError, match="At least one player"):
        start_run("sess1", [], seed=42)


# ---------------------------------------------------------------------------
# generate_choices
# ---------------------------------------------------------------------------

def test_generate_choices():
    state = start_run("sess1", ["p1"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=3, count_max=3, combat_weight=0.5)

    state = generate_choices(state, power=1, players=[player], config=config)
    assert len(state.current_options) == 3
    assert state.phase == ExplorationPhase.CHOOSING
    assert state.votes == ()  # Votes cleared


def test_generate_choices_predetermined():
    state = start_run("sess1", ["p1"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(predetermined_set_id="dark_cave_intro")

    state = generate_choices(state, power=1, players=[player], config=config)
    assert len(state.current_options) == 3
    assert state.current_options[0].name == "Goblin Ambush"


# ---------------------------------------------------------------------------
# submit_location_vote
# ---------------------------------------------------------------------------

def test_submit_vote():
    state = start_run("sess1", ["p1", "p2"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=3, count_max=3)
    state = generate_choices(state, power=1, players=[player], config=config)

    state = submit_location_vote(state, "p1", 0)
    assert len(state.votes) == 1
    assert state.votes[0].player_id == "p1"
    assert state.votes[0].location_index == 0


def test_submit_vote_rejects_duplicate():
    state = start_run("sess1", ["p1"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=2, count_max=2)
    state = generate_choices(state, power=1, players=[player], config=config)
    state = submit_location_vote(state, "p1", 0)

    with pytest.raises(ValueError, match="already voted"):
        submit_location_vote(state, "p1", 1)


def test_submit_vote_rejects_unknown_player():
    state = start_run("sess1", ["p1"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=2, count_max=2)
    state = generate_choices(state, power=1, players=[player], config=config)

    with pytest.raises(ValueError, match="not part of this exploration"):
        submit_location_vote(state, "p99", 0)


def test_submit_vote_rejects_invalid_index():
    state = start_run("sess1", ["p1"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=2, count_max=2)
    state = generate_choices(state, power=1, players=[player], config=config)

    with pytest.raises(ValueError, match="Invalid location index"):
        submit_location_vote(state, "p1", 99)


# ---------------------------------------------------------------------------
# resolve_location_choice
# ---------------------------------------------------------------------------

def test_resolve_solo():
    state = start_run("sess1", ["p1"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=3, count_max=3)
    state = generate_choices(state, power=1, players=[player], config=config)
    state = submit_location_vote(state, "p1", 1)

    new_state, picked = resolve_location_choice(state)
    assert new_state.phase == ExplorationPhase.RESOLVING
    assert new_state.depth == 1
    assert picked == state.current_options[1]
    assert picked.location_id in new_state.history


def test_resolve_multiplayer_majority():
    state = start_run("sess1", ["p1", "p2", "p3"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=3, count_max=3)
    state = generate_choices(state, power=3, players=[player], config=config)

    state = submit_location_vote(state, "p1", 0)
    state = submit_location_vote(state, "p2", 0)
    state = submit_location_vote(state, "p3", 2)

    _, picked = resolve_location_choice(state)
    assert picked == state.current_options[0]  # 2 votes vs 1


def test_resolve_tie_deterministic():
    state = start_run("sess1", ["p1", "p2"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=3, count_max=3)
    state = generate_choices(state, power=2, players=[player], config=config)

    state = submit_location_vote(state, "p1", 0)
    state = submit_location_vote(state, "p2", 1)
    _, picked1 = resolve_location_choice(state)

    # Same setup again
    state2 = start_run("sess1", ["p1", "p2"], seed=42)
    state2 = generate_choices(state2, power=2, players=[player], config=config)
    state2 = submit_location_vote(state2, "p1", 0)
    state2 = submit_location_vote(state2, "p2", 1)
    _, picked2 = resolve_location_choice(state2)

    assert picked1.location_type == picked2.location_type


def test_resolve_rejects_no_votes():
    state = start_run("sess1", ["p1"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=2, count_max=2)
    state = generate_choices(state, power=1, players=[player], config=config)

    with pytest.raises(ValueError, match="no votes"):
        resolve_location_choice(state)


def test_depth_increments():
    state = start_run("sess1", ["p1"], seed=42)
    player = make_warrior("p1")
    config = GenerationConfig(count_min=2, count_max=2)

    # First round
    state = generate_choices(state, power=1, players=[player], config=config)
    state = submit_location_vote(state, "p1", 0)
    state, _ = resolve_location_choice(state)
    assert state.depth == 1

    # Second round
    state = generate_choices(state, power=1, players=[player], config=config)
    state = submit_location_vote(state, "p1", 0)
    state, _ = resolve_location_choice(state)
    assert state.depth == 2
    assert len(state.history) == 2


# ---------------------------------------------------------------------------
# compute_power
# ---------------------------------------------------------------------------

def test_compute_power_single():
    player = make_warrior("p1")  # level=1
    assert compute_power([player]) == 1  # 1 * 1


def test_compute_power_multi():
    p1 = make_warrior("p1")  # level=1
    p2 = dc_replace(make_warrior("p2"), level=3)
    # 2 players * avg_level(floor(4/2)=2) = 4
    assert compute_power([p1, p2]) == 4


def test_compute_power_empty():
    assert compute_power([]) == 0
