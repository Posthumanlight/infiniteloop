from dataclasses import replace

from game.combat.damage import resolve_damage
from game.combat.effects import (
    apply_effect,
    build_effective_expr_context,
    get_damage_multiplier,
)
from game.combat.models import CombatState, HitResult, SummonSpawnResult
from game.combat.passives import PassiveEvent, check_passives
from game.combat.skill_modifiers import apply_post_hit_modifiers, collect_modifiers
from game.combat.summons import handle_owner_death, spawn_skill_summons
from game.combat.targeting import get_allies, resolve_targets
from game.core.data_loader import SkillData
from game.core.dice import SeededRNG
from game.core.enums import ModifierPhase, TriggerType


def resolve_skill(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    selected_targets: dict[int, str],
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, list[HitResult], tuple[SummonSpawnResult, ...]]:
    all_hits: list[HitResult] = []
    summon_results = ()

    # Collect modifiers for this actor + skill (damage_type filter re-checked per hit)
    actor = state.entities[actor_id]
    modifiers = collect_modifiers(actor, skill)

    # Cache of resolved target lists by hit index for share_with reuse.
    hit_target_cache: dict[int, list[str]] = {}

    for hit_index, hit in enumerate(skill.hits):
        if hit.share_with is not None:
            target_ids = hit_target_cache.get(hit.share_with, [])
        else:
            target_ids = resolve_targets(
                state, actor_id, hit.target_type, selected_targets.get(hit_index),
            )
        hit_target_cache[hit_index] = list(target_ids)

        pre_hit_mods = tuple(
            m for m in modifiers
            if m.phase == ModifierPhase.PRE_HIT
            and (m.damage_type_filter is None or (
                hit.damage_type is not None and hit.damage_type.value == m.damage_type_filter
            ))
        )

        for target_id in target_ids:
            attacker = state.entities[actor_id]
            defender = state.entities[target_id]

            if defender.current_hp <= 0:
                continue

            effect_mult = get_damage_multiplier(state, actor_id, target_id, hit.damage_type)

            dmg_result = resolve_damage(
                attacker=attacker,
                defender=defender,
                formula_expr=hit.formula,
                base_power=hit.base_power,
                damage_type=hit.damage_type,
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
            if new_hp <= 0:
                state = handle_owner_death(state, target_id)

            # Post-hit modifiers (vampirism, etc.)
            state, post_results = apply_post_hit_modifiers(
                state, actor_id, target_id, dmg_result.amount, modifiers, rng,
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
                skill_id=skill.skill_id,
            ))

            # Passive triggers: ON_HIT
            state, _ = check_passives(
                state,
                actor_id,
                PassiveEvent(
                    trigger=TriggerType.ON_HIT,
                    payload={
                        "damage_type": hit.damage_type,
                        "damage_dealt": dmg_result.amount,
                    },
                ),
            )

            # Passive triggers: ON_TAKE_DAMAGE
            state, _ = check_passives(
                state,
                target_id,
                PassiveEvent(
                    trigger=TriggerType.ON_TAKE_DAMAGE,
                    payload={
                        "damage_type": hit.damage_type,
                        "damage_taken": dmg_result.amount,
                    },
                ),
            )

            # Passive triggers: ON_KILL + ON_ALLY_DEATH
            if new_hp <= 0:
                state, kill_results = check_passives(
                    state,
                    actor_id,
                    PassiveEvent(
                        trigger=TriggerType.ON_KILL,
                        payload={"killed": build_effective_expr_context(state, target_id)},
                    ),
                )
                all_hits.extend(kill_results)

                for ally_id in get_allies(state, target_id):
                    if ally_id != target_id:
                        state, _ = check_passives(
                            state,
                            ally_id,
                            PassiveEvent(trigger=TriggerType.ON_ALLY_DEATH),
                        )

    for self_effect in skill.self_effects:
        state = apply_effect(state, actor_id, self_effect.effect_id, actor_id)

    state, summon_results = spawn_skill_summons(
        state,
        actor_id,
        skill,
        rng,
        constants,
    )

    return state, all_hits, summon_results
