from dataclasses import dataclass

from game.core.enums import ItemEffect, ItemType


@dataclass(frozen=True)
class ItemBlueprintEffect:
    effect_type: ItemEffect
    stat: str | None = None
    expr: str | None = None
    skill_id: str | None = None
    passive_id: str | None = None


@dataclass(frozen=True)
class ItemBlueprint:
    blueprint_id: str
    name: str
    item_type: ItemType
    effects: tuple[ItemBlueprintEffect, ...]
    item_sets: tuple[str, ...] = ()
    unique: bool = False
    rarity: str = "common"


@dataclass(frozen=True)
class ItemSetBonusData:
    required_count: int
    effects: tuple[ItemBlueprintEffect, ...]


@dataclass(frozen=True)
class ItemSetData:
    set_id: str
    name: str
    bonuses: tuple[ItemSetBonusData, ...]


@dataclass(frozen=True)
class GeneratedItemEffect:
    effect_type: ItemEffect
    stat: str | None = None
    value: float | None = None
    skill_id: str | None = None
    passive_id: str | None = None


@dataclass(frozen=True)
class ItemInstance:
    instance_id: str
    blueprint_id: str
    name: str
    item_type: ItemType
    quality: int
    effects: tuple[GeneratedItemEffect, ...]
    item_sets: tuple[str, ...] = ()
    unique: bool = False
    rarity: str = "common"
