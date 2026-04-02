from dataclasses import replace

from game.combat.effects import is_skipped
from game.combat.models import ActionRequest, ActionResult, CombatState
from game.combat.skill_resolver import resolve_skill
from game.combat.targeting import resolve_targets
from game.core.data_loader import load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType


def resolve_action(
    state: CombatState,
    action: ActionRequest,
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, ActionResult]:
    if is_skipped(state, action.actor_id):
        return state, ActionResult(
            actor_id=action.actor_id,
            action=action,
            skipped=True,
        )

    match action.action_type:
        case ActionType.ACTION:
            return _resolve_skill_action(state, action, rng, constants)
        case ActionType.ITEM:
            return state, ActionResult(
                actor_id=action.actor_id,
                action=action,
            )


def _resolve_skill_action(
    state: CombatState,
    action: ActionRequest,
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, ActionResult]:
    skill = load_skill(action.skill_id)
    actor = state.entities[action.actor_id]

    if actor.current_energy < skill.energy_cost:
        raise ValueError(
            f"Not enough energy: have {actor.current_energy}, "
            f"need {skill.energy_cost}"
        )

    if skill.energy_cost > 0:
        new_energy = actor.current_energy - skill.energy_cost
        new_entities = {
            **state.entities,
            action.actor_id: replace(actor, current_energy=new_energy),
        }
        state = replace(state, entities=new_entities)

    target_ids = resolve_targets(
        state, action.actor_id, skill.target_type, action.target_id,
    )

    state, hits = resolve_skill(state, action.actor_id, skill, target_ids, rng, constants)

    self_effects: list[str] = [se.effect_id for se in skill.self_effects]

    return state, ActionResult(
        actor_id=action.actor_id,
        action=action,
        hits=tuple(hits),
        self_effects_applied=tuple(self_effects),
    )
