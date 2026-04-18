from dataclasses import replace

import pytest

from bot.tools.combat_renderer import render_action_result
from game.combat.enemy_ai import build_ai_action
from game.combat.engine import start_combat, submit_action
from game.combat.models import ActionRequest
from game.combat.skill_targeting import (
    ActionTargetRef,
    TargetOwnerKind,
    iter_manual_target_requirements,
)
from game.combat.summons import commandable_summons_for_skill, spawn_skill_summons
from game.core.data_loader import clear_cache, load_constants, load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType, TargetType
from game.session.factories import build_enemy, build_player
from game_service import GameService


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _build_command_state(seed: int = 11):
    summoner = replace(
        build_player("summoner", entity_id="p1"),
        skills=("mana_reave", "summon_familiar", "command_spell"),
    )
    enemy = replace(build_enemy("goblin"), entity_id="e1")
    state = start_combat(
        session_id="test-session",
        players=[summoner],
        enemies=[enemy],
        seed=seed,
    )

    state, summon_results = spawn_skill_summons(
        state,
        "p1",
        load_skill("summon_familiar"),
        SeededRNG(seed + 1),
        load_constants(),
    )
    summon_id = summon_results[0].entity_id
    state = replace(
        state,
        current_turn_index=state.turn_order.index("p1"),
        rng_state=SeededRNG(seed + 2).get_state(),
    )
    return state, summon_id, enemy.entity_id


def test_command_spell_derives_manual_target_from_commanded_skill():
    skill = load_skill("command_spell")
    requirements = iter_manual_target_requirements(skill)

    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement.owner_kind == TargetOwnerKind.SUMMON_COMMAND
    assert requirement.owner_index == 0
    assert requirement.nested_index == 0
    assert requirement.target_type == TargetType.SINGLE_ENEMY


def test_command_spell_orders_owned_familiar_and_preserves_future_turn():
    state, summon_id, enemy_id = _build_command_state()

    command_skill = load_skill("command_spell")
    assert commandable_summons_for_skill(state, "p1", command_skill) == (summon_id,)

    state, result = submit_action(
        state,
        ActionRequest(
            actor_id="p1",
            action_type=ActionType.ACTION,
            skill_id="command_spell",
            target_refs=(
                ActionTargetRef(
                    owner_kind=TargetOwnerKind.SUMMON_COMMAND,
                    owner_index=0,
                    nested_index=0,
                    entity_id=enemy_id,
                ),
            ),
        ),
    )

    assert result.actor_id == "p1"
    assert result.hits == ()
    assert len(result.triggered_actions) == 1

    child = result.triggered_actions[0]
    assert child.actor_id == summon_id
    assert child.skill_id == "generic_enemy_attack"
    assert len(child.hits) == 1
    assert child.hits[0].target_id == enemy_id

    summon_turn_state = replace(
        state,
        current_turn_index=state.turn_order.index(summon_id),
    )
    summon_action = build_ai_action(summon_turn_state, summon_id, SeededRNG(99))

    assert summon_action is not None
    assert summon_action.actor_id == summon_id
    assert summon_action.skill_id == "generic_enemy_attack"


def test_command_spell_renders_combined_triggered_line():
    state, summon_id, enemy_id = _build_command_state(seed=21)
    state, result = submit_action(
        state,
        ActionRequest(
            actor_id="p1",
            action_type=ActionType.ACTION,
            skill_id="command_spell",
            target_refs=(
                ActionTargetRef(
                    owner_kind=TargetOwnerKind.SUMMON_COMMAND,
                    owner_index=0,
                    nested_index=0,
                    entity_id=enemy_id,
                ),
            ),
        ),
    )

    entities = {
        entity_id: GameService._entity_to_snapshot(entity, state)
        for entity_id, entity in state.entities.items()
    }
    text = render_action_result(result, entities)

    assert "command_spell" in text
    assert "Familiar hits" in text
    assert "Goblin" in text
