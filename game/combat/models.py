from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from game.core.enums import ActionType, CombatPhase, DamageType

if TYPE_CHECKING:
    from game.combat.passives import PassiveTracker


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
    skill_id: str | None = None


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
    passive_trackers: dict[str, PassiveTracker] = ()  # type: ignore[assignment]
    cooldowns: dict[str, dict[str, int]] = ()  # type: ignore[assignment]
    rng_state: tuple | None = None

    def __post_init__(self) -> None:
        if isinstance(self.passive_trackers, tuple):
            object.__setattr__(self, "passive_trackers", {})
        if isinstance(self.cooldowns, tuple):
            object.__setattr__(self, "cooldowns", {})
