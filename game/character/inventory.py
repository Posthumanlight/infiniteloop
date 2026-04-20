from dataclasses import dataclass, field, replace

from game.core.enums import ItemType
from game.items.items import ItemInstance


@dataclass(frozen=True)
class EquipmentLoadout:
    weapon_id: str | None = None
    armor_id: str | None = None
    relic_ids: tuple[str | None, ...] = (None, None, None, None, None)


@dataclass(frozen=True)
class Inventory:
    items: dict[str, ItemInstance] = field(default_factory=dict)
    equipment: EquipmentLoadout = field(default_factory=EquipmentLoadout)

    @property
    def content(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.items.values():
            counts[item.blueprint_id] = counts.get(item.blueprint_id, 0) + 1
        return counts

    def add_item(self, item: ItemInstance) -> "Inventory":
        if item.instance_id in self.items:
            raise ValueError(f"Item instance already exists: {item.instance_id}")
        return replace(self, items={**self.items, item.instance_id: item})

    def remove_item(self, instance_id: str) -> "Inventory":
        if instance_id in self.equipped_instance_ids:
            raise ValueError("Cannot remove an equipped item")
        if instance_id not in self.items:
            raise KeyError(instance_id)
        new_items = dict(self.items)
        del new_items[instance_id]
        return replace(self, items=new_items)

    def get_item(self, instance_id: str) -> ItemInstance:
        item = self.items.get(instance_id)
        if item is None:
            raise KeyError(instance_id)
        return item

    @property
    def equipped_instance_ids(self) -> tuple[str, ...]:
        ids: list[str] = []
        if self.equipment.weapon_id is not None:
            ids.append(self.equipment.weapon_id)
        if self.equipment.armor_id is not None:
            ids.append(self.equipment.armor_id)
        ids.extend(item_id for item_id in self.equipment.relic_ids if item_id is not None)
        return tuple(ids)

    def equipped_slot(self, instance_id: str) -> tuple[str | None, int | None]:
        if self.equipment.weapon_id == instance_id:
            return ("weapon", None)
        if self.equipment.armor_id == instance_id:
            return ("armor", None)
        for index, relic_id in enumerate(self.equipment.relic_ids):
            if relic_id == instance_id:
                return ("relic", index)
        return (None, None)

    def equipped_items(self) -> tuple[ItemInstance, ...]:
        items: list[ItemInstance] = []
        if self.equipment.weapon_id is not None:
            items.append(self.get_item(self.equipment.weapon_id))
        if self.equipment.armor_id is not None:
            items.append(self.get_item(self.equipment.armor_id))
        for relic_id in self.equipment.relic_ids:
            if relic_id is not None:
                items.append(self.get_item(relic_id))
        return tuple(items)

    def equip(self, instance_id: str, relic_slot: int | None = None) -> "Inventory":
        item = self.get_item(instance_id)
        if item.unique:
            for equipped in self.equipped_items():
                if equipped.instance_id == instance_id:
                    continue
                if equipped.blueprint_id == item.blueprint_id:
                    raise ValueError(
                        "Only one copy of this unique item can be equipped",
                    )
        equipment = self._without_instance_equipped(instance_id)

        if item.item_type == ItemType.WEAPON:
            return replace(self, equipment=replace(equipment, weapon_id=instance_id))
        if item.item_type == ItemType.ARMOR:
            return replace(self, equipment=replace(equipment, armor_id=instance_id))
        if item.item_type == ItemType.RELIC:
            slots = list(equipment.relic_ids)
            idx = relic_slot if relic_slot is not None else next(
                (i for i, value in enumerate(slots) if value is None),
                None,
            )
            if idx is None or not 0 <= idx < len(slots):
                raise ValueError("No valid relic slot available")
            slots[idx] = instance_id
            return replace(
                self,
                equipment=replace(equipment, relic_ids=tuple(slots)),
            )
        raise ValueError(f"Unsupported item type: {item.item_type.value}")

    def unequip(self, instance_id: str) -> "Inventory":
        slot, index = self.equipped_slot(instance_id)
        if slot is None:
            raise ValueError("Item is not equipped")
        if slot == "weapon":
            return replace(self, equipment=replace(self.equipment, weapon_id=None))
        if slot == "armor":
            return replace(self, equipment=replace(self.equipment, armor_id=None))
        slots = list(self.equipment.relic_ids)
        if index is None:
            raise ValueError("Invalid relic slot")
        slots[index] = None
        return replace(
            self,
            equipment=replace(self.equipment, relic_ids=tuple(slots)),
        )

    def _without_instance_equipped(self, instance_id: str) -> EquipmentLoadout:
        equipment = self.equipment
        if equipment.weapon_id == instance_id:
            equipment = replace(equipment, weapon_id=None)
        if equipment.armor_id == instance_id:
            equipment = replace(equipment, armor_id=None)
        relic_ids = tuple(
            None if relic_id == instance_id else relic_id
            for relic_id in equipment.relic_ids
        )
        return replace(equipment, relic_ids=relic_ids)

