from game.character.base_entity import BaseEntity
from game.core.dice import SeededRNG


def roll_initiative(entity: BaseEntity, rng: SeededRNG, dice_size: int) -> int:
    return entity.major_stats.speed + rng.d(dice_size)


def build_turn_order(
    entities: dict[str, BaseEntity],
    rng: SeededRNG,
    dice_size: int,
) -> tuple[str, ...]:
    rolls: list[tuple[str, int, int]] = []
    for eid, entity in entities.items():
        primary = roll_initiative(entity, rng, dice_size)
        tiebreak = rng.d(dice_size)
        rolls.append((eid, primary, tiebreak))
    rolls.sort(key=lambda r: (r[1], r[2]), reverse=True)
    return tuple(r[0] for r in rolls)
