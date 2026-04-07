import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from game.core.enums import (
    ActionType,
    DamageType,
    EffectAction,
    EventType,
    LocationType,
    ModifierPhase,
    OutcomeAction,
    OutcomeTarget,
    PassiveAction,
    TargetType,
    TriggerType,
    UsageLimit,
)
from game.events.models import (
    ChoiceDef,
    EventDef,
    EventRequirements,
    OutcomeDef,
)
_DATA_DIR = Path(__file__).parent / "data"
_cache: dict[str, Any] = {}


def _load_toml(filename: str) -> dict[str, Any]:
    if filename not in _cache:
        path = _DATA_DIR / filename
        with open(path, "rb") as f:
            _cache[filename] = tomllib.load(f)
    return _cache[filename]


# ---------------------------------------------------------------------------
# Effect definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EffectDef:
    effect_id: str
    name: str
    trigger: TriggerType
    action: EffectAction
    expr: str
    duration: int
    stackable: bool
    damage_type: DamageType | None = None


def load_effects() -> dict[str, EffectDef]:
    raw = _load_toml("effects.toml")["effects"]
    result: dict[str, EffectDef] = {}
    for eid, edata in raw.items():
        dmg_type = None
        if "damage_type" in edata:
            dmg_type = DamageType(edata["damage_type"])
        result[eid] = EffectDef(
            effect_id=eid,
            name=edata["name"],
            trigger=TriggerType(edata["trigger"]),
            action=EffectAction(edata["action"]),
            expr=edata["expr"],
            duration=edata["duration"],
            stackable=edata["stackable"],
            damage_type=dmg_type,
        )
    return result


def load_effect(effect_id: str) -> EffectDef:
    effects = load_effects()
    if effect_id not in effects:
        raise KeyError(f"Unknown effect: {effect_id}")
    return effects[effect_id]


# ---------------------------------------------------------------------------
# Skill definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OnHitEffectData:
    effect_id: str
    chance: float


@dataclass(frozen=True)
class SkillHitData:
    formula: str
    base_power: int
    variance: float | None = None
    on_hit_effects: tuple[OnHitEffectData, ...] = ()


@dataclass(frozen=True)
class SelfEffectData:
    effect_id: str
    duration_override: int | None = None


@dataclass(frozen=True)
class SkillData:
    skill_id: str
    name: str
    target_type: TargetType
    energy_cost: int
    action_type: ActionType
    damage_type: DamageType | None
    hits: tuple[SkillHitData, ...]
    self_effects: tuple[SelfEffectData, ...]


def _parse_hit(hit_raw: dict[str, Any]) -> SkillHitData:
    on_hits: list[OnHitEffectData] = []
    for ohe in hit_raw.get("on_hit_effects", []):
        on_hits.append(OnHitEffectData(
            effect_id=ohe["effect"],
            chance=ohe["chance"],
        ))
    return SkillHitData(
        formula=hit_raw["formula"],
        base_power=hit_raw["base_power"],
        variance=hit_raw.get("variance"),
        on_hit_effects=tuple(on_hits),
    )


def load_skills() -> dict[str, SkillData]:
    raw = _load_toml("skills.toml")["skills"]
    result: dict[str, SkillData] = {}
    for sid, sdata in raw.items():
        dmg_type = None
        if "damage_type" in sdata:
            dmg_type = DamageType(sdata["damage_type"])

        hits = tuple(_parse_hit(h) for h in sdata.get("hits", []))

        self_effects: list[SelfEffectData] = []
        for se in sdata.get("self_effects", []):
            self_effects.append(SelfEffectData(
                effect_id=se["effect"],
                duration_override=se.get("duration_override"),
            ))

        result[sid] = SkillData(
            skill_id=sid,
            name=sdata["name"],
            target_type=TargetType(sdata["target_type"]),
            energy_cost=sdata["energy_cost"],
            action_type=ActionType(sdata["action_type"]),
            damage_type=dmg_type,
            hits=hits,
            self_effects=tuple(self_effects),
        )
    return result


def load_skill(skill_id: str) -> SkillData:
    skills = load_skills()
    if skill_id not in skills:
        raise KeyError(f"Unknown skill: {skill_id}")
    return skills[skill_id]


# ---------------------------------------------------------------------------
# Class templates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassData:
    class_id: str
    name: str
    description: str
    major_stats: dict[str, float]
    minor_stats: dict[str, float]
    starting_skills: tuple[str, ...]
    starting_passives: tuple[str, ...] = ()


def load_classes() -> dict[str, ClassData]:
    raw = _load_toml("classes.toml")["classes"]
    return {
        cid: ClassData(
            class_id=cid,
            name=cdata["name"],
            description=cdata["description"],
            major_stats=dict(cdata["major_stats"]),
            minor_stats=dict(cdata.get("minor_stats", {})),
            starting_skills=tuple(cdata["starting_skills"]),
            starting_passives=tuple(cdata.get("starting_passives", [])),
        )
        for cid, cdata in raw.items()
    }


def load_class(class_id: str) -> ClassData:
    classes = load_classes()
    if class_id not in classes:
        raise KeyError(f"Unknown class: {class_id}")
    return classes[class_id]


# ---------------------------------------------------------------------------
# Enemy templates
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EnemyData:
    enemy_id: str
    name: str
    major_stats: dict[str, float]
    minor_stats: dict[str, float]
    skills: tuple[str, ...]
    xp_reward: int
    tags: tuple[str, ...] = ()
    passives: tuple[str, ...] = ()


def load_enemies() -> dict[str, EnemyData]:
    raw = _load_toml("enemies.toml")["enemies"]
    return {
        eid: EnemyData(
            enemy_id=eid,
            name=edata["name"],
            major_stats=dict(edata["major_stats"]),
            minor_stats=dict(edata.get("minor_stats", {})),
            skills=tuple(edata["skills"]),
            xp_reward=edata["xp_reward"],
            tags=tuple(edata.get("tags", [])),
            passives=tuple(edata.get("passives", [])),
        )
        for eid, edata in raw.items()
    }


def load_enemy(enemy_id: str) -> EnemyData:
    enemies = load_enemies()
    if enemy_id not in enemies:
        raise KeyError(f"Unknown enemy: {enemy_id}")
    return enemies[enemy_id]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def load_constants() -> dict[str, Any]:
    return _load_toml("constants.toml")["combat"]


def load_event_constants() -> dict[str, Any]:
    return _load_toml("constants.toml")["events"]


def load_restoration_constants() -> dict[str, Any]:
    return _load_toml("constants.toml")["restoration"]


# ---------------------------------------------------------------------------
# Event definitions
# ---------------------------------------------------------------------------

def _parse_outcome(raw: dict[str, Any]) -> OutcomeDef:
    enemy_group = tuple(raw.get("enemy_group", []))
    return OutcomeDef(
        action=OutcomeAction(raw["action"]),
        target=OutcomeTarget(raw["target"]),
        expr=raw.get("expr"),
        value=raw.get("value"),
        item_id=raw.get("item_id"),
        effect_id=raw.get("effect_id"),
        enemy_group=enemy_group,
    )


def _parse_choice(index: int, raw: dict[str, Any]) -> ChoiceDef:
    outcomes = tuple(_parse_outcome(o) for o in raw.get("outcomes", []))
    return ChoiceDef(
        index=index,
        label=raw["label"],
        description=raw["description"],
        outcomes=outcomes,
    )


def _parse_requirements(raw: dict[str, Any]) -> EventRequirements:
    return EventRequirements(
        min_level=raw.get("min_level", 0),
        max_level=raw.get("max_level", 999),
        required_classes=tuple(raw.get("required_classes", [])),
    )


def load_events() -> dict[str, EventDef]:
    raw = _load_toml("events.toml")["events"]
    result: dict[str, EventDef] = {}
    for eid, edata in raw.items():
        choices = tuple(
            _parse_choice(i, c) for i, c in enumerate(edata.get("choices", []))
        )
        requirements = _parse_requirements(edata.get("requirements", {}))
        result[eid] = EventDef(
            event_id=eid,
            name=edata["name"],
            description=edata["description"],
            event_type=EventType(edata["event_type"]),
            choices=choices,
            min_depth=edata.get("min_depth", 0),
            max_depth=edata.get("max_depth", 999),
            weight=edata.get("weight", 10),
            requirements=requirements,
        )
    return result


def load_event(event_id: str) -> EventDef:
    events = load_events()
    if event_id not in events:
        raise KeyError(f"Unknown event: {event_id}")
    return events[event_id]


# ---------------------------------------------------------------------------
# Passive skill definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PassiveSkillData:
    skill_id: str
    name: str
    trigger: TriggerType
    condition: str
    action: PassiveAction
    expr: str
    usage_limit: UsageLimit
    max_uses: int | None = None
    effect_id: str | None = None
    target_type: TargetType = TargetType.SELF


def load_passives() -> dict[str, PassiveSkillData]:
    raw = _load_toml("passives.toml").get("passives", {})
    return {
        pid: PassiveSkillData(
            skill_id=pid,
            name=pdata["name"],
            trigger=TriggerType(pdata["trigger"]),
            condition=pdata.get("condition", ""),
            action=PassiveAction(pdata["action"]),
            expr=pdata.get("expr", "0"),
            usage_limit=UsageLimit(pdata["usage_limit"]),
            max_uses=pdata.get("max_uses"),
            effect_id=pdata.get("effect_id"),
            target_type=TargetType(pdata.get("target_type", "self")),
        )
        for pid, pdata in raw.items()
    }


def load_passive(passive_id: str) -> PassiveSkillData:
    passives = load_passives()
    if passive_id not in passives:
        raise KeyError(f"Unknown passive: {passive_id}")
    return passives[passive_id]


# ---------------------------------------------------------------------------
# Skill modifier definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillModifierData:
    modifier_id: str
    name: str
    phase: ModifierPhase
    stackable: bool
    expr: str
    action: str
    skill_filter: str | None = None
    damage_type_filter: str | None = None
    damage_type_override: str | None = None


def load_modifiers() -> dict[str, SkillModifierData]:
    raw = _load_toml("modifiers.toml").get("modifiers", {})
    return {
        mid: SkillModifierData(
            modifier_id=mid,
            name=mdata["name"],
            phase=ModifierPhase(mdata["phase"]),
            stackable=mdata.get("stackable", False),
            expr=mdata.get("expr", "0"),
            action=mdata["action"],
            skill_filter=mdata.get("skill_filter"),
            damage_type_filter=mdata.get("damage_type_filter"),
            damage_type_override=mdata.get("damage_type_override"),
        )
        for mid, mdata in raw.items()
    }


def load_modifier(modifier_id: str) -> SkillModifierData:
    modifiers = load_modifiers()
    if modifier_id not in modifiers:
        raise KeyError(f"Unknown modifier: {modifier_id}")
    return modifiers[modifier_id]


# ---------------------------------------------------------------------------
# Location data definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LocationStatusDef:
    """A modifier applied to a combat location (e.g. dim light, burning ground)."""

    status_id: str
    name: str
    description: str
    affects: str  # "players", "enemies", "all"
    tags: tuple[str, ...]
    stat_modifiers: dict[str, float]  # e.g. {"crit_chance": -0.03}


@dataclass(frozen=True)
class LocationOption:
    """A single choosable destination in the exploration loop."""

    location_id: str
    name: str
    location_type: LocationType
    tags: tuple[str, ...]
    # Combat fields (populated when location_type == COMBAT)
    enemy_ids: tuple[str, ...] = ()
    status_ids: tuple[str, ...] = ()
    # Event fields (populated when location_type == EVENT)
    event_id: str | None = None


@dataclass(frozen=True)
class LocationSetDef:
    """A predetermined set of locations loaded from TOML."""

    set_id: str
    locations: tuple[LocationOption, ...]


# ---------------------------------------------------------------------------
# Location statuses
# ---------------------------------------------------------------------------

def load_location_statuses() -> dict[str, LocationStatusDef]:
    raw = _load_toml("location_statuses.toml")["statuses"]
    return {
        sid: LocationStatusDef(
            status_id=sid,
            name=sdata["name"],
            description=sdata["description"],
            affects=sdata["affects"],
            tags=tuple(sdata.get("tags", [])),
            stat_modifiers=dict(sdata.get("stat_modifiers", {})),
        )
        for sid, sdata in raw.items()
    }


def load_location_status(status_id: str) -> LocationStatusDef:
    statuses = load_location_statuses()
    if status_id not in statuses:
        raise KeyError(f"Unknown location status: {status_id}")
    return statuses[status_id]


# ---------------------------------------------------------------------------
# Predetermined location sets
# ---------------------------------------------------------------------------

def _parse_location_option(index: int, raw: dict[str, Any]) -> LocationOption:
    loc_type = LocationType(raw["type"])
    return LocationOption(
        location_id=f"preset_{index}",
        name=raw.get("name", f"{loc_type.value.title()} {index + 1}"),
        location_type=loc_type,
        tags=tuple(raw.get("tags", [])),
        enemy_ids=tuple(raw.get("enemies", [])),
        status_ids=tuple(raw.get("statuses", [])),
        event_id=raw.get("event_id"),
    )


def load_location_sets() -> dict[str, LocationSetDef]:
    raw = _load_toml("location_sets.toml")["sets"]
    result: dict[str, LocationSetDef] = {}
    for set_id, sdata in raw.items():
        locations = tuple(
            _parse_location_option(i, loc)
            for i, loc in enumerate(sdata.get("locations", []))
        )
        result[set_id] = LocationSetDef(
            set_id=set_id,
            locations=locations,
        )
    return result


def load_location_set(set_id: str) -> LocationSetDef:
    sets = load_location_sets()
    if set_id not in sets:
        raise KeyError(f"Unknown location set: {set_id}")
    return sets[set_id]


# ---------------------------------------------------------------------------
# Progression / level-up configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LevelScalingConfig:
    class_id: str
    stat_gains: dict[str, float]  # only stats that scale for this class


@dataclass(frozen=True)
class ProgressionConfig:
    xp_thresholds: tuple[int, ...]  # cumulative XP needed per level
    level_scaling: dict[str, LevelScalingConfig]  # keyed by class_id


def load_progression() -> ProgressionConfig:
    raw = _load_toml("progression.toml")
    thresholds = tuple(raw["progression"]["xp_thresholds"])
    scaling: dict[str, LevelScalingConfig] = {}
    for class_id, gains in raw.get("level_scaling", {}).items():
        scaling[class_id] = LevelScalingConfig(
            class_id=class_id,
            stat_gains=dict(gains),
        )
    return ProgressionConfig(xp_thresholds=thresholds, level_scaling=scaling)


def clear_cache() -> None:
    """Clear the TOML cache. Useful for testing."""
    _cache.clear()
