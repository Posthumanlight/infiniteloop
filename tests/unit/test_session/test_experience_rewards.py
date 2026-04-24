from dataclasses import replace

from game.session.experience_rewards import (
    build_combat_xp_award,
    enemy_xp_reward,
)
from game.world.difficulty import RoomDifficultyModifier

from tests.unit.conftest import make_goblin, make_warrior


def _difficulty(scalar: float) -> RoomDifficultyModifier:
    return RoomDifficultyModifier(
        scalar=scalar,
        average_level=1.0,
        party_size=1,
        power=1,
    )


def test_enemy_xp_reward_defaults_to_base_without_difficulty():
    enemy = make_goblin()

    assert enemy_xp_reward(enemy, None) == 15


def test_enemy_xp_reward_uses_difficulty_scalar():
    enemy = make_goblin()

    assert enemy_xp_reward(enemy, _difficulty(2.4)) == 36


def test_enemy_xp_reward_uses_custom_formula():
    enemy = replace(
        make_goblin(),
        base_xp_reward=10,
        xp_formula="base_xp_reward + difficulty_modifier * 5",
    )

    assert enemy_xp_reward(enemy, _difficulty(2.0)) == 20


def test_enemy_xp_reward_clamps_negative_result_to_zero():
    enemy = replace(make_goblin(), xp_formula="-10")

    assert enemy_xp_reward(enemy, _difficulty(2.0)) == 0


def test_combat_xp_award_splits_evenly():
    players = [make_warrior("p1"), make_warrior("p2"), make_warrior("p3")]
    enemies = [make_goblin()]

    award = build_combat_xp_award(enemies, players, None)

    assert award.total_enemy_xp == 15
    assert award.per_player == {"p1": 5, "p2": 5, "p3": 5}
    assert award.total_awarded_xp == 15


def test_combat_xp_award_drops_remainder():
    players = [make_warrior("p1"), make_warrior("p2"), make_warrior("p3")]
    enemies = [replace(make_goblin(), base_xp_reward=100)]

    award = build_combat_xp_award(enemies, players, None)

    assert award.total_enemy_xp == 100
    assert award.per_player == {"p1": 33, "p2": 33, "p3": 33}
    assert award.total_awarded_xp == 99


def test_combat_xp_award_includes_downed_players():
    players = [
        make_warrior("p1"),
        replace(make_warrior("p2"), current_hp=0),
        make_warrior("p3"),
    ]
    enemies = [make_goblin()]

    award = build_combat_xp_award(enemies, players, None)

    assert award.per_player == {"p1": 5, "p2": 5, "p3": 5}
