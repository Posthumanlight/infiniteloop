from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from game.character.inventory import Inventory
from game.character.player_character import PlayerCharacter
from game.character.progression import _apply_stat_gains
from game.character.stats import MajorStats, MinorStats
from game.combat.skill_modifiers import (
    ModifierInstance,
    add_modifier,
    remove_modifier,
)
from game.core.data_loader import (
    CharacterClassCatalog,
    HeroClassData,
    HeroItemRequirement,
    HeroModifierStack,
    HeroUpgradeDelta,
    ProgressionConfig,
    load_class_catalog,
    load_progression,
)
from game.items.equipment_effects import (
    get_effective_player_major_stat,
    get_effective_player_minor_stat,
)
from game.items.item_generator import generate_item_from_blueprint_id
from game.session.factories import build_player_from_saved

if TYPE_CHECKING:
    from game.session.lobby_manager import CharacterRecord


_MAJOR_STAT_NAMES = frozenset({
    "attack",
    "hp",
    "speed",
    "crit_chance",
    "crit_dmg",
    "resistance",
    "energy",
    "mastery",
})


@dataclass(frozen=True)
class HeroRequirementCheck:
    code: str
    label: str
    met: bool


@dataclass(frozen=True)
class HeroUpgradePreview:
    hero_class_id: str
    name: str
    description: str
    eligible: bool
    checks: tuple[HeroRequirementCheck, ...]
    gains: HeroUpgradeDelta
    losses: HeroUpgradeDelta


@dataclass(frozen=True)
class HeroUpgradeContext:
    record: CharacterRecord
    player: PlayerCharacter
    hero: HeroClassData
    progression: ProgressionConfig
    class_catalog: CharacterClassCatalog


def min_xp_for_level(level: int, thresholds: tuple[int, ...]) -> int:
    if level <= 1:
        return 0
    threshold_index = min(level - 2, len(thresholds) - 1)
    if threshold_index < 0:
        return 0
    return int(thresholds[threshold_index])


def build_major_stats_map(
    catalog: CharacterClassCatalog,
) -> dict[str, MajorStats]:
    classes = {
        **catalog.base_classes,
        **{
            class_id: hero.to_class_data()
            for class_id, hero in catalog.hero_classes.items()
        },
    }
    return {
        class_id: _major_stats_from_mapping(cls.major_stats)
        for class_id, cls in classes.items()
    }


def rebuild_major_stats_for_class(
    class_id: str,
    level: int,
    catalog: CharacterClassCatalog,
    progression: ProgressionConfig,
) -> MajorStats:
    class_data = catalog.get_character_class(class_id)
    scaling = progression.level_scaling.get(class_id)
    stat_gains = scaling.stat_gains if scaling else {}
    return _apply_stat_gains(
        _major_stats_from_mapping(class_data.major_stats),
        stat_gains,
        max(0, level - 1),
    )


def select_unequipped_items_by_blueprint(
    inventory: Inventory,
    costs: tuple[HeroItemRequirement, ...],
) -> dict[str, tuple[str, ...]]:
    equipped_ids = set(inventory.equipped_instance_ids)
    selected: dict[str, tuple[str, ...]] = {}

    for blueprint_id, count in _item_requirement_counts(costs).items():
        candidates = sorted(
            (
                item
                for item in inventory.items.values()
                if item.blueprint_id == blueprint_id
                and item.instance_id not in equipped_ids
            ),
            key=lambda item: (item.quality, item.instance_id),
        )
        selected[blueprint_id] = tuple(
            item.instance_id
            for item in candidates[:count]
        )

    return selected


class HeroUpgradeEvaluator:
    def preview(self, ctx: HeroUpgradeContext) -> HeroUpgradePreview:
        checks = tuple(self._checks(ctx))
        return HeroUpgradePreview(
            hero_class_id=ctx.hero.class_id,
            name=ctx.hero.name,
            description=ctx.hero.description,
            eligible=all(check.met for check in checks),
            checks=checks,
            gains=ctx.hero.gains,
            losses=ctx.hero.losses,
        )

    def _checks(self, ctx: HeroUpgradeContext) -> list[HeroRequirementCheck]:
        req = ctx.hero.requirements
        player = ctx.player
        checks: list[HeroRequirementCheck] = []

        if req.min_level is not None:
            checks.append(HeroRequirementCheck(
                code="min_level",
                label=f"Reach level {req.min_level}",
                met=player.level >= req.min_level,
            ))

        if req.class_ids:
            class_names = ", ".join(req.class_ids)
            checks.append(HeroRequirementCheck(
                code="class_ids",
                label=f"Class is one of: {class_names}",
                met=player.player_class in req.class_ids,
            ))

        for stat_name, required_value in sorted(req.min_stats.items()):
            current_value = _effective_stat(player, stat_name)
            checks.append(HeroRequirementCheck(
                code=f"min_stat:{stat_name}",
                label=(
                    f"{_label(stat_name)} at least "
                    f"{_format_number(required_value)}"
                ),
                met=current_value >= required_value,
            ))

        selected_items = select_unequipped_items_by_blueprint(
            player.inventory,
            req.items,
        )
        for blueprint_id, count in sorted(_item_requirement_counts(req.items).items()):
            checks.append(HeroRequirementCheck(
                code=f"item:{blueprint_id}",
                label=f"Own {count} unequipped {blueprint_id}",
                met=len(selected_items.get(blueprint_id, ())) >= count,
            ))

        for flag in req.flags:
            current = player.flags.get(flag.flag_name)
            if flag.require_value:
                met = current is not None and current.flag_value == flag.flag_value
                label = f"Flag {flag.flag_name} is {flag.flag_value!r}"
            else:
                met = current is not None
                label = f"Flag {flag.flag_name}"
            checks.append(HeroRequirementCheck(
                code=f"flag:{flag.flag_name}",
                label=label,
                met=met,
            ))

        for skill_id in req.skills:
            checks.append(HeroRequirementCheck(
                code=f"skill:{skill_id}",
                label=f"Know skill {skill_id}",
                met=skill_id in player.skills,
            ))

        for passive_id in req.passive_skills:
            checks.append(HeroRequirementCheck(
                code=f"passive:{passive_id}",
                label=f"Know passive {passive_id}",
                met=passive_id in player.passive_skills,
            ))

        modifier_counts = {
            modifier.modifier_id: modifier.stack_count
            for modifier in player.skill_modifiers
        }
        for modifier in req.modifiers:
            checks.append(HeroRequirementCheck(
                code=f"modifier:{modifier.modifier_id}",
                label=(
                    f"Have {modifier.stacks} stack"
                    f"{'' if modifier.stacks == 1 else 's'} of "
                    f"{modifier.modifier_id}"
                ),
                met=modifier_counts.get(modifier.modifier_id, 0) >= modifier.stacks,
            ))

        return checks


class HeroUpgradeApplier:
    def apply(self, ctx: HeroUpgradeContext) -> PlayerCharacter:
        preview = HeroUpgradeEvaluator().preview(ctx)
        if not preview.eligible:
            raise ValueError("Hero class requirements are not met")

        player = self._apply_losses(ctx.player, ctx.hero.losses, ctx.progression)
        player = self._switch_class(player, ctx)
        return self._apply_gains(
            player,
            ctx.hero.gains,
            ctx.progression,
            ctx.class_catalog,
        )

    def _apply_losses(
        self,
        player: PlayerCharacter,
        losses: HeroUpgradeDelta,
        progression: ProgressionConfig,
    ) -> PlayerCharacter:
        level = max(1, player.level - losses.levels)
        xp = (
            min_xp_for_level(level, progression.xp_thresholds)
            if losses.levels else player.xp
        )
        updated = replace(
            player,
            level=level,
            xp=xp,
            skills=_remove_values(player.skills, losses.skills),
            passive_skills=_remove_values(
                player.passive_skills,
                losses.passive_skills,
            ),
        )

        for flag_name in losses.flags:
            updated = updated.remove_flag(str(flag_name))

        for modifier in losses.modifiers:
            updated = _remove_modifier_stacks(updated, modifier)

        inventory = updated.inventory
        selected_items = select_unequipped_items_by_blueprint(inventory, losses.items)
        for instance_ids in selected_items.values():
            for instance_id in instance_ids:
                inventory = inventory.remove_item(instance_id)
        return replace(updated, inventory=inventory)

    def _switch_class(
        self,
        player: PlayerCharacter,
        ctx: HeroUpgradeContext,
    ) -> PlayerCharacter:
        major = rebuild_major_stats_for_class(
            ctx.hero.class_id,
            player.level,
            ctx.class_catalog,
            ctx.progression,
        )
        class_data = ctx.class_catalog.get_character_class(ctx.hero.class_id)
        return replace(
            player,
            entity_name=class_data.name,
            player_class=ctx.hero.class_id,
            major_stats=major,
            minor_stats=MinorStats(values=dict(class_data.minor_stats)),
            current_hp=major.hp,
            current_energy=major.energy,
        )

    def _apply_gains(
        self,
        player: PlayerCharacter,
        gains: HeroUpgradeDelta,
        progression: ProgressionConfig,
        catalog: CharacterClassCatalog,
    ) -> PlayerCharacter:
        level = player.level + gains.levels
        xp = (
            min_xp_for_level(level, progression.xp_thresholds)
            if gains.levels else player.xp
        )
        major = (
            rebuild_major_stats_for_class(
                player.player_class,
                level,
                catalog,
                progression,
            )
            if gains.levels else player.major_stats
        )
        updated = replace(
            player,
            level=level,
            xp=xp,
            major_stats=major,
            current_hp=major.hp,
            current_energy=major.energy,
            skills=_append_unique(player.skills, gains.skills),
            passive_skills=_append_unique(
                player.passive_skills,
                gains.passive_skills,
            ),
        )

        inventory = updated.inventory
        for item in gains.items:
            for _ in range(item.count):
                inventory = inventory.add_item(
                    generate_item_from_blueprint_id(item.blueprint_id),
                )
        updated = replace(updated, inventory=inventory)

        for flag in gains.flags:
            updated = updated.apply_flag(
                flag.flag_name,
                flag.flag_value,
                flag_persistence=flag.flag_persistence,
            )

        for modifier in gains.modifiers:
            updated = _add_modifier_stacks(updated, modifier)

        return updated


class HeroUpgradeService:
    def __init__(
        self,
        *,
        class_catalog: CharacterClassCatalog | None = None,
        progression: ProgressionConfig | None = None,
        evaluator: HeroUpgradeEvaluator | None = None,
        applier: HeroUpgradeApplier | None = None,
    ) -> None:
        self._class_catalog = class_catalog or load_class_catalog()
        self._progression = progression or load_progression()
        self._base_stats = build_major_stats_map(self._class_catalog)
        self._evaluator = evaluator or HeroUpgradeEvaluator()
        self._applier = applier or HeroUpgradeApplier()

    def list_previews(
        self,
        record: CharacterRecord,
    ) -> tuple[HeroUpgradePreview, ...]:
        return tuple(
            self.preview(record, hero_class_id)
            for hero_class_id in sorted(self._class_catalog.hero_classes)
        )

    def preview(
        self,
        record: CharacterRecord,
        hero_class_id: str,
    ) -> HeroUpgradePreview:
        return self._evaluator.preview(self._build_context(record, hero_class_id))

    def apply(
        self,
        record: CharacterRecord,
        hero_class_id: str,
    ) -> PlayerCharacter:
        return self._applier.apply(self._build_context(record, hero_class_id))

    def _build_context(
        self,
        record: CharacterRecord,
        hero_class_id: str,
    ) -> HeroUpgradeContext:
        try:
            hero = self._class_catalog.hero_classes[hero_class_id]
        except KeyError as exc:
            raise ValueError(f"Unknown hero class: {hero_class_id}") from exc
        player = build_player_from_saved(
            record,
            self._progression,
            self._base_stats,
        )
        return HeroUpgradeContext(
            record=record,
            player=player,
            hero=hero,
            progression=self._progression,
            class_catalog=self._class_catalog,
        )


def _major_stats_from_mapping(values: dict[str, float]) -> MajorStats:
    return MajorStats(
        attack=int(values["attack"]),
        hp=int(values["hp"]),
        speed=int(values["speed"]),
        crit_chance=float(values["crit_chance"]),
        crit_dmg=float(values["crit_dmg"]),
        resistance=int(values.get("resistance", 0)),
        energy=int(values.get("energy", 50)),
        mastery=int(values.get("mastery", 0)),
    )


def _item_requirement_counts(
    items: tuple[HeroItemRequirement, ...],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item.blueprint_id] = counts.get(item.blueprint_id, 0) + item.count
    return counts


def _effective_stat(player: PlayerCharacter, stat_name: str) -> float:
    if stat_name in _MAJOR_STAT_NAMES:
        return get_effective_player_major_stat(player, stat_name)
    return get_effective_player_minor_stat(player, stat_name)


def _remove_values(
    values: tuple[str, ...],
    removals: tuple[str, ...],
) -> tuple[str, ...]:
    removal_set = set(removals)
    return tuple(value for value in values if value not in removal_set)


def _append_unique(
    values: tuple[str, ...],
    additions: tuple[str, ...],
) -> tuple[str, ...]:
    result = list(values)
    seen = set(result)
    for value in additions:
        if value in seen:
            continue
        result.append(value)
        seen.add(value)
    return tuple(result)


def _add_modifier_stacks(
    player: PlayerCharacter,
    modifier: HeroModifierStack,
) -> PlayerCharacter:
    updated = player
    for _ in range(modifier.stacks):
        updated = add_modifier(updated, modifier.modifier_id)
    return updated


def _remove_modifier_stacks(
    player: PlayerCharacter,
    modifier: HeroModifierStack,
) -> PlayerCharacter:
    updated = player
    for _ in range(modifier.stacks):
        updated = remove_modifier(updated, modifier.modifier_id)
    return updated


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _format_number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:.2f}"
