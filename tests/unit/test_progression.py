"""Tests for the data-driven level-up system."""

from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats, MinorStats
from game.character.progression import apply_xp, compute_level, _apply_stat_gains
from game.core.data_loader import LevelScalingConfig, ProgressionConfig
from game.core.enums import EntityType
from game.character.inventory import Inventory


THRESHOLDS = (0, 100, 250, 500)

BASE_MAJOR = MajorStats(
    attack=10, hp=100, speed=10,
    crit_chance=0.1, crit_dmg=1.5,
    resistance=5, energy=50, mastery=5,
)

PROGRESSION = ProgressionConfig(
    xp_thresholds=THRESHOLDS,
    level_scaling={
        "warrior": LevelScalingConfig(
            class_id="warrior",
            stat_gains={"attack": 3, "hp": 15},
        ),
    },
)


def _make_player(**overrides) -> PlayerCharacter:
    defaults = dict(
        entity_id="p1",
        entity_name="Warrior",
        entity_type=EntityType.PLAYER,
        major_stats=BASE_MAJOR,
        minor_stats=MinorStats(values={}),
        current_hp=BASE_MAJOR.hp,
        current_energy=BASE_MAJOR.energy,
        player_class="warrior",
        skills=("slash",),
        inventory=Inventory(),
        level=1,
        xp=0,
    )
    defaults.update(overrides)
    return PlayerCharacter(**defaults)


# -- compute_level -----------------------------------------------------------

class TestComputeLevel:
    def test_zero_xp(self):
        assert compute_level(0, THRESHOLDS) == 2  # >= threshold[0]=0

    def test_below_second_threshold(self):
        assert compute_level(50, THRESHOLDS) == 2

    def test_exact_boundary(self):
        assert compute_level(100, THRESHOLDS) == 3

    def test_between_thresholds(self):
        assert compute_level(200, THRESHOLDS) == 3

    def test_max_level(self):
        assert compute_level(9999, THRESHOLDS) == 5  # past all 4 thresholds

    def test_empty_thresholds(self):
        assert compute_level(100, ()) == 1


# -- _apply_stat_gains -------------------------------------------------------

class TestApplyStatGains:
    def test_partial_gains(self):
        result = _apply_stat_gains(BASE_MAJOR, {"attack": 3, "hp": 15}, 2)
        assert result.attack == 10 + 6
        assert result.hp == 100 + 30
        # Unchanged stats
        assert result.speed == 10
        assert result.mastery == 5
        assert result.crit_chance == 0.1

    def test_empty_gains(self):
        result = _apply_stat_gains(BASE_MAJOR, {}, 5)
        assert result == BASE_MAJOR

    def test_unknown_stat_ignored(self):
        result = _apply_stat_gains(BASE_MAJOR, {"nonexistent": 10}, 1)
        assert result == BASE_MAJOR

    def test_float_stat_scaling(self):
        result = _apply_stat_gains(BASE_MAJOR, {"crit_chance": 0.02}, 3)
        assert abs(result.crit_chance - (0.1 + 0.06)) < 1e-9


# -- apply_xp ----------------------------------------------------------------

class TestApplyXp:
    def test_no_level_change(self):
        # Player already at level 2 (xp=50, past threshold[0]=0)
        level2_major = _apply_stat_gains(BASE_MAJOR, {"attack": 3, "hp": 15}, 1)
        player = _make_player(xp=50, level=2, major_stats=level2_major)
        result = apply_xp(player, 10, PROGRESSION, BASE_MAJOR)
        assert result.xp == 60
        assert result.level == 2
        assert result.major_stats == level2_major

    def test_level_up(self):
        # Player at level 2 (xp=90). Add 15 -> xp=105 -> level 3
        level2_major = _apply_stat_gains(BASE_MAJOR, {"attack": 3, "hp": 15}, 1)
        player = _make_player(xp=90, level=2, major_stats=level2_major)
        result = apply_xp(player, 15, PROGRESSION, BASE_MAJOR)
        assert result.xp == 105
        assert result.level == 3
        # Level 3 = 2 levels above base -> attack +6, hp +30
        assert result.major_stats.attack == 10 + 6
        assert result.major_stats.hp == 100 + 30
        # Non-scaling stats unchanged
        assert result.major_stats.mastery == 5

    def test_multi_level_jump(self):
        # Player at level 2 (xp=0, threshold[0]=0). Add 500 -> level 5
        level2_major = _apply_stat_gains(BASE_MAJOR, {"attack": 3, "hp": 15}, 1)
        player = _make_player(xp=0, level=2, major_stats=level2_major)
        result = apply_xp(player, 500, PROGRESSION, BASE_MAJOR)
        assert result.level == 5
        # 4 levels above base
        assert result.major_stats.attack == 10 + 12
        assert result.major_stats.hp == 100 + 60

    def test_hp_healed_on_level_up(self):
        level2_major = _apply_stat_gains(BASE_MAJOR, {"attack": 3, "hp": 15}, 1)
        player = _make_player(xp=90, level=2, major_stats=level2_major, current_hp=50)
        result = apply_xp(player, 15, PROGRESSION, BASE_MAJOR)
        # HP cap went from 115 to 130 (+15). Current was 50, gains 15 -> 65
        assert result.current_hp == 65

    def test_energy_unchanged_when_not_scaling(self):
        level2_major = _apply_stat_gains(BASE_MAJOR, {"attack": 3, "hp": 15}, 1)
        player = _make_player(xp=90, level=2, major_stats=level2_major, current_energy=30)
        result = apply_xp(player, 15, PROGRESSION, BASE_MAJOR)
        # Energy doesn't scale for warrior -> cap stays 50, current stays 30
        assert result.current_energy == 30

    def test_class_without_scaling_entry(self):
        player = _make_player(player_class="unknown_class", xp=90, level=2)
        result = apply_xp(player, 15, PROGRESSION, BASE_MAJOR)
        assert result.level == 3
        assert result.xp == 105
        # No scaling -> stats unchanged
        assert result.major_stats == BASE_MAJOR
