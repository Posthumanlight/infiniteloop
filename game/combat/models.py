from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from game.combat.skill_targeting import ActionTargetRef, TargetOwnerKind
from game.core.enums import ActionType, CombatPhase, DamageType

if TYPE_CHECKING:
    from game.combat.passives import PassiveTracker
    from game.world.difficulty import RoomDifficultyModifier


class TurnOrder(tuple):
    def __new__(
        cls,
        values: tuple[str, ...],
        initiative_scores: dict[str, tuple[int, int]] | None = None,
    ) -> "TurnOrder":
        obj = super().__new__(cls, values)
        obj.initiative_scores = initiative_scores or {}
        return obj


@dataclass(frozen=True)
class ActionRequest:
    actor_id: str
    action_type: ActionType
    skill_id: str | None = None
    target_ids: tuple[tuple[int, str], ...] = ()  # (hit_index, entity_id) pairs for single-target hits
    target_refs: tuple[ActionTargetRef, ...] = ()
    item_id: str | None = None

    def __post_init__(self) -> None:
        if self.target_refs and not self.target_ids:
            hit_pairs = tuple(
                (ref.owner_index, ref.entity_id)
                for ref in self.target_refs
                if ref.owner_kind == TargetOwnerKind.HIT
            )
            object.__setattr__(self, "target_ids", hit_pairs)
            return

        if self.target_ids and not self.target_refs:
            refs = tuple(
                ActionTargetRef(
                    owner_kind=TargetOwnerKind.HIT,
                    owner_index=hit_index,
                    nested_index=0,
                    entity_id=entity_id,
                )
                for hit_index, entity_id in self.target_ids
            )
            object.__setattr__(self, "target_refs", refs)

    def get_target_map(self) -> dict[int, str]:
        return self.targets_for_hits()

    def targets_for_hits(self) -> dict[int, str]:
        return {
            ref.owner_index: ref.entity_id
            for ref in self.target_refs
            if ref.owner_kind == TargetOwnerKind.HIT
        }

    def targets_for_command(self, command_index: int) -> dict[int, str]:
        return {
            ref.nested_index: ref.entity_id
            for ref in self.target_refs
            if ref.owner_kind == TargetOwnerKind.SUMMON_COMMAND
            and ref.owner_index == command_index
        }


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
class SummonSpawnResult:
    entity_id: str
    name: str
    owner_id: str
    summon_template_id: str


@dataclass(frozen=True)
class TriggeredActionResult:
    actor_id: str
    skill_id: str
    hits: tuple[HitResult, ...] = ()
    self_effects_applied: tuple[str, ...] = ()
    summons_created: tuple[SummonSpawnResult, ...] = ()
    triggered_actions: tuple["TriggeredActionResult", ...] = ()


@dataclass(frozen=True)
class SkillResolutionResult:
    hits: tuple[HitResult, ...] = ()
    self_effects_applied: tuple[str, ...] = ()
    summons_created: tuple[SummonSpawnResult, ...] = ()
    triggered_actions: tuple[TriggeredActionResult, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    actor_id: str
    action: ActionRequest
    hits: tuple[HitResult, ...] = ()
    self_effects_applied: tuple[str, ...] = ()
    summons_created: tuple[SummonSpawnResult, ...] = ()
    triggered_actions: tuple[TriggeredActionResult, ...] = ()
    skipped: bool = False
    round_number: int | None = None


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
    passive_trackers: dict[str, PassiveTracker] = field(default_factory=dict)
    cooldowns: dict[str, dict[str, int]] = field(default_factory=dict)
    initiative_scores: dict[str, tuple[int, int]] = field(default_factory=dict)
    next_summon_order: int = 1
    rng_state: tuple | None = None
    room_difficulty: RoomDifficultyModifier | None = None

    def __post_init__(self) -> None:
        if self.initiative_scores:
            return
        carried_scores = getattr(self.turn_order, "initiative_scores", None)
        if carried_scores:
            object.__setattr__(self, "initiative_scores", dict(carried_scores))
