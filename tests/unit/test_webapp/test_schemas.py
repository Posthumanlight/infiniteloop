from game.core.enums import TargetType
from game.core.game_models import (
    CharacterSheet,
    EffectInfo,
    ModifierInfo,
    PassiveInfo,
    SkillHitInfo,
    SkillInfo,
)
from webapp.schemas import CharacterSheetOut


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
            ),
        ),
        in_combat=True,
    )

    payload = CharacterSheetOut.from_domain(sheet)

    assert payload.skills[0].hits[0].target_type == "single_enemy"
    assert payload.passives[0].triggers == ["on_take_damage", "on_hit"]
    assert payload.modifiers[0].stack_count == 2
    assert payload.active_effects[0].is_buff is True
