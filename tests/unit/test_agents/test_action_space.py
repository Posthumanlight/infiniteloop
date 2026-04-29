from dataclasses import replace

import numpy as np
import pytest

import agents.action_space as action_space
from agents.action_space import (
    NO_TARGET_SLOT,
    ActionSpaceSpec,
    action_index_to_request,
    build_action_mask,
    build_action_space,
    build_action_space_spec,
)
from agents.observation import ObservationCatalog, build_observation_spec
from game.core.data_loader import SkillData, SkillHitData
from game.core.enums import ActionType, DamageType, TargetType

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


def _obs_spec(skill_ids=("cleave", "restoration", "slash")):
    return build_observation_spec(
        catalog=ObservationCatalog(
            skill_ids=skill_ids,
            effect_ids=("bleed",),
            passive_ids=(),
            class_ids=("warrior",),
            enemy_ids=("goblin",),
            summon_ids=(),
            location_ids=("test_location",),
            location_status_ids=(),
        ),
        max_team_slots=1,
        max_enemy_slots=2,
        max_effect_slots=1,
    )


def _skill(
    skill_id: str,
    target_type: TargetType,
    *,
    energy_cost: int = 0,
    cooldown: int = 0,
) -> SkillData:
    return SkillData(
        skill_id=skill_id,
        name=skill_id.title(),
        energy_cost=energy_cost,
        action_type=ActionType.ACTION,
        hits=(
            SkillHitData(
                target_type=target_type,
                formula="1",
                base_power=1,
                damage_type=DamageType.SLASHING,
            ),
        ),
        self_effects=(),
        cooldown=cooldown,
    )


@pytest.fixture(autouse=True)
def _patch_skill_loader(monkeypatch):
    skills = {
        "cleave": _skill("cleave", TargetType.ALL_ENEMIES, energy_cost=25),
        "restoration": _skill("restoration", TargetType.SINGLE_ALLY, energy_cost=30),
        "slash": _skill("slash", TargetType.SINGLE_ENEMY),
    }
    monkeypatch.setattr(action_space, "load_skill", lambda skill_id: skills[skill_id])


def _state(player=None, enemies=None, cooldowns=None):
    if player is None:
        player = replace(
            make_warrior("p1"),
            skills=("slash", "cleave", "restoration"),
        )
    if enemies is None:
        enemies = [replace(make_goblin("e1"), enemy_template_id="goblin")]
    return replace(
        make_combat_state(
            players=[player, make_warrior("p2")],
            enemies=enemies,
            turn_order=("p1", "p2", *(enemy.entity_id for enemy in enemies)),
        ),
        cooldowns=cooldowns or {},
    )


def _index(spec, skill_id: str, target_slot: int) -> int:
    return spec.skill_ids.index(skill_id) * spec.target_slot_count + target_slot


def test_action_space_shape_matches_observation_slots():
    pytest.importorskip("gymnasium")
    obs_spec = _obs_spec()
    spec = build_action_space_spec(obs_spec)
    space = build_action_space(spec)

    assert spec.target_slot_count == 5
    assert spec.action_count == len(obs_spec.catalog.skill_ids) * 5
    assert space.n == spec.action_count


def test_mask_enables_single_enemy_single_ally_and_all_target_actions():
    obs_spec = _obs_spec()
    spec = build_action_space_spec(obs_spec)
    mask = build_action_mask(_state(), "p1", spec)

    assert mask.dtype == np.bool_
    assert mask[_index(spec, "cleave", NO_TARGET_SLOT)]
    assert mask[_index(spec, "restoration", 1)]
    assert mask[_index(spec, "restoration", 2)]
    assert mask[_index(spec, "slash", 3)]
    assert not mask[_index(spec, "slash", NO_TARGET_SLOT)]


def test_mask_blocks_cooldown_and_insufficient_energy():
    obs_spec = _obs_spec()
    spec = build_action_space_spec(obs_spec)

    cooldown_mask = build_action_mask(
        _state(cooldowns={"p1": {"slash": 2}}),
        "p1",
        spec,
    )
    assert not cooldown_mask[_index(spec, "slash", 3)]

    tired_player = replace(
        make_warrior("p1"),
        skills=("restoration",),
        current_energy=0,
    )
    energy_mask = build_action_mask(_state(player=tired_player), "p1", spec)
    assert not energy_mask[_index(spec, "restoration", 1)]


def test_action_index_to_request_maps_target_slot_to_target_ref():
    obs_spec = _obs_spec()
    spec = build_action_space_spec(obs_spec)
    state = _state()
    action_index = _index(spec, "slash", 3)

    request = action_index_to_request(action_index, state, "p1", obs_spec, spec)

    assert request.actor_id == "p1"
    assert request.skill_id == "slash"
    assert request.target_refs[0].entity_id == "e1"


def test_multi_manual_target_skill_is_masked_for_v1(monkeypatch):
    obs_spec = _obs_spec(skill_ids=("multi",))
    spec = ActionSpaceSpec(
        skill_ids=("multi",),
        target_slot_count=3,
        action_count=3,
        max_team_slots=0,
        max_enemy_slots=1,
    )
    skill = SkillData(
        skill_id="multi",
        name="Multi",
        energy_cost=0,
        action_type=ActionType.ACTION,
        hits=(
            SkillHitData(
                target_type=TargetType.SINGLE_ENEMY,
                formula="1",
                base_power=1,
                damage_type=DamageType.SLASHING,
            ),
            SkillHitData(
                target_type=TargetType.SINGLE_ENEMY,
                formula="1",
                base_power=1,
                damage_type=DamageType.SLASHING,
            ),
        ),
        self_effects=(),
    )
    monkeypatch.setattr(action_space, "load_skill", lambda _skill_id: skill)
    monkeypatch.setattr(action_space, "is_skill_usable", lambda *_args: True)

    mask = build_action_mask(_state(), "p1", spec)

    assert not mask.any()
    with pytest.raises(ValueError):
        action_index_to_request(0, _state(), "p1", obs_spec, spec)
