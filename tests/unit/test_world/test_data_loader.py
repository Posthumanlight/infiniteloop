import pytest

from game.core.data_loader import (
    clear_cache,
    load_enemies,
    load_location_set,
    load_location_sets,
    load_location_status,
    load_location_statuses,
)
from game.core.enums import CombatLocationType, EnemyCombatType, LocationType


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# Enemy tags / combat types
# ---------------------------------------------------------------------------

def test_enemies_have_tags():
    enemies = load_enemies()
    goblin = enemies["goblin"]
    assert "forest" in goblin.tags
    assert "cave" in goblin.tags


def test_enemies_parse_combat_type():
    enemies = load_enemies()
    assert enemies["goblin"].combat_type == EnemyCombatType.NORMAL
    assert enemies["fire_imp"].combat_type == EnemyCombatType.ELITE
    assert enemies["goblin_boss"].combat_type == EnemyCombatType.BOSS


def test_enemy_tags_are_tuples():
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
    sets_ = load_location_sets()
    assert "dark_cave_intro" in sets_


def test_set_locations():
    loc_set = load_location_set("dark_cave_intro")
    assert len(loc_set.locations) == 3
    types = [loc.location_type for loc in loc_set.locations]
    assert LocationType.COMBAT in types
    assert LocationType.EVENT in types


def test_set_combat_locations_have_enemies_and_optional_combat_type():
    loc_set = load_location_set("dark_cave_intro")
    combat_locs = [loc for loc in loc_set.locations if loc.location_type == LocationType.COMBAT]
    assert len(combat_locs) == 2
    assert all(loc.enemy_ids for loc in combat_locs)
    assert all(loc.combat_type == CombatLocationType.NORMAL for loc in combat_locs)


def test_set_event_location_has_event_id_and_no_combat_type():
    loc_set = load_location_set("dark_cave_intro")
    event_locs = [loc for loc in loc_set.locations if loc.location_type == LocationType.EVENT]
    assert len(event_locs) == 1
    assert event_locs[0].event_id == "cursed_shrine"
    assert event_locs[0].combat_type is None


def test_unknown_set_raises():
    with pytest.raises(KeyError, match="Unknown location set"):
        load_location_set("nonexistent")
