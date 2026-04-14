"""Tests for the damage pipeline."""

import pytest

from game.combat.damage import resolve_damage
from game.combat.effects import apply_effect
from game.core.data_loader import clear_cache
from game.core.dice import SeededRNG
from game.core.enums import DamageType

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


CONSTANTS = {"min_damage": 0}


def test_damage_positive():
    rng = SeededRNG(42)
    result = resolve_damage(
        attacker=make_warrior(),
        defender=make_goblin(),
        formula_expr="base_power + attacker.attack * 1.5 - target.resistance",
        base_power=10,
        damage_type=DamageType.SLASHING,
        rng=rng,
        effect_multiplier=1.0,
        constants=CONSTANTS,
    )
    assert result.amount > 0
    assert result.damage_type == DamageType.SLASHING
    assert result.formula_id == "expr"


def test_damage_deterministic():
    kwargs = dict(
        attacker=make_warrior(),
        defender=make_goblin(),
        formula_expr="base_power + attacker.attack * 1.5 - target.resistance",
        base_power=10,
        damage_type=DamageType.SLASHING,
        effect_multiplier=1.0,
        constants=CONSTANTS,
    )
    r1 = resolve_damage(rng=SeededRNG(42), **kwargs)
    r2 = resolve_damage(rng=SeededRNG(42), **kwargs)
    assert r1.amount == r2.amount
    assert r1.is_crit == r2.is_crit


def test_damage_manual_calculation():
    for seed in range(100):
        rng = SeededRNG(seed)
        result = resolve_damage(
            attacker=make_warrior(),
            defender=make_goblin(),
            formula_expr="base_power + attacker.attack * 1.5 - target.resistance",
            base_power=10,
            damage_type=DamageType.SLASHING,
            rng=rng,
            effect_multiplier=1.0,
            constants=CONSTANTS,
        )
        if not result.is_crit:
            assert 28 <= result.amount <= 38, f"seed={seed}, amount={result.amount}"
            break
    else:
        pytest.fail("Could not find a non-crit seed in 100 tries")


def test_damage_with_effect_multiplier():
    rng1 = SeededRNG(42)
    base = resolve_damage(
        attacker=make_warrior(),
        defender=make_goblin(),
        formula_expr="base_power + attacker.attack * 1.5 - target.resistance",
        base_power=10,
        damage_type=DamageType.SLASHING,
        rng=rng1,
        effect_multiplier=1.0,
        constants=CONSTANTS,
    )

    rng2 = SeededRNG(42)
    boosted = resolve_damage(
        attacker=make_warrior(),
        defender=make_goblin(),
        formula_expr="base_power + attacker.attack * 1.5 - target.resistance",
        base_power=10,
        damage_type=DamageType.SLASHING,
        rng=rng2,
        effect_multiplier=2.0,
        constants=CONSTANTS,
    )

    assert boosted.amount == int(base.amount * 2) or abs(boosted.amount - base.amount * 2) <= 1


def test_damage_min_floor():
    rng = SeededRNG(42)
    result = resolve_damage(
        attacker=make_goblin(),
        defender=make_warrior(),
        formula_expr="base_power + attacker.attack * 1.5 - target.resistance",
        base_power=0,
        damage_type=DamageType.SLASHING,
        rng=rng,
        effect_multiplier=0.01,
        constants={"min_damage": 0},
    )
    assert result.amount >= 0


def test_effective_mastery_buff_changes_damage_formula():
    state = make_combat_state()
    buffed_state = apply_effect(state, "p1", "enlightenment", "p1")

    base_damage = resolve_damage(
        attacker=state.entities["p1"],
        defender=state.entities["e1"],
        formula_expr="attacker.mastery",
        base_power=0,
        damage_type=DamageType.ARCANE,
        rng=SeededRNG(7),
        effect_multiplier=1.0,
        constants=CONSTANTS,
        state=state,
    )
    buffed_damage = resolve_damage(
        attacker=buffed_state.entities["p1"],
        defender=buffed_state.entities["e1"],
        formula_expr="attacker.mastery",
        base_power=0,
        damage_type=DamageType.ARCANE,
        rng=SeededRNG(7),
        effect_multiplier=1.0,
        constants=CONSTANTS,
        state=buffed_state,
    )

    assert buffed_damage.amount > base_damage.amount
