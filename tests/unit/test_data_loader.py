"""Tests for TOML data loading."""

import pytest

from game.core.data_loader import (
    clear_cache,
    load_class,
    load_constants,
    load_effect,
    load_enemy,
    load_enemy_loot,
    load_item_blueprint,
    load_loot_constants,
    load_modifier,
    load_passive,
    load_skill,
)
from game.core.enums import (
    ActionType,
    DamageType,
    EffectActionType,
    ItemEffect,
    ItemType,
    TargetType,
    TriggerType,
)


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_load_effect_bleed():
    e = load_effect("bleed")
    assert e.effect_id == "bleed"
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


def test_load_effect_enlightenment():
    e = load_effect("enlightenment")
    assert e.trigger == TriggerType.ON_APPLY
    assert e.duration == 3
    assert e.actions[0].action_type == EffectActionType.STAT_MODIFY
    assert e.actions[0].stat == "mastery"
    assert e.actions[0].expr == "10 + 2 * target.mastery"
    assert e.actions[1].action_type == EffectActionType.GRANT_ENERGY
    assert e.actions[1].expr == "target.energy * 0.2"


def test_load_effect_berserker_skill_access():
    e = load_effect("berserker")

    assert e.trigger == TriggerType.ON_DAMAGE_CALC
    assert e.actions[2].action_type == EffectActionType.GRANT_SKILL
    assert e.actions[2].skill_id == "rampage"
    assert e.actions[3].action_type == EffectActionType.BLOCK_SKILL
    assert e.actions[3].skill_id == "slash"


def test_load_skill_slash():
    s = load_skill("slash")
    assert s.skill_id == "slash"
    assert s.name == "Slash"
    assert s.energy_cost == 0
    assert s.action_type == ActionType.ACTION
    assert len(s.hits) == 1
    assert s.hits[0].target_type == TargetType.SINGLE_ENEMY
    assert s.hits[0].damage_type == DamageType.SLASHING
    assert "attacker.attack" in s.hits[0].formula
    assert s.hits[0].base_power == 1
    assert s.summary == (
        "Hits a [target_type] for [damage_non_crit] / "
        "[damage_crit] [damage_type] damage."
    )


def test_load_skill_enlightenment():
    s = load_skill("enlightenment")
    assert s.skill_id == "enlightenment"
    assert s.name == "Enlightenment"
    assert s.energy_cost == 0
    assert s.action_type == ActionType.ACTION
    assert s.hits == ()
    assert len(s.self_effects) == 1
    assert s.self_effects[0].effect_id == "enlightenment"
    assert s.summary == "Applies Enlightenment to yourself."


def test_load_class_warrior():
    c = load_class("warrior")
    assert c.name == "Warrior"
    assert "slash" in c.starting_skills
    assert c.major_stats["attack"] == 12
    assert c.major_stats["hp"] == 125
    assert c.minor_stats.get("slashing_dmg_pct") == 0.1


def test_load_class_mage_starts_with_enlightenment():
    c = load_class("mage")
    assert "enlightenment" in c.starting_skills


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


def test_load_passive_multi_trigger():
    passive = load_passive("battle_master")

    assert passive.triggers == (
        TriggerType.ON_HIT,
        TriggerType.ON_TAKE_DAMAGE,
    )
    assert passive.trigger == TriggerType.ON_HIT
    assert passive.action.value == "grant_energy"
    assert passive.level_eligibility == (3, 99)
    assert passive.class_tags == ()


def test_load_passive_offer_metadata():
    passive = load_passive("arcane_rupture")

    assert passive.level_eligibility == (6, 99)
    assert passive.class_tags == ("mage",)
    assert passive.cast_skill_id == "arcane_rupture"


def test_load_item_blueprint_long_sword():
    item = load_item_blueprint("long_sword")

    assert item.blueprint_id == "long_sword"
    assert item.item_type == ItemType.WEAPON
    assert item.effects[0].effect_type == ItemEffect.MODIFY_STAT
    assert item.effects[0].stat == "attack"
    assert item.effects[0].expr == "10 + quality"


def test_load_item_blueprint_sealed_talisman():
    item = load_item_blueprint("sealed_talisman")

    assert item.item_type == ItemType.RELIC
    assert item.effects[0].effect_type == ItemEffect.BLOCK_SKILL
    assert item.effects[0].skill_id == "slash"


def test_load_loot_constants():
    loot = load_loot_constants()

    assert loot["item_quality_formula"] == "room_difficulty_scalar"


def test_load_enemy_loot_goblin_boss():
    loot = load_enemy_loot("goblin_boss")

    assert len(loot) == 1
    assert loot[0].enemy_id == "goblin_boss"
    assert loot[0].item_id == "long_sword"
    assert loot[0].min_quantity == 1
    assert loot[0].max_quantity == 1
    assert loot[0].drop_rate == 1.0
