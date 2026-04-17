from dataclasses import replace

import pytest

from game.combat.enemy_ai import build_ai_action
from game.combat.engine import start_combat, submit_action
from game.combat.models import ActionRequest
from game.combat.skill_modifiers import ModifierInstance
from game.combat.summons import (
    SummonEntity,
    handle_owner_death,
    spawn_skill_summons,
    tick_summon_duration_after_turn,
)
from game.combat.targeting import get_allies, get_enemies
from game.core.data_loader import clear_cache, load_constants, load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType, EntityType
from game.session.factories import build_enemy, build_player


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _start_summoner_combat(seed: int = 7):
    summoner = build_player("summoner", entity_id="p1")
    summoner = replace(
        summoner,
        major_stats=replace(summoner.major_stats, speed=60),
    )
    enemy = replace(build_enemy("goblin"), entity_id="e1")
    state = start_combat(
        session_id="test-session",
        players=[summoner],
        enemies=[enemy],
        seed=seed,
    )
    return state, enemy.entity_id


def _spawn_familiar_state(seed: int = 7):
    state, enemy_id = _start_summoner_combat(seed=seed)
    state, result = submit_action(
        state,
        ActionRequest(
            actor_id="p1",
            action_type=ActionType.ACTION,
            skill_id="summon_familiar",
        ),
    )
    summon_id = result.summons_created[0].entity_id
    return state, result, summon_id, enemy_id


def test_summon_familiar_spawns_ally_with_owner_and_initiative_position():
    state, result, summon_id, enemy_id = _spawn_familiar_state()

    assert len(result.summons_created) == 1
    summon = state.entities[summon_id]

    assert isinstance(summon, SummonEntity)
    assert summon.entity_type == EntityType.ALLY
    assert summon.owner_id == "p1"
    assert summon.summon_template_id == "familiar"
    assert summon.source_skill_id == "summon_familiar"
    assert summon.remaining_turns == 3
    assert summon.skills == ("generic_enemy_attack",)

    remaining = state.turn_order[state.current_turn_index :]
    assert set(remaining) == {summon_id, enemy_id}
    assert list(remaining) == sorted(
        remaining,
        key=lambda entity_id: state.initiative_scores[entity_id],
        reverse=True,
    )


def test_summon_counts_as_ally_for_player_team_targeting():
    state, _, summon_id, enemy_id = _spawn_familiar_state()

    assert set(get_allies(state, "p1")) == {"p1", summon_id}
    assert get_enemies(state, "p1") == [enemy_id]
    assert set(get_allies(state, summon_id)) == {"p1", summon_id}
    assert get_enemies(state, summon_id) == [enemy_id]


def test_summon_uses_ai_against_enemy_team():
    state, _, summon_id, enemy_id = _spawn_familiar_state()

    action = build_ai_action(state, summon_id, SeededRNG(19))

    assert action is not None
    assert action.skill_id == "generic_enemy_attack"
    assert dict(action.target_ids) == {0: enemy_id}


def test_owner_death_despawns_owned_summons():
    state, _, summon_id, _ = _spawn_familiar_state()
    dead_owner = replace(state.entities["p1"], current_hp=0)
    state = replace(
        state,
        entities={**state.entities, "p1": dead_owner},
    )

    state = handle_owner_death(state, "p1")

    assert summon_id not in state.entities
    assert summon_id not in state.turn_order


def test_recasting_same_summon_replaces_oldest_owned_copy():
    state, _ = _start_summoner_combat(seed=11)
    skill = load_skill("summon_familiar")
    constants = load_constants()
    rng = SeededRNG(31)

    state, first_results = spawn_skill_summons(state, "p1", skill, rng, constants)
    first_id = first_results[0].entity_id

    state, second_results = spawn_skill_summons(state, "p1", skill, rng, constants)
    second_id = second_results[0].entity_id

    owned = [
        entity
        for entity in state.entities.values()
        if isinstance(entity, SummonEntity) and entity.owner_id == "p1"
    ]

    assert first_id not in state.entities
    assert second_id in state.entities
    assert len(owned) == 1


def test_summon_modifiers_apply_on_spawn_only():
    base_summoner = build_player("summoner", entity_id="p1")
    summoner = replace(
        base_summoner,
        major_stats=replace(base_summoner.major_stats, speed=60),
        skill_modifiers=(
            ModifierInstance("familiar_training", stack_count=2),
            ModifierInstance("familiar_arcane_surge"),
            ModifierInstance("familiar_deep_wounds"),
            ModifierInstance("familiar_guardian_instinct"),
        ),
    )
    enemy = replace(build_enemy("goblin"), entity_id="e1")
    state = start_combat(
        session_id="test-session",
        players=[summoner],
        enemies=[enemy],
        seed=13,
    )
    state, result = submit_action(
        state,
        ActionRequest(
            actor_id="p1",
            action_type=ActionType.ACTION,
            skill_id="summon_familiar",
        ),
    )
    summon = state.entities[result.summons_created[0].entity_id]

    assert isinstance(summon, SummonEntity)
    assert summon.major_stats.attack == 21
    assert summon.minor_stats.values["arcane_dmg_pct"] == pytest.approx(0.15)
    assert "deep_wounds" in summon.skills
    assert "battle_master" in summon.passive_skills


def test_summon_duration_ticks_on_its_own_turn_and_despawns_at_zero():
    state, _, summon_id, _ = _spawn_familiar_state(seed=17)
    summon = replace(state.entities[summon_id], remaining_turns=1)
    state = replace(
        state,
        entities={**state.entities, summon_id: summon},
    )

    state = tick_summon_duration_after_turn(state, summon_id)

    assert summon_id not in state.entities
