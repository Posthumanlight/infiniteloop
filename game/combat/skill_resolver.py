from dataclasses import replace

from game.combat.death import resolve_death_event
from game.combat.damage import resolve_damage
from game.combat.effects import (
    apply_effect,
    get_damage_multiplier,
)
from game.combat.effect_targeting import (
    EffectApplicationTargetContext,
    apply_effect_to_targets,
    resolve_effect_targets,
)
from game.combat.models import CombatState, HitResult, SummonSpawnResult
from game.combat.passives import PassiveEvent, check_passives
from game.combat.skill_modifiers import apply_post_hit_modifiers, collect_modifiers
from game.combat.summons import (
    execute_summon_commands,
    spawn_skill_summons,
)
from game.combat.targeting import resolve_targets
from game.combat.trackers import (
    TrackedCombatEvent,
    TrackerEventType,
    process_tracked_event,
)
from game.core.data_loader import SkillData
from game.core.dice import SeededRNG
from game.core.enums import ModifierPhase, TriggerType
from game.combat.models import ActionRequest, SkillResolutionResult


def _live_target_entity(state: CombatState, target_id: str):
    target = state.entities.get(target_id)
    if target is None or target.current_hp <= 0:
        return None
    return target


def _is_effect_only_hit(hit: HitResult) -> bool:
    return hit.damage is None and hit.heal_amount == 0 and bool(hit.effects_applied)


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
                state,
                actor_id,
                target_id,
                dmg_result.amount,
                modifiers,
                rng,
                damage_type=hit.damage_type,
            )

            effects_applied: list[str] = []
            extra_effect_hits: list[HitResult] = []
            for post_result in post_results:
                if (
                    post_result.target_id == target_id
                    and _is_effect_only_hit(post_result)
                ):
                    effects_applied.extend(post_result.effects_applied)
                else:
                    extra_effect_hits.append(post_result)

            for on_hit in hit.on_hit_effects:
                if rng.random_float() < on_hit.chance:
                    target_context = EffectApplicationTargetContext(
                        source_id=actor_id,
                        hit_target_id=target_id,
                        damage_dealt=dmg_result.amount,
                        damage_type=hit.damage_type,
                    )
                    effect_targets = resolve_effect_targets(
                        state,
                        target_context,
                        on_hit.targets,
                    )
                    state, applications = apply_effect_to_targets(
                        state,
                        effect_id=on_hit.effect_id,
                        source_id=actor_id,
                        target_ids=effect_targets,
                    )
                    for application in applications:
                        if application.target_id == target_id:
                            effects_applied.extend(application.effects_applied)
                        else:
                            extra_effect_hits.append(HitResult(
                                target_id=application.target_id,
                                effects_applied=application.effects_applied,
                                skill_id=skill.skill_id,
                            ))

            # Passive triggers: ON_HIT
            state, passive_hits = check_passives(
                state,
                actor_id,
                PassiveEvent(
                    trigger=TriggerType.ON_HIT,
                    payload={
                        "damage_type": hit.damage_type,
                        "damage_dealt": dmg_result.amount,
                        "hit_target_id": target_id,
                    },
                ),
            )
            for passive_hit in passive_hits:
                if (
                    passive_hit.target_id == target_id
                    and _is_effect_only_hit(passive_hit)
                ):
                    effects_applied.extend(passive_hit.effects_applied)
                else:
                    extra_effect_hits.append(passive_hit)

            # Passive triggers: ON_TAKE_DAMAGE
            state, passive_take_hits = check_passives(
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
            for passive_hit in passive_take_hits:
                if (
                    passive_hit.target_id == target_id
                    and _is_effect_only_hit(passive_hit)
                ):
                    effects_applied.extend(passive_hit.effects_applied)
                else:
                    extra_effect_hits.append(passive_hit)

            all_hits.append(HitResult(
                target_id=target_id,
                damage=dmg_result,
                effects_applied=tuple(effects_applied),
                skill_id=skill.skill_id,
            ))
            all_hits.extend(extra_effect_hits)

            state, tracker_hits = process_tracked_event(
                state,
                TrackedCombatEvent(
                    event_type=TrackerEventType.HIT,
                    source_id=actor_id,
                    target_id=target_id,
                    damage_amount=dmg_result.amount,
                    damage_type=hit.damage_type,
                    skill_id=skill.skill_id,
                ),
                rng,
                constants,
            )
            all_hits.extend(tracker_hits)

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
