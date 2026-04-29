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
    load_event_constants,
    load_events,
    load_location_sets,
    load_location_statuses,
    load_modifiers,
    load_passives,
    load_skills,
    load_summon_constants,
    load_summons,
    load_world_difficulty_constants,
)
from game.core.enums import (
    DamageType,
    EntityType,
    LevelRewardType,
    LocationType,
    OutcomeAction,
    SessionPhase,
    TargetType,
)
from game.core.game_models import parse_reward_key
from game.session.models import SessionState
from game.world.models import GenerationConfig


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
SESSION_PHASE_IDS = tuple(phase.value for phase in SessionPhase)
DECISION_TYPE_IDS = ("none", "combat", "location", "event", "reward")
LOCATION_TYPE_IDS = tuple(location_type.value for location_type in LocationType)
OUTCOME_ACTION_IDS = tuple(action.value for action in OutcomeAction)
REWARD_KIND_IDS = ("modifier", "skill", "passive")
REWARD_TYPE_IDS = tuple(reward_type.value for reward_type in LevelRewardType)

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
RUN_STAT_NORMALIZER = 100.0
DEPTH_NORMALIZER = 100.0
CHOICE_INDEX_NORMALIZER = 10.0
ENEMY_COUNT_NORMALIZER = 10.0

RUN_GLOBAL_SCALAR_FEATURES = (
    "actor_is_alive",
    "depth_norm",
    "max_depth_norm",
    "rooms_explored_norm",
    "combats_completed_norm",
    "events_completed_norm",
    "enemies_defeated_norm",
    "total_damage_dealt_norm",
    "total_damage_taken_norm",
    "total_healing_norm",
    "total_xp_gained_norm",
    "pending_reward",
)

LOCATION_SCALAR_FEATURES = (
    "present",
    "difficulty_modifier_norm",
    "enemy_count_norm",
    "is_combat",
    "is_event",
)

EVENT_CHOICE_SCALAR_FEATURES = (
    "present",
    "choice_index_norm",
    "starts_combat",
    "enemy_group_size_norm",
)

REWARD_SCALAR_FEATURES = (
    "present",
)


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


@dataclass(frozen=True)
class RunObservationCatalog:
    combat: ObservationCatalog
    modifier_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    event_stage_ids: tuple[str, ...]
    location_tag_ids: tuple[str, ...]


@dataclass(frozen=True)
class RunObservationSpec:
    combat: ObservationSpec
    catalog: RunObservationCatalog
    max_location_choices: int
    max_event_choices: int
    max_reward_choices: int
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


def build_run_observation_catalog(
    combat_catalog: ObservationCatalog | None = None,
) -> RunObservationCatalog:
    events = load_events()
    stage_ids = {
        f"{event_id}:{stage_id}"
        for event_id, event in events.items()
        for stage_id in event.stages
    }
    location_tags = set()
    for location in load_combat_locations().values():
        location_tags.update(location.tags)
    for location_set in load_location_sets().values():
        for option in location_set.locations:
            location_tags.update(option.tags)

    return RunObservationCatalog(
        combat=combat_catalog or build_observation_catalog(),
        modifier_ids=tuple(sorted(load_modifiers())),
        event_ids=tuple(sorted(events)),
        event_stage_ids=tuple(sorted(stage_ids)),
        location_tag_ids=tuple(sorted(location_tags)),
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


def infer_max_location_choices() -> int:
    return max(
        int(load_event_constants().get("max_choices", 4)),
        int(GenerationConfig().count_max),
    )


def infer_max_event_choices() -> int:
    maximum = 1
    for event in load_events().values():
        for stage in event.stages.values():
            maximum = max(maximum, len(stage.choices))
    return maximum


def infer_max_reward_choices() -> int:
    return max(2, int(getattr(load_progression_safe(), "skill_reward_offer_size", 2)))


def load_progression_safe():
    from game.core.data_loader import load_progression

    return load_progression()


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


def run_global_block_size() -> int:
    return (
        len(RUN_GLOBAL_SCALAR_FEATURES)
        + len(SESSION_PHASE_IDS)
        + len(DECISION_TYPE_IDS)
    )


def location_option_block_size(spec: RunObservationSpec) -> int:
    return (
        len(LOCATION_SCALAR_FEATURES)
        + len(LOCATION_TYPE_IDS)
        + len(spec.catalog.location_tag_ids)
        + len(spec.catalog.combat.location_status_ids)
    )


def event_choice_block_size(spec: RunObservationSpec) -> int:
    return (
        len(EVENT_CHOICE_SCALAR_FEATURES)
        + len(spec.catalog.event_ids)
        + len(spec.catalog.event_stage_ids)
        + len(OUTCOME_ACTION_IDS)
    )


def reward_choice_block_size(spec: RunObservationSpec) -> int:
    return (
        len(REWARD_SCALAR_FEATURES)
        + len(REWARD_TYPE_IDS)
        + len(REWARD_KIND_IDS)
        + len(spec.catalog.modifier_ids)
        + len(spec.catalog.combat.skill_ids)
        + len(spec.catalog.combat.passive_ids)
    )


def build_run_observation_spec(
    *,
    combat_spec: ObservationSpec | None = None,
    catalog: RunObservationCatalog | None = None,
    max_location_choices: int | None = None,
    max_event_choices: int | None = None,
    max_reward_choices: int | None = None,
) -> RunObservationSpec:
    combat_spec = combat_spec or build_observation_spec()
    catalog = catalog or build_run_observation_catalog(combat_spec.catalog)
    max_location_choices = (
        infer_max_location_choices()
        if max_location_choices is None
        else max_location_choices
    )
    max_event_choices = (
        infer_max_event_choices()
        if max_event_choices is None
        else max_event_choices
    )
    max_reward_choices = (
        infer_max_reward_choices()
        if max_reward_choices is None
        else max_reward_choices
    )

    temp = RunObservationSpec(
        combat=combat_spec,
        catalog=catalog,
        max_location_choices=max_location_choices,
        max_event_choices=max_event_choices,
        max_reward_choices=max_reward_choices,
        vector_size=0,
        slices={},
    )
    cursor = 0
    slices: dict[str, slice] = {}
    slices["run_global"] = slice(cursor, cursor + run_global_block_size())
    cursor = slices["run_global"].stop
    slices["combat"] = slice(cursor, cursor + combat_spec.vector_size)
    cursor = slices["combat"].stop
    slices["locations"] = slice(
        cursor,
        cursor + location_option_block_size(temp) * max_location_choices,
    )
    cursor = slices["locations"].stop
    slices["events"] = slice(
        cursor,
        cursor + event_choice_block_size(temp) * max_event_choices,
    )
    cursor = slices["events"].stop
    slices["rewards"] = slice(
        cursor,
        cursor + reward_choice_block_size(temp) * max_reward_choices,
    )
    cursor = slices["rewards"].stop

    return RunObservationSpec(
        combat=combat_spec,
        catalog=catalog,
        max_location_choices=max_location_choices,
        max_event_choices=max_event_choices,
        max_reward_choices=max_reward_choices,
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


def build_run_observation_space(spec: RunObservationSpec):
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


def _actor_alive_in_session(state: SessionState, actor_id: str) -> bool:
    if state.combat is not None and actor_id in state.combat.entities:
        return state.combat.entities[actor_id].current_hp > 0
    for player in state.players:
        if player.entity_id == actor_id:
            return player.current_hp > 0
    if state.last_combat is not None and actor_id in state.last_combat.entities:
        return state.last_combat.entities[actor_id].current_hp > 0
    return False


def _run_decision_type(state: SessionState, actor_id: str) -> str:
    if _current_reward_offer(state, actor_id):
        return "reward"
    if state.phase == SessionPhase.IN_COMBAT and state.combat is not None:
        current = (
            state.combat.turn_order[state.combat.current_turn_index]
            if state.combat.turn_order
            and state.combat.current_turn_index < len(state.combat.turn_order)
            else None
        )
        return "combat" if current == actor_id else "none"
    if state.phase == SessionPhase.EXPLORING and state.exploration is not None:
        if state.exploration.current_options:
            return "location"
    if state.phase == SessionPhase.IN_EVENT and state.event is not None:
        return "event"
    return "none"


def _run_global_features(
    state: SessionState,
    actor_id: str,
    spec: RunObservationSpec,
) -> list[float]:
    exploration = state.exploration
    depth = exploration.depth if exploration is not None else 0
    decision_type = _run_decision_type(state, actor_id)
    stats = state.run_stats
    return [
        1.0 if _actor_alive_in_session(state, actor_id) else 0.0,
        normalized(depth, max(1.0, float(state.max_depth or DEPTH_NORMALIZER))),
        normalized(state.max_depth, DEPTH_NORMALIZER),
        normalized(stats.rooms_explored, RUN_STAT_NORMALIZER),
        normalized(stats.combats_completed, RUN_STAT_NORMALIZER),
        normalized(stats.events_completed, RUN_STAT_NORMALIZER),
        normalized(stats.enemies_defeated, RUN_STAT_NORMALIZER),
        normalized(stats.total_damage_dealt, DAMAGE_NORMALIZER * 10.0),
        normalized(stats.total_damage_taken, DAMAGE_NORMALIZER * 10.0),
        normalized(stats.total_healing, DAMAGE_NORMALIZER * 10.0),
        normalized(stats.total_xp_gained, RUN_STAT_NORMALIZER * 10.0),
        1.0 if _current_reward_offer(state, actor_id) else 0.0,
        *one_hot(state.phase.value, SESSION_PHASE_IDS),
        *one_hot(decision_type, DECISION_TYPE_IDS),
    ]


def _location_option_features(option: object, spec: RunObservationSpec) -> list[float]:
    room_difficulty = getattr(option, "room_difficulty", None)
    difficulty = 1.0 if room_difficulty is None else float(room_difficulty.scalar)
    location_type = getattr(option, "location_type", None)
    location_type_value = getattr(location_type, "value", None)
    return [
        1.0,
        normalize_difficulty(difficulty),
        normalized(len(getattr(option, "enemy_ids", ())), ENEMY_COUNT_NORMALIZER),
        1.0 if location_type == LocationType.COMBAT else 0.0,
        1.0 if location_type == LocationType.EVENT else 0.0,
        *one_hot(location_type_value, LOCATION_TYPE_IDS),
        *multi_hot(getattr(option, "tags", ()), spec.catalog.location_tag_ids),
        *multi_hot(
            getattr(option, "status_ids", ()),
            spec.catalog.combat.location_status_ids,
        ),
    ]


def _location_features_or_zero(
    option: object | None,
    spec: RunObservationSpec,
) -> list[float]:
    if option is None:
        return [0.0] * location_option_block_size(spec)
    return _location_option_features(option, spec)


def _event_choice_features(
    state: SessionState,
    choice: object,
    spec: RunObservationSpec,
) -> list[float]:
    event = state.event
    event_id = event.event_def.event_id if event is not None else None
    stage_id = (
        f"{event.event_def.event_id}:{event.current_stage_id}"
        if event is not None
        else None
    )
    outcomes = getattr(choice, "outcomes", ())
    outcome_actions = [outcome.action.value for outcome in outcomes]
    starts_combat = any(outcome.action == OutcomeAction.START_COMBAT for outcome in outcomes)
    enemy_group_size = sum(len(outcome.enemy_group) for outcome in outcomes)
    return [
        1.0,
        normalized(getattr(choice, "index", 0), CHOICE_INDEX_NORMALIZER),
        1.0 if starts_combat else 0.0,
        normalized(enemy_group_size, ENEMY_COUNT_NORMALIZER),
        *one_hot(event_id, spec.catalog.event_ids),
        *one_hot(stage_id, spec.catalog.event_stage_ids),
        *multi_hot(outcome_actions, OUTCOME_ACTION_IDS),
    ]


def _event_choice_features_or_zero(
    state: SessionState,
    choice: object | None,
    spec: RunObservationSpec,
) -> list[float]:
    if choice is None:
        return [0.0] * event_choice_block_size(spec)
    return _event_choice_features(state, choice, spec)


def _current_reward_offer(state: SessionState, actor_id: str) -> tuple[str, ...]:
    queue = state.pending_rewards.get(actor_id)
    if queue is None:
        return ()
    return tuple(queue.current_offer)


def _current_reward_type(state: SessionState, actor_id: str) -> LevelRewardType | None:
    queue = state.pending_rewards.get(actor_id)
    if queue is None:
        return None
    return queue.current_type


def _reward_choice_features(
    state: SessionState,
    actor_id: str,
    reward_key: str,
    spec: RunObservationSpec,
) -> list[float]:
    reward_type = _current_reward_type(state, actor_id)
    reward_kind, reward_id = parse_reward_key(reward_key)
    return [
        1.0,
        *one_hot(
            reward_type.value if reward_type is not None else None,
            REWARD_TYPE_IDS,
        ),
        *one_hot(reward_kind, REWARD_KIND_IDS),
        *one_hot(reward_id if reward_kind == "modifier" else None, spec.catalog.modifier_ids),
        *one_hot(reward_id if reward_kind == "skill" else None, spec.catalog.combat.skill_ids),
        *one_hot(reward_id if reward_kind == "passive" else None, spec.catalog.combat.passive_ids),
    ]


def _reward_choice_features_or_zero(
    state: SessionState,
    actor_id: str,
    reward_key: str | None,
    spec: RunObservationSpec,
) -> list[float]:
    if reward_key is None:
        return [0.0] * reward_choice_block_size(spec)
    return _reward_choice_features(state, actor_id, reward_key, spec)


def _pad_values(values: tuple[object, ...], max_slots: int) -> tuple[object | None, ...]:
    return values[:max_slots] + ((None,) * max(0, max_slots - len(values)))


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


def build_run_observation(
    state: SessionState,
    actor_id: str,
    spec: RunObservationSpec,
) -> np.ndarray:
    values: list[float] = []
    values.extend(_run_global_features(state, actor_id, spec))

    if state.combat is not None and actor_id in state.combat.entities:
        values.extend(build_observation(state.combat, actor_id, spec.combat))
    else:
        values.extend([0.0] * spec.combat.vector_size)

    location_options = (
        tuple(state.exploration.current_options)
        if state.exploration is not None
        else ()
    )
    for option in _pad_values(location_options, spec.max_location_choices):
        values.extend(_location_features_or_zero(option, spec))

    event_choices = (
        tuple(state.event.current_stage.choices)
        if state.event is not None
        else ()
    )
    for choice in _pad_values(event_choices, spec.max_event_choices):
        values.extend(_event_choice_features_or_zero(state, choice, spec))

    reward_offer = _current_reward_offer(state, actor_id)
    for reward_key in _pad_values(reward_offer, spec.max_reward_choices):
        values.extend(_reward_choice_features_or_zero(state, actor_id, reward_key, spec))

    obs = np.asarray(values, dtype=np.float32)
    if obs.shape != (spec.vector_size,):
        raise ValueError(
            f"Run observation size mismatch: {obs.shape} != {(spec.vector_size,)}",
        )
    return obs
