from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest

import agents.observation as observation
from agents.observation import (
    ENTITY_SCALAR_FEATURES,
    ENTITY_TYPE_IDS,
    GLOBAL_FEATURES,
    ObservationCatalog,
    average_damage_per_round,
    build_observation,
    build_observation_catalog,
    build_observation_space,
    build_observation_spec,
    difficulty_modifier,
    entity_block_size,
    normalized,
)
from game.combat.effects import StatusEffectInstance
from game.combat.models import ActionRequest, ActionResult, DamageResult, HitResult
from game.combat.summons import SummonEntity
from game.core.data_loader import CombatLocation, SkillData, SkillHitData
from game.core.enums import ActionType, DamageType, EntityType, TargetType
from game.world.difficulty import RoomDifficultyModifier

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


def _catalog() -> ObservationCatalog:
    return ObservationCatalog(
        skill_ids=("cleave", "restoration", "slash"),
        effect_ids=("bleed", "stun"),
        passive_ids=("battle_master",),
        class_ids=("warrior",),
        enemy_ids=("goblin",),
        summon_ids=("familiar",),
        location_ids=("test_location",),
        location_status_ids=("dim_light",),
    )


def _spec():
    return build_observation_spec(
        catalog=_catalog(),
        max_team_slots=2,
        max_enemy_slots=2,
        max_effect_slots=2,
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
def _patch_skill_catalog(monkeypatch):
    skills = {
        "cleave": _skill("cleave", TargetType.ALL_ENEMIES, energy_cost=25),
        "restoration": _skill("restoration", TargetType.SINGLE_ALLY, energy_cost=30),
        "slash": _skill("slash", TargetType.SINGLE_ENEMY),
    }
    monkeypatch.setattr(observation, "load_skills", lambda: skills)


def _state(**kwargs):
    player = replace(
        make_warrior("p1"),
        passive_skills=("battle_master",),
        skills=("slash", "cleave", "restoration"),
    )
    enemy = replace(make_goblin("e1"), enemy_template_id="goblin")
    state = make_combat_state(
        players=[player],
        enemies=[enemy],
        turn_order=("p1", "e1"),
    )
    return replace(
        state,
        location=CombatLocation(
            location_id="test_location",
            name="Test Location",
            tags=("test",),
            status_ids=("dim_light",),
        ),
        **kwargs,
    )


def _global_value(obs: np.ndarray, spec, name: str) -> float:
    return float(obs[spec.slices["global"].start + GLOBAL_FEATURES.index(name)])


def _actor_value(obs: np.ndarray, spec, name: str) -> float:
    return float(obs[spec.slices["actor"].start + ENTITY_SCALAR_FEATURES.index(name)])


def _entity_identity_offsets(spec):
    cursor = spec.slices["actor"].start + len(ENTITY_SCALAR_FEATURES)
    entity_type = slice(cursor, cursor + len(ENTITY_TYPE_IDS))
    cursor = entity_type.stop
    classes = slice(cursor, cursor + len(spec.catalog.class_ids))
    cursor = classes.stop
    enemies = slice(cursor, cursor + len(spec.catalog.enemy_ids))
    cursor = enemies.stop
    summons = slice(cursor, cursor + len(spec.catalog.summon_ids))
    cursor = summons.stop
    passives = slice(cursor, cursor + len(spec.catalog.passive_ids))
    cursor = passives.stop
    effects = slice(cursor, spec.slices["actor"].stop)
    return entity_type, classes, enemies, summons, passives, effects


def _action(actor_id: str, amount: int) -> ActionResult:
    return ActionResult(
        actor_id=actor_id,
        action=ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id="slash",
        ),
        hits=(
            HitResult(
                target_id="e1",
                damage=DamageResult(
                    amount=amount,
                    damage_type=DamageType.SLASHING,
                    is_crit=False,
                    formula_id="slash",
                ),
            ),
        ),
        round_number=1,
    )


def test_build_observation_catalog_sorts_loader_ids(monkeypatch):
    monkeypatch.setattr(
        observation,
        "load_class_catalog",
        lambda: SimpleNamespace(
            base_classes={"warrior": object()},
            hero_classes={"gladiator": object()},
        ),
    )
    monkeypatch.setattr(observation, "load_skills", lambda: {"slash": object(), "cleave": object()})
    monkeypatch.setattr(observation, "load_effects", lambda: {"stun": object(), "bleed": object()})
    monkeypatch.setattr(observation, "load_passives", lambda: {"battle_master": object()})
    monkeypatch.setattr(observation, "load_enemies", lambda: {"goblin": object()})
    monkeypatch.setattr(observation, "load_summons", lambda: {"familiar": object()})
    monkeypatch.setattr(observation, "load_combat_locations", lambda: {"cave": object()})
    monkeypatch.setattr(observation, "load_location_statuses", lambda: {"dim_light": object()})

    catalog = build_observation_catalog()

    assert catalog.class_ids == ("gladiator", "warrior")
    assert catalog.skill_ids == ("cleave", "slash")
    assert catalog.effect_ids == ("bleed", "stun")


def test_observation_shape_space_and_required_global_features():
    pytest.importorskip("gymnasium")
    spec = _spec()
    difficulty = RoomDifficultyModifier(
        scalar=2.0,
        average_level=3.0,
        party_size=1,
        power=4,
    )
    state = _state(
        round_number=2,
        room_difficulty=difficulty,
        action_log=(
            _action("p1", 40),
            _action("e1", 100),
        ),
    )

    obs = build_observation(state, "p1", spec)
    space = build_observation_space(spec)

    assert obs.dtype == np.float32
    assert obs.shape == (spec.vector_size,)
    assert space.shape == (spec.vector_size,)
    assert space.dtype == np.float32
    assert difficulty_modifier(state) == 2.0
    assert average_damage_per_round(state, "p1") == 20
    assert _global_value(obs, spec, "difficulty_modifier_norm") == pytest.approx(
        normalized(2.0, 999.99),
    )
    assert _global_value(obs, spec, "average_damage_per_round_norm") == pytest.approx(
        normalized(20, 500),
    )
    assert _global_value(obs, spec, "actor_is_current_turn") == 1.0


def test_observation_defaults_difficulty_to_identity():
    assert difficulty_modifier(_state(room_difficulty=None)) == 1.0


def test_entity_alive_flags_location_and_actor_identities_are_encoded():
    spec = _spec()
    enemy = replace(make_goblin("e1"), current_hp=0, enemy_template_id="goblin")
    state = _state(
        entities={
            "p1": replace(
                make_warrior("p1"),
                passive_skills=("battle_master",),
                skills=("slash", "cleave", "restoration"),
            ),
            "e1": enemy,
        },
    )

    obs = build_observation(state, "p1", spec)
    entity_types, classes, _enemies, _summons, passives, _effects = _entity_identity_offsets(spec)

    assert _actor_value(obs, spec, "is_alive") == 1.0
    assert obs[classes][0] == 1.0
    assert obs[passives][0] == 1.0
    assert obs[spec.slices["location"]][0] == 1.0
    assert obs[spec.slices["location"]][1] == 1.0
    assert obs[entity_types][ENTITY_TYPE_IDS.index(EntityType.PLAYER.value)] == 1.0

    enemy_start = spec.slices["enemies"].start
    is_alive_offset = ENTITY_SCALAR_FEATURES.index("is_alive")
    assert obs[enemy_start + is_alive_offset] == 0.0


def test_active_effect_and_summon_identity_are_encoded():
    spec = _spec()
    player = replace(
        make_warrior("p1"),
        skills=("slash", "cleave", "restoration"),
        active_effects=(
            StatusEffectInstance(
                effect_id="bleed",
                source_id="e1",
                remaining_duration=3,
                stack_count=2,
            ),
        ),
    )
    summon = SummonEntity(
        entity_id="ally_familiar_1",
        entity_name="Familiar",
        entity_type=EntityType.ALLY,
        major_stats=player.major_stats,
        minor_stats=player.minor_stats,
        current_hp=20,
        current_energy=20,
        summon_template_id="familiar",
        owner_id="p1",
        skills=("slash",),
    )
    enemy = replace(make_goblin("e1"), enemy_template_id="goblin")
    state = _state(
        entities={"p1": player, "ally_familiar_1": summon, "e1": enemy},
        turn_order=("p1", "ally_familiar_1", "e1"),
    )

    obs = build_observation(state, "p1", spec)
    *_unused, effects = _entity_identity_offsets(spec)
    effect_start = effects.start
    assert obs[effect_start] == 1.0
    assert obs[effect_start + 1] == 1.0
    assert obs[effect_start + 1 + len(spec.catalog.effect_ids)] == pytest.approx(
        normalized(3, 20),
    )

    team_start = spec.slices["team"].start
    _types, _classes, _enemies, summons, _passives, _effects = _entity_identity_offsets(spec)
    summon_offset_inside_actor_block = summons.start - spec.slices["actor"].start
    assert obs[team_start + summon_offset_inside_actor_block] == 1.0


def test_slot_ordering_and_empty_slots_are_deterministic_zeroes():
    spec = _spec()
    p2 = make_warrior("p2")
    e1 = replace(make_goblin("e1"), enemy_template_id="goblin")
    e2 = replace(make_goblin("e2"), enemy_template_id="goblin")
    state = _state(
        entities={
            "p1": make_warrior("p1"),
            "p2": p2,
            "e1": e1,
            "e2": e2,
        },
        turn_order=("p1", "e2", "p2", "e1"),
    )

    obs = build_observation(state, "p1", spec)
    block = entity_block_size(spec)
    enemy_name_offset = ENTITY_SCALAR_FEATURES.index("present")

    assert obs[spec.slices["team"].start + enemy_name_offset] == 1.0
    assert obs[spec.slices["team"].start + block + enemy_name_offset] == 0.0
    assert obs[spec.slices["enemies"].start + enemy_name_offset] == 1.0
    assert obs[spec.slices["enemies"].start + block + enemy_name_offset] == 1.0
