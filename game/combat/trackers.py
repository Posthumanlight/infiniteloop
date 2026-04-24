from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Iterable, Protocol

from game.core.enums import DamageType, PassiveAction, TargetType

if TYPE_CHECKING:
    from game.combat.models import CombatState, HitResult
    from game.core.data_loader import PassiveSkillData
    from game.core.dice import SeededRNG


class TrackerEventType(str, Enum):
    HIT = "hit"


class TrackerRelation(str, Enum):
    SELF = "self"
    ALLY = "ally"
    ENEMY = "enemy"
    SUMMONS = "summons"
    ALL = "all"


class TrackerGroupBy(str, Enum):
    TARGET = "target"
    SOURCE = "source"
    NONE = "none"


class TrackerResetPolicy(str, Enum):
    MATCHED = "matched"


class TrackerCastPolicy(str, Enum):
    NORMAL = "normal"
    FREE = "free"


class TrackerCastTarget(str, Enum):
    DEFAULT = "default"
    TRACKED_TARGET = "tracked_target"


@dataclass(frozen=True)
class TrackedCombatEvent:
    event_type: TrackerEventType
    source_id: str
    target_id: str | None
    damage_amount: int = 0
    damage_type: DamageType | None = None
    skill_id: str | None = None


@dataclass(frozen=True)
class TrackerAction:
    action: PassiveAction
    cast_skill_id: str | None = None
    effect_id: str | None = None
    cast_policy: TrackerCastPolicy = TrackerCastPolicy.NORMAL
    cast_target: TrackerCastTarget = TrackerCastTarget.DEFAULT


@dataclass(frozen=True)
class TrackerDefinition:
    tracker_id: str
    event: TrackerEventType
    source: TrackerRelation
    target: TrackerRelation
    group_by: TrackerGroupBy
    threshold: int
    only_damaging: bool
    reset: TrackerResetPolicy
    action: TrackerAction


class CombatTracker(ABC):
    @property
    @abstractmethod
    def owner_id(self) -> str:
        ...

    @property
    @abstractmethod
    def definition(self) -> TrackerDefinition:
        ...

    @abstractmethod
    def can_observe(self, state: CombatState) -> bool:
        ...


class TrackerProvider(Protocol):
    def collect(self, state: CombatState) -> Iterable[CombatTracker]:
        ...


@dataclass(frozen=True)
class PassiveCombatTracker(CombatTracker):
    _owner_id: str
    passive: PassiveSkillData

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def definition(self) -> TrackerDefinition:
        assert self.passive.tracker is not None
        return self.passive.tracker

    def can_observe(self, state: CombatState) -> bool:
        owner = state.entities.get(self.owner_id)
        return owner is not None and owner.current_hp > 0


class PassiveTrackerProvider:
    def collect(self, state: CombatState) -> Iterable[CombatTracker]:
        from game.core.data_loader import load_passive
        from game.core.enums import TriggerType
        from game.items.equipment_effects import get_effective_passive_ids

        for owner_id, entity in state.entities.items():
            if entity.current_hp <= 0:
                continue
            for passive_id in get_effective_passive_ids(entity):
                passive = load_passive(passive_id)
                if passive.tracker is None:
                    continue
                if TriggerType.ON_TRACKED_EVENT not in passive.triggers:
                    continue
                yield PassiveCombatTracker(owner_id, passive)


DEFAULT_TRACKER_PROVIDERS: tuple[TrackerProvider, ...] = (
    PassiveTrackerProvider(),
)


def process_tracked_event(
    state: CombatState,
    event: TrackedCombatEvent,
    rng: SeededRNG,
    constants: dict,
    providers: tuple[TrackerProvider, ...] = DEFAULT_TRACKER_PROVIDERS,
) -> tuple[CombatState, list[HitResult]]:
    results: list[HitResult] = []

    for provider in providers:
        for tracker in provider.collect(state):
            if not tracker.can_observe(state):
                continue
            if not _matches_tracker(state, tracker, event):
                continue

            key = _counter_key(tracker, event)
            next_count = state.tracker_counts.get(key, 0) + 1
            state = _set_counter(state, key, next_count)
            if next_count < tracker.definition.threshold:
                continue

            if tracker.definition.reset == TrackerResetPolicy.MATCHED:
                state = _set_counter(state, key, 0)

            state, hits, fired = _execute_tracker_action(
                state,
                tracker,
                event,
                rng,
                constants,
            )
            if fired:
                state = _record_tracker_fire(state, tracker)
            results.extend(hits)

    return state, results


def _set_counter(
    state: CombatState,
    key: tuple[str, str, str],
    value: int,
) -> CombatState:
    return replace(state, tracker_counts={**state.tracker_counts, key: value})


def _matches_tracker(
    state: CombatState,
    tracker: CombatTracker,
    event: TrackedCombatEvent,
) -> bool:
    definition = tracker.definition
    if definition.event != event.event_type:
        return False
    if definition.only_damaging and event.damage_amount <= 0:
        return False
    if not _matches_relation(
        state,
        tracker.owner_id,
        event.source_id,
        definition.source,
    ):
        return False
    if event.target_id is None:
        return definition.target == TrackerRelation.ALL
    return _matches_relation(
        state,
        tracker.owner_id,
        event.target_id,
        definition.target,
    )


def _matches_relation(
    state: CombatState,
    owner_id: str,
    subject_id: str,
    relation: TrackerRelation,
) -> bool:
    if relation == TrackerRelation.ALL:
        return True
    owner = state.entities.get(owner_id)
    subject = state.entities.get(subject_id)
    if owner is None or subject is None:
        return False
    if relation == TrackerRelation.SELF:
        return subject_id == owner_id
    if relation == TrackerRelation.SUMMONS:
        from game.combat.summons import SummonEntity

        return isinstance(subject, SummonEntity) and subject.owner_id == owner_id
    if relation == TrackerRelation.ALLY:
        from game.combat.targeting import are_allies

        return subject_id != owner_id and are_allies(owner, subject)
    if relation == TrackerRelation.ENEMY:
        from game.combat.targeting import are_enemies

        return are_enemies(owner, subject)
    return False


def _counter_key(
    tracker: CombatTracker,
    event: TrackedCombatEvent,
) -> tuple[str, str, str]:
    match tracker.definition.group_by:
        case TrackerGroupBy.TARGET:
            group_id = event.target_id or "__none__"
        case TrackerGroupBy.SOURCE:
            group_id = event.source_id
        case TrackerGroupBy.NONE:
            group_id = "__all__"
    return (tracker.owner_id, tracker.definition.tracker_id, group_id)


def _execute_tracker_action(
    state: CombatState,
    tracker: CombatTracker,
    event: TrackedCombatEvent,
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, list[HitResult], bool]:
    if not _can_fire_tracker(state, tracker):
        return state, [], False

    action = tracker.definition.action
    match action.action:
        case PassiveAction.CAST_SKILL:
            return _execute_cast_skill_action(state, tracker, event, rng, constants)
        case PassiveAction.APPLY_EFFECT:
            return _execute_apply_effect_action(state, tracker)
        case _:
            return state, [], False


def _can_fire_tracker(state: CombatState, tracker: CombatTracker) -> bool:
    if isinstance(tracker, PassiveCombatTracker):
        from game.combat.passives import can_fire_passive

        return can_fire_passive(state, tracker.owner_id, tracker.passive)
    return True


def _record_tracker_fire(
    state: CombatState,
    tracker: CombatTracker,
) -> CombatState:
    if isinstance(tracker, PassiveCombatTracker):
        from game.combat.passives import record_passive_fire

        return record_passive_fire(state, tracker.owner_id, tracker.passive)
    return state


def _execute_apply_effect_action(
    state: CombatState,
    tracker: CombatTracker,
) -> tuple[CombatState, list[HitResult], bool]:
    effect_id = tracker.definition.action.effect_id
    if effect_id is None:
        return state, [], False
    from game.combat.effects import apply_effect

    return apply_effect(state, tracker.owner_id, effect_id, tracker.owner_id), [], True


def _execute_cast_skill_action(
    state: CombatState,
    tracker: CombatTracker,
    event: TrackedCombatEvent,
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, list[HitResult], bool]:
    action = tracker.definition.action
    if action.cast_skill_id is None:
        return state, [], False

    from game.combat.action_resolver import (
        cast_skill_now,
        options_for_passive_cast_policy,
    )
    from game.core.data_loader import load_skill

    skill = load_skill(action.cast_skill_id)
    target_refs = _build_target_refs_for_tracker_skill(
        state,
        tracker.owner_id,
        skill,
        event,
        action.cast_target,
    )
    if target_refs is None:
        return state, [], False

    try:
        state, result = cast_skill_now(
            state,
            tracker.owner_id,
            action.cast_skill_id,
            target_refs,
            rng,
            constants,
            options=options_for_passive_cast_policy(action.cast_policy),
        )
    except ValueError:
        return state, [], False

    return state, list(result.hits), True


def _build_target_refs_for_tracker_skill(
    state: CombatState,
    actor_id: str,
    skill,
    event: TrackedCombatEvent,
    cast_target: TrackerCastTarget,
):
    from game.combat.skill_targeting import ActionTargetRef, TargetOwnerKind
    from game.combat.targeting import get_allies, get_enemies
    from game.combat.skill_targeting import iter_target_requirements

    refs: list[ActionTargetRef] = []
    for requirement in iter_target_requirements(skill):
        chosen: str | None = None
        match requirement.target_type:
            case TargetType.SINGLE_ENEMY:
                if cast_target == TrackerCastTarget.TRACKED_TARGET:
                    chosen = event.target_id
                    if chosen not in get_enemies(state, actor_id):
                        return None
                else:
                    candidates = get_enemies(state, actor_id)
                    if not candidates:
                        return None
                    chosen = candidates[0]
            case TargetType.SINGLE_ALLY:
                if cast_target == TrackerCastTarget.TRACKED_TARGET:
                    chosen = event.target_id
                    if chosen not in get_allies(state, actor_id):
                        return None
                else:
                    candidates = get_allies(state, actor_id)
                    if not candidates:
                        return None
                    chosen = candidates[0]
            case TargetType.SELF | TargetType.ALL_ENEMIES | TargetType.ALL_ALLIES:
                continue
            case _:
                continue

        if chosen is None:
            return None
        entity = state.entities.get(chosen)
        if entity is None or entity.current_hp <= 0:
            return None
        refs.append(ActionTargetRef(
            owner_kind=requirement.owner_kind,
            owner_index=requirement.owner_index,
            nested_index=requirement.nested_index,
            entity_id=chosen,
        ))

    return tuple(refs)
