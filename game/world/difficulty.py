from dataclasses import dataclass

from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats
from game.core.data_loader import load_world_difficulty_constants


@dataclass(frozen=True)
class RoomDifficultyModifier:
    scalar: float
    average_level: float
    party_size: int
    power: int
    hp_mult: float = 1.0
    attack_mult: float = 1.0
    speed_mult: float = 1.0
    resistance_mult: float = 1.0
    mastery_mult: float = 1.0

    @classmethod
    def identity(cls) -> "RoomDifficultyModifier":
        return cls(
            scalar=1.0,
            average_level=1.0,
            party_size=1,
            power=1,
        )


def build_room_difficulty(
    players: list[PlayerCharacter],
    power: int,
) -> RoomDifficultyModifier:
    if not players:
        return RoomDifficultyModifier.identity()

    cfg = load_world_difficulty_constants()
    average_level = sum(player.level for player in players) / len(players)
    party_size = len(players)

    scalar = min(
        cfg["max_scalar"],
        cfg["base_scalar"]
        + max(0.0, average_level - 1.0) * cfg["per_avg_level"]
        + max(0, party_size - 1) * cfg["per_extra_player"],
    )

    weights = cfg["stat_weights"]
    return RoomDifficultyModifier(
        scalar=scalar,
        average_level=average_level,
        party_size=party_size,
        power=power,
        hp_mult=1.0 + (scalar - 1.0) * weights["hp"],
        attack_mult=1.0 + (scalar - 1.0) * weights["attack"],
        speed_mult=1.0 + (scalar - 1.0) * weights["speed"],
        resistance_mult=1.0 + (scalar - 1.0) * weights["resistance"],
        mastery_mult=1.0 + (scalar - 1.0) * weights["mastery"],
    )


def apply_room_difficulty(
    major: MajorStats,
    room_difficulty: RoomDifficultyModifier | None,
) -> MajorStats:
    if room_difficulty is None:
        return major

    return MajorStats(
        attack=max(1, round(major.attack * room_difficulty.attack_mult)),
        hp=max(1, round(major.hp * room_difficulty.hp_mult)),
        speed=max(1, round(major.speed * room_difficulty.speed_mult)),
        crit_chance=major.crit_chance,
        crit_dmg=major.crit_dmg,
        resistance=max(
            0,
            round(major.resistance * room_difficulty.resistance_mult),
        ),
        energy=major.energy,
        mastery=max(0, round(major.mastery * room_difficulty.mastery_mult)),
    )


def describe_room_difficulty(diff: RoomDifficultyModifier | None) -> str:
    if diff is None:
        return "difficulty=none"
    return (
        f"difficulty scalar={diff.scalar:.2f} "
        f"lvl={diff.average_level:.1f} "
        f"party={diff.party_size} "
        f"hp={diff.hp_mult:.2f} atk={diff.attack_mult:.2f}"
    )
