import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from game.core.enums import (
    ActionType,
    DamageType,
    EffectAction,
    TargetType,
    TriggerType,
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
# Formula configs
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FormulaConfig:
    formula_id: str
    attack_scaling: float
    mastery_scaling: float
    resistance_scaling: float
    variance: float


def load_formulas() -> dict[str, FormulaConfig]:
    raw = _load_toml("formulas.toml")["formulas"]
    return {
        fid: FormulaConfig(
            formula_id=fid,
            attack_scaling=fdata["attack_scaling"],
            mastery_scaling=fdata["mastery_scaling"],
            resistance_scaling=fdata["resistance_scaling"],
            variance=fdata["variance"],
        )
        for fid, fdata in raw.items()
    }


def load_formula(formula_id: str) -> FormulaConfig:
    formulas = load_formulas()
    if formula_id not in formulas:
        raise KeyError(f"Unknown formula: {formula_id}")
    return formulas[formula_id]


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
    on_hit_effects: tuple[OnHitEffectData, ...]


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


def clear_cache() -> None:
    """Clear the TOML cache. Useful for testing."""
    _cache.clear()
