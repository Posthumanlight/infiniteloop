from dataclasses import replace

from game.combat.damage import resolve_damage
from game.combat.effects import apply_effect, get_damage_multiplier
from game.combat.models import CombatState, HitResult
from game.core.data_loader import SkillData
from game.core.dice import SeededRNG


def resolve_skill(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    target_ids: list[str],
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, list[HitResult]]:
    all_hits: list[HitResult] = []

    for target_id in target_ids:
        for hit in skill.hits:
            attacker = state.entities[actor_id]
            defender = state.entities[target_id]

            if defender.current_hp <= 0:
                break

            effect_mult = get_damage_multiplier(state, actor_id, target_id)

            dmg_result = resolve_damage(
                attacker=attacker,
                defender=defender,
                formula_id=hit.formula,
                base_power=hit.base_power,
                damage_type=skill.damage_type,
                rng=rng,
                effect_multiplier=effect_mult,
                constants=constants,
            )

            current_defender = state.entities[target_id]
            new_hp = max(0, current_defender.current_hp - dmg_result.amount)
            new_entities = {
                **state.entities,
                target_id: replace(current_defender, current_hp=new_hp),
            }
            state = replace(state, entities=new_entities)

            effects_applied: list[str] = []
            for on_hit in hit.on_hit_effects:
                if rng.random_float() < on_hit.chance:
                    state = apply_effect(state, target_id, on_hit.effect_id, actor_id)
                    effects_applied.append(on_hit.effect_id)

            all_hits.append(HitResult(
                target_id=target_id,
                damage=dmg_result,
                effects_applied=tuple(effects_applied),
            ))

    for self_effect in skill.self_effects:
        state = apply_effect(state, actor_id, self_effect.effect_id, actor_id)

    return state, all_hits
