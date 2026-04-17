from dataclasses import replace

from game.combat.cooldowns import is_on_cooldown, put_on_cooldown
from game.combat.effects import get_effective_skill_access, is_skipped
from game.combat.models import ActionRequest, ActionResult, CombatState
from game.combat.passives import PassiveEvent, check_passives
from game.combat.skill_resolver import resolve_skill
from game.core.data_loader import load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType, TriggerType


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
    actor = state.entities[action.actor_id]
    access = get_effective_skill_access(actor, state)

    if action.skill_id is None:
        raise ValueError("Skill id is required for action")
    if action.skill_id not in access.available_set:
        if action.skill_id in access.blocked_set:
            raise ValueError(
                f"Skill '{action.skill_id}' is blocked by an active effect",
            )
        raise ValueError(f"Skill '{action.skill_id}' is not available to this actor")

    skill = load_skill(action.skill_id)

    if is_on_cooldown(state, action.actor_id, action.skill_id):
        raise ValueError(
            f"Skill '{action.skill_id}' is on cooldown"
        )

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

    state, hits, summons_created = resolve_skill(
        state, action.actor_id, skill, action.get_target_map(), rng, constants,
    )

    state = put_on_cooldown(state, action.actor_id, action.skill_id, skill.cooldown)

    # Fire ON_CAST passives (e.g. arcane_rupture consuming stacks)
    state, cast_hits = check_passives(
        state,
        action.actor_id,
        PassiveEvent(
            trigger=TriggerType.ON_CAST,
            payload={"skill_id": action.skill_id},
        ),
        rng=rng,
        constants=constants,
    )
    hits.extend(cast_hits)

    self_effects: list[str] = [se.effect_id for se in skill.self_effects]

    return state, ActionResult(
        actor_id=action.actor_id,
        action=action,
        hits=tuple(hits),
        self_effects_applied=tuple(self_effects),
        summons_created=summons_created,
    )
