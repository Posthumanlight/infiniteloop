from game.combat.cooldowns import is_on_cooldown
from game.combat.effects import get_effective_skill_access
from game.combat.models import ActionRequest, CombatState
from game.combat.skill_targeting import (
    ActionTargetRef,
    build_ai_target_refs as build_target_refs_for_ai,
    skill_has_targets_available,
)
from game.combat.summons import commandable_summons_for_skill
from game.core.data_loader import SkillData, load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType


def iter_priority_skill_ids(
    state: CombatState,
    actor_id: str,
) -> tuple[str, ...]:
    actor = state.entities[actor_id]
    access = get_effective_skill_access(actor, state)
    allowed = set(access.available)

    ordered = [
        skill_id for skill_id in getattr(actor, "skills", ())
        if skill_id in allowed
    ]
    trailing = [
        skill_id for skill_id in access.available
        if skill_id not in ordered
    ]
    return tuple([*ordered, *trailing])


def is_skill_usable(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
) -> bool:
    actor = state.entities[actor_id]
    access = get_effective_skill_access(actor, state)

    if skill.skill_id not in access.available_set:
        return False
    if is_on_cooldown(state, actor_id, skill.skill_id):
        return False
    if actor.current_energy < skill.energy_cost:
        return False

    if not skill_has_targets_available(state, actor_id, skill):
        return False

    if skill.summon_commands and not commandable_summons_for_skill(
        state,
        actor_id,
        skill,
    ):
        return False

    return True


def build_ai_target_refs(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    rng: SeededRNG,
) -> tuple[ActionTargetRef, ...] | None:
    return build_target_refs_for_ai(state, actor_id, skill, rng)


def build_ai_action(
    state: CombatState,
    actor_id: str,
    rng: SeededRNG,
) -> ActionRequest | None:
    for skill_id in iter_priority_skill_ids(state, actor_id):
        skill = load_skill(skill_id)
        if not is_skill_usable(state, actor_id, skill):
            continue

        target_refs = build_ai_target_refs(state, actor_id, skill, rng)
        if target_refs is None:
            continue

        return ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id=skill.skill_id,
            target_refs=target_refs,
        )

    return None


def build_enemy_action(
    state: CombatState,
    actor_id: str,
    rng: SeededRNG,
) -> ActionRequest | None:
    return build_ai_action(state, actor_id, rng)
