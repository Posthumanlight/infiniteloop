from dataclasses import dataclass

from game.core.enums import ActionType, CombatPhase, DamageType


@dataclass(frozen=True)
class ActionRequest:
    actor_id: str
    action_type: ActionType
    skill_id: str | None = None
    target_id: str | None = None
    item_id: str | None = None


@dataclass(frozen=True)
class DamageResult:
    amount: int
    damage_type: DamageType | None
    is_crit: bool
    formula_id: str


@dataclass(frozen=True)
class HitResult:
    target_id: str
    damage: DamageResult | None = None
    heal_amount: int = 0
    effects_applied: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    actor_id: str
    action: ActionRequest
    hits: tuple[HitResult, ...] = ()
    self_effects_applied: tuple[str, ...] = ()
    skipped: bool = False


@dataclass(frozen=True)
class CombatState:
    combat_id: str
    session_id: str
    round_number: int
    turn_order: tuple[str, ...]
    current_turn_index: int
    entities: dict[str, object]  # str -> BaseEntity (avoid circular import)
    phase: CombatPhase
    action_log: tuple[ActionResult, ...] = ()
    rng_state: tuple | None = None
