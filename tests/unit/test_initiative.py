"""Tests for initiative rolling and turn order."""

from game.combat.initiative import build_turn_order, roll_initiative
from game.core.dice import SeededRNG

from tests.unit.conftest import make_goblin, make_warrior


def test_roll_initiative_uses_speed():
    warrior = make_warrior()
    rng = SeededRNG(42)
    roll = roll_initiative(warrior, rng, 20)
    assert warrior.major_stats.speed < roll <= warrior.major_stats.speed + 20


def test_same_seed_same_turn_order():
    entities = {
        "p1": make_warrior("p1"),
        "e1": make_goblin("e1"),
    }
    order1 = build_turn_order(entities, SeededRNG(42), 20)
    order2 = build_turn_order(entities, SeededRNG(42), 20)
    assert order1 == order2


def test_turn_order_contains_all_entities():
    entities = {
        "p1": make_warrior("p1"),
        "e1": make_goblin("e1"),
    }
    order = build_turn_order(entities, SeededRNG(42), 20)
    assert set(order) == {"p1", "e1"}


def test_different_seed_can_produce_different_order():
    entities = {
        "p1": make_warrior("p1"),
        "e1": make_goblin("e1"),
    }
    orders = set()
    for seed in range(100):
        order = build_turn_order(entities, SeededRNG(seed), 20)
        orders.add(order)
    # With 100 different seeds, we should see both orderings
    assert len(orders) > 1
