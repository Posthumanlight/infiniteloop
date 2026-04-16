from dataclasses import dataclass

from game.character.base_entity import BaseEntity
from game.character.inventory import Inventory
from game.character.player_character import PlayerCharacter
from game.core.enums import ItemEffect


@dataclass(frozen=True)
class EquippedItemEffects:
    stat_modifiers: dict[str, float]
    granted_skills: tuple[str, ...]
    blocked_skills: tuple[str, ...]
    granted_passives: tuple[str, ...]
    blocked_passives: tuple[str, ...]


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def collect_equipped_item_effects(inventory: Inventory) -> EquippedItemEffects:
    stats: dict[str, float] = {}
    grant_skills: list[str] = []
    block_skills: list[str] = []
    grant_passives: list[str] = []
    block_passives: list[str] = []

    for item in inventory.equipped_items():
        for effect in item.effects:
            match effect.effect_type:
                case ItemEffect.MODIFY_STAT:
                    if effect.stat is None:
                        continue
                    stats[effect.stat] = stats.get(effect.stat, 0.0) + float(
                        effect.value or 0.0,
                    )
                case ItemEffect.GRANT_SKILL:
                    if effect.skill_id is not None:
                        grant_skills.append(effect.skill_id)
                case ItemEffect.BLOCK_SKILL:
                    if effect.skill_id is not None:
                        block_skills.append(effect.skill_id)
                case ItemEffect.GRANT_PASSIVE:
                    if effect.passive_id is not None:
                        grant_passives.append(effect.passive_id)
                case ItemEffect.BLOCK_PASSIVE:
                    if effect.passive_id is not None:
                        block_passives.append(effect.passive_id)

    return EquippedItemEffects(
        stat_modifiers=stats,
        granted_skills=_ordered_unique(grant_skills),
        blocked_skills=_ordered_unique(block_skills),
        granted_passives=_ordered_unique(grant_passives),
        blocked_passives=_ordered_unique(block_passives),
    )


def get_effective_passive_ids(entity: BaseEntity) -> tuple[str, ...]:
    base = tuple(entity.passive_skills)
    if not isinstance(entity, PlayerCharacter) or entity.inventory is None:
        return base

    item_effects = collect_equipped_item_effects(entity.inventory)
    ordered = [*base, *item_effects.granted_passives]
    blocked = set(item_effects.blocked_passives)
    return tuple(
        passive_id
        for passive_id in _ordered_unique(ordered)
        if passive_id not in blocked
    )


def get_effective_player_major_stat(
    player: PlayerCharacter,
    stat_name: str,
) -> float:
    base_value = float(getattr(player.major_stats, stat_name))
    if player.inventory is None:
        return base_value
    item_effects = collect_equipped_item_effects(player.inventory)
    return base_value + item_effects.stat_modifiers.get(stat_name, 0.0)


def get_effective_player_minor_stat(
    player: PlayerCharacter,
    stat_key: str,
) -> float:
    base_value = player.minor_stats.values.get(stat_key, 0.0)
    if player.inventory is None:
        return base_value
    item_effects = collect_equipped_item_effects(player.inventory)
    return base_value + item_effects.stat_modifiers.get(stat_key, 0.0)
