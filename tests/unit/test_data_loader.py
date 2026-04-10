"""Tests for TOML data loading."""

import pytest

from game.core.data_loader import (
    clear_cache,
    load_class,
    load_constants,
    load_effect,
    load_enemy,
    load_modifier,
    load_skill,
)
from game.core.enums import (
    ActionType,
    DamageType,
    EffectActionType,
    TargetType,
    TriggerType,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_load_effect_poison():
    e = load_effect("poison")
    assert e.effect_id == "poison"
    assert e.trigger == TriggerType.ON_TURN_START
    assert len(e.actions) == 1
    assert e.actions[0].action_type == EffectActionType.DAMAGE
    assert e.actions[0].damage_type == DamageType.SLASHING
    assert e.duration == 3
    assert e.stackable is True


def test_load_effect_stun():
    e = load_effect("stun")
    assert len(e.actions) == 1
    assert e.actions[0].action_type == EffectActionType.SKIP_TURN
    assert e.duration == 1


def test_load_effect_fortify():
    e = load_effect("fortify")
    assert e.trigger == TriggerType.ON_DAMAGE_CALC
    assert len(e.actions) == 1
    assert e.actions[0].action_type == EffectActionType.DAMAGE_TAKEN_MULT
    assert e.actions[0].expr == "0.75"


def test_load_skill_slash():
    s = load_skill("slash")
    assert s.skill_id == "slash"
    assert s.name == "Slash"
    assert s.target_type == TargetType.SINGLE_ENEMY
    assert s.energy_cost == 0
    assert s.action_type == ActionType.ACTION
    assert s.damage_type == DamageType.SLASHING
    assert len(s.hits) == 1
    assert "attacker.attack" in s.hits[0].formula
    assert s.hits[0].base_power == 10


def test_load_class_warrior():
    c = load_class("warrior")
    assert c.name == "Warrior"
    assert "slash" in c.starting_skills
    assert c.major_stats["attack"] == 12
    assert c.major_stats["hp"] == 125
    assert c.minor_stats.get("slashing_dmg_pct") == 0.1


def test_load_enemy_goblin():
    e = load_enemy("goblin")
    assert e.name == "Goblin"
    assert "generic_enemy_attack" in e.skills
    assert e.major_stats["attack"] == 3
    assert e.major_stats["hp"] == 40


def test_load_constants():
    c = load_constants()
    assert c["initiative_dice"] == 20
    assert c["min_damage"] == 0
    assert c["min_party_size"] == 1
    assert c["max_party_size"] == 4
    assert c["turn_timer_seconds"] == 45


def test_load_modifier_with_class_tags():
    m = load_modifier("slash_power")
    assert m.modifier_id == "slash_power"
    assert m.skill_filter == "slash"
    assert "warrior" in m.class_tags
