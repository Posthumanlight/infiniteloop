from game.character.base_entity import BaseEntity
from game.combat.models import DamageResult
from game.core.data_loader import load_formula
from game.core.dice import SeededRNG
from game.core.enums import DamageType


def resolve_damage(
    attacker: BaseEntity,
    defender: BaseEntity,
    formula_id: str,
    base_power: int,
    damage_type: DamageType,
    rng: SeededRNG,
    effect_multiplier: float,
    constants: dict,
) -> DamageResult:
    formula = load_formula(formula_id)

    raw = (
        base_power
        + attacker.major_stats.attack * formula.attack_scaling
        + attacker.major_stats.mastery * formula.mastery_scaling
        + attacker.major_stats.hp * formula.hp_scaling
    )

    after_def = raw - defender.major_stats.resistance

    after_type = (
        after_def
        * (1.0 + attacker.minor_stats.get_dmg_pct(damage_type))
        * (1.0 - defender.minor_stats.get_def_pct(damage_type))
    )

    is_crit = rng.random_float() < attacker.major_stats.crit_chance
    if is_crit:
        after_type *= attacker.major_stats.crit_dmg

    variance = formula.variance
    after_var = after_type * rng.uniform(1.0 - variance, 1.0 + variance)

    after_effects = after_var * effect_multiplier

    min_damage = constants.get("min_damage", 0)
    final = max(min_damage, int(after_effects))

    return DamageResult(
        amount=final,
        damage_type=damage_type,
        is_crit=is_crit,
        formula_id=formula_id,
    )
