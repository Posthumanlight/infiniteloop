from dataclasses import replace

from game.combat.cooldowns import put_on_cooldown
from game.combat.enemy_ai import build_enemy_action, iter_priority_skill_ids
from game.core.dice import SeededRNG
from game.session.factories import build_enemy

from tests.unit.conftest import make_combat_state, make_warrior


def _make_draugr_state():
    draugr = replace(build_enemy("draugr"), entity_id="e1")
    players = [make_warrior("p1"), make_warrior("p2")]
    state = make_combat_state(
        players=players,
        enemies=[draugr],
        turn_order=("e1", "p1", "p2"),
    )
    return replace(state, rng_state=SeededRNG(42).get_state())


def test_draugr_priority_uses_enemy_skill_order():
    state = _make_draugr_state()

    assert iter_priority_skill_ids(state, "e1") == (
        "draugr_chilling_wind",
        "generic_enemy_attack",
    )


def test_draugr_uses_chilling_wind_first_when_available():
    state = _make_draugr_state()
    rng = SeededRNG(42)

    action = build_enemy_action(state, "e1", rng)

    assert action is not None
    assert action.skill_id == "draugr_chilling_wind"
    assert action.target_ids == ()


def test_draugr_falls_back_to_generic_attack_when_chilling_wind_on_cooldown():
    state = put_on_cooldown(_make_draugr_state(), "e1", "draugr_chilling_wind", 4)
    rng1 = SeededRNG(7)
    rng2 = SeededRNG(7)

    action1 = build_enemy_action(state, "e1", rng1)
    action2 = build_enemy_action(state, "e1", rng2)

    assert action1 is not None
    assert action1.skill_id == "generic_enemy_attack"
    assert action1.target_ids == action2.target_ids
    assert dict(action1.target_ids)[0] in {"p1", "p2"}


def test_draugr_returns_none_when_no_living_player_targets_exist():
    dead_players = [
        replace(make_warrior("p1"), current_hp=0),
        replace(make_warrior("p2"), current_hp=0),
    ]
    draugr = replace(build_enemy("draugr"), entity_id="e1")
    state = make_combat_state(
        players=dead_players,
        enemies=[draugr],
        turn_order=("e1", "p1", "p2"),
    )
    state = replace(state, rng_state=SeededRNG(99).get_state())

    action = build_enemy_action(state, "e1", SeededRNG(99))

    assert action is None
