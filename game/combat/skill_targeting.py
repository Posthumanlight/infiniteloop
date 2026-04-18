from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from game.core.data_loader import SkillData, load_skill
from game.core.dice import SeededRNG
from game.core.enums import TargetType

if TYPE_CHECKING:
    from game.combat.models import CombatState, ActionRequest


class TargetOwnerKind(str, Enum):
    HIT = "hit"
    SUMMON_COMMAND = "summon_command"


@dataclass(frozen=True)
class ActionTargetRef:
    owner_kind: TargetOwnerKind
    owner_index: int
    nested_index: int
    entity_id: str


@dataclass(frozen=True)
class ManualTargetRequirement:
    owner_kind: TargetOwnerKind
    owner_index: int
    nested_index: int
    target_type: TargetType


_MANUAL_TARGET_TYPES = frozenset({
    TargetType.SINGLE_ENEMY,
    TargetType.SINGLE_ALLY,
})


def iter_target_requirements(skill: SkillData) -> tuple[ManualTargetRequirement, ...]:
    requirements: list[ManualTargetRequirement] = []

    for hit_index, hit in enumerate(skill.hits):
        if hit.share_with is not None:
            continue
        requirements.append(ManualTargetRequirement(
            owner_kind=TargetOwnerKind.HIT,
            owner_index=hit_index,
            nested_index=0,
            target_type=hit.target_type,
        ))

    for command_index, command in enumerate(skill.summon_commands):
        commanded_skill = load_skill(command.summon_skill_id)
        for hit_index, hit in enumerate(commanded_skill.hits):
            if hit.share_with is not None:
                continue
            requirements.append(ManualTargetRequirement(
                owner_kind=TargetOwnerKind.SUMMON_COMMAND,
                owner_index=command_index,
                nested_index=hit_index,
                target_type=hit.target_type,
            ))

    return tuple(requirements)


def iter_manual_target_requirements(skill: SkillData) -> tuple[ManualTargetRequirement, ...]:
    return tuple(
        requirement
        for requirement in iter_target_requirements(skill)
        if requirement.target_type in _MANUAL_TARGET_TYPES
    )


def _has_candidates(
    state: CombatState,
    actor_id: str,
    target_type: TargetType,
) -> bool:
    from game.combat.targeting import get_allies, get_enemies

    match target_type:
        case TargetType.SINGLE_ENEMY | TargetType.ALL_ENEMIES:
            return bool(get_enemies(state, actor_id))
        case TargetType.SINGLE_ALLY | TargetType.ALL_ALLIES:
            return bool(get_allies(state, actor_id))
        case TargetType.SELF:
            return True
    return False


def _is_valid_selected_target(
    state: CombatState,
    actor_id: str,
    target_type: TargetType,
    target_id: str,
) -> bool:
    from game.combat.targeting import get_allies, get_enemies

    entity = state.entities.get(target_id)
    if entity is None or entity.current_hp <= 0:
        return False

    match target_type:
        case TargetType.SINGLE_ENEMY:
            return target_id in get_enemies(state, actor_id)
        case TargetType.SINGLE_ALLY:
            return target_id in get_allies(state, actor_id)
        case TargetType.SELF:
            return target_id == actor_id
        case _:
            return _has_candidates(state, actor_id, target_type)


def skill_has_targets_available(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
) -> bool:
    return all(
        _has_candidates(state, actor_id, requirement.target_type)
        for requirement in iter_target_requirements(skill)
    )


def build_ai_target_refs(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    rng: SeededRNG,
) -> tuple[ActionTargetRef, ...] | None:
    from game.combat.targeting import get_allies, get_enemies

    refs: list[ActionTargetRef] = []

    for requirement in iter_target_requirements(skill):
        match requirement.target_type:
            case TargetType.SINGLE_ENEMY:
                candidates = get_enemies(state, actor_id)
                if not candidates:
                    return None
                chosen = candidates[rng.d(len(candidates)) - 1]
                refs.append(ActionTargetRef(
                    owner_kind=requirement.owner_kind,
                    owner_index=requirement.owner_index,
                    nested_index=requirement.nested_index,
                    entity_id=chosen,
                ))
            case TargetType.SINGLE_ALLY:
                candidates = get_allies(state, actor_id)
                if not candidates:
                    return None
                chosen = candidates[rng.d(len(candidates)) - 1]
                refs.append(ActionTargetRef(
                    owner_kind=requirement.owner_kind,
                    owner_index=requirement.owner_index,
                    nested_index=requirement.nested_index,
                    entity_id=chosen,
                ))
            case TargetType.ALL_ENEMIES | TargetType.ALL_ALLIES | TargetType.SELF:
                if not _has_candidates(state, actor_id, requirement.target_type):
                    return None

    return tuple(refs)


def build_forwarded_command_target_refs(
    action: ActionRequest,
    command_index: int,
) -> tuple[ActionTargetRef, ...]:
    refs: list[ActionTargetRef] = []
    for ref in action.target_refs:
        if ref.owner_kind != TargetOwnerKind.SUMMON_COMMAND:
            continue
        if ref.owner_index != command_index:
            continue
        refs.append(ActionTargetRef(
            owner_kind=TargetOwnerKind.HIT,
            owner_index=ref.nested_index,
            nested_index=0,
            entity_id=ref.entity_id,
        ))
    return tuple(refs)


def target_refs_are_still_valid(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    target_refs: tuple[ActionTargetRef, ...],
) -> bool:
    ref_map = {
        (ref.owner_kind, ref.owner_index, ref.nested_index): ref.entity_id
        for ref in target_refs
    }

    for requirement in iter_target_requirements(skill):
        if requirement.target_type not in _MANUAL_TARGET_TYPES:
            if not _has_candidates(state, actor_id, requirement.target_type):
                return False
            continue

        key = (
            requirement.owner_kind,
            requirement.owner_index,
            requirement.nested_index,
        )
        target_id = ref_map.get(key)
        if target_id is None:
            return False
        if not _is_valid_selected_target(
            state,
            actor_id,
            requirement.target_type,
            target_id,
        ):
            return False

    return True
