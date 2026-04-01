"""Tests for TOML data loading."""

import pytest

from game.core.data_loader import (
    clear_cache,
    load_class,
    load_constants,
    load_effect,
    load_enemy,
    load_formula,
    load_skill,
)
from game.core.enums import (
    ActionType,
    DamageType,
    EffectAction,
    TargetType,
    TriggerType,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_load_formula_physical_slash():
    f = load_formula("physical_slash")
    assert f.formula_id == "physical_slash"
    assert f.attack_scaling == 1.5
    assert f.mastery_scaling == 0.0
    assert f.resistance_scaling == 0.5
    assert f.variance == 0.1


def test_load_formula_unknown_raises():
    with pytest.raises(KeyError, match="Unknown formula"):
        load_formula("nonexistent")


def test_load_effect_poison():
    e = load_effect("poison")
    assert e.effect_id == "poison"
    assert e.trigger == TriggerType.ON_TURN_START
    assert e.action == EffectAction.DAMAGE
    assert e.duration == 3
    assert e.stackable is False
    assert e.damage_type == DamageType.SLASHING


def test_load_effect_stun():
    e = load_effect("stun")
    assert e.action == EffectAction.DEBUFF
    assert e.duration == 1


def test_load_effect_fortify():
    e = load_effect("fortify")
    assert e.trigger == TriggerType.ON_DAMAGE_CALC
    assert e.action == EffectAction.BUFF
    assert e.expr == "0.75"


def test_load_skill_slash():
    s = load_skill("slash")
    assert s.skill_id == "slash"
    assert s.name == "Slash"
    assert s.target_type == TargetType.SINGLE_ENEMY
    assert s.energy_cost == 0
    assert s.action_type == ActionType.ACTION
    assert s.damage_type == DamageType.SLASHING
    assert len(s.hits) == 1
    assert s.hits[0].formula == "physical_slash"
    assert s.hits[0].base_power == 10


def test_load_class_warrior():
    c = load_class("warrior")
    assert c.name == "Warrior"
    assert "slash" in c.starting_skills
    assert c.major_stats["attack"] == 15
    assert c.major_stats["hp"] == 120
    assert c.minor_stats.get("slashing_dmg_pct") == 0.1


def test_load_enemy_goblin():
    e = load_enemy("goblin")
    assert e.name == "Goblin"
    assert "slash" in e.skills
    assert e.major_stats["attack"] == 8
    assert e.major_stats["hp"] == 40


def test_load_constants():
    c = load_constants()
    assert c["initiative_dice"] == 20
    assert c["min_damage"] == 0
    assert c["min_party_size"] == 1
    assert c["max_party_size"] == 4
    assert c["turn_timer_seconds"] == 45
