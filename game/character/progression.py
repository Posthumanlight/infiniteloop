"""Pure level-up logic. No I/O — all data passed in as parameters."""

from dataclasses import replace

from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats
from game.core.data_loader import ProgressionConfig


def compute_level(total_xp: int, thresholds: tuple[int, ...]) -> int:
    """Return the level corresponding to total cumulative XP.

    Level 1 is the base. Each threshold index *i* represents the
    cumulative XP needed to reach level *i* + 1.
    """
    level = 1
    for threshold in thresholds:
        if total_xp >= threshold:
            level += 1
        else:
            break
    return level


def _apply_stat_gains(
    base_stats: MajorStats,
    stat_gains: dict[str, float],
    levels_above_base: int,
) -> MajorStats:
    """Apply per-level stat gains for *levels_above_base* levels.

    Only stats present in *stat_gains* are modified — this is the core
    of the partial-definition requirement.
    """
    changes: dict[str, object] = {}
    for stat_name, gain_per_level in stat_gains.items():
        if not hasattr(base_stats, stat_name):
            continue
        base_value = getattr(base_stats, stat_name)
        if isinstance(base_value, int):
            changes[stat_name] = base_value + int(gain_per_level * levels_above_base)
        else:
            changes[stat_name] = base_value + gain_per_level * levels_above_base
    return replace(base_stats, **changes)


def apply_xp(
    player: PlayerCharacter,
    xp_gained: int,
    progression: ProgressionConfig,
    base_major_stats: MajorStats,
) -> tuple[PlayerCharacter, list[int]]:
    """Award XP and level up if thresholds are crossed.

    Stats are always recalculated from *base_major_stats* + (level-1) * gains
    to avoid drift on multi-level jumps.  When HP/energy cap increases the
    player gains the difference immediately.

    Returns:
        (updated_player, crossed_levels) — crossed_levels lists the new level
        numbers the player reached this call (empty if no level-up).
    """
    new_xp = player.xp + xp_gained
    new_level = compute_level(new_xp, progression.xp_thresholds)

    if new_level == player.level:
        return replace(player, xp=new_xp), []

    crossed_levels = list(range(player.level + 1, new_level + 1))

    levels_above_base = new_level - 1
    scaling = progression.level_scaling.get(player.player_class)
    stat_gains = scaling.stat_gains if scaling else {}

    new_major = _apply_stat_gains(base_major_stats, stat_gains, levels_above_base)

    hp_increase = new_major.hp - player.major_stats.hp
    new_current_hp = min(player.current_hp + max(0, hp_increase), new_major.hp)

    energy_increase = new_major.energy - player.major_stats.energy
    new_current_energy = min(
        player.current_energy + max(0, energy_increase), new_major.energy,
    )

    updated = replace(
        player,
        xp=new_xp,
        level=new_level,
        major_stats=new_major,
        current_hp=new_current_hp,
        current_energy=new_current_energy,
    )
    return updated, crossed_levels
