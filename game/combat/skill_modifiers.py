from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from game.combat.effects import build_effective_expr_context, get_effective_major_stat
from game.combat.effect_targeting import (
    EffectApplicationTargetContext,
    EffectTargetSpec,
    apply_effect_to_targets,
    resolve_effect_targets,
)
from game.combat.models import CombatState, HitResult
from game.core.data_loader import SkillData, load_modifier
from game.core.dice import SeededRNG
from game.core.enums import DamageType, ModifierPhase
from game.core.formula_eval import evaluate_expr

if TYPE_CHECKING:
    from game.character.base_entity import BaseEntity


_MAJOR_STAT_KEYS = frozenset({
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
class ModifierInstance:
    """A modifier attached to an entity. Tracks stacking."""

    modifier_id: str
    stack_count: int = 1


@dataclass(frozen=True)
class ResolvedModifier:
    """A modifier resolved for a specific skill, ready to apply."""

    modifier_id: str
    phase: ModifierPhase
    expr: str
    action: str
    stack_count: int
    damage_type_filter: str | None = None
    effect_id: str | None = None
    chance: float = 1.0
    targets: tuple[EffectTargetSpec, ...] = ()


@dataclass(frozen=True)
class SummonModifierBundle:
    major_stat_bonuses: dict[str, float]
    minor_stat_bonuses: dict[str, float]
    granted_skills: tuple[str, ...]
    granted_passives: tuple[str, ...]


def add_modifier(entity: BaseEntity, modifier_id: str) -> BaseEntity:
    mod_data = load_modifier(modifier_id)
    existing = list(entity.skill_modifiers)
    for i, inst in enumerate(existing):
        if inst.modifier_id == modifier_id:
            if mod_data.stackable:
                at_max = (
                    mod_data.max_stacks is not None
                    and inst.stack_count >= mod_data.max_stacks
                )
                if not at_max:
                    existing[i] = replace(inst, stack_count=inst.stack_count + 1)
            return replace(entity, skill_modifiers=tuple(existing))
    existing.append(ModifierInstance(modifier_id=modifier_id))
    return replace(entity, skill_modifiers=tuple(existing))


def remove_modifier(entity: BaseEntity, modifier_id: str) -> BaseEntity:
    existing = list(entity.skill_modifiers)
    for i, inst in enumerate(existing):
        if inst.modifier_id == modifier_id:
            if inst.stack_count > 1:
                existing[i] = replace(inst, stack_count=inst.stack_count - 1)
            else:
                existing.pop(i)
            return replace(entity, skill_modifiers=tuple(existing))
    return entity


def collect_modifiers(
    entity: BaseEntity,
    skill: SkillData,
) -> tuple[ResolvedModifier, ...]:
    """Gather all active modifiers applicable to this skill, with stack counts."""
    result: list[ResolvedModifier] = []
    for inst in entity.skill_modifiers:
        mod_data = load_modifier(inst.modifier_id)
        if mod_data.skill_filter and mod_data.skill_filter != skill.skill_id:
            continue
        # damage_type filter is re-checked per hit in skill_resolver, since
        # skills no longer carry a single damage_type.
        result.append(ResolvedModifier(
            modifier_id=inst.modifier_id,
            phase=mod_data.phase,
            expr=mod_data.expr,
            action=mod_data.action,
            stack_count=inst.stack_count,
            damage_type_filter=mod_data.damage_type_filter,
            effect_id=mod_data.effect_id,
            chance=mod_data.chance,
            targets=mod_data.targets,
        ))
    return tuple(result)


def collect_summon_modifiers(
    state: CombatState,
    entity: BaseEntity,
    skill: SkillData,
    summon_id: str,
) -> SummonModifierBundle:
    owner_ctx = build_effective_expr_context(state, entity.entity_id)
    major_bonuses: dict[str, float] = {}
    minor_bonuses: dict[str, float] = {}
    granted_skills: list[str] = []
    granted_passives: list[str] = []

    for inst in entity.skill_modifiers:
        mod_data = load_modifier(inst.modifier_id)
        if mod_data.phase != ModifierPhase.ON_SUMMON:
            continue
        if mod_data.skill_filter and mod_data.skill_filter != skill.skill_id:
            continue
        if mod_data.summon_filter and mod_data.summon_filter != summon_id:
            continue

        ctx: dict[str, object] = {
            "owner": owner_ctx,
            "attacker": owner_ctx,
            "stack_count": inst.stack_count,
        }
        value = evaluate_expr(mod_data.expr, ctx)
        if mod_data.stackable:
            value *= inst.stack_count

        match mod_data.action:
            case "summon_stat_bonus":
                if mod_data.summon_stat is None:
                    continue
                target_map = (
                    major_bonuses
                    if mod_data.summon_stat in _MAJOR_STAT_KEYS
                    else minor_bonuses
                )
                target_map[mod_data.summon_stat] = (
                    target_map.get(mod_data.summon_stat, 0.0) + value
                )
            case "summon_grant_skill":
                if mod_data.granted_skill_id is not None:
                    granted_skills.append(mod_data.granted_skill_id)
            case "summon_grant_passive":
                if mod_data.granted_passive_id is not None:
                    granted_passives.append(mod_data.granted_passive_id)

    return SummonModifierBundle(
        major_stat_bonuses=major_bonuses,
        minor_stat_bonuses=minor_bonuses,
        granted_skills=tuple(dict.fromkeys(granted_skills)),
        granted_passives=tuple(dict.fromkeys(granted_passives)),
    )


def apply_post_hit_modifiers(
    state: CombatState,
    actor_id: str,
    target_id: str,
    damage_dealt: int,
    modifiers: tuple[ResolvedModifier, ...],
    rng: SeededRNG,
    *,
    damage_type: DamageType | None = None,
) -> tuple[CombatState, list[HitResult]]:
    """Apply post-hit modifiers. Extensible via match on action."""
    post_mods = [m for m in modifiers if m.phase == ModifierPhase.POST_HIT]
    results: list[HitResult] = []
    for mod in post_mods:
        ctx: dict[str, object] = {
            "attacker": build_effective_expr_context(state, actor_id),
            "target": build_effective_expr_context(state, target_id),
            "damage_dealt": damage_dealt,
            "stack_count": mod.stack_count,
        }
        value = evaluate_expr(mod.expr, ctx) * mod.stack_count

        match mod.action:
            case "vampirism":
                if rng.random_float() >= mod.chance:
                    continue
                actor = state.entities[actor_id]
                heal = int(abs(value))
                max_hp = int(get_effective_major_stat(state, actor_id, "hp"))
                new_hp = min(actor.current_hp + heal, max_hp)
                applied = max(0, new_hp - actor.current_hp)
                new_entities = {**state.entities, actor_id: replace(actor, current_hp=new_hp)}
                state = replace(state, entities=new_entities)
                results.append(HitResult(target_id=actor_id, heal_amount=applied))
            case "apply_effect":
                if mod.effect_id is None:
                    continue
                if rng.random_float() >= mod.chance:
                    continue
                applications = max(0, int(value))
                target_context = EffectApplicationTargetContext(
                    source_id=actor_id,
                    hit_target_id=target_id,
                    damage_dealt=damage_dealt,
                    damage_type=damage_type,
                )
                target_ids = resolve_effect_targets(state, target_context, mod.targets)
                state, effect_results = apply_effect_to_targets(
                    state,
                    effect_id=mod.effect_id,
                    source_id=actor_id,
                    target_ids=target_ids,
                    applications=applications,
                )
                results.extend(
                    HitResult(
                        target_id=effect_result.target_id,
                        effects_applied=effect_result.effects_applied,
                    )
                    for effect_result in effect_results
                )
            case _:
                pass  # other post-hit actions can be added here

    return state, results
