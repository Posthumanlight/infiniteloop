from typing import Any

from game.items.items import ItemInstance


def dissolve_currency_name(config: dict[str, Any]) -> str:
    return str(config.get("currency_name", "Fortuna Motes"))


def dissolve_rarity_values(config: dict[str, Any]) -> dict[str, int]:
    raw_values = config.get("rarity_values", {})
    if not isinstance(raw_values, dict):
        return {"common": 1}

    values: dict[str, int] = {}
    for rarity, value in raw_values.items():
        try:
            values[str(rarity)] = int(value)
        except (TypeError, ValueError):
            continue

    if "common" not in values:
        values["common"] = 1
    return values


def dissolve_value_for_item(
    item: ItemInstance,
    config: dict[str, Any],
) -> int:
    values = dissolve_rarity_values(config)
    return values.get(item.rarity, values["common"])


def dissolve_value_for_items(
    items: tuple[ItemInstance, ...],
    config: dict[str, Any],
) -> int:
    return sum(dissolve_value_for_item(item, config) for item in items)
