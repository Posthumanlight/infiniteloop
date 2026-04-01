from dataclasses import dataclass

from game.core.enums import ActionType, DamageType, TargetType


@dataclass(frozen=True)
class OnHitEffect:
    effect_id: str
    chance: float


@dataclass(frozen=True)
class SkillHit:
    formula: str
    base_power: int
    on_hit_effects: tuple[OnHitEffect, ...] = ()


@dataclass(frozen=True)
class SelfEffect:
    effect_id: str
    duration_override: int | None = None


@dataclass(frozen=True)
class SkillDef:
    skill_id: str
    name: str
    target_type: TargetType
    energy_cost: int
    action_type: ActionType
    damage_type: DamageType | None
    hits: tuple[SkillHit, ...]
    self_effects: tuple[SelfEffect, ...] = ()
