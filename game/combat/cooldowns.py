from dataclasses import replace

from game.combat.models import CombatState


def is_on_cooldown(state: CombatState, entity_id: str, skill_id: str) -> bool:
    return state.cooldowns.get(entity_id, {}).get(skill_id, 0) > 0


def get_remaining_cooldown(state: CombatState, entity_id: str, skill_id: str) -> int:
    return state.cooldowns.get(entity_id, {}).get(skill_id, 0)


def put_on_cooldown(
    state: CombatState, entity_id: str, skill_id: str, turns: int,
) -> CombatState:
    """Set cooldown for a skill. Called after skill/passive is used."""
    if turns <= 0:
        return state
    entity_cds = {**state.cooldowns.get(entity_id, {}), skill_id: turns}
    return replace(state, cooldowns={**state.cooldowns, entity_id: entity_cds})


def tick_cooldowns(state: CombatState, entity_id: str) -> CombatState:
    """Decrement all cooldowns for an entity by 1. Called at start of their turn."""
    entity_cds = state.cooldowns.get(entity_id, {})
    if not entity_cds:
        return state
    new_cds = {sid: rem - 1 for sid, rem in entity_cds.items() if rem > 1}
    if new_cds:
        return replace(state, cooldowns={**state.cooldowns, entity_id: new_cds})
    new_cooldowns = {**state.cooldowns}
    new_cooldowns.pop(entity_id, None)
    return replace(state, cooldowns=new_cooldowns)


def reset_all_cooldowns(state: CombatState, entity_id: str) -> CombatState:
    """Reset all cooldowns for an entity to 0."""
    if entity_id not in state.cooldowns:
        return state
    new_cooldowns = {**state.cooldowns}
    new_cooldowns.pop(entity_id, None)
    return replace(state, cooldowns=new_cooldowns)


def reset_cooldown(state: CombatState, entity_id: str, skill_id: str) -> CombatState:
    """Reset a single skill's cooldown."""
    entity_cds = state.cooldowns.get(entity_id, {})
    if skill_id not in entity_cds:
        return state
    new_cds = {k: v for k, v in entity_cds.items() if k != skill_id}
    if new_cds:
        return replace(state, cooldowns={**state.cooldowns, entity_id: new_cds})
    new_cooldowns = {**state.cooldowns}
    new_cooldowns.pop(entity_id, None)
    return replace(state, cooldowns=new_cooldowns)
