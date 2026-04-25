from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Iterable

from game.core.enums import DamageType, EntityType
from game.core.formula_eval import evaluate_expr

if TYPE_CHECKING:
    from game.combat.models import CombatState


class EffectTargetRelation(str, Enum):
    SELF = "self"
    HIT_TARGET = "hit_target"
    ENEMIES = "enemies"
    ALLIES = "allies"
    SUMMONS = "summons"


class EffectTargetSelect(str, Enum):
    SINGLE = "single"
    ALL = "all"


@dataclass(frozen=True)
class EffectTargetSpec:
    relation: EffectTargetRelation
    select: EffectTargetSelect
    condition: str | None = None


@dataclass(frozen=True)
class EffectApplicationTargetContext:
    source_id: str
    hit_target_id: str
    damage_dealt: int
    damage_type: DamageType | None = None


@dataclass(frozen=True)
class EffectApplicationResult:
    target_id: str
    effects_applied: tuple[str, ...]


_DAMAGE_TYPE_NUMERIC: dict[DamageType, int] = {
    DamageType.SLASHING: 1,
    DamageType.PIERCING: 2,
    DamageType.ARCANE: 3,
    DamageType.FIRE: 4,
    DamageType.ICE: 5,
}

_PLAYER_TEAM = frozenset({EntityType.PLAYER, EntityType.ALLY})


def parse_effect_target_specs(
    raw_targets: Any,
    owner_label: str,
) -> tuple[EffectTargetSpec, ...]:
    if not isinstance(raw_targets, list) or not raw_targets:
        raise ValueError(f"{owner_label}: targets must be a non-empty list")

    specs: list[EffectTargetSpec] = []
    for index, raw in enumerate(raw_targets):
        if not isinstance(raw, dict):
            raise ValueError(f"{owner_label}: targets[{index}] must be a table")
        try:
            relation = EffectTargetRelation(raw["relation"])
            select = EffectTargetSelect(raw["select"])
        except KeyError as exc:
            raise ValueError(
                f"{owner_label}: targets[{index}] is missing {exc.args[0]}",
            ) from exc
        except ValueError as exc:
            raise ValueError(
                f"{owner_label}: targets[{index}] has invalid relation or select",
            ) from exc

        condition = raw.get("condition")
        if condition is not None and not isinstance(condition, str):
            raise ValueError(
                f"{owner_label}: targets[{index}].condition must be a string",
            )
        specs.append(EffectTargetSpec(
            relation=relation,
            select=select,
            condition=condition,
        ))

    return tuple(specs)


def resolve_effect_targets(
    state: CombatState,
    context: EffectApplicationTargetContext,
    specs: Iterable[EffectTargetSpec],
) -> tuple[str, ...]:
    resolved: list[str] = []
    seen: set[str] = set()

    for spec in specs:
        candidates = [
            candidate_id
            for candidate_id in _candidate_ids_for_relation(state, context, spec.relation)
            if _matches_condition(state, context, candidate_id, spec.condition)
        ]
        if spec.select == EffectTargetSelect.SINGLE:
            candidates = candidates[:1]
        for candidate_id in candidates:
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            resolved.append(candidate_id)

    return tuple(resolved)


def apply_effect_to_targets(
    state: CombatState,
    *,
    effect_id: str,
    source_id: str,
    target_ids: Iterable[str],
    applications: int = 1,
) -> tuple[CombatState, tuple[EffectApplicationResult, ...]]:
    from game.combat.effects import apply_effect

    if applications <= 0:
        return state, ()

    results: list[EffectApplicationResult] = []
    for target_id in target_ids:
        if target_id not in state.entities:
            continue
        for _ in range(applications):
            state = apply_effect(state, target_id, effect_id, source_id)
        results.append(EffectApplicationResult(
            target_id=target_id,
            effects_applied=tuple(effect_id for _ in range(applications)),
        ))

    return state, tuple(results)


def _candidate_ids_for_relation(
    state: CombatState,
    context: EffectApplicationTargetContext,
    relation: EffectTargetRelation,
) -> tuple[str, ...]:
    match relation:
        case EffectTargetRelation.SELF:
            return (
                (context.source_id,)
                if context.source_id in state.entities
                else ()
            )
        case EffectTargetRelation.HIT_TARGET:
            return (
                (context.hit_target_id,)
                if context.hit_target_id in state.entities
                else ()
            )
        case EffectTargetRelation.ENEMIES:
            return tuple(_ordered_related_entities(state, context.source_id, enemies=True))
        case EffectTargetRelation.ALLIES:
            return tuple(_ordered_related_entities(
                state,
                context.source_id,
                allies=True,
                exclude_source=True,
            ))
        case EffectTargetRelation.SUMMONS:
            owner_id = _summon_owner_id(state, context.source_id)
            if owner_id is None:
                return ()
            return tuple(_ordered_owned_summon_ids(state, owner_id))


def _ordered_entity_ids(state: CombatState) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for entity_id in state.turn_order:
        if entity_id in state.entities and entity_id not in seen:
            seen.add(entity_id)
            ordered.append(entity_id)
    for entity_id in state.entities:
        if entity_id not in seen:
            ordered.append(entity_id)
    return tuple(ordered)


def _ordered_related_entities(
    state: CombatState,
    source_id: str,
    *,
    allies: bool = False,
    enemies: bool = False,
    exclude_source: bool = False,
) -> tuple[str, ...]:
    source = state.entities.get(source_id)
    if source is None:
        return ()

    related: list[str] = []
    for candidate_id in _ordered_entity_ids(state):
        if exclude_source and candidate_id == source_id:
            continue
        candidate = state.entities[candidate_id]
        if candidate.current_hp <= 0:
            continue
        if allies and _are_allies(source, candidate):
            related.append(candidate_id)
        elif enemies and not _are_allies(source, candidate):
            related.append(candidate_id)
    return tuple(related)


def _summon_owner_id(state: CombatState, source_id: str) -> str | None:
    from game.combat.summons import SummonEntity

    source = state.entities.get(source_id)
    if source is None:
        return None
    if isinstance(source, SummonEntity):
        return source.owner_id
    return source_id


def _ordered_owned_summon_ids(
    state: CombatState,
    owner_id: str,
) -> tuple[str, ...]:
    from game.combat.summons import SummonEntity

    summon_ids: list[str] = []
    for entity_id in _ordered_entity_ids(state):
        entity = state.entities[entity_id]
        if (
            isinstance(entity, SummonEntity)
            and entity.owner_id == owner_id
            and entity.current_hp > 0
        ):
            summon_ids.append(entity_id)
    return tuple(summon_ids)


def _matches_condition(
    state: CombatState,
    context: EffectApplicationTargetContext,
    candidate_id: str,
    condition: str | None,
) -> bool:
    if condition is None:
        return True
    if (
        context.source_id not in state.entities
        or context.hit_target_id not in state.entities
        or candidate_id not in state.entities
    ):
        return False

    from game.combat.effects import build_effective_expr_context

    source_ctx = build_effective_expr_context(state, context.source_id)
    hit_target_ctx = build_effective_expr_context(state, context.hit_target_id)
    candidate_ctx = build_effective_expr_context(state, candidate_id)
    condition_ctx: dict[str, Any] = {
        "owner": source_ctx,
        "source": source_ctx,
        "attacker": source_ctx,
        "hit_target": hit_target_ctx,
        "target": hit_target_ctx,
        "candidate": candidate_ctx,
        "damage_dealt": context.damage_dealt,
        "damage_type": _damage_type_to_numeric(context.damage_type),
        **_build_damage_type_constants(),
    }
    return bool(evaluate_expr(condition, condition_ctx))


def _damage_type_to_numeric(value: DamageType | None) -> int:
    if value is None:
        return 0
    return _DAMAGE_TYPE_NUMERIC[value]


def _build_damage_type_constants() -> dict[str, int]:
    return {dt.name: _damage_type_to_numeric(dt) for dt in DamageType}


def _are_allies(a: Any, b: Any) -> bool:
    return (a.entity_type in _PLAYER_TEAM) == (b.entity_type in _PLAYER_TEAM)
