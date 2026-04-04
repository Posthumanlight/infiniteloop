import pytest

from game.core.data_loader import clear_cache
from game.core.dice import SeededRNG
from game.core.enums import LocationType
from game.world.generator import generate_locations
from game.world.models import GenerationConfig

from tests.unit.conftest import make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Predetermined sets
# ---------------------------------------------------------------------------

def test_predetermined_set():
    config = GenerationConfig(predetermined_set_id="dark_cave_intro")
    rng = SeededRNG(42)
    players = [make_warrior("p1")]

    locations = generate_locations(power=1, players=players, rng=rng, config=config)
    assert len(locations) == 3  # dark_cave_intro has 3 locations
    assert locations[0].name == "Goblin Ambush"


# ---------------------------------------------------------------------------
# Random generation
# ---------------------------------------------------------------------------

def test_random_generation_count_in_range():
    config = GenerationConfig(count_min=2, count_max=5)
    rng = SeededRNG(42)
    players = [make_warrior("p1")]

    locations = generate_locations(power=1, players=players, rng=rng, config=config)
    assert 2 <= len(locations) <= 5


def test_random_generation_deterministic():
    config = GenerationConfig(count_min=3, count_max=3)
    players = [make_warrior("p1")]

    rng1 = SeededRNG(42)
    loc1 = generate_locations(power=1, players=players, rng=rng1, config=config)

    rng2 = SeededRNG(42)
    loc2 = generate_locations(power=1, players=players, rng=rng2, config=config)

    assert len(loc1) == len(loc2)
    for a, b in zip(loc1, loc2):
        assert a.location_type == b.location_type
        assert a.enemy_ids == b.enemy_ids
        assert a.event_id == b.event_id


def test_random_generation_has_combat_and_event():
    """With enough locations and balanced weight, we should see both types."""
    config = GenerationConfig(count_min=5, count_max=5, combat_weight=0.5)
    players = [make_warrior("p1")]

    types_seen: set[LocationType] = set()
    for seed in range(50):
        rng = SeededRNG(seed)
        locations = generate_locations(
            power=1, players=players, rng=rng, config=config, depth=5,
        )
        for loc in locations:
            types_seen.add(loc.location_type)

    assert LocationType.COMBAT in types_seen
    assert LocationType.EVENT in types_seen


def test_tag_filtering_enemies():
    """With 'fire' tag, only fire-tagged enemies should appear."""
    config = GenerationConfig(
        tags=("fire",), count_min=3, count_max=3, combat_weight=1.0,
    )
    players = [make_warrior("p1")]
    rng = SeededRNG(42)

    locations = generate_locations(power=1, players=players, rng=rng, config=config)
    for loc in locations:
        if loc.location_type == LocationType.COMBAT:
            # fire_imp and goblin (cave+forest, no fire) — only fire_imp should appear
            # Actually goblin has cave tag, fire_imp has fire+cave
            # With tags=("fire",), only fire_imp matches
            for eid in loc.enemy_ids:
                assert eid == "fire_imp", f"Expected fire_imp, got {eid}"


def test_all_combat_weight():
    config = GenerationConfig(count_min=3, count_max=3, combat_weight=1.0)
    players = [make_warrior("p1")]
    rng = SeededRNG(42)

    locations = generate_locations(power=1, players=players, rng=rng, config=config)
    assert all(loc.location_type == LocationType.COMBAT for loc in locations)


def test_combat_locations_have_enemies():
    config = GenerationConfig(count_min=3, count_max=3, combat_weight=1.0)
    players = [make_warrior("p1")]
    rng = SeededRNG(42)

    locations = generate_locations(power=1, players=players, rng=rng, config=config)
    for loc in locations:
        assert len(loc.enemy_ids) >= 1


def test_event_locations_have_event_id():
    config = GenerationConfig(count_min=5, count_max=5, combat_weight=0.0)
    players = [make_warrior("p1")]

    for seed in range(10):
        rng = SeededRNG(seed)
        locations = generate_locations(power=1, players=players, rng=rng, config=config)
        for loc in locations:
            # With combat_weight=0, events are attempted; fallback to combat if none eligible
            if loc.location_type == LocationType.EVENT:
                assert loc.event_id is not None
