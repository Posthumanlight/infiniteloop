from __future__ import annotations

from dataclasses import dataclass

import numpy as np
try:
    import gymnasium as gym
except ModuleNotFoundError:  # pragma: no cover - depends on local training deps
    gym = None

from agents.observation import (
    ObservationSpec,
    ordered_enemy_entities,
    ordered_team_entities,
)
from game.character.base_entity import BaseEntity
from game.combat.enemy_ai import is_skill_usable
from game.combat.models import ActionRequest, CombatState
from game.combat.skill_targeting import (
    ActionTargetRef,
    ManualTargetRequirement,
    iter_manual_target_requirements,
)
from game.core.data_loader import load_skill
from game.core.enums import TargetType


NO_TARGET_SLOT = 0
ACTOR_TARGET_SLOT = 1


@dataclass(frozen=True)
class ActionSpaceSpec:
    skill_ids: tuple[str, ...]
    target_slot_count: int
    action_count: int
    max_team_slots: int
    max_enemy_slots: int


def build_action_space_spec(obs_spec: ObservationSpec) -> ActionSpaceSpec:
    target_slot_count = 1 + 1 + obs_spec.max_team_slots + obs_spec.max_enemy_slots
    action_count = len(obs_spec.catalog.skill_ids) * target_slot_count
    return ActionSpaceSpec(
        skill_ids=obs_spec.catalog.skill_ids,
        target_slot_count=target_slot_count,
        action_count=action_count,
        max_team_slots=obs_spec.max_team_slots,
        max_enemy_slots=obs_spec.max_enemy_slots,
    )


def build_action_space(spec: ActionSpaceSpec):
    if gym is None:
        raise ModuleNotFoundError("gymnasium is required to build action spaces")
    return gym.spaces.Discrete(spec.action_count)


def decode_action(action_index: int, spec: ActionSpaceSpec) -> tuple[str, int]:
    if action_index < 0 or action_index >= spec.action_count:
        raise ValueError(f"Action index out of range: {action_index}")
    skill_index, target_slot = divmod(action_index, spec.target_slot_count)
    return spec.skill_ids[skill_index], target_slot


def _team_slot_offset() -> int:
    return ACTOR_TARGET_SLOT + 1


def _enemy_slot_offset(spec: ActionSpaceSpec) -> int:
    return _team_slot_offset() + spec.max_team_slots


def _slot_entities(
    state: CombatState,
    actor_id: str,
    spec: ActionSpaceSpec,
) -> dict[int, BaseEntity]:
    entities: dict[int, BaseEntity] = {
        ACTOR_TARGET_SLOT: state.entities[actor_id],
    }
    team_offset = _team_slot_offset()
    for index, entity in enumerate(
        ordered_team_entities(state, actor_id, spec.max_team_slots),
    ):
        if entity is not None:
            entities[team_offset + index] = entity
    enemy_offset = _enemy_slot_offset(spec)
    for index, entity in enumerate(
        ordered_enemy_entities(state, actor_id, spec.max_enemy_slots),
    ):
        if entity is not None:
            entities[enemy_offset + index] = entity
    return entities


def _valid_target_slots(
    state: CombatState,
    actor_id: str,
    spec: ActionSpaceSpec,
    requirement: ManualTargetRequirement,
) -> tuple[int, ...]:
    from game.combat.targeting import get_allies, get_enemies

    slot_entities = _slot_entities(state, actor_id, spec)
    if requirement.target_type == TargetType.SINGLE_ALLY:
        valid_ids = set(get_allies(state, actor_id))
    elif requirement.target_type == TargetType.SINGLE_ENEMY:
        valid_ids = set(get_enemies(state, actor_id))
    else:
        return ()

    return tuple(
        slot
        for slot, entity in sorted(slot_entities.items())
        if entity.entity_id in valid_ids and entity.current_hp > 0
    )


def build_action_mask(
    state: CombatState,
    actor_id: str,
    spec: ActionSpaceSpec,
) -> np.ndarray:
    if actor_id not in state.entities:
        raise ValueError(f"Unknown actor_id: {actor_id}")

    mask = np.zeros(spec.action_count, dtype=bool)

    for skill_index, skill_id in enumerate(spec.skill_ids):
        skill = load_skill(skill_id)
        if not is_skill_usable(state, actor_id, skill):
            continue

        requirements = iter_manual_target_requirements(skill)
        if len(requirements) == 0:
            mask[skill_index * spec.target_slot_count + NO_TARGET_SLOT] = True
            continue

        if len(requirements) > 1:
            continue

        for target_slot in _valid_target_slots(
            state,
            actor_id,
            spec,
            requirements[0],
        ):
            mask[skill_index * spec.target_slot_count + target_slot] = True

    return mask


def _target_ref_for_slot(
    target_slot: int,
    requirement: ManualTargetRequirement,
    state: CombatState,
    actor_id: str,
    spec: ActionSpaceSpec,
) -> ActionTargetRef:
    slot_entities = _slot_entities(state, actor_id, spec)
    target = slot_entities.get(target_slot)
    if target is None:
        raise ValueError(f"Target slot {target_slot} is empty")
    return ActionTargetRef(
        owner_kind=requirement.owner_kind,
        owner_index=requirement.owner_index,
        nested_index=requirement.nested_index,
        entity_id=target.entity_id,
    )


def action_index_to_request(
    action_index: int,
    state: CombatState,
    actor_id: str,
    obs_spec: ObservationSpec,
    action_spec: ActionSpaceSpec,
) -> ActionRequest:
    if (
        obs_spec.max_team_slots != action_spec.max_team_slots
        or obs_spec.max_enemy_slots != action_spec.max_enemy_slots
    ):
        raise ValueError("Observation and action specs use different target slots")

    skill_id, target_slot = decode_action(action_index, action_spec)
    mask = build_action_mask(state, actor_id, action_spec)
    if not mask[action_index]:
        raise ValueError(
            f"Action index is not valid for the current state: {action_index}",
        )

    skill = load_skill(skill_id)
    requirements = iter_manual_target_requirements(skill)

    target_refs = ()
    if len(requirements) == 1:
        target_refs = (
            _target_ref_for_slot(
                target_slot,
                requirements[0],
                state,
                actor_id,
                action_spec,
            ),
        )

    return ActionRequest(
        actor_id=actor_id,
        action_type=skill.action_type,
        skill_id=skill.skill_id,
        target_refs=target_refs,
    )
