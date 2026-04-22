from game.core.enums import TargetType
from game.core.game_models import (
    CharacterSheet,
    EffectInfo,
    EquipmentSlotInfo,
    InventorySnapshot,
    ItemEffectInfo,
    ItemInfo,
    ItemSetBonusInfo,
    ItemSetInfo,
    ModifierInfo,
    PassiveInfo,
    SkillHitInfo,
    SkillInfo,
)
from game.character.hero_upgrades import HeroRequirementCheck, HeroUpgradePreview
from game.character.flags import CharacterFlag
from game.core.data_loader import HeroUpgradeDelta, HeroItemRequirement, HeroModifierStack
from webapp.schemas import CharacterSheetOut, HeroUpgradePreviewOut, InventoryOut


def test_character_sheet_out_serializes_nested_domain_objects():
    sheet = CharacterSheet(
        entity_id="42",
        display_name="PlayerOne",
        class_id="warrior",
        class_name="Warrior",
        level=3,
        xp=250,
        current_hp=70,
        max_hp=100,
        current_energy=35,
        max_energy=60,
        major_stats={"attack": 12.0, "crit_chance": 0.15},
        minor_stats={"slashing_dmg_pct": 0.1},
        skills=(
            SkillInfo(
                skill_id="slash",
                name="Slash",
                energy_cost=0,
                hits=(SkillHitInfo(target_type=TargetType.SINGLE_ENEMY, damage_type="slashing"),),
                temporary=True,
            ),
        ),
        passives=(
            PassiveInfo(
                skill_id="last_stand",
                name="Last Stand",
                triggers=("on_take_damage", "on_hit"),
                action="apply_effect",
            ),
        ),
        modifiers=(
            ModifierInfo(
                modifier_id="slash_power",
                name="Sharpened Edge",
                stack_count=2,
            ),
        ),
        active_effects=(
            EffectInfo(
                effect_id="fortify",
                name="Fortify",
                remaining_duration=2,
                stack_count=1,
                is_buff=True,
                granted_skills=("rampage",),
                blocked_skills=("slash",),
            ),
        ),
        in_combat=True,
    )

    payload = CharacterSheetOut.from_domain(sheet)

    assert payload.skills[0].hits[0].target_type == "single_enemy"
    assert payload.skills[0].temporary is True
    assert payload.passives[0].triggers == ["on_take_damage", "on_hit"]
    assert payload.modifiers[0].stack_count == 2
    assert payload.active_effects[0].is_buff is True
    assert payload.active_effects[0].granted_skills == ["rampage"]
    assert payload.active_effects[0].blocked_skills == ["slash"]


def test_inventory_out_serializes_item_sets():
    item = ItemInfo(
        instance_id="i1",
        blueprint_id="crocodile_tears",
        name="Crocodile Tears",
        item_type="relic",
        rarity="rare",
        quality=1,
        equipped_slot="relic",
        equipped_index=0,
        effects=(
            ItemEffectInfo(
                effect_type="modify_stat",
                stat="crit_chance",
                value=0.045,
            ),
        ),
        item_sets=("crocodile_regalia",),
        item_set_names=("Crocodile Regalia",),
        unique=True,
    )
    snapshot = InventorySnapshot(
        items=(item,),
        unequipped_items=(),
        equipment_slots=(
            EquipmentSlotInfo(
                slot_type="relic",
                slot_index=0,
                label="Relic 1",
                accepts_item_type="relic",
                item=item,
            ),
        ),
        can_manage_equipment=True,
        item_sets=(
            ItemSetInfo(
                set_id="crocodile_regalia",
                name="Crocodile Regalia",
                equipped_count=1,
                bonuses=(
                    ItemSetBonusInfo(
                        required_count=2,
                        active=False,
                        effects=(
                            ItemEffectInfo(
                                effect_type="modify_stat",
                                stat="crit_chance",
                                value=0.1,
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )

    payload = InventoryOut.from_domain(snapshot)

    assert payload.items[0].item_sets == ["crocodile_regalia"]
    assert payload.items[0].item_set_names == ["Crocodile Regalia"]
    assert payload.items[0].rarity == "rare"
    assert payload.items[0].unique is True
    assert payload.item_sets[0].bonuses[0].active is False
    assert payload.item_sets[0].bonuses[0].effects[0].value == 0.1
    assert payload.dissolve_currency_name == "Fortuna Motes"
    assert payload.dissolve_rarity_values == {}


def test_hero_upgrade_preview_out_serializes_nested_deltas():
    preview = HeroUpgradePreview(
        hero_class_id="flamecaller",
        name="Flamecaller",
        description="Fire path",
        eligible=True,
        checks=(HeroRequirementCheck("min_level", "Reach level 7", True),),
        gains=HeroUpgradeDelta(
            levels=1,
            skills=("summon_blaze",),
            passive_skills=("blaze_of_glory",),
            items=(HeroItemRequirement("long_sword", 1),),
            flags=(CharacterFlag("upgraded_to_flamecaller", True, True),),
            modifiers=(HeroModifierStack("familiar_training", 2),),
        ),
        losses=HeroUpgradeDelta(flags=("old_flag",)),
    )

    payload = HeroUpgradePreviewOut.from_domain(preview)

    assert payload.hero_class_id == "flamecaller"
    assert payload.checks[0].met is True
    assert payload.gains.items[0].blueprint_id == "long_sword"
    assert payload.gains.flags[0].flag_value is True
    assert payload.losses.flags[0].flag_name == "old_flag"
