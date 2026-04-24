from dataclasses import dataclass, replace

from game.combat.cooldowns import is_on_cooldown, put_on_cooldown
from game.combat.effects import get_effective_skill_access, is_skipped
from game.combat.models import (
    ActionRequest,
    ActionResult,
    CombatState,
    TriggeredActionResult,
)
from game.combat.passives import PassiveEvent, check_passives
from game.combat.skill_resolver import resolve_skill_request
from game.core.data_loader import load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType, TriggerType


@dataclass(frozen=True)
class SkillCastOptions:
    enforce_access: bool = True
    enforce_energy: bool = True
    spend_energy: bool = True
    enforce_cooldown: bool = True
    apply_cooldown: bool = True
    trigger_on_cast_passives: bool = True


NORMAL_CAST_OPTIONS = SkillCastOptions()
FREE_CAST_OPTIONS = SkillCastOptions(
    enforce_energy=False,
    spend_energy=False,
    enforce_cooldown=False,
    apply_cooldown=False,
)
PROC_FREE_CAST_OPTIONS = SkillCastOptions(
    enforce_access=False,
    enforce_energy=False,
    spend_energy=False,
    enforce_cooldown=False,
    apply_cooldown=False,
)


def can_cast_skill(
    state: CombatState,
    actor_id: str,
    skill_id: str,
    *,
    options: SkillCastOptions = NORMAL_CAST_OPTIONS,
) -> bool:
    actor = state.entities[actor_id]
    if options.enforce_access:
        access = get_effective_skill_access(actor, state)
        if skill_id not in access.available_set:
            return False

    skill = load_skill(skill_id)
    if options.enforce_cooldown and is_on_cooldown(state, actor_id, skill_id):
        return False
    if options.enforce_energy and actor.current_energy < skill.energy_cost:
        return False
    return True


def options_for_command_policy(policy) -> SkillCastOptions:
    if getattr(policy, "value", policy) == "free":
        return FREE_CAST_OPTIONS
    return NORMAL_CAST_OPTIONS


def options_for_passive_cast_policy(policy) -> SkillCastOptions:
    if getattr(policy, "value", policy) == "free":
        return PROC_FREE_CAST_OPTIONS
    return NORMAL_CAST_OPTIONS


def cast_skill_now(
    state: CombatState,
    actor_id: str,
    skill_id: str,
    target_refs,
    rng: SeededRNG,
    constants: dict,
    *,
    options: SkillCastOptions = NORMAL_CAST_OPTIONS,
) -> tuple[CombatState, TriggeredActionResult]:
    actor = state.entities[actor_id]

    if options.enforce_access:
        access = get_effective_skill_access(actor, state)
        if skill_id not in access.available_set:
            if skill_id in access.blocked_set:
                raise ValueError(
                    f"Skill '{skill_id}' is blocked by an active effect",
                )
            raise ValueError(f"Skill '{skill_id}' is not available to this actor")

    skill = load_skill(skill_id)

    if options.enforce_cooldown and is_on_cooldown(state, actor_id, skill_id):
        raise ValueError(f"Skill '{skill_id}' is on cooldown")

    if options.enforce_energy and actor.current_energy < skill.energy_cost:
        raise ValueError(
            f"Not enough energy: have {actor.current_energy}, "
            f"need {skill.energy_cost}",
        )

    if options.spend_energy and skill.energy_cost > 0:
        new_energy = actor.current_energy - skill.energy_cost
        new_entities = {
            **state.entities,
            actor_id: replace(actor, current_energy=new_energy),
        }
        state = replace(state, entities=new_entities)

    action = ActionRequest(
        actor_id=actor_id,
        action_type=ActionType.ACTION,
        skill_id=skill_id,
        target_refs=tuple(target_refs),
    )
    state, resolution = resolve_skill_request(
        state,
        actor_id,
        skill,
        action,
        rng,
        constants,
    )

    if options.apply_cooldown:
        state = put_on_cooldown(state, actor_id, skill_id, skill.cooldown)

    hits = list(resolution.hits)
    if options.trigger_on_cast_passives:
        state, cast_hits = check_passives(
            state,
            actor_id,
            PassiveEvent(
                trigger=TriggerType.ON_CAST,
                payload={"skill_id": skill_id},
            ),
            rng=rng,
            constants=constants,
        )
        hits.extend(cast_hits)

    return state, TriggeredActionResult(
        actor_id=actor_id,
        skill_id=skill_id,
        hits=tuple(hits),
        self_effects_applied=resolution.self_effects_applied,
        summons_created=resolution.summons_created,
        triggered_actions=resolution.triggered_actions,
    )


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
    if action.skill_id is None:
        raise ValueError("Skill id is required for action")
    state, child = cast_skill_now(
        state,
        action.actor_id,
        action.skill_id,
        action.target_refs,
        rng,
        constants,
    )

    return state, ActionResult(
        actor_id=action.actor_id,
        action=action,
        hits=child.hits,
        self_effects_applied=child.self_effects_applied,
        summons_created=child.summons_created,
        triggered_actions=child.triggered_actions,
    )
