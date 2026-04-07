from __future__ import annotations

from typing import TYPE_CHECKING

from game.character.base_entity import BaseEntity
from game.combat.effects import build_expr_context, get_effective_minor_stat
from game.combat.models import CombatState, DamageResult
from game.core.dice import SeededRNG
from game.core.enums import DamageType
from game.core.formula_eval import evaluate_expr

if TYPE_CHECKING:
    from game.combat.skill_modifiers import ResolvedModifier


def resolve_damage(
    attacker: BaseEntity,
    defender: BaseEntity,
    formula_expr: str,
    base_power: int,
    damage_type: DamageType,
    rng: SeededRNG,
    constants: dict,
    modifiers: tuple[ResolvedModifier, ...] = (),
    variance: float | None = None,
    effect_multiplier: float = 1.0,
    state: CombatState | None = None,
) -> DamageResult:
    ctx: dict[str, object] = {
        "base_power": base_power,
        "attacker": build_expr_context(attacker),
        "target": build_expr_context(defender),
    }

    raw = evaluate_expr(formula_expr, ctx)

    for mod in modifiers:
        raw += evaluate_expr(mod.expr, ctx) * mod.stack_count

    after_def = raw * 200 / (200 * defender.major_stats.resistance)

    # Type scaling — use effective minor stats if state is available
    if state is not None:
        atk_dmg_pct = get_effective_minor_stat(
            state, attacker.entity_id, f"{damage_type.value}_dmg_pct",
        )
        def_def_pct = get_effective_minor_stat(
            state, defender.entity_id, f"{damage_type.value}_def_pct",
        )
    else:
        atk_dmg_pct = attacker.minor_stats.get_dmg_pct(damage_type)
        def_def_pct = defender.minor_stats.get_def_pct(damage_type)

    after_type = (
        after_def
        * (1.0 + atk_dmg_pct)
        * (1.0 - def_def_pct)
    )

    is_crit = rng.random_float() < attacker.major_stats.crit_chance
    if is_crit:
        after_type *= attacker.major_stats.crit_dmg

    var = variance if variance is not None else constants.get("default_variance", 0)
    after_var = after_type * rng.uniform(1.0 - var, 1.0 + var)

    after_effects = after_var * effect_multiplier

    min_damage = constants.get("min_damage", 0)
    final = max(min_damage, int(after_effects))

    return DamageResult(
        amount=final,
        damage_type=damage_type,
        is_crit=is_crit,
        formula_id="expr",
    )
