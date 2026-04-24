import tomllib
import re
from dataclasses import dataclass, field
from enum import Enum
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
from game.items.items import (
    ItemBlueprint,
    ItemBlueprintEffect,
    ItemSetBonusData,
    ItemSetData,
)
from game.events.models import (
    ChoiceDef,
    EventDef,
    EventRequirements,
    EventStageDef,
    OutcomeDef,
)
from game.character.flags import CharacterFlag, JsonValue

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
class SkillSummonData:
    summon_id: str
    count_expr: str = "1"
    duration_own_turns: int | None = None


class SummonCommandCastPolicy(str, Enum):
    NORMAL = "normal"
    FREE = "free"


@dataclass(frozen=True)
class SkillSummonCommandData:
    summon_skill_id: str
    summon_types: tuple[str, ...] = ()
    cast_policy: SummonCommandCastPolicy = SummonCommandCastPolicy.NORMAL


@dataclass(frozen=True)
class SkillData:
    skill_id: str
    name: str
    energy_cost: int
    action_type: ActionType
    hits: tuple[SkillHitData, ...]
    self_effects: tuple[SelfEffectData, ...]
    summons: tuple[SkillSummonData, ...] = ()
    summon_commands: tuple[SkillSummonCommandData, ...] = ()
    cooldown: int = 0
    level_eligibility: tuple[int, int] | None = None
    class_tags: tuple[str, ...] = ()
    summary: str = ""


def _parse_level_eligibility(
    entry_kind: str,
    entry_id: str,
    raw_eligibility: object,
) -> tuple[int, int] | None:
    if raw_eligibility is None:
        return None
    if not isinstance(raw_eligibility, (list, tuple)) or len(raw_eligibility) != 2:
        raise ValueError(
            f"{entry_kind} {entry_id}: level_eligibility must be [min, max], got {raw_eligibility}",
        )
    lo = int(raw_eligibility[0])
    hi = int(raw_eligibility[1])
    if hi < lo:
        raise ValueError(
            f"{entry_kind} {entry_id}: level_eligibility max must be >= min, got {raw_eligibility}",
        )
    return lo, hi


def _is_level_class_offerable(
    level_eligibility: tuple[int, int] | None,
    class_tags: tuple[str, ...],
    player_level: int,
    player_class: str,
) -> bool:
    if level_eligibility is None:
        return False
    lo, hi = level_eligibility
    if player_level < lo or player_level > hi:
        return False
    if class_tags and player_class not in class_tags:
        return False
    return True


_SKILL_SUMMARY_PLACEHOLDER_RE = re.compile(r"\[([A-Za-z0-9_.]+)\]")
_SKILL_SUMMARY_BASE_KEYS = frozenset({
    "hits.count",
    "target_type",
    "damage_type",
    "damage_non_crit",
    "damage_crit",
    "summary_text",
})
_SKILL_SUMMARY_HIT_KEYS = frozenset({
    "target_type",
    "damage_type",
    "damage_non_crit",
    "damage_crit",
    "formula",
})


def _validate_skill_summary_template(
    skill_id: str,
    summary: object,
    *,
    hit_count: int,
) -> str:
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError(f"Skill {skill_id}: summary must be a non-empty string")

    for match in _SKILL_SUMMARY_PLACEHOLDER_RE.finditer(summary):
        key = match.group(1)
        if key in _SKILL_SUMMARY_BASE_KEYS:
            continue

        parts = key.split(".")
        if len(parts) != 3 or parts[0] != "hits" or not parts[1].isdigit():
            raise ValueError(
                f"Skill {skill_id}: unknown summary placeholder [{key}]",
            )

        hit_index = int(parts[1])
        if hit_index < 0 or hit_index >= hit_count:
            raise ValueError(
                f"Skill {skill_id}: summary placeholder [{key}] "
                f"references missing hit index {hit_index}",
            )
        if parts[2] not in _SKILL_SUMMARY_HIT_KEYS:
            raise ValueError(
                f"Skill {skill_id}: unknown summary placeholder [{key}]",
            )

    return summary


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


def _parse_skill_summon(
    skill_id: str,
    summon_raw: dict[str, Any],
) -> SkillSummonData:
    summon_id = str(summon_raw["summon_id"])
    if summon_id not in load_summons():
        raise KeyError(
            f"Skill {skill_id}: unknown summon template '{summon_id}'",
        )

    duration = summon_raw.get("duration_own_turns")
    if duration is not None:
        duration = int(duration)
        if duration <= 0:
            raise ValueError(
                f"Skill {skill_id}: duration_own_turns must be > 0 if provided",
            )

    return SkillSummonData(
        summon_id=summon_id,
        count_expr=str(summon_raw.get("count_expr", "1")),
        duration_own_turns=duration,
    )


def _parse_skill_summon_command(
    skill_id: str,
    command_raw: dict[str, Any],
    *,
    available_skill_ids: set[str],
    available_summon_ids: set[str],
) -> SkillSummonCommandData:
    summon_skill_id = str(command_raw["summon_skill_id"])
    if summon_skill_id not in available_skill_ids:
        raise KeyError(
            f"Skill {skill_id}: unknown summon command skill '{summon_skill_id}'",
        )

    summon_types = tuple(str(value) for value in command_raw.get("summon_types", ()))
    unknown_summons = [
        summon_id
        for summon_id in summon_types
        if summon_id not in available_summon_ids
    ]
    if unknown_summons:
        raise KeyError(
            f"Skill {skill_id}: unknown summon type(s) {unknown_summons}",
        )

    return SkillSummonCommandData(
        summon_skill_id=summon_skill_id,
        summon_types=summon_types,
        cast_policy=SummonCommandCastPolicy(
            command_raw.get("cast_policy", SummonCommandCastPolicy.NORMAL.value),
        ),
    )


def load_skills() -> dict[str, SkillData]:
    raw = _load_toml("skills.toml")["skills"]
    result: dict[str, SkillData] = {}
    available_skill_ids = set(raw)
    available_summon_ids = set(load_summons())
    for sid, sdata in raw.items():
        hits = tuple(_parse_hit(h) for h in sdata.get("hits", []))

        self_effects: list[SelfEffectData] = []
        for se in sdata.get("self_effects", []):
            self_effects.append(SelfEffectData(
                effect_id=se["effect"],
                duration_override=se.get("duration_override"),
            ))

        summons = tuple(
            _parse_skill_summon(sid, summon_raw)
            for summon_raw in sdata.get("summons", [])
        )
        summon_commands = tuple(
            _parse_skill_summon_command(
                sid,
                command_raw,
                available_skill_ids=available_skill_ids,
                available_summon_ids=available_summon_ids,
            )
            for command_raw in sdata.get("summon_commands", [])
        )

        level_eligibility = _parse_level_eligibility(
            "Skill",
            sid,
            sdata.get("level_eligibility"),
        )

        summary = _validate_skill_summary_template(
            sid,
            sdata.get("summary"),
            hit_count=len(hits),
        )

        result[sid] = SkillData(
            skill_id=sid,
            name=sdata["name"],
            energy_cost=sdata["energy_cost"],
            action_type=ActionType(sdata["action_type"]),
            hits=hits,
            self_effects=tuple(self_effects),
            summons=summons,
            summon_commands=summon_commands,
            cooldown=sdata.get("cooldown", 0),
            level_eligibility=level_eligibility,
            class_tags=tuple(sdata.get("class_tags", [])),
            summary=summary,
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
    return _is_level_class_offerable(
        skill.level_eligibility,
        skill.class_tags,
        player_level,
        player_class,
    )


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


@dataclass(frozen=True)
class HeroItemRequirement:
    blueprint_id: str
    count: int = 1


@dataclass(frozen=True)
class HeroFlagRequirement:
    flag_name: str
    flag_value: JsonValue | None = None
    require_value: bool = False


@dataclass(frozen=True)
class HeroModifierStack:
    modifier_id: str
    stacks: int = 1


@dataclass(frozen=True)
class HeroUpgradeRequirements:
    min_level: int | None = None
    class_ids: tuple[str, ...] = ()
    min_stats: dict[str, float] = field(default_factory=dict)
    items: tuple[HeroItemRequirement, ...] = ()
    flags: tuple[HeroFlagRequirement, ...] = ()
    skills: tuple[str, ...] = ()
    passive_skills: tuple[str, ...] = ()
    modifiers: tuple[HeroModifierStack, ...] = ()


@dataclass(frozen=True)
class HeroUpgradeDelta:
    levels: int = 0
    skills: tuple[str, ...] = ()
    passive_skills: tuple[str, ...] = ()
    items: tuple[HeroItemRequirement, ...] = ()
    flags: tuple[str | CharacterFlag, ...] = ()
    modifiers: tuple[HeroModifierStack, ...] = ()


@dataclass(frozen=True)
class HeroClassData:
    class_id: str
    name: str
    description: str
    major_stats: dict[str, float]
    minor_stats: dict[str, float]
    level_scaling: dict[str, float]
    requirements: HeroUpgradeRequirements
    gains: HeroUpgradeDelta = field(default_factory=HeroUpgradeDelta)
    losses: HeroUpgradeDelta = field(default_factory=HeroUpgradeDelta)

    @property
    def starting_skills(self) -> tuple[str, ...]:
        return ()

    @property
    def starting_passives(self) -> tuple[str, ...]:
        return ()

    def to_class_data(self) -> ClassData:
        return ClassData(
            class_id=self.class_id,
            name=self.name,
            description=self.description,
            major_stats=dict(self.major_stats),
            minor_stats=dict(self.minor_stats),
            starting_skills=(),
            starting_passives=(),
        )


@dataclass(frozen=True)
class CharacterClassCatalog:
    base_classes: dict[str, ClassData]
    hero_classes: dict[str, HeroClassData]

    def get_base_class(self, class_id: str) -> ClassData:
        try:
            return self.base_classes[class_id]
        except KeyError as exc:
            raise KeyError(f"Unknown base class: {class_id}") from exc

    def get_character_class(self, class_id: str) -> ClassData:
        if class_id in self.base_classes:
            return self.base_classes[class_id]
        if class_id in self.hero_classes:
            return self.hero_classes[class_id].to_class_data()
        raise KeyError(f"Unknown class: {class_id}")

    def is_hero_class(self, class_id: str) -> bool:
        return class_id in self.hero_classes


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


def load_character_class(class_id: str) -> ClassData:
    return load_class_catalog().get_character_class(class_id)


def _parse_hero_item_requirements(
    raw_items: list[dict[str, Any]] | None,
) -> tuple[HeroItemRequirement, ...]:
    result: list[HeroItemRequirement] = []
    for raw in raw_items or []:
        count = int(raw.get("count", 1))
        if count <= 0:
            raise ValueError("Hero item requirement count must be positive")
        result.append(HeroItemRequirement(
            blueprint_id=str(raw["blueprint_id"]),
            count=count,
        ))
    return tuple(result)


def _parse_hero_flags(
    raw_flags: list[dict[str, Any]] | None,
) -> tuple[HeroFlagRequirement, ...]:
    result: list[HeroFlagRequirement] = []
    for raw in raw_flags or []:
        if "flag_name" not in raw:
            raise ValueError("Hero flag requirement requires flag_name")
        result.append(HeroFlagRequirement(
            flag_name=str(raw["flag_name"]).strip(),
            flag_value=raw.get("flag_value"),
            require_value="flag_value" in raw,
        ))
    return tuple(result)


def _parse_hero_modifier_stacks(
    raw_modifiers: list[dict[str, Any]] | None,
) -> tuple[HeroModifierStack, ...]:
    result: list[HeroModifierStack] = []
    for raw in raw_modifiers or []:
        stacks = int(raw.get("stacks", 1))
        if stacks <= 0:
            raise ValueError("Hero modifier stack count must be positive")
        result.append(HeroModifierStack(
            modifier_id=str(raw["modifier_id"]),
            stacks=stacks,
        ))
    return tuple(result)


def _parse_hero_requirements(raw: dict[str, Any] | None) -> HeroUpgradeRequirements:
    raw = raw or {}
    return HeroUpgradeRequirements(
        min_level=raw.get("min_level"),
        class_ids=tuple(str(value) for value in raw.get("class_ids", ())),
        min_stats={
            str(stat_name): float(value)
            for stat_name, value in raw.get("min_stats", {}).items()
        },
        items=_parse_hero_item_requirements(raw.get("items")),
        flags=_parse_hero_flags(raw.get("flags")),
        skills=tuple(str(value) for value in raw.get("skills", ())),
        passive_skills=tuple(str(value) for value in raw.get("passive_skills", ())),
        modifiers=_parse_hero_modifier_stacks(raw.get("modifiers")),
    )


def _parse_hero_gain_flags(
    raw_flags: list[dict[str, Any]] | None,
) -> tuple[CharacterFlag, ...]:
    result: list[CharacterFlag] = []
    for raw in raw_flags or []:
        result.append(CharacterFlag(
            flag_name=str(raw["flag_name"]),
            flag_value=raw.get("flag_value"),
            flag_persistence=bool(raw.get("flag_persistence", True)),
        ))
    return tuple(result)


def _parse_hero_delta(
    raw: dict[str, Any] | None,
    *,
    gains: bool,
) -> HeroUpgradeDelta:
    raw = raw or {}
    levels = int(raw.get("levels", 0))
    if levels < 0:
        raise ValueError("Hero level gains/losses must be non-negative")
    raw_flags = raw.get("flags", ())
    flags: tuple[str | CharacterFlag, ...]
    if gains:
        flags = _parse_hero_gain_flags(raw_flags)
    else:
        flags = tuple(str(value) for value in raw_flags)
    return HeroUpgradeDelta(
        levels=levels,
        skills=tuple(str(value) for value in raw.get("skills", ())),
        passive_skills=tuple(str(value) for value in raw.get("passive_skills", ())),
        items=_parse_hero_item_requirements(raw.get("items")),
        flags=flags,
        modifiers=_parse_hero_modifier_stacks(raw.get("modifiers")),
    )


def _validate_hero_class(
    hero: HeroClassData,
    *,
    base_class_ids: set[str],
    skill_ids: set[str],
    passive_ids: set[str],
    modifier_ids: set[str],
    item_ids: set[str],
) -> None:
    if hero.class_id in base_class_ids:
        raise ValueError(f"Hero class '{hero.class_id}' collides with a base class")

    def validate_skills(values: tuple[str, ...], label: str) -> None:
        unknown = sorted(set(values) - skill_ids)
        if unknown:
            raise ValueError(f"Hero {hero.class_id}: unknown {label} {unknown}")

    def validate_passives(values: tuple[str, ...], label: str) -> None:
        unknown = sorted(set(values) - passive_ids)
        if unknown:
            raise ValueError(f"Hero {hero.class_id}: unknown {label} {unknown}")

    def validate_modifiers(values: tuple[HeroModifierStack, ...], label: str) -> None:
        unknown = sorted({value.modifier_id for value in values} - modifier_ids)
        if unknown:
            raise ValueError(f"Hero {hero.class_id}: unknown {label} {unknown}")

    def validate_items(values: tuple[HeroItemRequirement, ...], label: str) -> None:
        unknown = sorted({value.blueprint_id for value in values} - item_ids)
        if unknown:
            raise ValueError(f"Hero {hero.class_id}: unknown {label} {unknown}")

    validate_skills(hero.requirements.skills, "required skills")
    validate_skills(hero.gains.skills, "gained skills")
    validate_skills(hero.losses.skills, "lost skills")
    validate_passives(hero.requirements.passive_skills, "required passives")
    validate_passives(hero.gains.passive_skills, "gained passives")
    validate_passives(hero.losses.passive_skills, "lost passives")
    validate_modifiers(hero.requirements.modifiers, "required modifiers")
    validate_modifiers(hero.gains.modifiers, "gained modifiers")
    validate_modifiers(hero.losses.modifiers, "lost modifiers")
    validate_items(hero.requirements.items, "required items")
    validate_items(hero.gains.items, "gained items")
    validate_items(hero.losses.items, "lost items")


def load_hero_classes() -> dict[str, HeroClassData]:
    raw = _load_toml("hero_classes.toml").get("hero_classes", {})
    base_classes = load_classes()
    skill_ids = set(load_skills())
    passive_ids = set(load_passives())
    modifier_ids = set(load_modifiers())
    item_ids = set(load_item_blueprints())
    result: dict[str, HeroClassData] = {}

    for class_id, data in raw.items():
        hero = HeroClassData(
            class_id=class_id,
            name=data["name"],
            description=data["description"],
            major_stats=dict(data["major_stats"]),
            minor_stats=dict(data.get("minor_stats", {})),
            level_scaling=dict(data.get("level_scaling", {})),
            requirements=_parse_hero_requirements(data.get("requirements")),
            gains=_parse_hero_delta(data.get("gains"), gains=True),
            losses=_parse_hero_delta(data.get("losses"), gains=False),
        )
        _validate_hero_class(
            hero,
            base_class_ids=set(base_classes),
            skill_ids=skill_ids,
            passive_ids=passive_ids,
            modifier_ids=modifier_ids,
            item_ids=item_ids,
        )
        result[class_id] = hero

    known_class_ids = set(base_classes) | set(result)
    for hero in result.values():
        unknown = sorted(set(hero.requirements.class_ids) - known_class_ids)
        if unknown:
            raise ValueError(
                f"Hero {hero.class_id}: unknown required classes {unknown}",
            )
    return result


def load_class_catalog() -> CharacterClassCatalog:
    return CharacterClassCatalog(
        base_classes=load_classes(),
        hero_classes=load_hero_classes(),
    )


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
    base_xp_reward: int
    xp_formula: str | None
    combat_type: EnemyCombatType
    tags: tuple[str, ...] = ()
    passives: tuple[str, ...] = ()


def load_enemies() -> dict[str, EnemyData]:
    raw = _load_toml("enemies.toml")["enemies"]
    enemies: dict[str, EnemyData] = {}
    for eid, edata in raw.items():
        base_xp_reward = edata.get("base_xp_reward", edata.get("xp_reward"))
        if base_xp_reward is None:
            raise ValueError(f"Enemy '{eid}' is missing base_xp_reward")
        enemies[eid] = EnemyData(
            enemy_id=eid,
            name=edata["name"],
            major_stats=dict(edata["major_stats"]),
            minor_stats=dict(edata.get("minor_stats", {})),
            skills=tuple(edata["skills"]),
            base_xp_reward=int(base_xp_reward),
            xp_formula=edata.get("xp_formula"),
            combat_type=EnemyCombatType(edata["combat_type"]),
            tags=tuple(edata.get("tags", [])),
            passives=tuple(edata.get("passives", [])),
        )
    return enemies


def load_enemy(enemy_id: str) -> EnemyData:
    enemies = load_enemies()
    if enemy_id not in enemies:
        raise KeyError(f"Unknown enemy: {enemy_id}")
    return enemies[enemy_id]


# ---------------------------------------------------------------------------
# Summon templates
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SummonTemplateData:
    summon_id: str
    name: str
    max_per_owner: int
    skills: tuple[str, ...]
    passives: tuple[str, ...]
    major_stat_formulas: dict[str, str]
    minor_stat_formulas: dict[str, str]


_SUMMON_MAJOR_STAT_KEYS = (
    "attack",
    "hp",
    "speed",
    "crit_chance",
    "crit_dmg",
    "resistance",
    "energy",
    "mastery",
)


def _parse_formula_map(
    summon_id: str,
    section_name: str,
    raw_section: object,
    *,
    required_keys: tuple[str, ...] = (),
) -> dict[str, str]:
    if not isinstance(raw_section, dict):
        raise ValueError(
            f"Summon {summon_id}: {section_name} must be a table of formulas",
        )

    formulas = {
        str(key): str(value)
        for key, value in raw_section.items()
    }
    missing = [key for key in required_keys if key not in formulas]
    if missing:
        raise ValueError(
            f"Summon {summon_id}: missing required {section_name} keys {missing}",
        )
    return formulas


def load_summons() -> dict[str, SummonTemplateData]:
    raw = _load_toml("summons.toml").get("summons", {})
    result: dict[str, SummonTemplateData] = {}

    for summon_id, summon_data in raw.items():
        max_per_owner = int(summon_data["max_per_owner"])
        if max_per_owner <= 0:
            raise ValueError(
                f"Summon {summon_id}: max_per_owner must be > 0",
            )

        result[summon_id] = SummonTemplateData(
            summon_id=summon_id,
            name=summon_data["name"],
            max_per_owner=max_per_owner,
            skills=tuple(summon_data.get("skills", [])),
            passives=tuple(summon_data.get("passives", [])),
            major_stat_formulas=_parse_formula_map(
                summon_id,
                "major_stat_formulas",
                summon_data.get("major_stat_formulas", {}),
                required_keys=_SUMMON_MAJOR_STAT_KEYS,
            ),
            minor_stat_formulas=_parse_formula_map(
                summon_id,
                "minor_stat_formulas",
                summon_data.get("minor_stat_formulas", {}),
            ),
        )

    return result


def load_summon(summon_id: str) -> SummonTemplateData:
    summons = load_summons()
    if summon_id not in summons:
        raise KeyError(f"Unknown summon: {summon_id}")
    return summons[summon_id]


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


def load_summon_constants() -> dict[str, Any]:
    return _load_toml("constants.toml")["summons"]


def load_item_dissolve_constants() -> dict[str, Any]:
    return _load_toml("constants.toml")["item_dissolve"]


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

_ITEM_STAT_EFFECTS = {ItemEffect.MODIFY_STAT, ItemEffect.MODIFY_STAT_PERCENT}
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


def _parse_item_set_bonus(
    set_id: str,
    raw: dict[str, Any],
) -> ItemSetBonusData:
    required_count = int(raw["required_count"])
    if required_count <= 0:
        raise ValueError(
            f"Item set {set_id}: required_count must be positive",
        )

    effects = tuple(
        _parse_item_effect(effect_raw)
        for effect_raw in raw.get("effects", [])
    )
    if not effects:
        raise ValueError(
            f"Item set {set_id}: bonus at {required_count} requires effects",
        )

    return ItemSetBonusData(
        required_count=required_count,
        effects=effects,
    )


def load_item_sets() -> dict[str, ItemSetData]:
    raw = _load_toml("item_sets.toml").get("item_sets", {})
    result: dict[str, ItemSetData] = {}

    for set_id, set_data in raw.items():
        bonuses = tuple(
            _parse_item_set_bonus(set_id, bonus_raw)
            for bonus_raw in set_data.get("bonuses", [])
        )
        required_counts = [bonus.required_count for bonus in bonuses]
        if len(required_counts) != len(set(required_counts)):
            raise ValueError(
                f"Item set {set_id}: duplicate required_count values",
            )

        result[set_id] = ItemSetData(
            set_id=set_id,
            name=set_data["name"],
            bonuses=tuple(sorted(
                bonuses,
                key=lambda bonus: bonus.required_count,
            )),
        )

    return result


def load_item_blueprints() -> dict[str, ItemBlueprint]:
    raw = _load_toml("items.toml").get("items", {})
    item_sets = load_item_sets()
    result: dict[str, ItemBlueprint] = {}

    for item_id, item_data in raw.items():
        if "item_set" in item_data:
            raise ValueError(
                f"Item {item_id}: use item_sets, not item_set",
            )

        raw_item_sets = item_data.get("item_sets", [])
        if not isinstance(raw_item_sets, list):
            raise ValueError(f"Item {item_id}: item_sets must be a list")
        parsed_item_sets = tuple(str(set_id) for set_id in raw_item_sets)
        if len(parsed_item_sets) != len(set(parsed_item_sets)):
            raise ValueError(f"Item {item_id}: duplicate item_sets entries")
        for set_id in parsed_item_sets:
            if set_id not in item_sets:
                raise ValueError(
                    f"Item {item_id}: unknown item set '{set_id}'",
                )
        rarity = str(item_data.get("rarity", "common")).strip()
        if not rarity:
            raise ValueError(f"Item {item_id}: rarity must be a non-empty string")

        result[item_id] = ItemBlueprint(
            blueprint_id=item_id,
            name=item_data["name"],
            item_type=ItemType(item_data["item_type"]),
            effects=tuple(
                _parse_item_effect(effect_raw)
                for effect_raw in item_data.get("effects", [])
            ),
            item_sets=parsed_item_sets,
            unique=bool(item_data.get("unique", False)),
            rarity=rarity,
        )

    return result


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
    next_stage = raw.get("next_stage")
    return ChoiceDef(
        index=index,
        label=raw["label"],
        description=raw["description"],
        outcomes=outcomes,
        next_stage=next_stage,
    )


def _parse_event_stages(event_id: str, raw: dict[str, Any]) -> dict[str, EventStageDef]:
    if "choices" in raw:
        raise ValueError(
            f"Event {event_id}: top-level choices are no longer supported; "
            "move choices under stages.<stage_id>.choices"
        )

    raw_stages = raw.get("stages")
    if not isinstance(raw_stages, dict) or not raw_stages:
        raise ValueError(f"Event {event_id}: stages must be a non-empty table")

    stages: dict[str, EventStageDef] = {}
    for stage_id, stage_raw in raw_stages.items():
        if not isinstance(stage_raw, dict):
            raise ValueError(f"Event {event_id}: stage {stage_id} must be a table")

        raw_choices = stage_raw.get("choices", [])
        if not raw_choices:
            raise ValueError(
                f"Event {event_id}: stage {stage_id} must define at least one choice"
            )

        stages[stage_id] = EventStageDef(
            stage_id=stage_id,
            title=stage_raw["title"],
            description=stage_raw["description"],
            choices=tuple(
                _parse_choice(i, c) for i, c in enumerate(raw_choices)
            ),
        )

    return stages


def _validate_event_stages(
    event_id: str,
    stages: dict[str, EventStageDef],
    initial_stage_id: str,
) -> None:
    if initial_stage_id not in stages:
        raise ValueError(
            f"Event {event_id}: initial_stage_id '{initial_stage_id}' "
            "does not exist"
        )

    for stage in stages.values():
        for choice in stage.choices:
            if choice.next_stage is not None and choice.next_stage not in stages:
                raise ValueError(
                    f"Event {event_id}: choice {choice.index} in stage "
                    f"{stage.stage_id} points to unknown next_stage "
                    f"'{choice.next_stage}'"
                )
            if choice.next_stage is not None and any(
                outcome.action == OutcomeAction.START_COMBAT
                for outcome in choice.outcomes
            ):
                raise ValueError(
                    f"Event {event_id}: choice {choice.index} in stage "
                    f"{stage.stage_id} cannot combine next_stage and start_combat"
                )

    _validate_event_stage_graph_is_acyclic(event_id, stages)


def _validate_event_stage_graph_is_acyclic(
    event_id: str,
    stages: dict[str, EventStageDef],
) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(stage_id: str) -> None:
        if stage_id in visited:
            return
        if stage_id in visiting:
            raise ValueError(
                f"Event {event_id}: stage graph contains a cycle at '{stage_id}'"
            )

        visiting.add(stage_id)
        for choice in stages[stage_id].choices:
            if choice.next_stage is not None:
                visit(choice.next_stage)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id in stages:
        visit(stage_id)


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
        stages = _parse_event_stages(eid, edata)
        initial_stage_id = edata.get("initial_stage_id", "start")
        _validate_event_stages(eid, stages, initial_stage_id)
        requirements = _parse_requirements(edata.get("requirements", {}))
        result[eid] = EventDef(
            event_id=eid,
            name=edata["name"],
            event_type=EventType(edata["event_type"]),
            stages=stages,
            initial_stage_id=initial_stage_id,
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
    level_eligibility: tuple[int, int] | None = None
    class_tags: tuple[str, ...] = ()

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
    result: dict[str, PassiveSkillData] = {}
    for pid, pdata in raw.items():
        result[pid] = PassiveSkillData(
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
            level_eligibility=_parse_level_eligibility(
                "Passive",
                pid,
                pdata.get("level_eligibility"),
            ),
            class_tags=tuple(pdata.get("class_tags", [])),
        )
    return result


def load_passive(passive_id: str) -> PassiveSkillData:
    passives = load_passives()
    if passive_id not in passives:
        raise KeyError(f"Unknown passive: {passive_id}")
    return passives[passive_id]


def is_passive_offerable(
    passive: PassiveSkillData,
    player_level: int,
    player_class: str,
) -> bool:
    return _is_level_class_offerable(
        passive.level_eligibility,
        passive.class_tags,
        player_level,
        player_class,
    )


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
    effect_id: str | None = None
    summon_filter: str | None = None
    summon_stat: str | None = None
    granted_skill_id: str | None = None
    granted_passive_id: str | None = None
    chance: float = 1.0


def load_modifiers() -> dict[str, SkillModifierData]:
    raw = _load_toml("modifiers.toml").get("modifiers", {})
    result: dict[str, SkillModifierData] = {}
    for mid, mdata in raw.items():
        chance = float(mdata.get("chance", 1.0))
        if not 0.0 <= chance <= 1.0:
            raise ValueError(
                f"Modifier {mid}: chance must be between 0.0 and 1.0, got {chance}",
            )

        result[mid] = SkillModifierData(
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
            effect_id=mdata.get("effect_id"),
            summon_filter=mdata.get("summon_filter"),
            summon_stat=mdata.get("summon_stat"),
            granted_skill_id=mdata.get("granted_skill_id"),
            granted_passive_id=mdata.get("granted_passive_id"),
            chance=chance,
        )

        if result[mid].action == "summon_stat_bonus" and result[mid].summon_stat is None:
            raise ValueError(
                f"Modifier {mid}: summon_stat_bonus requires summon_stat",
            )
        if result[mid].action == "summon_grant_skill" and result[mid].granted_skill_id is None:
            raise ValueError(
                f"Modifier {mid}: summon_grant_skill requires granted_skill_id",
            )
        if result[mid].action == "summon_grant_passive" and result[mid].granted_passive_id is None:
            raise ValueError(
                f"Modifier {mid}: summon_grant_passive requires granted_passive_id",
            )
    return result


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
    for class_id, hero in load_hero_classes().items():
        scaling[class_id] = LevelScalingConfig(
            class_id=class_id,
            stat_gains=dict(hero.level_scaling),
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
