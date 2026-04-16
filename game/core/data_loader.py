import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from game.core.enums import (
    ActionType,
    CombatLocationType,
    DamageType,
    EnemyCombatType,
    EffectActionType,
    EventType,
    LocationType,
    ModifierPhase,
    OutcomeAction,
    OutcomeTarget,
    PassiveAction,
    ItemEffect,
    ItemType,
    TargetType,
    TriggerType,
    UsageLimit,
)
from game.items.items import ItemBlueprint, ItemBlueprintEffect
from game.events.models import (
    ChoiceDef,
    EventDef,
    EventRequirements,
    OutcomeDef,
)

if TYPE_CHECKING:
    from game.world.difficulty import RoomDifficultyModifier
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
class EffectActionDef:
    action_type: EffectActionType
    expr: str = "0"
    scales_with_stacks: bool = True
    damage_type: DamageType | None = None   # for "damage" — what type of damage
    stat: str | None = None                  # for "stat_modify" — which stat
    skill_id: str | None = None             # for skill grant/block — which skill


@dataclass(frozen=True)
class EffectDef:
    effect_id: str
    name: str
    trigger: TriggerType
    duration: int
    stackable: bool
    actions: tuple[EffectActionDef, ...]
    max_stacks: int | None = None            # None = unlimited
    apply_condition: str | None = None       # checked once on apply
    tick_condition: str | None = None         # checked each tick/on-demand


def _parse_effect_action(raw: dict[str, Any]) -> EffectActionDef:
    action_type = EffectActionType(raw["type"])
    skill_id = raw.get("skill_id")
    dmg_type = None
    if "damage_type" in raw:
        dmg_type = DamageType(raw["damage_type"])
    skill_access_actions = {
        EffectActionType.GRANT_SKILL,
        EffectActionType.BLOCK_SKILL,
    }
    if action_type in skill_access_actions and not skill_id:
        raise ValueError(
            f"Effect action '{action_type.value}' requires skill_id",
        )
    if action_type not in skill_access_actions and skill_id is not None:
        raise ValueError(
            f"skill_id is only valid for skill access actions, got '{action_type.value}'",
        )
    return EffectActionDef(
        action_type=action_type,
        expr=raw.get("expr", "0"),
        scales_with_stacks=raw.get("scales_with_stacks", True),
        damage_type=dmg_type,
        stat=raw.get("stat"),
        skill_id=skill_id,
    )


def load_effects() -> dict[str, EffectDef]:
    raw = _load_toml("effects.toml")["effects"]
    result: dict[str, EffectDef] = {}
    for eid, edata in raw.items():
        actions = tuple(_parse_effect_action(a) for a in edata.get("actions", []))
        result[eid] = EffectDef(
            effect_id=eid,
            name=edata["name"],
            trigger=TriggerType(edata["trigger"]),
            duration=edata["duration"],
            stackable=edata["stackable"],
            actions=actions,
            max_stacks=edata.get("max_stacks"),
            apply_condition=edata.get("apply_condition"),
            tick_condition=edata.get("tick_condition"),
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
    target_type: TargetType
    formula: str
    base_power: int
    damage_type: DamageType | None = None
    variance: float | None = None
    on_hit_effects: tuple[OnHitEffectData, ...] = ()
    share_with: int | None = None


@dataclass(frozen=True)
class SelfEffectData:
    effect_id: str
    duration_override: int | None = None


@dataclass(frozen=True)
class SkillData:
    skill_id: str
    name: str
    energy_cost: int
    action_type: ActionType
    hits: tuple[SkillHitData, ...]
    self_effects: tuple[SelfEffectData, ...]
    cooldown: int = 0
    level_eligibility: tuple[int, int] | None = None
    class_tags: tuple[str, ...] = ()


def _parse_hit(hit_raw: dict[str, Any]) -> SkillHitData:
    on_hits: list[OnHitEffectData] = []
    for ohe in hit_raw.get("on_hit_effects", []):
        on_hits.append(OnHitEffectData(
            effect_id=ohe["effect"],
            chance=ohe["chance"],
        ))
    dmg_type = None
    if "damage_type" in hit_raw:
        dmg_type = DamageType(hit_raw["damage_type"])
    return SkillHitData(
        target_type=TargetType(hit_raw["target_type"]),
        formula=hit_raw["formula"],
        base_power=hit_raw["base_power"],
        damage_type=dmg_type,
        variance=hit_raw.get("variance"),
        on_hit_effects=tuple(on_hits),
        share_with=hit_raw.get("share_with"),
    )


def load_skills() -> dict[str, SkillData]:
    raw = _load_toml("skills.toml")["skills"]
    result: dict[str, SkillData] = {}
    for sid, sdata in raw.items():
        hits = tuple(_parse_hit(h) for h in sdata.get("hits", []))

        self_effects: list[SelfEffectData] = []
        for se in sdata.get("self_effects", []):
            self_effects.append(SelfEffectData(
                effect_id=se["effect"],
                duration_override=se.get("duration_override"),
            ))

        level_eligibility: tuple[int, int] | None = None
        raw_eligibility = sdata.get("level_eligibility")
        if raw_eligibility is not None:
            if len(raw_eligibility) != 2:
                raise ValueError(
                    f"Skill {sid}: level_eligibility must be [min, max], got {raw_eligibility}",
                )
            level_eligibility = (int(raw_eligibility[0]), int(raw_eligibility[1]))

        result[sid] = SkillData(
            skill_id=sid,
            name=sdata["name"],
            energy_cost=sdata["energy_cost"],
            action_type=ActionType(sdata["action_type"]),
            hits=hits,
            self_effects=tuple(self_effects),
            cooldown=sdata.get("cooldown", 0),
            level_eligibility=level_eligibility,
            class_tags=tuple(sdata.get("class_tags", [])),
        )
    return result


def load_skill(skill_id: str) -> SkillData:
    skills = load_skills()
    if skill_id not in skills:
        raise KeyError(f"Unknown skill: {skill_id}")
    return skills[skill_id]


def is_skill_offerable(
    skill: SkillData, player_level: int, player_class: str,
) -> bool:
    """Whether a skill can be offered to a player at level-up.

    Skills must declare `level_eligibility` to be in the pool. Level must fall
    within [min, max] inclusive. If `class_tags` is non-empty, the player's
    class must be in the list.
    """
    if skill.level_eligibility is None:
        return False
    lo, hi = skill.level_eligibility
    if player_level < lo or player_level > hi:
        return False
    if skill.class_tags and player_class not in skill.class_tags:
        return False
    return True


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
    combat_type: EnemyCombatType
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
            combat_type=EnemyCombatType(edata["combat_type"]),
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


def load_world_difficulty_constants() -> dict[str, Any]:
    return _load_toml("constants.toml")["world_difficulty"]


def load_loot_constants() -> dict[str, Any]:
    return _load_toml("constants.toml")["loot"]


# ---------------------------------------------------------------------------
# Loot tables
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LootDropData:
    enemy_id: str
    item_id: str
    min_quantity: int
    max_quantity: int
    drop_rate: float


def load_loot_table() -> dict[str, tuple[LootDropData, ...]]:
    raw = _load_toml("loot_table.toml").get("drops", [])
    grouped: dict[str, list[LootDropData]] = {}

    for row in raw:
        min_quantity = int(row["min_quantity"])
        max_quantity = int(row["max_quantity"])
        drop_rate = float(row["drop_rate"])

        if min_quantity < 0:
            raise ValueError("loot min_quantity must be >= 0")
        if max_quantity < min_quantity:
            raise ValueError("loot max_quantity must be >= min_quantity")
        if not 0.0 <= drop_rate <= 1.0:
            raise ValueError("loot drop_rate must be between 0.0 and 1.0")

        entry = LootDropData(
            enemy_id=str(row["enemy_id"]),
            item_id=str(row["item_id"]),
            min_quantity=min_quantity,
            max_quantity=max_quantity,
            drop_rate=drop_rate,
        )
        grouped.setdefault(entry.enemy_id, []).append(entry)

    return {
        enemy_id: tuple(entries)
        for enemy_id, entries in grouped.items()
    }


def load_enemy_loot(enemy_id: str) -> tuple[LootDropData, ...]:
    return load_loot_table().get(enemy_id, ())


# ---------------------------------------------------------------------------
# Item definitions
# ---------------------------------------------------------------------------

_ITEM_STAT_EFFECTS = {ItemEffect.MODIFY_STAT}
_ITEM_SKILL_EFFECTS = {
    ItemEffect.GRANT_SKILL,
    ItemEffect.BLOCK_SKILL,
}
_ITEM_PASSIVE_EFFECTS = {
    ItemEffect.GRANT_PASSIVE,
    ItemEffect.BLOCK_PASSIVE,
}


def _parse_item_effect(raw: dict[str, Any]) -> ItemBlueprintEffect:
    effect_type = ItemEffect(raw["type"])
    stat = raw.get("stat")
    expr = raw.get("expr")
    skill_id = raw.get("skill_id")
    passive_id = raw.get("passive_id")

    if effect_type in _ITEM_STAT_EFFECTS:
        if stat is None or expr is None:
            raise ValueError(
                f"Item effect '{effect_type.value}' requires stat and expr",
            )
        if skill_id is not None or passive_id is not None:
            raise ValueError(
                f"Item effect '{effect_type.value}' does not accept skill_id/passive_id",
            )
    elif effect_type in _ITEM_SKILL_EFFECTS:
        if skill_id is None:
            raise ValueError(
                f"Item effect '{effect_type.value}' requires skill_id",
            )
        if stat is not None or expr is not None or passive_id is not None:
            raise ValueError(
                f"Item effect '{effect_type.value}' only accepts skill_id",
            )
    elif effect_type in _ITEM_PASSIVE_EFFECTS:
        if passive_id is None:
            raise ValueError(
                f"Item effect '{effect_type.value}' requires passive_id",
            )
        if stat is not None or expr is not None or skill_id is not None:
            raise ValueError(
                f"Item effect '{effect_type.value}' only accepts passive_id",
            )

    return ItemBlueprintEffect(
        effect_type=effect_type,
        stat=stat,
        expr=expr,
        skill_id=skill_id,
        passive_id=passive_id,
    )


def load_item_blueprints() -> dict[str, ItemBlueprint]:
    raw = _load_toml("items.toml").get("items", {})
    return {
        item_id: ItemBlueprint(
            blueprint_id=item_id,
            name=item_data["name"],
            item_type=ItemType(item_data["item_type"]),
            effects=tuple(
                _parse_item_effect(effect_raw)
                for effect_raw in item_data.get("effects", [])
            ),
        )
        for item_id, item_data in raw.items()
    }


def load_item_blueprint(blueprint_id: str) -> ItemBlueprint:
    blueprints = load_item_blueprints()
    if blueprint_id not in blueprints:
        raise KeyError(f"Unknown item blueprint: {blueprint_id}")
    return blueprints[blueprint_id]


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
    triggers: tuple[TriggerType, ...]
    condition: str
    action: PassiveAction
    expr: str
    usage_limit: UsageLimit
    max_uses: int | None = None
    effect_id: str | None = None
    cast_skill_id: str | None = None
    consume_effect_id: str | None = None
    target_type: TargetType = TargetType.SELF
    cooldown: int = 0

    @property
    def trigger(self) -> TriggerType:
        """Compatibility shim for older call sites/tests."""
        return self.triggers[0]


def _parse_passive_triggers(raw: str | list[str]) -> tuple[TriggerType, ...]:
    if isinstance(raw, str):
        return (TriggerType(raw),)
    if isinstance(raw, list) and raw:
        seen: set[TriggerType] = set()
        ordered: list[TriggerType] = []
        for item in raw:
            trigger = TriggerType(item)
            if trigger not in seen:
                seen.add(trigger)
                ordered.append(trigger)
        return tuple(ordered)
    raise ValueError("Passive trigger must be a trigger string or non-empty list")


def load_passives() -> dict[str, PassiveSkillData]:
    raw = _load_toml("passives.toml").get("passives", {})
    return {
        pid: PassiveSkillData(
            skill_id=pid,
            name=pdata["name"],
            triggers=_parse_passive_triggers(pdata["trigger"]),
            condition=pdata.get("condition", ""),
            action=PassiveAction(pdata["action"]),
            expr=pdata.get("expr", "0"),
            usage_limit=UsageLimit(pdata["usage_limit"]),
            max_uses=pdata.get("max_uses"),
            effect_id=pdata.get("effect_id"),
            cast_skill_id=pdata.get("cast_skill_id"),
            consume_effect_id=pdata.get("consume_effect_id"),
            target_type=TargetType(pdata.get("target_type", "self")),
            cooldown=pdata.get("cooldown", 0),
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
    max_stacks: int | None = None            # None = unlimited
    skill_filter: str | None = None
    class_tags: tuple[str, ...] = ()
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
            max_stacks=mdata.get("max_stacks"),
            skill_filter=mdata.get("skill_filter"),
            class_tags=tuple(mdata.get("class_tags", [])),
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
    combat_type: CombatLocationType | None = None
    # Event fields (populated when location_type == EVENT)
    event_id: str | None = None
    room_difficulty: "RoomDifficultyModifier | None" = None


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
    combat_type = None
    if loc_type == LocationType.COMBAT and "combat_type" in raw:
        combat_type = CombatLocationType(raw["combat_type"])
    return LocationOption(
        location_id=f"preset_{index}",
        name=raw.get("name", f"{loc_type.value.title()} {index + 1}"),
        location_type=loc_type,
        tags=tuple(raw.get("tags", [])),
        enemy_ids=tuple(raw.get("enemies", [])),
        status_ids=tuple(raw.get("statuses", [])),
        combat_type=combat_type,
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
    skill_reward_levels: tuple[int, ...] = ()
    skill_reward_offer_size: int = 2


def load_progression() -> ProgressionConfig:
    raw = _load_toml("progression.toml")
    prog_raw = raw["progression"]
    thresholds = tuple(prog_raw["xp_thresholds"])
    skill_reward_levels = tuple(prog_raw.get("skill_reward_levels", []))
    skill_reward_offer_size = int(prog_raw.get("skill_reward_offer_size", 2))
    scaling: dict[str, LevelScalingConfig] = {}
    for class_id, gains in raw.get("level_scaling", {}).items():
        scaling[class_id] = LevelScalingConfig(
            class_id=class_id,
            stat_gains=dict(gains),
        )
    return ProgressionConfig(
        xp_thresholds=thresholds,
        level_scaling=scaling,
        skill_reward_levels=skill_reward_levels,
        skill_reward_offer_size=skill_reward_offer_size,
    )


def clear_cache() -> None:
    """Clear the TOML cache. Useful for testing."""
    _cache.clear()
