from dataclasses import replace

import pytest

import game.combat.effects as effects_module
from game.combat.effects import (
    StatusEffectInstance,
    get_effective_major_stat,
    get_effective_minor_stat,
    get_effective_skill_access,
)
from game.core.data_loader import EffectActionDef, EffectDef
from game.core.enums import EffectActionType, ItemEffect, ItemType, TriggerType
from game.items.items import (
    GeneratedItemEffect,
    ItemBlueprint,
    ItemBlueprintEffect,
    ItemInstance,
)
from game.items.equipment_effects import (
    get_effective_passive_ids,
    get_effective_player_major_stat,
    get_effective_player_minor_stat,
)
from game.items.dissolve import dissolve_value_for_items
from game.items.item_generator import generate_item, generate_item_from_blueprint_id
from game.core.data_loader import clear_cache, load_item_blueprint

from tests.unit.conftest import make_combat_state, make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_generate_item_resolves_quality_formula():
    blueprint = load_item_blueprint("long_sword")

    item = generate_item(blueprint, quality=3)

    assert item.blueprint_id == "long_sword"
    assert item.quality == 3
    assert item.effects[0].stat == "attack"
    assert item.effects[0].value == 11.0


def _test_relic(
    instance_id: str,
    *,
    effects: tuple[GeneratedItemEffect, ...] = (),
    item_sets: tuple[str, ...] = (),
    blueprint_id: str | None = None,
    unique: bool = False,
    rarity: str = "common",
) -> ItemInstance:
    return ItemInstance(
        instance_id=instance_id,
        blueprint_id=blueprint_id or instance_id,
        name=instance_id.replace("_", " ").title(),
        item_type=ItemType.RELIC,
        quality=1,
        effects=effects,
        item_sets=item_sets,
        unique=unique,
        rarity=rarity,
    )


def test_generate_item_carries_sets_and_unique_flag():
    item = generate_item_from_blueprint_id("crocodile_tears", quality=1)

    assert item.item_sets == ("wrath_of_beasts",)
    assert item.unique is True
    assert item.rarity == "rare"


def test_generate_item_resolves_percent_stat_formula():
    blueprint = ItemBlueprint(
        blueprint_id="percent_charm",
        name="Percent Charm",
        item_type=ItemType.RELIC,
        effects=(
            ItemBlueprintEffect(
                effect_type=ItemEffect.MODIFY_STAT_PERCENT,
                stat="attack",
                expr="0.05 + quality * 0.01",
            ),
        ),
    )

    item = generate_item(blueprint, quality=3)

    assert item.effects[0].effect_type == ItemEffect.MODIFY_STAT_PERCENT
    assert item.effects[0].stat == "attack"
    assert item.effects[0].value == pytest.approx(0.08)


def test_inventory_equip_and_remove_rules():
    warrior = make_warrior()
    sword = generate_item_from_blueprint_id("long_sword", quality=2)
    charm = generate_item_from_blueprint_id("crocodile_tears")

    inventory = warrior.inventory.add_item(sword).add_item(charm)
    inventory = inventory.equip(sword.instance_id)
    inventory = inventory.equip(charm.instance_id, relic_slot=0)

    assert inventory.equipment.weapon_id == sword.instance_id
    assert inventory.equipment.relic_ids[0] == charm.instance_id

    with pytest.raises(ValueError):
        inventory.remove_item(sword.instance_id)

    inventory = inventory.unequip(sword.instance_id)
    inventory = inventory.remove_item(sword.instance_id)

    assert sword.instance_id not in inventory.items


def test_inventory_dissolve_items_removes_unequipped_items_atomically():
    warrior = make_warrior()
    common = _test_relic("common_relic")
    rare = _test_relic("rare_relic", rarity="rare")
    equipped = _test_relic("equipped_relic")
    inventory = (
        warrior.inventory
        .add_item(common)
        .add_item(rare)
        .add_item(equipped)
        .equip(equipped.instance_id, relic_slot=0)
    )

    updated, dissolved = inventory.dissolve_items((common.instance_id, rare.instance_id))

    assert [item.instance_id for item in dissolved] == ["common_relic", "rare_relic"]
    assert common.instance_id not in updated.items
    assert rare.instance_id not in updated.items
    assert equipped.instance_id in updated.items
    assert updated.equipment.relic_ids[0] == equipped.instance_id


def test_inventory_dissolve_rejects_invalid_selection_without_mutating():
    warrior = make_warrior()
    item = _test_relic("item")
    equipped = _test_relic("equipped")
    inventory = (
        warrior.inventory
        .add_item(item)
        .add_item(equipped)
        .equip(equipped.instance_id, relic_slot=0)
    )

    with pytest.raises(ValueError, match="Duplicate"):
        inventory.dissolve_items((item.instance_id, item.instance_id))
    with pytest.raises(ValueError, match="Equipped"):
        inventory.dissolve_items((equipped.instance_id,))
    with pytest.raises(KeyError):
        inventory.dissolve_items(("missing",))

    assert item.instance_id in inventory.items
    assert equipped.instance_id in inventory.items


def test_dissolve_value_uses_rarity_config_and_common_fallback():
    common = _test_relic("common")
    rare = _test_relic("rare", rarity="rare")
    weird = _test_relic("weird", rarity="mythic")
    config = {
        "rarity_values": {
            "common": 1,
            "rare": 8,
        },
    }

    assert dissolve_value_for_items((common, rare, weird), config) == 10


def test_unique_item_rejects_duplicate_equipped_blueprint():
    warrior = make_warrior()
    first = generate_item_from_blueprint_id(
        "crocodile_tears",
        instance_id="croc_1",
    )
    second = generate_item_from_blueprint_id(
        "crocodile_tears",
        instance_id="croc_2",
    )
    inventory = (
        warrior.inventory
        .add_item(first)
        .add_item(second)
        .equip(first.instance_id, relic_slot=0)
    )

    with pytest.raises(ValueError, match="Only one copy"):
        inventory.equip(second.instance_id, relic_slot=1)

    assert inventory.equipment.relic_ids[0] == first.instance_id
    assert inventory.equipment.relic_ids[1] is None


def test_equipped_item_grants_skill_without_mutating_base_skills():
    warrior = make_warrior()
    relic = _test_relic(
        "battle_charm",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.GRANT_SKILL,
                skill_id="rampage",
            ),
        ),
    )
    warrior = replace(
        warrior,
        inventory=warrior.inventory.add_item(relic).equip(relic.instance_id, relic_slot=0),
    )

    access = get_effective_skill_access(warrior, None)

    assert warrior.skills == ("slash",)
    assert "rampage" in access.available
    assert "rampage" in access.granted


def test_equipped_item_blocks_passive_from_effective_passive_ids():
    warrior = replace(make_warrior(), passive_skills=("battle_master",))
    relic = _test_relic(
        "silencing_relic",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.BLOCK_PASSIVE,
                passive_id="battle_master",
            ),
        ),
    )
    warrior = replace(
        warrior,
        inventory=warrior.inventory.add_item(relic).equip(relic.instance_id, relic_slot=0),
    )

    assert "battle_master" not in get_effective_passive_ids(warrior)


def test_equipped_item_modifies_major_and_minor_stats():
    warrior = make_warrior()
    sword = generate_item_from_blueprint_id("long_sword", quality=2)
    charm = _test_relic(
        "precision_charm",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.MODIFY_STAT,
                stat="slashing_dmg_pct",
                value=0.1,
            ),
        ),
    )
    warrior = replace(
        warrior,
        inventory=(
            warrior.inventory
            .add_item(sword)
            .add_item(charm)
            .equip(sword.instance_id)
            .equip(charm.instance_id, relic_slot=0)
        ),
    )
    state = make_combat_state(players=[warrior])

    assert get_effective_player_major_stat(warrior, "attack") == 24.0
    assert get_effective_major_stat(state, "p1", "attack") == 24.0
    assert get_effective_minor_stat(state, "p1", "slashing_dmg_pct") == pytest.approx(0.2)


def test_percent_stat_bonuses_sum_and_apply_after_flats():
    warrior = make_warrior()
    flat = _test_relic(
        "flat_attack",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.MODIFY_STAT,
                stat="attack",
                value=5,
            ),
        ),
    )
    percent_a = _test_relic(
        "percent_attack_a",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.MODIFY_STAT_PERCENT,
                stat="attack",
                value=0.15,
            ),
        ),
    )
    percent_b = _test_relic(
        "percent_attack_b",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.MODIFY_STAT_PERCENT,
                stat="attack",
                value=0.15,
            ),
        ),
    )
    warrior = replace(
        warrior,
        inventory=(
            warrior.inventory
            .add_item(flat)
            .add_item(percent_a)
            .add_item(percent_b)
            .equip(flat.instance_id, relic_slot=0)
            .equip(percent_a.instance_id, relic_slot=1)
            .equip(percent_b.instance_id, relic_slot=2)
        ),
    )

    assert get_effective_player_major_stat(warrior, "attack") == pytest.approx(26.0)


def test_percent_stat_bonuses_apply_to_minor_stats():
    warrior = make_warrior()
    relic = _test_relic(
        "slash_percent",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.MODIFY_STAT_PERCENT,
                stat="slashing_dmg_pct",
                value=0.5,
            ),
        ),
    )
    warrior = replace(
        warrior,
        inventory=warrior.inventory.add_item(relic).equip(relic.instance_id, relic_slot=0),
    )

    assert get_effective_player_minor_stat(warrior, "slashing_dmg_pct") == pytest.approx(0.15)


def test_combat_temporary_effects_apply_after_item_percent_bonuses(monkeypatch):
    warrior = make_warrior()
    flat = _test_relic(
        "flat_attack",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.MODIFY_STAT,
                stat="attack",
                value=5,
            ),
        ),
    )
    percent = _test_relic(
        "percent_attack",
        effects=(
            GeneratedItemEffect(
                effect_type=ItemEffect.MODIFY_STAT_PERCENT,
                stat="attack",
                value=0.1,
            ),
        ),
    )
    warrior = replace(
        warrior,
        active_effects=(StatusEffectInstance("attack_up", "p1", 1),),
        inventory=(
            warrior.inventory
            .add_item(flat)
            .add_item(percent)
            .equip(flat.instance_id, relic_slot=0)
            .equip(percent.instance_id, relic_slot=1)
        ),
    )
    state = make_combat_state(players=[warrior])
    effect = EffectDef(
        effect_id="attack_up",
        name="Attack Up",
        trigger=TriggerType.ON_APPLY,
        duration=1,
        stackable=False,
        actions=(
            EffectActionDef(
                action_type=EffectActionType.STAT_MODIFY,
                stat="attack",
                expr="10",
            ),
        ),
    )
    monkeypatch.setattr(effects_module, "load_effect", lambda effect_id: effect)

    assert get_effective_major_stat(state, "p1", "attack") == pytest.approx(32.0)


def test_equipped_item_set_bonuses_are_cumulative():
    warrior = make_warrior()
    crocodile = generate_item_from_blueprint_id(
        "crocodile_tears",
        quality=1,
        instance_id="croc",
    )
    wolf = generate_item_from_blueprint_id(
        "wolf_pelt",
        quality=1,
        instance_id="wolf",
    )
    third_piece = _test_relic(
        "third_piece",
        item_sets=("wrath_of_beasts",),
    )
    warrior = replace(
        warrior,
        inventory=(
            warrior.inventory
            .add_item(crocodile)
            .add_item(wolf)
            .add_item(third_piece)
            .equip(crocodile.instance_id, relic_slot=0)
            .equip(wolf.instance_id, relic_slot=1)
            .equip(third_piece.instance_id, relic_slot=2)
        ),
    )
    state = make_combat_state(players=[warrior])

    assert get_effective_player_major_stat(warrior, "crit_dmg") == pytest.approx(1.6)
    assert get_effective_player_major_stat(warrior, "attack") == pytest.approx(16.5)
    assert get_effective_major_stat(state, "p1", "attack") == pytest.approx(16.5)
