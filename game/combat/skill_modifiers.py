from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from game.combat.effects import (
    apply_effect,
    build_effective_expr_context,
    get_effective_major_stat,
)
from game.combat.models import CombatState, HitResult
from game.core.data_loader import SkillData, load_modifier
from game.core.dice import SeededRNG
from game.core.enums import ModifierPhase
from game.core.formula_eval import evaluate_expr

if TYPE_CHECKING:
    from game.character.base_entity import BaseEntity


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
        ))
    return tuple(result)


def apply_post_hit_modifiers(
    state: CombatState,
    actor_id: str,
    target_id: str,
    damage_dealt: int,
    modifiers: tuple[ResolvedModifier, ...],
    rng: SeededRNG,
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
                for _ in range(applications):
                    state = apply_effect(state, target_id, mod.effect_id, actor_id)
                if applications > 0:
                    results.append(HitResult(
                        target_id=target_id,
                        effects_applied=tuple(mod.effect_id for _ in range(applications)),
                    ))
            case _:
                pass  # other post-hit actions can be added here

    return state, results
