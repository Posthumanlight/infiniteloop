from dataclasses import dataclass

from game.character.base_entity import BaseEntity
from game.character.inventory import Inventory
from game.character.player_character import PlayerCharacter
from game.core.data_loader import load_item_sets
from game.core.enums import ItemEffect
from game.core.formula_eval import evaluate_expr
from game.items.items import GeneratedItemEffect, ItemSetBonusData


@dataclass(frozen=True)
class EquippedItemEffects:
    stat_modifiers: dict[str, float]
    granted_skills: tuple[str, ...]
    blocked_skills: tuple[str, ...]
    granted_passives: tuple[str, ...]
    blocked_passives: tuple[str, ...]


@dataclass
class _EffectAccumulator:
    stats: dict[str, float]
    grant_skills: list[str]
    block_skills: list[str]
    grant_passives: list[str]
    block_passives: list[str]


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return tuple(ordered)


def _apply_generated_effect(
    acc: _EffectAccumulator,
    effect: GeneratedItemEffect,
) -> None:
    match effect.effect_type:
        case ItemEffect.MODIFY_STAT:
            if effect.stat is None:
                return
            acc.stats[effect.stat] = acc.stats.get(effect.stat, 0.0) + float(
                effect.value or 0.0,
            )
        case ItemEffect.GRANT_SKILL:
            if effect.skill_id is not None:
                acc.grant_skills.append(effect.skill_id)
        case ItemEffect.BLOCK_SKILL:
            if effect.skill_id is not None:
                acc.block_skills.append(effect.skill_id)
        case ItemEffect.GRANT_PASSIVE:
            if effect.passive_id is not None:
                acc.grant_passives.append(effect.passive_id)
        case ItemEffect.BLOCK_PASSIVE:
            if effect.passive_id is not None:
                acc.block_passives.append(effect.passive_id)


def collect_equipped_item_set_counts(inventory: Inventory) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in inventory.equipped_items():
        for set_id in item.item_sets:
            counts[set_id] = counts.get(set_id, 0) + 1
    return counts


def resolve_item_set_bonus_effects(
    bonus: ItemSetBonusData,
    *,
    equipped_count: int,
) -> tuple[GeneratedItemEffect, ...]:
    resolved: list[GeneratedItemEffect] = []
    ctx = {
        "count": equipped_count,
        "required_count": bonus.required_count,
    }
    for effect in bonus.effects:
        value = None
        if effect.effect_type == ItemEffect.MODIFY_STAT:
            value = evaluate_expr(effect.expr or "0", ctx)

        resolved.append(GeneratedItemEffect(
            effect_type=effect.effect_type,
            stat=effect.stat,
            value=value,
            skill_id=effect.skill_id,
            passive_id=effect.passive_id,
        ))

    return tuple(resolved)


def collect_equipped_item_effects(inventory: Inventory) -> EquippedItemEffects:
    acc = _EffectAccumulator(
        stats={},
        grant_skills=[],
        block_skills=[],
        grant_passives=[],
        block_passives=[],
    )

    for item in inventory.equipped_items():
        for effect in item.effects:
            _apply_generated_effect(acc, effect)

    item_sets = load_item_sets()
    for set_id, equipped_count in collect_equipped_item_set_counts(inventory).items():
        item_set = item_sets.get(set_id)
        if item_set is None:
            continue
        for bonus in item_set.bonuses:
            if equipped_count < bonus.required_count:
                continue
            for effect in resolve_item_set_bonus_effects(
                bonus,
                equipped_count=equipped_count,
            ):
                _apply_generated_effect(acc, effect)

    return EquippedItemEffects(
        stat_modifiers=acc.stats,
        granted_skills=_ordered_unique(acc.grant_skills),
        blocked_skills=_ordered_unique(acc.block_skills),
        granted_passives=_ordered_unique(acc.grant_passives),
        blocked_passives=_ordered_unique(acc.block_passives),
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
