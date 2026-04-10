from dataclasses import dataclass

from game.core.enums import ActionType, DamageType, TargetType


@dataclass(frozen=True)
class OnHitEffect:
    effect_id: str
    chance: float


@dataclass(frozen=True)
class SkillHit:
    target_type: TargetType
    formula: str
    base_power: int
    damage_type: DamageType | None = None
    variance: float | None = None
    on_hit_effects: tuple[OnHitEffect, ...] = ()
    share_with: int | None = None


@dataclass(frozen=True)
class SelfEffect:
    effect_id: str
    duration_override: int | None = None


@dataclass(frozen=True)
class SkillDef:
    skill_id: str
    name: str
    energy_cost: int
    action_type: ActionType
    hits: tuple[SkillHit, ...]
    self_effects: tuple[SelfEffect, ...] = ()
