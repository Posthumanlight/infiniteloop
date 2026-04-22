import pytest

from game.character.hero_upgrades import (
    HeroUpgradeService,
    select_unequipped_items_by_blueprint,
)
from game.character.inventory import Inventory
from game.combat.skill_modifiers import ModifierInstance
from game.core.data_loader import (
    HeroItemRequirement,
    clear_cache,
    load_character_class,
    load_classes,
    load_hero_classes,
    load_progression,
)
from game.items.item_generator import generate_item_from_blueprint_id
from game.session.lobby_manager import CharacterRecord


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _eligible_summoner_record() -> CharacterRecord:
    return CharacterRecord(
        character_id=42,
        tg_id=1001,
        character_name="Asha",
        class_id="summoner",
        level=7,
        xp=1250,
        skills=("mana_reave", "summon_familiar", "command_spell"),
        passive_skills=(),
        skill_modifiers=(ModifierInstance("familiar_training", 1),),
        inventory=Inventory(),
    )


def test_hero_class_loader_keeps_base_selection_separate():
    heroes = load_hero_classes()

    assert "flamecaller" in heroes
    assert "flamecaller" not in load_classes()
    assert load_character_class("flamecaller").name == "Flamecaller"
    assert "flamecaller" in load_progression().level_scaling


def test_hero_upgrade_preview_uses_shared_requirements():
    preview = HeroUpgradeService().preview(
        _eligible_summoner_record(),
        "flamecaller",
    )

    assert preview.eligible is True
    assert {check.code for check in preview.checks} >= {
        "min_level",
        "class_ids",
        "min_stat:mastery",
    }


def test_hero_upgrade_apply_preserves_state_and_applies_deltas():
    upgraded = HeroUpgradeService().apply(
        _eligible_summoner_record(),
        "flamecaller",
    )

    assert upgraded.player_class == "flamecaller"
    assert upgraded.entity_name == "Flamecaller"
    assert upgraded.level == 6
    assert upgraded.xp == 750
    assert "summon_familiar" not in upgraded.skills
    assert "summon_blaze" in upgraded.skills
    assert "blaze_of_glory" in upgraded.passive_skills
    assert upgraded.flags["upgraded_to_flamecaller"].flag_persistence is True
    assert upgraded.major_stats.attack == 47
    assert upgraded.major_stats.mastery == 58


def test_hero_upgrade_rejects_unmet_requirements():
    record = _eligible_summoner_record()
    record = CharacterRecord(
        character_id=record.character_id,
        tg_id=record.tg_id,
        character_name=record.character_name,
        class_id=record.class_id,
        level=2,
        xp=0,
        skills=record.skills,
        passive_skills=record.passive_skills,
        skill_modifiers=record.skill_modifiers,
        inventory=record.inventory,
    )

    with pytest.raises(ValueError, match="requirements"):
        HeroUpgradeService().apply(record, "flamecaller")


def test_item_cost_selection_uses_unequipped_lowest_quality_then_id():
    item_equipped = generate_item_from_blueprint_id(
        "long_sword",
        quality=1,
        instance_id="a-equipped",
    )
    item_low = generate_item_from_blueprint_id(
        "long_sword",
        quality=2,
        instance_id="b-low",
    )
    item_high = generate_item_from_blueprint_id(
        "long_sword",
        quality=3,
        instance_id="c-high",
    )
    inventory = (
        Inventory()
        .add_item(item_high)
        .add_item(item_equipped)
        .add_item(item_low)
        .equip("a-equipped")
    )

    selected = select_unequipped_items_by_blueprint(
        inventory,
        (HeroItemRequirement("long_sword", 1),),
    )

    assert selected == {"long_sword": ("b-low",)}
