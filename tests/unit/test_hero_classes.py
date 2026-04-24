import pytest

from game.character.hero_upgrades import (
    HeroUpgradeService,
    HeroUpgradeVisibilityPolicy,
    select_unequipped_items_by_blueprint,
)
from game.character.inventory import Inventory
from game.combat.skill_modifiers import ModifierInstance
from game.core.data_loader import (
    CharacterClassCatalog,
    ClassData,
    HeroClassData,
    HeroItemRequirement,
    HeroUpgradeRequirements,
    LevelScalingConfig,
    ProgressionConfig,
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


def _record(
    *,
    class_id: str,
    level: int = 10,
    skills: tuple[str, ...] = (),
) -> CharacterRecord:
    return CharacterRecord(
        character_id=43,
        tg_id=1002,
        character_name="Test",
        class_id=class_id,
        level=level,
        xp=0,
        skills=skills,
        passive_skills=(),
        skill_modifiers=(),
        inventory=Inventory(),
    )


def _class_data(class_id: str) -> ClassData:
    return ClassData(
        class_id=class_id,
        name=class_id.title(),
        description="Test class",
        major_stats={
            "attack": 10,
            "hp": 100,
            "speed": 10,
            "crit_chance": 0.1,
            "crit_dmg": 1.25,
            "resistance": 10,
            "energy": 100,
            "mastery": 5,
        },
        minor_stats={},
        starting_skills=(),
    )


def _hero(
    class_id: str,
    *,
    required_classes: tuple[str, ...],
    required_skills: tuple[str, ...] = (),
) -> HeroClassData:
    return HeroClassData(
        class_id=class_id,
        name=class_id.title(),
        description="Test hero class",
        major_stats={
            "attack": 20,
            "hp": 120,
            "speed": 12,
            "crit_chance": 0.1,
            "crit_dmg": 1.25,
            "resistance": 12,
            "energy": 100,
            "mastery": 8,
        },
        minor_stats={},
        level_scaling={},
        requirements=HeroUpgradeRequirements(
            class_ids=required_classes,
            skills=required_skills,
        ),
    )


def _visibility_service() -> HeroUpgradeService:
    catalog = CharacterClassCatalog(
        base_classes={
            "warrior": _class_data("warrior"),
            "mage": _class_data("mage"),
        },
        hero_classes={
            "archmage": _hero("archmage", required_classes=("mage",)),
            "gladiator": _hero(
                "gladiator",
                required_classes=("warrior",),
                required_skills=("deep_wounds",),
            ),
            "wanderer": _hero("wanderer", required_classes=()),
        },
    )
    progression = ProgressionConfig(
        xp_thresholds=(0, 100, 250, 500),
        level_scaling={
            "warrior": LevelScalingConfig("warrior", {}),
            "mage": LevelScalingConfig("mage", {}),
            "archmage": LevelScalingConfig("archmage", {}),
            "gladiator": LevelScalingConfig("gladiator", {}),
            "wanderer": LevelScalingConfig("wanderer", {}),
        },
    )
    return HeroUpgradeService(class_catalog=catalog, progression=progression)


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


def test_hero_upgrade_visibility_policy_uses_required_classes_only():
    policy = HeroUpgradeVisibilityPolicy()
    service = _visibility_service()
    warrior = service._build_context(_record(class_id="warrior"), "gladiator").player
    mage = service._build_context(_record(class_id="mage"), "gladiator").player
    gladiator = service._class_catalog.hero_classes["gladiator"]
    wanderer = service._class_catalog.hero_classes["wanderer"]

    assert policy.is_visible(warrior, gladiator) is True
    assert policy.is_visible(mage, gladiator) is False
    assert policy.is_visible(mage, wanderer) is True


def test_hero_upgrade_list_hides_only_class_blocked_heroes():
    service = _visibility_service()

    previews = service.list_previews(_record(class_id="warrior"))

    assert tuple(preview.hero_class_id for preview in previews) == (
        "gladiator",
        "wanderer",
    )
    gladiator = next(preview for preview in previews if preview.hero_class_id == "gladiator")
    assert gladiator.eligible is False
    assert any(check.code == "skill:deep_wounds" for check in gladiator.checks)


def test_hero_upgrade_direct_preview_and_apply_still_validate_all_requirements():
    service = _visibility_service()
    mage_record = _record(class_id="mage")
    preview = service.preview(mage_record, "gladiator")

    assert preview.eligible is False
    assert any(
        check.code == "class_ids" and check.met is False
        for check in preview.checks
    )

    with pytest.raises(ValueError, match="requirements"):
        service.apply(mage_record, "gladiator")


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
