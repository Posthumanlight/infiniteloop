import asyncio

from db.queries.users_namespace import UserCharactersData, UserCurrenciesDB
from game.combat.skill_modifiers import ModifierInstance
from game.core.enums import ItemEffect, ItemType
from game.items.items import GeneratedItemEffect, ItemInstance


class _FakeAcquire:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return _FakeAcquire(self._conn)


class _FakeCurrencyConn:
    def __init__(self, row):
        self.row = row
        self.calls = []

    async def fetchrow(self, sql, *args):
        self.calls.append((sql, args))
        return self.row


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
        rarity="rare",
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
    assert parsed.rarity == "common"


def test_user_currency_add_uses_composite_currency_key():
    conn = _FakeCurrencyConn({
        "currency_name": "Fortuna Motes",
        "current_value": 8,
    })

    balance = asyncio.run(
        UserCurrenciesDB(_FakePool(conn)).add_currency(
            123,
            "Fortuna Motes",
            8,
        ),
    )

    sql, args = conn.calls[0]
    assert "ON CONFLICT (tg_id, currency_name)" in sql
    assert args == (123, "Fortuna Motes", 8)
    assert balance.currency_name == "Fortuna Motes"
    assert balance.current_value == 8


def test_user_currency_get_missing_returns_zero():
    conn = _FakeCurrencyConn(None)

    balance = asyncio.run(
        UserCurrenciesDB(_FakePool(conn)).get_currency(
            123,
            "Fortuna Motes",
        ),
    )

    assert balance.currency_name == "Fortuna Motes"
    assert balance.current_value == 0
