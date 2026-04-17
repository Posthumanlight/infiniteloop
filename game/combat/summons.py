from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

from game.character.base_entity import BaseEntity
from game.character.stats import MajorStats, MinorStats
from game.combat.initiative import insert_into_turn_order, roll_initiative_pair
from game.combat.models import CombatState, SummonSpawnResult
from game.core.data_loader import (
    SkillData,
    SkillSummonData,
    load_skill,
    load_summon,
    load_summon_constants,
)
from game.core.dice import SeededRNG
from game.core.enums import EntityType
from game.core.formula_eval import evaluate_expr


_INT_MAJOR_STATS = frozenset({
    "attack",
    "hp",
    "speed",
    "resistance",
    "energy",
    "mastery",
})


@dataclass(frozen=True)
class SummonEntity(BaseEntity):
    summon_template_id: str = ""
    owner_id: str = ""
    source_skill_id: str = ""
    skills: tuple[str, ...] = ()
    remaining_turns: int | None = None
    spawn_order: int = 0


def _round_stat(stat_name: str, value: float) -> int | float:
    if stat_name in _INT_MAJOR_STATS:
        return int(round(value))
    return float(value)


def _summon_entity_id(summon_id: str) -> str:
    return f"ally_{summon_id}_{uuid.uuid4().hex[:8]}"


def _iter_owner_summons(
    state: CombatState,
    owner_id: str,
) -> list[SummonEntity]:
    summons: list[SummonEntity] = []
    for entity in state.entities.values():
        if isinstance(entity, SummonEntity) and entity.owner_id == owner_id:
            summons.append(entity)
    summons.sort(key=lambda entity: entity.spawn_order)
    return summons


def despawn_entity(
    state: CombatState,
    entity_id: str,
) -> CombatState:
    if entity_id not in state.entities:
        return state

    turn_order = list(state.turn_order)
    removed_index = None
    if entity_id in turn_order:
        removed_index = turn_order.index(entity_id)
        turn_order.pop(removed_index)

    entities = {
        key: value
        for key, value in state.entities.items()
        if key != entity_id
    }
    passive_trackers = {
        key: value
        for key, value in state.passive_trackers.items()
        if key != entity_id
    }
    cooldowns = {
        key: value
        for key, value in state.cooldowns.items()
        if key != entity_id
    }
    initiative_scores = {
        key: value
        for key, value in state.initiative_scores.items()
        if key != entity_id
    }

    current_turn_index = state.current_turn_index
    if removed_index is not None and removed_index < current_turn_index:
        current_turn_index -= 1

    if current_turn_index < 0:
        current_turn_index = 0

    return replace(
        state,
        entities=entities,
        turn_order=tuple(turn_order),
        current_turn_index=current_turn_index,
        passive_trackers=passive_trackers,
        cooldowns=cooldowns,
        initiative_scores=initiative_scores,
    )


def despawn_owner_summons(
    state: CombatState,
    owner_id: str,
) -> CombatState:
    for summon in _iter_owner_summons(state, owner_id):
        state = despawn_entity(state, summon.entity_id)
    return state


def handle_owner_death(
    state: CombatState,
    dead_id: str,
) -> CombatState:
    dead = state.entities.get(dead_id)
    if dead is None or dead.entity_type != EntityType.PLAYER:
        return state
    return despawn_owner_summons(state, dead_id)


def tick_summon_duration_after_turn(
    state: CombatState,
    actor_id: str,
) -> CombatState:
    entity = state.entities.get(actor_id)
    if not isinstance(entity, SummonEntity):
        return state
    if entity.remaining_turns is None:
        return state

    remaining = entity.remaining_turns - 1
    if remaining <= 0:
        return despawn_entity(state, actor_id)
    return replace(
        state,
        entities={
            **state.entities,
            actor_id: replace(entity, remaining_turns=remaining),
        },
    )


def _apply_spawn_caps(
    state: CombatState,
    owner_id: str,
    summon_id: str,
) -> CombatState:
    template = load_summon(summon_id)
    summon_constants = load_summon_constants()
    global_cap = int(summon_constants["max_total_per_owner"])

    same_type = [
        summon
        for summon in _iter_owner_summons(state, owner_id)
        if summon.summon_template_id == summon_id
    ]
    if len(same_type) >= template.max_per_owner:
        state = despawn_entity(state, same_type[0].entity_id)

    owned = _iter_owner_summons(state, owner_id)
    if len(owned) >= global_cap:
        state = despawn_entity(state, owned[0].entity_id)

    return state


def build_summon_entity(
    state: CombatState,
    owner_id: str,
    summon_id: str,
    *,
    source_skill_id: str,
    duration_own_turns: int | None,
) -> SummonEntity:
    from game.combat.effects import build_effective_expr_context
    from game.combat.skill_modifiers import collect_summon_modifiers

    owner = state.entities[owner_id]
    owner_ctx = build_effective_expr_context(state, owner_id)
    template = load_summon(summon_id)
    source_skill = load_skill(source_skill_id)
    skill = next(
        entry for entry in source_skill.summons
        if entry.summon_id == summon_id
    )
    modifier_bundle = collect_summon_modifiers(
        state,
        owner,
        source_skill,
        summon_id,
    )

    major_values: dict[str, int | float] = {}
    for stat_name, expr in template.major_stat_formulas.items():
        value = evaluate_expr(expr, {"owner": owner_ctx})
        value += modifier_bundle.major_stat_bonuses.get(stat_name, 0.0)
        major_values[stat_name] = _round_stat(stat_name, value)

    minor_values = {
        stat_name: float(evaluate_expr(expr, {"owner": owner_ctx}))
        for stat_name, expr in template.minor_stat_formulas.items()
    }
    for stat_name, bonus in modifier_bundle.minor_stat_bonuses.items():
        minor_values[stat_name] = minor_values.get(stat_name, 0.0) + float(bonus)

    remaining_turns = duration_own_turns
    if remaining_turns is None:
        remaining_turns = skill.duration_own_turns

    return SummonEntity(
        entity_id=_summon_entity_id(summon_id),
        entity_name=template.name,
        entity_type=EntityType.ALLY,
        major_stats=MajorStats(
            attack=int(major_values["attack"]),
            hp=int(major_values["hp"]),
            speed=int(major_values["speed"]),
            crit_chance=float(major_values["crit_chance"]),
            crit_dmg=float(major_values["crit_dmg"]),
            resistance=int(major_values["resistance"]),
            energy=int(major_values["energy"]),
            mastery=int(major_values["mastery"]),
        ),
        minor_stats=MinorStats(values=minor_values),
        current_hp=int(major_values["hp"]),
        current_energy=int(major_values["energy"]),
        passive_skills=tuple(
            dict.fromkeys([
                *template.passives,
                *modifier_bundle.granted_passives,
            ]),
        ),
        summon_template_id=summon_id,
        owner_id=owner_id,
        source_skill_id=source_skill_id,
        skills=tuple(
            dict.fromkeys([
                *template.skills,
                *modifier_bundle.granted_skills,
            ]),
        ),
        remaining_turns=remaining_turns,
        spawn_order=state.next_summon_order,
    )


def _spawn_one_summon(
    state: CombatState,
    actor_id: str,
    summon_data: SkillSummonData,
    source_skill_id: str,
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, SummonSpawnResult]:
    state = _apply_spawn_caps(state, actor_id, summon_data.summon_id)
    summon = build_summon_entity(
        state,
        actor_id,
        summon_data.summon_id,
        source_skill_id=source_skill_id,
        duration_own_turns=summon_data.duration_own_turns,
    )
    new_entities = {
        **state.entities,
        summon.entity_id: summon,
    }
    state = replace(
        state,
        entities=new_entities,
        next_summon_order=state.next_summon_order + 1,
    )

    initiative_score = roll_initiative_pair(
        summon,
        rng,
        int(constants["initiative_dice"]),
        state,
    )
    state = insert_into_turn_order(state, summon.entity_id, initiative_score)
    return state, SummonSpawnResult(
        entity_id=summon.entity_id,
        name=summon.entity_name,
        owner_id=summon.owner_id,
        summon_template_id=summon.summon_template_id,
    )


def spawn_skill_summons(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, tuple[SummonSpawnResult, ...]]:
    results: list[SummonSpawnResult] = []
    from game.combat.effects import build_effective_expr_context

    owner_ctx = build_effective_expr_context(state, actor_id)

    for summon_data in skill.summons:
        count = max(
            0,
            int(round(evaluate_expr(
                summon_data.count_expr,
                {"owner": owner_ctx, "attacker": owner_ctx},
            ))),
        )
        for _ in range(count):
            state, result = _spawn_one_summon(
                state,
                actor_id,
                summon_data,
                skill.skill_id,
                rng,
                constants,
            )
            results.append(result)

    return state, tuple(results)
