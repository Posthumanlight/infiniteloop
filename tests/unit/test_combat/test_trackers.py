from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from game.character.stats import MajorStats, MinorStats
from game.combat.models import CombatState
from game.combat.summons import SummonEntity
from game.combat.trackers import (
    CombatTracker,
    TrackedCombatEvent,
    TrackerAction,
    TrackerDefinition,
    TrackerEventType,
    TrackerGroupBy,
    TrackerRelation,
    TrackerResetPolicy,
    process_tracked_event,
)
from game.core.dice import SeededRNG
from game.core.enums import EntityType, PassiveAction

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


CONSTANTS = {"min_damage": 0}


@dataclass(frozen=True)
class StaticTracker(CombatTracker):
    _owner_id: str
    _definition: TrackerDefinition

    @property
    def owner_id(self) -> str:
        return self._owner_id

    @property
    def definition(self) -> TrackerDefinition:
        return self._definition

    def can_observe(self, state: CombatState) -> bool:
        return True


@dataclass(frozen=True)
class StaticProvider:
    trackers: tuple[CombatTracker, ...]

    def collect(self, state: CombatState) -> Iterable[CombatTracker]:
        return self.trackers


def _summon(entity_id: str, owner_id: str) -> SummonEntity:
    return SummonEntity(
        entity_id=entity_id,
        entity_name="Test Summon",
        entity_type=EntityType.ALLY,
        major_stats=MajorStats(
            attack=5,
            hp=30,
            speed=20,
            crit_chance=0,
            crit_dmg=1.5,
            resistance=0,
            energy=40,
            mastery=0,
        ),
        minor_stats=MinorStats(values={}),
        current_hp=30,
        current_energy=40,
        owner_id=owner_id,
        skills=("generic_enemy_attack",),
    )


def _tracker_definition(
    *,
    source: TrackerRelation = TrackerRelation.SUMMONS,
    target: TrackerRelation = TrackerRelation.ENEMY,
    group_by: TrackerGroupBy = TrackerGroupBy.TARGET,
    threshold: int = 4,
    only_damaging: bool = True,
) -> TrackerDefinition:
    return TrackerDefinition(
        tracker_id="test_tracker",
        event=TrackerEventType.HIT,
        source=source,
        target=target,
        group_by=group_by,
        threshold=threshold,
        only_damaging=only_damaging,
        reset=TrackerResetPolicy.MATCHED,
        action=TrackerAction(action=PassiveAction.MODIFY_STAT),
    )


def _state() -> CombatState:
    owner = make_warrior("p1")
    ally = make_warrior("p2")
    enemy_a = replace(make_goblin("e1"), current_hp=100)
    enemy_b = replace(make_goblin("e2"), current_hp=100)
    state = make_combat_state(
        players=[owner, ally],
        enemies=[enemy_a, enemy_b],
        turn_order=("p1", "p2", "s1", "s2", "e1", "e2"),
    )
    return replace(
        state,
        entities={
            **state.entities,
            "s1": _summon("s1", "p1"),
            "s2": _summon("s2", "p2"),
        },
    )


def _event(
    *,
    source_id: str = "s1",
    target_id: str = "e1",
    damage_amount: int = 1,
) -> TrackedCombatEvent:
    return TrackedCombatEvent(
        event_type=TrackerEventType.HIT,
        source_id=source_id,
        target_id=target_id,
        damage_amount=damage_amount,
    )


def _process(
    state: CombatState,
    definition: TrackerDefinition,
    event: TrackedCombatEvent,
) -> CombatState:
    tracker = StaticTracker("p1", definition)
    state, _ = process_tracked_event(
        state,
        event,
        SeededRNG(1),
        CONSTANTS,
        providers=(StaticProvider((tracker,)),),
    )
    return state


def test_summons_relation_matches_owned_summons_and_excludes_others():
    definition = _tracker_definition()
    state = _process(_state(), definition, _event(source_id="s1"))

    assert state.tracker_counts[("p1", "test_tracker", "e1")] == 1

    state = _process(state, definition, _event(source_id="s2"))

    assert state.tracker_counts[("p1", "test_tracker", "e1")] == 1


def test_enemy_target_relation_excludes_allies():
    definition = _tracker_definition()
    state = _process(_state(), definition, _event(target_id="p2"))

    assert state.tracker_counts == {}


def test_only_damaging_ignores_zero_damage_hits():
    definition = _tracker_definition()
    state = _process(_state(), definition, _event(damage_amount=0))

    assert state.tracker_counts == {}

    state = _process(state, definition, _event(damage_amount=1))

    assert state.tracker_counts[("p1", "test_tracker", "e1")] == 1


def test_grouping_by_target_keeps_separate_counters():
    definition = _tracker_definition()
    state = _state()

    state = _process(state, definition, _event(target_id="e1"))
    state = _process(state, definition, _event(target_id="e2"))
    state = _process(state, definition, _event(target_id="e1"))
    state = _process(state, definition, _event(target_id="e2"))

    assert state.tracker_counts[("p1", "test_tracker", "e1")] == 2
    assert state.tracker_counts[("p1", "test_tracker", "e2")] == 2


def test_matched_reset_clears_only_counter_that_reaches_threshold():
    definition = _tracker_definition(threshold=2)
    state = _state()

    state = _process(state, definition, _event(target_id="e1"))
    state = _process(state, definition, _event(target_id="e2"))
    state = _process(state, definition, _event(target_id="e1"))

    assert state.tracker_counts[("p1", "test_tracker", "e1")] == 0
    assert state.tracker_counts[("p1", "test_tracker", "e2")] == 1
