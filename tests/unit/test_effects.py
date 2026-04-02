"""Tests for status effects: apply, tick, expire, damage multiplier, stun."""

import pytest
from dataclasses import replace

from game.combat.effects import (
    StatusEffectInstance,
    apply_effect,
    expire_effects,
    get_damage_multiplier,
    is_skipped,
    tick_effects,
)
from game.core.data_loader import clear_cache
from game.core.dice import SeededRNG
from game.core.enums import TriggerType

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


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
    # Manually reduce duration
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
    """Poison expr = target.hp * 0.05. Goblin hp=40 → 2 damage."""
    state = make_combat_state()
    state = apply_effect(state, "e1", "poison", "p1")
    rng = SeededRNG(42)

    state, results = tick_effects(state, "e1", TriggerType.ON_TURN_START, rng)
    assert results[0].damage.amount == 2
    assert state.entities["e1"].current_hp == 38
