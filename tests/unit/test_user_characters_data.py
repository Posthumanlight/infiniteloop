from db.queries.users_namespace import UserCharactersData
from game.combat.skill_modifiers import ModifierInstance
from game.core.enums import ItemEffect
from game.items.items import GeneratedItemEffect


def test_parse_modifiers_accepts_json_string_with_stacks():
    parsed = UserCharactersData._parse_modifiers(
        '[{"modifier_id": "slash_power", "stack_count": 2}, '
        '{"modifier_id": "battle_hardened", "stack_count": 1}]',
    )

    assert [(mod.modifier_id, mod.stack_count) for mod in parsed] == [
        ("slash_power", 2),
        ("battle_hardened", 1),
    ]


def test_parse_modifiers_treats_missing_or_invalid_data_as_empty():
    assert UserCharactersData._parse_modifiers(None) == ()
    assert UserCharactersData._parse_modifiers("not-json") == ()
    assert UserCharactersData._parse_modifiers({"modifier_id": "slash_power"}) == ()


def test_serialize_modifiers_round_trips_with_parse():
    modifiers = (
        ModifierInstance("slash_power", 3),
        ModifierInstance("battle_hardened", 1),
    )

    serialized = UserCharactersData._serialize_modifiers(modifiers)
    parsed = UserCharactersData._parse_modifiers(serialized)

    assert [(mod.modifier_id, mod.stack_count) for mod in parsed] == [
        ("slash_power", 3),
        ("battle_hardened", 1),
    ]


def test_generated_effects_round_trip():
    effects = (
        GeneratedItemEffect(
            effect_type=ItemEffect.MODIFY_STAT,
            stat="attack",
            value=12.0,
        ),
        GeneratedItemEffect(
            effect_type=ItemEffect.GRANT_SKILL,
            skill_id="rampage",
        ),
    )

    serialized = UserCharactersData._serialize_generated_effects(effects)
    parsed = UserCharactersData._parse_generated_effects(serialized)

    assert parsed == effects
