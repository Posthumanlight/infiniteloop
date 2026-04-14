from game.combat.effects import get_effective_major_stat
from game.combat.models import CombatState
from game.core.enums import CombatPhase
from game.character.base_entity import BaseEntity
from game.core.dice import SeededRNG


def _initiative_state(entities: dict[str, BaseEntity]) -> CombatState:
    return CombatState(
        combat_id="initiative-preview",
        session_id="initiative-preview",
        round_number=1,
        turn_order=tuple(entities.keys()),
        current_turn_index=0,
        entities=entities,
        phase=CombatPhase.ACTING,
    )


def roll_initiative(
    entity: BaseEntity,
    rng: SeededRNG,
    dice_size: int,
    state: CombatState | None = None,
) -> int:
    speed = (
        get_effective_major_stat(state, entity.entity_id, "speed")
        if state is not None
        else entity.major_stats.speed
    )
    return int(speed) + rng.d(dice_size)


def build_turn_order(
    entities: dict[str, BaseEntity],
    rng: SeededRNG,
    dice_size: int,
) -> tuple[str, ...]:
    state = _initiative_state(entities)
    rolls: list[tuple[str, int, int]] = []
    for eid, entity in entities.items():
        primary = roll_initiative(entity, rng, dice_size, state)
        tiebreak = rng.d(dice_size)
        rolls.append((eid, primary, tiebreak))
    rolls.sort(key=lambda r: (r[1], r[2]), reverse=True)
    return tuple(r[0] for r in rolls)
