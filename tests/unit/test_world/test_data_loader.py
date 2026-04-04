import pytest

from game.core.data_loader import (
    clear_cache,
    load_enemies,
    load_location_set,
    load_location_sets,
    load_location_status,
    load_location_statuses,
)
from game.core.enums import LocationType


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Enemy tags
# ---------------------------------------------------------------------------

def test_enemies_have_tags():
    enemies = load_enemies()
    goblin = enemies["goblin"]
    assert "forest" in goblin.tags
    assert "cave" in goblin.tags


def test_enemy_without_tags_gets_empty():
    """All current enemies have tags, but the loader handles missing gracefully."""
    enemies = load_enemies()
    for enemy in enemies.values():
        assert isinstance(enemy.tags, tuple)


# ---------------------------------------------------------------------------
# Location statuses
# ---------------------------------------------------------------------------

def test_load_statuses():
    statuses = load_location_statuses()
    assert "dim_light" in statuses
    assert "burning_ground" in statuses


def test_status_fields():
    status = load_location_status("dim_light")
    assert status.name == "Dim Light"
    assert status.affects == "all"
    assert "dark" in status.tags
    assert "crit_chance" in status.stat_modifiers


def test_unknown_status_raises():
    with pytest.raises(KeyError, match="Unknown location status"):
        load_location_status("nonexistent")


# ---------------------------------------------------------------------------
# Location sets
# ---------------------------------------------------------------------------

def test_load_sets():
    sets = load_location_sets()
    assert "dark_cave_intro" in sets


def test_set_locations():
    loc_set = load_location_set("dark_cave_intro")
    assert len(loc_set.locations) == 3
    types = [loc.location_type for loc in loc_set.locations]
    assert LocationType.COMBAT in types
    assert LocationType.EVENT in types


def test_set_combat_location_has_enemies():
    loc_set = load_location_set("dark_cave_intro")
    combat_locs = [l for l in loc_set.locations if l.location_type == LocationType.COMBAT]
    assert len(combat_locs) >= 1
    assert len(combat_locs[0].enemy_ids) > 0


def test_set_event_location_has_event_id():
    loc_set = load_location_set("dark_cave_intro")
    event_locs = [l for l in loc_set.locations if l.location_type == LocationType.EVENT]
    assert len(event_locs) >= 1
    assert event_locs[0].event_id is not None


def test_unknown_set_raises():
    with pytest.raises(KeyError, match="Unknown location set"):
        load_location_set("nonexistent")
