from dataclasses import replace

from game.combat.effects import expire_effects, is_skipped, tick_effects
from game.combat.models import CombatState, HitResult
from game.combat.targeting import is_alive
from game.core.dice import SeededRNG
from game.core.enums import CombatPhase, EntityType, TriggerType


def start_round(state: CombatState, rng: SeededRNG) -> CombatState:
    state = replace(
        state,
        round_number=state.round_number + 1,
        current_turn_index=0,
        phase=CombatPhase.ACTING,
    )

    for eid in state.turn_order:
        entity = state.entities[eid]
        if is_alive(entity):
            state, _ = tick_effects(state, eid, TriggerType.ON_ROUND_START, rng)

    return state


def start_turn(
    state: CombatState,
    rng: SeededRNG,
) -> tuple[CombatState, bool, list[HitResult]]:
    current_id = state.turn_order[state.current_turn_index]

    state, tick_results = tick_effects(
        state, current_id, TriggerType.ON_TURN_START, rng,
    )

    skipped = is_skipped(state, current_id)
    return state, skipped, tick_results


def end_turn(state: CombatState, rng: SeededRNG) -> CombatState:
    current_id = state.turn_order[state.current_turn_index]

    state, _ = tick_effects(state, current_id, TriggerType.ON_TURN_END, rng)
    state = expire_effects(state, current_id)

    next_index = state.current_turn_index + 1
    if next_index >= len(state.turn_order):
        return replace(state, current_turn_index=next_index, phase=CombatPhase.ROUND_END)

    # Skip dead entities
    while next_index < len(state.turn_order):
        eid = state.turn_order[next_index]
        if is_alive(state.entities[eid]):
            break
        next_index += 1

    if next_index >= len(state.turn_order):
        return replace(state, current_turn_index=next_index, phase=CombatPhase.ROUND_END)

    return replace(state, current_turn_index=next_index)


def check_combat_end(state: CombatState) -> CombatState:
    players_alive = any(
        is_alive(e)
        for e in state.entities.values()
        if e.entity_type == EntityType.PLAYER
    )
    enemies_alive = any(
        is_alive(e)
        for e in state.entities.values()
        if e.entity_type == EntityType.ENEMY
    )

    if not players_alive or not enemies_alive:
        return replace(state, phase=CombatPhase.ENDED)
    return state
