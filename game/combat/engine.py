import uuid
from dataclasses import replace

from game.character.base_entity import BaseEntity
from game.character.enemy import Enemy
from game.character.player_character import PlayerCharacter
from game.combat.action_resolver import resolve_action
from game.combat.initiative import build_turn_order
from game.combat.models import ActionRequest, ActionResult, CombatState
from game.combat.turn_manager import (
    check_combat_end,
    end_turn,
    start_round,
    start_turn,
)
from game.core.data_loader import load_constants, load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType, CombatPhase


def start_combat(
    session_id: str,
    players: list[PlayerCharacter],
    enemies: list[Enemy],
    seed: int,
) -> CombatState:
    rng = SeededRNG(seed)
    constants = load_constants()

    entities: dict[str, BaseEntity] = {}
    for p in players:
        entities[p.entity_id] = p
    for e in enemies:
        entities[e.entity_id] = e

    turn_order = build_turn_order(entities, rng, constants["initiative_dice"])

    state = CombatState(
        combat_id=uuid.uuid4().hex,
        session_id=session_id,
        round_number=1,
        turn_order=turn_order,
        current_turn_index=0,
        entities=entities,
        phase=CombatPhase.ACTING,
        rng_state=rng.get_state(),
    )

    # Skip to first alive entity
    while state.current_turn_index < len(state.turn_order):
        eid = state.turn_order[state.current_turn_index]
        if state.entities[eid].current_hp > 0:
            break
        state = replace(state, current_turn_index=state.current_turn_index + 1)

    return state


def submit_action(
    state: CombatState,
    action: ActionRequest,
) -> tuple[CombatState, ActionResult]:
    if state.phase == CombatPhase.ENDED:
        raise ValueError("Combat has ended")

    current_id = state.turn_order[state.current_turn_index]
    if action.actor_id != current_id:
        raise ValueError(
            f"Not {action.actor_id}'s turn. Current turn: {current_id}"
        )

    rng = SeededRNG(0)
    rng.set_state(state.rng_state)
    constants = load_constants()

    state, skipped, _ = start_turn(state, rng)

    if skipped:
        result = ActionResult(
            actor_id=action.actor_id,
            action=action,
            skipped=True,
        )
    else:
        state, result = resolve_action(state, action, rng, constants)

    state = replace(
        state,
        action_log=state.action_log + (result,),
    )

    state = end_turn(state, rng)
    state = check_combat_end(state)

    if state.phase == CombatPhase.ROUND_END:
        state = start_round(state, rng)
        state = check_combat_end(state)

    state = replace(state, rng_state=rng.get_state())
    return state, result


def skip_turn(
    state: CombatState,
    actor_id: str,
) -> tuple[CombatState, ActionResult]:
    action = ActionRequest(
        actor_id=actor_id,
        action_type=ActionType.ACTION,
        skill_id=None,
    )
    result = ActionResult(
        actor_id=actor_id,
        action=action,
        skipped=True,
    )

    rng = SeededRNG(0)
    rng.set_state(state.rng_state)
    constants = load_constants()

    state, _, _ = start_turn(state, rng)
    state = replace(state, action_log=state.action_log + (result,))
    state = end_turn(state, rng)
    state = check_combat_end(state)

    if state.phase == CombatPhase.ROUND_END:
        state = start_round(state, rng)
        state = check_combat_end(state)

    state = replace(state, rng_state=rng.get_state())
    return state, result


def get_available_actions(state: CombatState, actor_id: str) -> list:
    entity = state.entities[actor_id]
    skills = []
    for skill_id in entity.skills:
        skill_data = load_skill(skill_id)
        if skill_data.energy_cost <= entity.current_energy:
            skills.append(skill_data)
    return skills
