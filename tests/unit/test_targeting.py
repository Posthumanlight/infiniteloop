"""Tests for targeting resolution."""

import pytest
from dataclasses import replace

from game.combat.targeting import get_allies, get_enemies, is_alive, resolve_targets
from game.core.enums import TargetType

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


def test_is_alive_true():
    assert is_alive(make_warrior()) is True


def test_is_alive_false():
    w = make_warrior()
    dead = replace(w, current_hp=0)
    assert is_alive(dead) is False


def test_get_enemies_from_player():
    state = make_combat_state()
    enemies = get_enemies(state, "p1")
    assert "e1" in enemies
    assert "p1" not in enemies


def test_get_allies_from_player():
    state = make_combat_state()
    allies = get_allies(state, "p1")
    assert "p1" in allies
    assert "e1" not in allies


def test_get_enemies_excludes_dead():
    goblin = make_goblin()
    dead_goblin = replace(goblin, current_hp=0)
    state = make_combat_state(enemies=[dead_goblin])
    enemies = get_enemies(state, "p1")
    assert len(enemies) == 0


def test_resolve_single_enemy():
    state = make_combat_state()
    targets = resolve_targets(state, "p1", TargetType.SINGLE_ENEMY, "e1")
    assert targets == ["e1"]


def test_resolve_single_enemy_invalid_raises():
    state = make_combat_state()
    with pytest.raises(ValueError, match="Invalid target"):
        resolve_targets(state, "p1", TargetType.SINGLE_ENEMY, "p1")


def test_resolve_single_enemy_none_raises():
    state = make_combat_state()
    with pytest.raises(ValueError, match="Invalid target"):
        resolve_targets(state, "p1", TargetType.SINGLE_ENEMY, None)


def test_resolve_all_enemies():
    g1 = make_goblin("e1")
    g2 = make_goblin("e2")
    state = make_combat_state(enemies=[g1, g2])
    targets = resolve_targets(state, "p1", TargetType.ALL_ENEMIES, None)
    assert set(targets) == {"e1", "e2"}


def test_resolve_self():
    state = make_combat_state()
    targets = resolve_targets(state, "p1", TargetType.SELF, None)
    assert targets == ["p1"]


def test_resolve_single_ally():
    state = make_combat_state()
    targets = resolve_targets(state, "p1", TargetType.SINGLE_ALLY, "p1")
    assert targets == ["p1"]


def test_resolve_all_allies():
    w1 = make_warrior("p1")
    w2 = make_warrior("p2")
    state = make_combat_state(players=[w1, w2])
    targets = resolve_targets(state, "p1", TargetType.ALL_ALLIES, None)
    assert set(targets) == {"p1", "p2"}
