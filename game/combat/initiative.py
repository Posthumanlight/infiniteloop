from game.combat.models import CombatState, TurnOrder
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
    from game.combat.effects import get_effective_major_stat

    speed = (
        get_effective_major_stat(state, entity.entity_id, "speed")
        if state is not None
        else entity.major_stats.speed
    )
    return int(speed) + rng.d(dice_size)


def roll_initiative_pair(
    entity: BaseEntity,
    rng: SeededRNG,
    dice_size: int,
    state: CombatState | None = None,
) -> tuple[int, int]:
    primary = roll_initiative(entity, rng, dice_size, state)
    return primary, rng.d(dice_size)


def build_turn_order_with_scores(
    entities: dict[str, BaseEntity],
    rng: SeededRNG,
    dice_size: int,
) -> tuple[TurnOrder, dict[str, tuple[int, int]]]:
    state = _initiative_state(entities)
    rolls: list[tuple[str, int, int]] = []
    for eid, entity in entities.items():
        primary, tiebreak = roll_initiative_pair(entity, rng, dice_size, state)
        rolls.append((eid, primary, tiebreak))
    rolls.sort(key=lambda r: (r[1], r[2]), reverse=True)
    order = tuple(r[0] for r in rolls)
    scores = {
        eid: (primary, tiebreak)
        for eid, primary, tiebreak in rolls
    }
    return TurnOrder(order, initiative_scores=scores), scores


def build_turn_order(
    entities: dict[str, BaseEntity],
    rng: SeededRNG,
    dice_size: int,
) -> tuple[str, ...]:
    order, _ = build_turn_order_with_scores(entities, rng, dice_size)
    return order


def insert_into_turn_order(
    state: CombatState,
    entity_id: str,
    initiative_score: tuple[int, int],
) -> CombatState:
    acted_prefix = list(state.turn_order[: state.current_turn_index + 1])
    remaining = list(state.turn_order[state.current_turn_index + 1 :])
    insert_offset = len(remaining)

    for idx, existing_id in enumerate(remaining):
        existing_score = state.initiative_scores.get(existing_id, (0, 0))
        if initiative_score > existing_score:
            insert_offset = idx
            break

    remaining.insert(insert_offset, entity_id)
    new_turn_order = TurnOrder(
        tuple([*acted_prefix, *remaining]),
        initiative_scores={
            **state.initiative_scores,
            entity_id: initiative_score,
        },
    )
    return CombatState(
        combat_id=state.combat_id,
        session_id=state.session_id,
        round_number=state.round_number,
        turn_order=new_turn_order,
        current_turn_index=state.current_turn_index,
        entities=state.entities,
        phase=state.phase,
        action_log=state.action_log,
        passive_trackers=state.passive_trackers,
        cooldowns=state.cooldowns,
        initiative_scores={**state.initiative_scores, entity_id: initiative_score},
        next_summon_order=state.next_summon_order,
        rng_state=state.rng_state,
        room_difficulty=state.room_difficulty,
    )
