from dataclasses import replace

import pytest

from game.combat.skill_modifiers import ModifierInstance
from game.core import data_loader
from game.core.data_loader import clear_cache, load_skills
from game.session.factories import build_player
from game_service import GameService


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


@pytest.mark.parametrize(
    ("summary", "message"),
    [
        ("Hits a [bad_key].", "unknown summary placeholder"),
        ("Hits a [hits.1.formula].", "references missing hit index 1"),
    ],
)
def test_load_skills_rejects_invalid_summary_placeholders(monkeypatch, summary: str, message: str):
    original = data_loader._load_toml

    def fake_load_toml(filename: str):
        if filename == "skills.toml":
            return {
                "skills": {
                    "test_skill": {
                        "name": "Test Skill",
                        "energy_cost": 0,
                        "action_type": "action",
                        "summary": summary,
                        "hits": [
                            {
                                "target_type": "single_enemy",
                                "damage_type": "slashing",
                                "formula": "base_power + attacker.attack",
                                "base_power": 1,
                                "variance": 0.0,
                            },
                        ],
                    },
                },
            }
        return original(filename)

    monkeypatch.setattr(data_loader, "_load_toml", fake_load_toml)

    with pytest.raises(ValueError, match=message):
        load_skills()


def test_build_skill_info_slash_has_summary_parts_and_formula_preview():
    player = build_player("warrior", entity_id="p1")

    info = GameService._build_skill_info(player, "slash")

    assert [part.kind for part in info.summary_parts].count("damage_non_crit") == 1
    assert [part.kind for part in info.summary_parts].count("damage_crit") == 1
    assert "".join(part.value for part in info.summary_parts) == (
        "Hits a single enemy for 20 / 26 slashing damage."
    )
    assert info.hit_details[0].formula == "base_power + attacker.attack * 1.5"
    assert info.hit_details[0].preview_damage_non_crit == 20
    assert info.hit_details[0].preview_damage_crit == 26


def test_build_skill_info_respects_damage_type_override_modifier():
    player = replace(
        build_player("warrior", entity_id="p1"),
        skill_modifiers=(ModifierInstance(modifier_id="fire_brand"),),
    )

    info = GameService._build_skill_info(player, "slash")

    assert "".join(part.value for part in info.summary_parts) == (
        "Hits a single enemy for 19 / 23 fire damage."
    )
    assert info.hit_details[0].damage_type == "fire"
    assert info.hit_details[0].preview_damage_non_crit == 19
    assert info.hit_details[0].preview_damage_crit == 23


def test_build_skill_info_includes_effect_details():
    player = build_player("warrior", entity_id="p1")

    deep_wounds = GameService._build_skill_info(player, "deep_wounds")
    berserker = GameService._build_skill_info(player, "berserker")

    assert deep_wounds.hit_details[0].on_hit_effects[0].name == "Bleed"
    assert deep_wounds.hit_details[0].on_hit_effects[0].chance == 1.0
    assert "slashing damage each turn" in deep_wounds.hit_details[0].on_hit_effects[0].summary
    assert berserker.self_effects[0].name == "Berserker"
    assert "grants Rampage" in berserker.self_effects[0].summary
