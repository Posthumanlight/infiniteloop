from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
try:
    import gymnasium as gym
except ModuleNotFoundError:  # pragma: no cover - depends on local training deps
    gym = None

from game.character.base_entity import BaseEntity
from game.character.enemy import Enemy
from game.character.player_character import PlayerCharacter
from game.combat.cooldowns import get_remaining_cooldown
from game.combat.effects import (
    get_effective_major_stat,
    get_effective_skill_access,
)
from game.combat.enemy_ai import is_skill_usable
from game.combat.models import ActionResult, CombatState, TriggeredActionResult
from game.combat.summons import SummonEntity
from game.core.data_loader import (
    load_class_catalog,
    load_combat_locations,
    load_constants,
    load_effects,
    load_enemies,
    load_events,
    load_location_sets,
    load_location_statuses,
    load_passives,
    load_skills,
    load_summon_constants,
    load_summons,
    load_world_difficulty_constants,
)
from game.core.enums import DamageType, EntityType, LocationType, TargetType


GLOBAL_FEATURES = (
    "round_number_norm",
    "current_turn_index_norm",
    "difficulty_modifier_norm",
    "average_damage_per_round_norm",
    "actor_is_current_turn",
    "enemy_alive_ratio",
    "team_alive_ratio",
)

ENTITY_SCALAR_FEATURES = (
    "present",
    "is_actor",
    "is_player_team",
    "is_enemy",
    "is_alive",
    "hp_pct",
    "energy_pct",
    "current_hp_norm",
    "current_energy_norm",
    "effective_attack_norm",
    "effective_hp_norm",
    "effective_speed_norm",
    "effective_crit_chance",
    "effective_crit_dmg_norm",
    "effective_resistance_norm",
    "effective_mastery_norm",
)

EFFECT_SCALAR_FEATURES = (
    "present",
    "remaining_duration_norm",
    "stack_count_norm",
)

SKILL_SCALAR_FEATURES = (
    "known_or_granted",
    "available_after_blocks",
    "usable_now",
    "energy_cost_pct",
    "cooldown_norm",
    "hit_count_norm",
    "has_self_effect",
    "has_summon",
    "has_summon_command",
)

ENTITY_TYPE_IDS = tuple(entity_type.value for entity_type in EntityType)
TARGET_TYPE_IDS = tuple(target_type.value for target_type in TargetType)
DAMAGE_TYPE_IDS = tuple(damage_type.value for damage_type in DamageType)

GENERATED_COMBAT_MAX_ENEMIES = 5
ROUND_NORMALIZER = 100.0
TURN_INDEX_NORMALIZER = 50.0
DAMAGE_NORMALIZER = 500.0
HP_NORMALIZER = 500.0
ENERGY_NORMALIZER = 250.0
ATTACK_NORMALIZER = 100.0
SPEED_NORMALIZER = 100.0
CRIT_DMG_NORMALIZER = 5.0
RESISTANCE_NORMALIZER = 300.0
MASTERY_NORMALIZER = 100.0
DURATION_NORMALIZER = 20.0
STACK_NORMALIZER = 20.0
COOLDOWN_NORMALIZER = 20.0
HIT_COUNT_NORMALIZER = 10.0


@dataclass(frozen=True)
class ObservationCatalog:
    skill_ids: tuple[str, ...]
    effect_ids: tuple[str, ...]
    passive_ids: tuple[str, ...]
    class_ids: tuple[str, ...]
    enemy_ids: tuple[str, ...]
    summon_ids: tuple[str, ...]
    location_ids: tuple[str, ...]
    location_status_ids: tuple[str, ...]


@dataclass(frozen=True)
class ObservationSpec:
    catalog: ObservationCatalog
    max_team_slots: int
    max_enemy_slots: int
    max_effect_slots: int
    vector_size: int
    slices: dict[str, slice]


def clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def normalized(value: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return clamp01(float(value) / denominator)


def one_hot(value: str | None, ids: tuple[str, ...]) -> list[float]:
    return [1.0 if value == item else 0.0 for item in ids]


def multi_hot(values: Iterable[str], ids: tuple[str, ...]) -> list[float]:
    value_set = set(values)
    return [1.0 if item in value_set else 0.0 for item in ids]


def build_observation_catalog() -> ObservationCatalog:
    class_catalog = load_class_catalog()
    class_ids = tuple(sorted([
        *class_catalog.base_classes.keys(),
        *class_catalog.hero_classes.keys(),
    ]))

    return ObservationCatalog(
        skill_ids=tuple(sorted(load_skills())),
        effect_ids=tuple(sorted(load_effects())),
        passive_ids=tuple(sorted(load_passives())),
        class_ids=class_ids,
        enemy_ids=tuple(sorted(load_enemies())),
        summon_ids=tuple(sorted(load_summons())),
        location_ids=tuple(sorted(load_combat_locations())),
        location_status_ids=tuple(sorted(load_location_statuses())),
    )


def _max_event_enemy_group_size() -> int:
    maximum = 0
    for event in load_events().values():
        for stage in event.stages.values():
            for choice in stage.choices:
                for outcome in choice.outcomes:
                    maximum = max(maximum, len(outcome.enemy_group))
    return maximum


def _max_predetermined_enemy_group_size() -> int:
    maximum = 0
    for location_set in load_location_sets().values():
        for location in location_set.locations:
            if location.location_type == LocationType.COMBAT:
                maximum = max(maximum, len(location.enemy_ids))
    return maximum


def infer_max_team_slots() -> int:
    max_party_size = int(load_constants().get("max_party_size", 1))
    max_total_per_owner = int(load_summon_constants().get("max_total_per_owner", 0))
    return max(0, max_party_size * (1 + max_total_per_owner) - 1)


def infer_max_enemy_slots() -> int:
    return max(
        1,
        GENERATED_COMBAT_MAX_ENEMIES,
        _max_event_enemy_group_size(),
        _max_predetermined_enemy_group_size(),
    )


def entity_block_size(spec: ObservationSpec) -> int:
    catalog = spec.catalog
    return (
        len(ENTITY_SCALAR_FEATURES)
        + len(ENTITY_TYPE_IDS)
        + len(catalog.class_ids)
        + len(catalog.enemy_ids)
        + len(catalog.summon_ids)
        + len(catalog.passive_ids)
        + effect_block_size(spec) * spec.max_effect_slots
    )


def effect_block_size(spec: ObservationSpec) -> int:
    return len(EFFECT_SCALAR_FEATURES) + len(spec.catalog.effect_ids)


def skill_block_size(spec: ObservationSpec) -> int:
    return (
        len(SKILL_SCALAR_FEATURES)
        + len(TARGET_TYPE_IDS)
        + len(DAMAGE_TYPE_IDS)
    )


def build_observation_spec(
    *,
    catalog: ObservationCatalog | None = None,
    max_team_slots: int | None = None,
    max_enemy_slots: int | None = None,
    max_effect_slots: int | None = None,
) -> ObservationSpec:
    catalog = catalog or build_observation_catalog()
    max_team_slots = infer_max_team_slots() if max_team_slots is None else max_team_slots
    max_enemy_slots = infer_max_enemy_slots() if max_enemy_slots is None else max_enemy_slots
    max_effect_slots = (
        max(1, len(catalog.effect_ids))
        if max_effect_slots is None
        else max_effect_slots
    )

    location_size = len(catalog.location_ids) + len(catalog.location_status_ids)
    effect_size = len(EFFECT_SCALAR_FEATURES) + len(catalog.effect_ids)
    entity_size = (
        len(ENTITY_SCALAR_FEATURES)
        + len(ENTITY_TYPE_IDS)
        + len(catalog.class_ids)
        + len(catalog.enemy_ids)
        + len(catalog.summon_ids)
        + len(catalog.passive_ids)
        + effect_size * max_effect_slots
    )
    skill_size = (
        len(SKILL_SCALAR_FEATURES)
        + len(TARGET_TYPE_IDS)
        + len(DAMAGE_TYPE_IDS)
    ) * len(catalog.skill_ids)

    cursor = 0
    slices: dict[str, slice] = {}
    slices["global"] = slice(cursor, cursor + len(GLOBAL_FEATURES))
    cursor = slices["global"].stop
    slices["location"] = slice(cursor, cursor + location_size)
    cursor = slices["location"].stop
    slices["actor"] = slice(cursor, cursor + entity_size)
    cursor = slices["actor"].stop
    slices["team"] = slice(cursor, cursor + entity_size * max_team_slots)
    cursor = slices["team"].stop
    slices["enemies"] = slice(cursor, cursor + entity_size * max_enemy_slots)
    cursor = slices["enemies"].stop
    slices["skills"] = slice(cursor, cursor + skill_size)
    cursor = slices["skills"].stop

    return ObservationSpec(
        catalog=catalog,
        max_team_slots=max_team_slots,
        max_enemy_slots=max_enemy_slots,
        max_effect_slots=max_effect_slots,
        vector_size=cursor,
        slices=slices,
    )


def build_observation_space(spec: ObservationSpec):
    if gym is None:
        raise ModuleNotFoundError("gymnasium is required to build observation spaces")
    return gym.spaces.Box(
        low=0.0,
        high=1.0,
        shape=(spec.vector_size,),
        dtype=np.float32,
    )


def difficulty_modifier(state: CombatState) -> float:
    if state.room_difficulty is None:
        return 1.0
    return float(state.room_difficulty.scalar)


def normalize_difficulty(value: float) -> float:
    max_scalar = float(load_world_difficulty_constants()["max_scalar"])
    return normalized(value, max_scalar)


def average_damage_per_round(state: CombatState, actor_id: str) -> float:
    total = 0

    def collect(result: ActionResult | TriggeredActionResult) -> None:
        nonlocal total
        if result.actor_id == actor_id:
            total += sum(
                hit.damage.amount
                for hit in result.hits
                if hit.damage is not None
            )
        for nested in result.triggered_actions:
            collect(nested)

    for result in state.action_log:
        collect(result)

    return total / max(1, state.round_number)


def _ordered_by_turn(state: CombatState, entities: Iterable[BaseEntity]) -> tuple[BaseEntity, ...]:
    turn_index = {entity_id: index for index, entity_id in enumerate(state.turn_order)}
    fallback = len(turn_index) + 1
    return tuple(sorted(
        entities,
        key=lambda entity: (turn_index.get(entity.entity_id, fallback), entity.entity_id),
    ))


def is_player_team_type(entity_type: EntityType) -> bool:
    return entity_type in {EntityType.PLAYER, EntityType.ALLY}


def ordered_team_entities(
    state: CombatState,
    actor_id: str,
    max_slots: int,
) -> tuple[BaseEntity | None, ...]:
    entities = _ordered_by_turn(
        state,
        (
            entity
            for entity in state.entities.values()
            if entity.entity_id != actor_id
            and is_player_team_type(entity.entity_type)
        ),
    )
    return _pad_entities(entities[:max_slots], max_slots)


def ordered_enemy_entities(
    state: CombatState,
    actor_id: str,
    max_slots: int,
) -> tuple[BaseEntity | None, ...]:
    actor = state.entities[actor_id]
    actor_on_player_team = is_player_team_type(actor.entity_type)
    entities = _ordered_by_turn(
        state,
        (
            entity
            for entity in state.entities.values()
            if is_player_team_type(entity.entity_type) != actor_on_player_team
        ),
    )
    return _pad_entities(entities[:max_slots], max_slots)


def _pad_entities(
    entities: tuple[BaseEntity, ...],
    max_slots: int,
) -> tuple[BaseEntity | None, ...]:
    return entities + ((None,) * max(0, max_slots - len(entities)))


def _alive_ratio(entities: Iterable[BaseEntity]) -> float:
    items = tuple(entities)
    if not items:
        return 0.0
    alive = sum(1 for entity in items if entity.current_hp > 0)
    return alive / len(items)


def _global_features(
    state: CombatState,
    actor_id: str,
    spec: ObservationSpec,
) -> list[float]:
    actor = state.entities[actor_id]
    team = tuple(
        entity
        for entity in state.entities.values()
        if is_player_team_type(entity.entity_type)
    )
    enemies = tuple(
        entity
        for entity in state.entities.values()
        if is_player_team_type(entity.entity_type) != is_player_team_type(actor.entity_type)
    )
    current_actor_id = (
        state.turn_order[state.current_turn_index]
        if state.turn_order and state.current_turn_index < len(state.turn_order)
        else None
    )
    return [
        normalized(state.round_number, ROUND_NORMALIZER),
        normalized(state.current_turn_index, TURN_INDEX_NORMALIZER),
        normalize_difficulty(difficulty_modifier(state)),
        normalized(average_damage_per_round(state, actor_id), DAMAGE_NORMALIZER),
        1.0 if current_actor_id == actor_id else 0.0,
        _alive_ratio(enemies),
        _alive_ratio(team),
    ]


def _location_features(state: CombatState, spec: ObservationSpec) -> list[float]:
    catalog = spec.catalog
    return [
        *one_hot(state.location.location_id, catalog.location_ids),
        *multi_hot(state.location.status_ids, catalog.location_status_ids),
    ]


def _entity_features_or_zero(
    state: CombatState,
    entity: BaseEntity | None,
    actor_id: str,
    spec: ObservationSpec,
    *,
    is_actor: bool = False,
) -> list[float]:
    if entity is None:
        return [0.0] * entity_block_size(spec)
    return _entity_features(state, entity, actor_id, spec, is_actor=is_actor)


def _entity_features(
    state: CombatState,
    entity: BaseEntity,
    actor_id: str,
    spec: ObservationSpec,
    *,
    is_actor: bool,
) -> list[float]:
    catalog = spec.catalog
    entity_id = entity.entity_id
    max_hp = max(0.0, float(get_effective_major_stat(state, entity_id, "hp")))
    max_energy = max(0.0, float(get_effective_major_stat(state, entity_id, "energy")))
    effective_attack = float(get_effective_major_stat(state, entity_id, "attack"))
    effective_speed = float(get_effective_major_stat(state, entity_id, "speed"))
    effective_crit_chance = float(get_effective_major_stat(state, entity_id, "crit_chance"))
    effective_crit_dmg = float(get_effective_major_stat(state, entity_id, "crit_dmg"))
    effective_resistance = float(get_effective_major_stat(state, entity_id, "resistance"))
    effective_mastery = float(get_effective_major_stat(state, entity_id, "mastery"))

    player_class = entity.player_class if isinstance(entity, PlayerCharacter) else None
    enemy_id = entity.enemy_template_id if isinstance(entity, Enemy) else None
    summon_id = entity.summon_template_id if isinstance(entity, SummonEntity) else None

    values = [
        1.0,
        1.0 if is_actor else 0.0,
        1.0 if is_player_team_type(entity.entity_type) else 0.0,
        1.0 if not is_player_team_type(entity.entity_type) else 0.0,
        1.0 if entity.current_hp > 0 else 0.0,
        normalized(entity.current_hp, max_hp),
        normalized(entity.current_energy, max_energy),
        normalized(entity.current_hp, HP_NORMALIZER),
        normalized(entity.current_energy, ENERGY_NORMALIZER),
        normalized(effective_attack, ATTACK_NORMALIZER),
        normalized(max_hp, HP_NORMALIZER),
        normalized(effective_speed, SPEED_NORMALIZER),
        clamp01(effective_crit_chance),
        normalized(effective_crit_dmg, CRIT_DMG_NORMALIZER),
        normalized(effective_resistance, RESISTANCE_NORMALIZER),
        normalized(effective_mastery, MASTERY_NORMALIZER),
        *one_hot(entity.entity_type.value, ENTITY_TYPE_IDS),
        *one_hot(player_class, catalog.class_ids),
        *one_hot(enemy_id, catalog.enemy_ids),
        *one_hot(summon_id, catalog.summon_ids),
        *multi_hot(entity.passive_skills, catalog.passive_ids),
    ]

    active_effects = tuple(entity.active_effects)[:spec.max_effect_slots]
    for effect in active_effects:
        values.extend(_effect_features(effect, spec))
    for _ in range(spec.max_effect_slots - len(active_effects)):
        values.extend([0.0] * effect_block_size(spec))

    return values


def _effect_features(effect: object, spec: ObservationSpec) -> list[float]:
    effect_id = getattr(effect, "effect_id", None)
    return [
        1.0,
        *one_hot(effect_id, spec.catalog.effect_ids),
        normalized(getattr(effect, "remaining_duration", 0), DURATION_NORMALIZER),
        normalized(getattr(effect, "stack_count", 1), STACK_NORMALIZER),
    ]


def _skill_features(
    state: CombatState,
    actor_id: str,
    spec: ObservationSpec,
) -> list[float]:
    actor = state.entities[actor_id]
    access = get_effective_skill_access(actor, state)
    base_skills = set(getattr(actor, "skills", ()))
    granted = set(access.granted)
    max_energy = max(1.0, float(get_effective_major_stat(state, actor_id, "energy")))

    values: list[float] = []
    for skill_id in spec.catalog.skill_ids:
        skill = load_skills()[skill_id]
        target_types: list[str] = []
        damage_types: list[str] = []
        for hit in skill.hits:
            target_types.append(hit.target_type.value)
            if hit.damage_type is not None:
                damage_types.append(hit.damage_type.value)
        for command in skill.summon_commands:
            command_skill = load_skills()[command.summon_skill_id]
            for hit in command_skill.hits:
                target_types.append(hit.target_type.value)
                if hit.damage_type is not None:
                    damage_types.append(hit.damage_type.value)

        values.extend([
            1.0 if skill_id in base_skills or skill_id in granted else 0.0,
            1.0 if skill_id in access.available_set else 0.0,
            1.0 if is_skill_usable(state, actor_id, skill) else 0.0,
            normalized(skill.energy_cost, max_energy),
            normalized(get_remaining_cooldown(state, actor_id, skill_id), COOLDOWN_NORMALIZER),
            normalized(len(skill.hits), HIT_COUNT_NORMALIZER),
            1.0 if skill.self_effects else 0.0,
            1.0 if skill.summons else 0.0,
            1.0 if skill.summon_commands else 0.0,
            *multi_hot(target_types, TARGET_TYPE_IDS),
            *multi_hot(damage_types, DAMAGE_TYPE_IDS),
        ])

    return values


def build_observation(
    state: CombatState,
    actor_id: str,
    spec: ObservationSpec,
) -> np.ndarray:
    if actor_id not in state.entities:
        raise ValueError(f"Unknown actor_id: {actor_id}")

    values: list[float] = []
    actor = state.entities[actor_id]

    values.extend(_global_features(state, actor_id, spec))
    values.extend(_location_features(state, spec))
    values.extend(_entity_features(state, actor, actor_id, spec, is_actor=True))

    for entity in ordered_team_entities(state, actor_id, spec.max_team_slots):
        values.extend(_entity_features_or_zero(state, entity, actor_id, spec))

    for entity in ordered_enemy_entities(state, actor_id, spec.max_enemy_slots):
        values.extend(_entity_features_or_zero(state, entity, actor_id, spec))

    values.extend(_skill_features(state, actor_id, spec))

    obs = np.asarray(values, dtype=np.float32)
    if obs.shape != (spec.vector_size,):
        raise ValueError(
            f"Observation size mismatch: {obs.shape} != {(spec.vector_size,)}",
        )
    return obs
