from game.combat.cooldowns import is_on_cooldown
from game.combat.effects import get_effective_skill_access
from game.combat.models import ActionRequest, CombatState
from game.combat.targeting import get_allies, get_enemies
from game.core.data_loader import SkillData, load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType, TargetType


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

    for hit in skill.hits:
        if hit.share_with is not None:
            continue

        match hit.target_type:
            case TargetType.SINGLE_ENEMY | TargetType.ALL_ENEMIES:
                if not get_enemies(state, actor_id):
                    return False
            case TargetType.SINGLE_ALLY | TargetType.ALL_ALLIES:
                if not get_allies(state, actor_id):
                    return False
            case TargetType.SELF:
                continue

    return True


def build_ai_target_pairs(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    rng: SeededRNG,
) -> tuple[tuple[int, str], ...] | None:
    pairs: list[tuple[int, str]] = []

    for hit_index, hit in enumerate(skill.hits):
        if hit.share_with is not None:
            continue

        match hit.target_type:
            case TargetType.SINGLE_ENEMY:
                candidates = get_enemies(state, actor_id)
                if not candidates:
                    return None
                chosen = candidates[rng.d(len(candidates)) - 1]
                pairs.append((hit_index, chosen))

            case TargetType.SINGLE_ALLY:
                candidates = get_allies(state, actor_id)
                if not candidates:
                    return None
                chosen = candidates[rng.d(len(candidates)) - 1]
                pairs.append((hit_index, chosen))

            case TargetType.ALL_ENEMIES:
                if not get_enemies(state, actor_id):
                    return None

            case TargetType.ALL_ALLIES:
                if not get_allies(state, actor_id):
                    return None

            case TargetType.SELF:
                continue

    return tuple(pairs)


def build_enemy_action(
    state: CombatState,
    actor_id: str,
    rng: SeededRNG,
) -> ActionRequest | None:
    for skill_id in iter_priority_skill_ids(state, actor_id):
        skill = load_skill(skill_id)
        if not is_skill_usable(state, actor_id, skill):
            continue

        target_ids = build_ai_target_pairs(state, actor_id, skill, rng)
        if target_ids is None:
            continue

        return ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id=skill.skill_id,
            target_ids=target_ids,
        )

    return None
