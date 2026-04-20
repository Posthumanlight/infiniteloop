from dataclasses import replace

from game.combat.death import resolve_death_event
from game.combat.damage import resolve_damage
from game.combat.effects import (
    apply_effect,
    get_damage_multiplier,
)
from game.combat.models import CombatState, HitResult, SummonSpawnResult
from game.combat.passives import PassiveEvent, check_passives
from game.combat.skill_modifiers import apply_post_hit_modifiers, collect_modifiers
from game.combat.summons import (
    execute_summon_commands,
    spawn_skill_summons,
)
from game.combat.targeting import resolve_targets
from game.core.data_loader import SkillData
from game.core.dice import SeededRNG
from game.core.enums import ModifierPhase, TriggerType
from game.combat.models import ActionRequest, SkillResolutionResult


def _live_target_entity(state: CombatState, target_id: str):
    target = state.entities.get(target_id)
    if target is None or target.current_hp <= 0:
        return None
    return target


def _resolve_skill_core(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    action: ActionRequest,
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, SkillResolutionResult]:
    all_hits: list[HitResult] = []
    summon_results: tuple[SummonSpawnResult, ...] = ()
    triggered_actions = ()
    selected_targets = action.targets_for_hits()

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
            defender = _live_target_entity(state, target_id)
            if defender is None:
                continue
            attacker = state.entities[actor_id]

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

            if new_hp <= 0:
                state, death_results = resolve_death_event(
                    state,
                    target_id,
                    killer_id=actor_id,
                    rng=rng,
                    constants=constants,
                )
                all_hits.extend(death_results)

    for self_effect in skill.self_effects:
        state = apply_effect(state, actor_id, self_effect.effect_id, actor_id)

    state, summon_results = spawn_skill_summons(
        state,
        actor_id,
        skill,
        rng,
        constants,
    )

    state, triggered_actions = execute_summon_commands(
        state,
        actor_id,
        skill,
        action,
        rng,
        constants,
    )

    return state, SkillResolutionResult(
        hits=tuple(all_hits),
        self_effects_applied=tuple(se.effect_id for se in skill.self_effects),
        summons_created=summon_results,
        triggered_actions=triggered_actions,
    )


def resolve_skill_request(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    action: ActionRequest,
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, SkillResolutionResult]:
    return _resolve_skill_core(state, actor_id, skill, action, rng, constants)


def resolve_skill(
    state: CombatState,
    actor_id: str,
    skill: SkillData,
    selected_targets: dict[int, str],
    rng: SeededRNG,
    constants: dict,
) -> tuple[CombatState, list[HitResult], tuple[SummonSpawnResult, ...]]:
    action = ActionRequest(
        actor_id=actor_id,
        action_type=skill.action_type,
        skill_id=skill.skill_id,
        target_ids=tuple(sorted(selected_targets.items())),
    )
    state, resolution = _resolve_skill_core(
        state,
        actor_id,
        skill,
        action,
        rng,
        constants,
    )
    return state, list(resolution.hits), resolution.summons_created
