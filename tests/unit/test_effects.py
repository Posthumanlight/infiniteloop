"""Tests for status effects: apply, tick, expire, damage multiplier, stun."""

import pytest
from dataclasses import replace

import game.combat.effects as combat_effects
from game.combat.effects import (
    StatusEffectInstance,
    apply_effect,
    expire_effects,
    get_effective_major_stat,
    get_damage_multiplier,
    is_skipped,
    tick_effects,
)
from game.core.data_loader import EffectActionDef, EffectDef, clear_cache
from game.core.dice import SeededRNG
from game.core.enums import EffectActionType, TriggerType

from tests.unit.conftest import make_combat_state, make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_apply_poison():
    state = make_combat_state()
    state = apply_effect(state, "e1", "poison", "p1")
    goblin = state.entities["e1"]
    assert len(goblin.active_effects) == 1
    assert goblin.active_effects[0].effect_id == "poison"
    assert goblin.active_effects[0].remaining_duration == 3


def test_apply_same_effect_refreshes_duration():
    state = make_combat_state()
    state = apply_effect(state, "e1", "poison", "p1")
    goblin = state.entities["e1"]
    reduced = replace(
        goblin.active_effects[0], remaining_duration=1,
    )
    goblin = replace(goblin, active_effects=(reduced,))
    state = replace(state, entities={**state.entities, "e1": goblin})

    state = apply_effect(state, "e1", "poison", "p1")
    assert state.entities["e1"].active_effects[0].remaining_duration == 3


def test_tick_poison_deals_damage():
    state = make_combat_state()
    state = apply_effect(state, "e1", "poison", "p1")
    rng = SeededRNG(42)

    initial_hp = state.entities["e1"].current_hp
    state, results = tick_effects(state, "e1", TriggerType.ON_TURN_START, rng)

    assert state.entities["e1"].current_hp < initial_hp
    assert len(results) == 1
    assert results[0].damage is not None
    assert results[0].damage.amount > 0


def test_tick_wrong_trigger_does_nothing():
    state = make_combat_state()
    state = apply_effect(state, "e1", "poison", "p1")
    rng = SeededRNG(42)

    initial_hp = state.entities["e1"].current_hp
    state, results = tick_effects(state, "e1", TriggerType.ON_TURN_END, rng)

    assert state.entities["e1"].current_hp == initial_hp
    assert len(results) == 0


def test_expire_effects_decrements():
    state = make_combat_state()
    state = apply_effect(state, "e1", "poison", "p1")
    assert state.entities["e1"].active_effects[0].remaining_duration == 3

    state = expire_effects(state, "e1")
    assert state.entities["e1"].active_effects[0].remaining_duration == 2

    state = expire_effects(state, "e1")
    assert state.entities["e1"].active_effects[0].remaining_duration == 1

    state = expire_effects(state, "e1")
    assert len(state.entities["e1"].active_effects) == 0


def test_is_skipped():
    state = make_combat_state()
    assert is_skipped(state, "e1") is False

    state = apply_effect(state, "e1", "stun", "p1")
    assert is_skipped(state, "e1") is True


def test_fortify_reduces_damage_multiplier():
    state = make_combat_state()
    assert get_damage_multiplier(state, "p1", "e1") == 1.0

    state = apply_effect(state, "e1", "fortify", "e1")
    mult = get_damage_multiplier(state, "p1", "e1")
    assert mult == pytest.approx(0.75)


def test_poison_damage_amount():
    state = make_combat_state()
    state = apply_effect(state, "e1", "poison", "p1")
    rng = SeededRNG(42)

    state, results = tick_effects(state, "e1", TriggerType.ON_TURN_START, rng)
    assert results[0].damage.amount == 2
    assert state.entities["e1"].current_hp == 38


def test_enlightenment_modifies_effective_mastery_and_restores_energy():
    warrior = replace(make_warrior(), current_energy=60)
    state = make_combat_state(players=[warrior])

    state = apply_effect(state, "p1", "enlightenment", "p1")

    assert state.entities["p1"].current_energy == 70
    assert get_effective_major_stat(state, "p1", "mastery") == 25
    assert state.entities["p1"].major_stats.mastery == 5


def test_effect_grant_energy_clamps_to_effective_energy_cap(monkeypatch: pytest.MonkeyPatch):
    def fake_load_effect(effect_id: str) -> EffectDef:
        if effect_id == "energy_cap":
            return EffectDef(
                effect_id="energy_cap",
                name="Energy Cap",
                trigger=TriggerType.ON_APPLY,
                duration=3,
                stackable=False,
                actions=(
                    EffectActionDef(
                        action_type=EffectActionType.STAT_MODIFY,
                        stat="energy",
                        expr="50",
                        scales_with_stacks=False,
                    ),
                ),
            )
        if effect_id == "energy_burst":
            return EffectDef(
                effect_id="energy_burst",
                name="Energy Burst",
                trigger=TriggerType.ON_APPLY,
                duration=1,
                stackable=False,
                actions=(
                    EffectActionDef(
                        action_type=EffectActionType.GRANT_ENERGY,
                        expr="target.energy",
                        scales_with_stacks=False,
                    ),
                ),
            )
        raise KeyError(effect_id)

    monkeypatch.setattr(combat_effects, "load_effect", fake_load_effect)

    warrior = replace(make_warrior(), current_energy=100)
    state = make_combat_state(players=[warrior])

    state = apply_effect(state, "p1", "energy_cap", "p1")
    state = apply_effect(state, "p1", "energy_burst", "p1")

    assert state.entities["p1"].current_energy == 150


def test_effect_heal_clamps_to_effective_hp_cap(monkeypatch: pytest.MonkeyPatch):
    def fake_load_effect(effect_id: str) -> EffectDef:
        if effect_id == "hp_cap":
            return EffectDef(
                effect_id="hp_cap",
                name="HP Cap",
                trigger=TriggerType.ON_APPLY,
                duration=3,
                stackable=False,
                actions=(
                    EffectActionDef(
                        action_type=EffectActionType.STAT_MODIFY,
                        stat="hp",
                        expr="50",
                        scales_with_stacks=False,
                    ),
                ),
            )
        if effect_id == "regen":
            return EffectDef(
                effect_id="regen",
                name="Regen",
                trigger=TriggerType.ON_TURN_START,
                duration=1,
                stackable=False,
                actions=(
                    EffectActionDef(
                        action_type=EffectActionType.HEAL,
                        expr="999",
                        scales_with_stacks=False,
                    ),
                ),
            )
        raise KeyError(effect_id)

    monkeypatch.setattr(combat_effects, "load_effect", fake_load_effect)

    warrior = make_warrior()
    state = make_combat_state(players=[warrior])

    state = apply_effect(state, "p1", "hp_cap", "p1")
    state = apply_effect(state, "p1", "regen", "p1")
    state, results = tick_effects(state, "p1", TriggerType.ON_TURN_START, SeededRNG(42))

    assert state.entities["p1"].current_hp == 170
    assert results[0].heal_amount == 50
