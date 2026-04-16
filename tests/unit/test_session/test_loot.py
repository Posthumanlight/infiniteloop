from dataclasses import replace

import pytest

from game.core.data_loader import clear_cache
from game.core.dice import SeededRNG
from game.core.enums import CombatPhase
from game.core.game_models import LootResolutionSnapshot, PlayerInfo
from game.session.factories import build_enemy
from game.session.node_manager import (
    resolve_and_award_combat_loot,
    resolve_loot_item_quality,
    roll_public_item_contest,
)
from game.session.session_manager import SessionManager
from game.world.difficulty import RoomDifficultyModifier
from game_service import GameService, _ActiveSession

from tests.unit.conftest import make_warrior


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_resolve_loot_item_quality_uses_room_difficulty_scalar():
    difficulty = RoomDifficultyModifier(
        scalar=2.6,
        average_level=5.0,
        party_size=2,
        power=10,
    )

    assert resolve_loot_item_quality(None) == 1
    assert resolve_loot_item_quality(difficulty) == 3


def test_roll_public_item_contest_rerolls_tied_top_players():
    players = [
        make_warrior("p1"),
        make_warrior("p2"),
        make_warrior("p3"),
    ]
    rng = SeededRNG(63)

    winner_id, rounds = roll_public_item_contest(players, rng)

    assert winner_id == "p2"
    assert len(rounds) == 2
    assert tuple(roll.roll for roll in rounds[0].rolls) == (57, 57, 38)
    assert tuple(roll.player_id for roll in rounds[1].rolls) == ("p1", "p2")
    assert tuple(roll.roll for roll in rounds[1].rolls) == (33, 62)


def test_resolve_and_award_combat_loot_adds_generated_item_to_winner_inventory():
    players = [
        make_warrior("p1"),
        make_warrior("p2"),
    ]
    defeated_enemy = replace(build_enemy("goblin_boss"), current_hp=0)
    difficulty = RoomDifficultyModifier(
        scalar=2.2,
        average_level=4.0,
        party_size=2,
        power=8,
    )

    updated_players, loot = resolve_and_award_combat_loot(
        players=players,
        defeated_enemies=[defeated_enemy],
        room_difficulty=difficulty,
        rng=SeededRNG(123),
    )

    assert len(loot.awards) == 1
    award = loot.awards[0]
    assert award.source_enemy_id == "goblin_boss"
    assert award.item_blueprint_id == "long_sword"
    assert award.quality == 2

    winner = next(player for player in updated_players if player.entity_id == award.winner_id)
    assert award.winner_item_instance_id in winner.inventory.items
    assert winner.inventory.items[award.winner_item_instance_id].quality == 2


def test_finalize_combat_stores_pending_loot_and_awards_inventory():
    mgr = SessionManager(seed=42)
    difficulty = RoomDifficultyModifier(
        scalar=2.4,
        average_level=5.0,
        party_size=1,
        power=9,
    )
    player = make_warrior("p1")
    state = mgr.start_run("test-session", [player])
    state = mgr._node.enter_combat(
        state,
        ("goblin_boss",),
        room_difficulty=difficulty,
    )

    assert state.combat is not None
    enemy_id = next(
        entity_id
        for entity_id, entity in state.combat.entities.items()
        if entity.entity_id != "p1"
    )
    defeated_enemy = replace(state.combat.entities[enemy_id], current_hp=0)
    combat = replace(
        state.combat,
        phase=CombatPhase.ENDED,
        entities={**state.combat.entities, enemy_id: defeated_enemy},
    )
    state = replace(state, combat=combat)

    finalized = mgr._node.finalize_combat(state)

    assert finalized.pending_loot is not None
    assert len(finalized.pending_loot.awards) == 1
    assert finalized.pending_loot.awards[0].quality == 2
    assert finalized.combat is None
    assert finalized.run_stats.combats_completed == 1
    assert len(finalized.players[0].inventory.items) == 1


def test_consume_pending_loot_clears_session_snapshot():
    service = GameService()
    manager = SessionManager(seed=7)
    player = make_warrior("p1")
    state = manager.start_run("test-session", [player])
    snapshot = LootResolutionSnapshot(awards=())
    state = replace(state, pending_loot=snapshot)
    player_info = PlayerInfo(
        entity_id="p1",
        tg_user_id=1,
        display_name="Tester",
        class_id="warrior",
    )
    service._sessions["test-session"] = _ActiveSession(
        session_id="test-session",
        players={"p1": player_info},
        manager=manager,
        state=state,
        save_origins={},
    )

    pending = service.consume_pending_loot("test-session")

    assert pending == snapshot
    assert service._sessions["test-session"].state.pending_loot is None
