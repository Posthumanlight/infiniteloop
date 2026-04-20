from dataclasses import replace

import pytest

from game.combat.effects import (
    get_effective_major_stat,
    get_effective_minor_stat,
    get_effective_skill_access,
)
from game.items.equipment_effects import (
    get_effective_passive_ids,
    get_effective_player_major_stat,
    get_effective_player_minor_stat,
)
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
    assert item.effects[0].value == 13.0


def test_generate_item_carries_sets_and_unique_flag():
    item = generate_item_from_blueprint_id("crocodile_tears", quality=1)

    assert item.item_sets == ("crocodile_regalia",)
    assert item.unique is True


def test_inventory_equip_and_remove_rules():
    warrior = make_warrior()
    sword = generate_item_from_blueprint_id("long_sword", quality=2)
    charm = generate_item_from_blueprint_id("battle_charm")

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
    relic = generate_item_from_blueprint_id("battle_charm")
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
    relic = generate_item_from_blueprint_id("silencing_relic")
    warrior = replace(
        warrior,
        inventory=warrior.inventory.add_item(relic).equip(relic.instance_id, relic_slot=0),
    )

    assert "battle_master" not in get_effective_passive_ids(warrior)


def test_equipped_item_modifies_major_and_minor_stats():
    warrior = make_warrior()
    sword = generate_item_from_blueprint_id("long_sword", quality=2)
    charm = generate_item_from_blueprint_id("precision_charm", quality=2)
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

    assert get_effective_player_major_stat(warrior, "attack") == 27.0
    assert get_effective_major_stat(state, "p1", "attack") == 27.0
    assert get_effective_minor_stat(state, "p1", "slashing_dmg_pct") == pytest.approx(0.2)


def test_equipped_item_set_bonuses_are_cumulative_and_multi_set():
    warrior = make_warrior()
    crocodile = generate_item_from_blueprint_id(
        "crocodile_tears",
        quality=1,
        instance_id="croc",
    )
    fang = generate_item_from_blueprint_id(
        "river_fang",
        quality=1,
        instance_id="fang",
    )
    hide = generate_item_from_blueprint_id(
        "marsh_hide_charm",
        quality=1,
        instance_id="hide",
    )
    claw = generate_item_from_blueprint_id(
        "predator_claw",
        quality=1,
        instance_id="claw",
    )
    warrior = replace(
        warrior,
        inventory=(
            warrior.inventory
            .add_item(crocodile)
            .add_item(fang)
            .add_item(hide)
            .add_item(claw)
            .equip(crocodile.instance_id, relic_slot=0)
            .equip(fang.instance_id, relic_slot=1)
            .equip(hide.instance_id, relic_slot=2)
            .equip(claw.instance_id, relic_slot=3)
        ),
    )
    state = make_combat_state(players=[warrior])

    assert get_effective_player_major_stat(warrior, "crit_chance") == pytest.approx(
        0.05 + 0.045 + 0.15,
    )
    assert get_effective_player_minor_stat(warrior, "slashing_dmg_pct") == pytest.approx(
        0.1 + 0.03,
    )
    assert "battle_master" in get_effective_passive_ids(warrior)

    access = get_effective_skill_access(warrior, state)
    assert "rampage" in access.available
