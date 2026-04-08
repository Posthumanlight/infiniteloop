from dataclasses import replace

from game.combat.damage import resolve_damage
from game.combat.effects import apply_effect, build_expr_context, get_damage_multiplier
from game.combat.models import CombatState, HitResult
from game.combat.passives import check_passives
from game.combat.skill_modifiers import apply_post_hit_modifiers, collect_modifiers
from game.combat.targeting import get_allies
from game.core.data_loader import SkillData
from game.core.dice import SeededRNG
from game.core.enums import ModifierPhase, TriggerType


def resolve_skill(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    target_ids: list[str],
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, list[HitResult]]:
    all_hits: list[HitResult] = []

    # Collect modifiers for this actor + skill
    actor = state.entities[actor_id]
    modifiers = collect_modifiers(actor, skill)
    pre_hit_mods = tuple(m for m in modifiers if m.phase == ModifierPhase.PRE_HIT)

    for target_id in target_ids:
        for hit in skill.hits:
            attacker = state.entities[actor_id]
            defender = state.entities[target_id]

            if defender.current_hp <= 0:
                break

            effect_mult = get_damage_multiplier(state, actor_id, target_id, skill.damage_type)

            dmg_result = resolve_damage(
                attacker=attacker,
                defender=defender,
                formula_expr=hit.formula,
                base_power=hit.base_power,
                damage_type=skill.damage_type,
                rng=rng,
                constants=constants,
                modifiers=pre_hit_mods,
                variance=hit.variance,
                effect_multiplier=effect_mult,
                state=state,
            )

            current_defender = state.entities[target_id]
            new_hp = max(0, current_defender.current_hp - dmg_result.amount)
            new_entities = {
                **state.entities,
                target_id: replace(current_defender, current_hp=new_hp),
            }
            state = replace(state, entities=new_entities)

            # Post-hit modifiers (vampirism, etc.)
            state, post_results = apply_post_hit_modifiers(
                state, actor_id, target_id, dmg_result.amount, modifiers,
            )
            all_hits.extend(post_results)

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

            # Passive triggers: ON_HIT
            state, _ = check_passives(
                state, actor_id, TriggerType.ON_HIT,
                {"damage_type": skill.damage_type},
            )

            # Passive triggers: ON_TAKE_DAMAGE
            state, _ = check_passives(
                state, target_id, TriggerType.ON_TAKE_DAMAGE,
                {"damage_taken": dmg_result.amount},
            )

            # Passive triggers: ON_KILL + ON_ALLY_DEATH
            if new_hp <= 0:
                state, kill_results = check_passives(
                    state, actor_id, TriggerType.ON_KILL,
                    {"killed": build_expr_context(defender)},
                )
                all_hits.extend(kill_results)

                for ally_id in get_allies(state, target_id):
                    if ally_id != target_id:
                        state, _ = check_passives(
                            state, ally_id, TriggerType.ON_ALLY_DEATH,
                        )

    for self_effect in skill.self_effects:
        state = apply_effect(state, actor_id, self_effect.effect_id, actor_id)

    return state, all_hits
