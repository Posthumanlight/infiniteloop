from db.queries.users_namespace import UserCharactersData
from game.combat.skill_modifiers import ModifierInstance
from game.core.enums import ItemEffect, ItemType
from game.items.items import GeneratedItemEffect, ItemInstance


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


def test_item_instance_serialization_preserves_sets_and_unique():
    item = ItemInstance(
        instance_id="i1",
        blueprint_id="crocodile_tears",
        name="Crocodile Tears",
        item_type=ItemType.RELIC,
        quality=2,
        effects=(),
        item_sets=("crocodile_regalia", "predator_trinkets"),
        unique=True,
    )

    payload = UserCharactersData._serialize_item_instance(item)
    parsed = UserCharactersData._deserialize_item_instance({
        "instance_id": payload["instance_id"],
        "blueprint_id": payload["blueprint_id"],
        "item_type": payload["item_type"],
        "quality": payload["quality"],
        "generated_effects": payload["generated_effects"],
        "additional_data": payload["additional_data"],
    })

    assert parsed == item


def test_old_item_instance_data_does_not_backfill_sets_or_unique():
    parsed = UserCharactersData._deserialize_item_instance({
        "instance_id": "i1",
        "blueprint_id": "crocodile_tears",
        "item_type": "relic",
        "quality": 1,
        "generated_effects": "[]",
        "additional_data": '{"name": "Old Crocodile Tears"}',
    })

    assert parsed.item_sets == ()
    assert parsed.unique is False
