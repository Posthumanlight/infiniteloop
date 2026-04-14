"""Tests for initiative rolling and turn order."""

from dataclasses import replace

import game.combat.effects as combat_effects
from game.combat.effects import StatusEffectInstance
from game.combat.initiative import build_turn_order, roll_initiative
from game.combat.models import CombatState
from game.core.data_loader import EffectActionDef, EffectDef
from game.core.dice import SeededRNG
from game.core.enums import CombatPhase, EffectActionType, TriggerType

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
    assert len(orders) > 1


def test_speed_buff_changes_initiative_roll(monkeypatch):
    def fake_load_effect(effect_id: str) -> EffectDef:
        if effect_id != "haste":
            raise KeyError(effect_id)
        return EffectDef(
            effect_id="haste",
            name="Haste",
            trigger=TriggerType.ON_APPLY,
            duration=3,
            stackable=False,
            actions=(
                EffectActionDef(
                    action_type=EffectActionType.STAT_MODIFY,
                    stat="speed",
                    expr="7",
                    scales_with_stacks=False,
                ),
            ),
        )

    monkeypatch.setattr(combat_effects, "load_effect", fake_load_effect)

    warrior = replace(
        make_warrior(),
        active_effects=(StatusEffectInstance("haste", "p1", 3),),
    )
    state = CombatState(
        combat_id="test",
        session_id="test",
        round_number=1,
        turn_order=("p1",),
        current_turn_index=0,
        entities={"p1": warrior},
        phase=CombatPhase.ACTING,
    )

    raw_roll = roll_initiative(make_warrior(), SeededRNG(42), 20)
    buffed_roll = roll_initiative(warrior, SeededRNG(42), 20, state)

    assert buffed_roll == raw_roll + 7


def test_speed_buff_changes_turn_order(monkeypatch):
    def fake_load_effect(effect_id: str) -> EffectDef:
        if effect_id != "haste":
            raise KeyError(effect_id)
        return EffectDef(
            effect_id="haste",
            name="Haste",
            trigger=TriggerType.ON_APPLY,
            duration=3,
            stackable=False,
            actions=(
                EffectActionDef(
                    action_type=EffectActionType.STAT_MODIFY,
                    stat="speed",
                    expr="10",
                    scales_with_stacks=False,
                ),
            ),
        )

    monkeypatch.setattr(combat_effects, "load_effect", fake_load_effect)

    warrior = replace(
        make_warrior("p1"),
        major_stats=replace(make_warrior("p1").major_stats, speed=10),
        active_effects=(StatusEffectInstance("haste", "p1", 3),),
    )
    goblin = replace(make_goblin("e1"), major_stats=replace(make_goblin("e1").major_stats, speed=10))

    order = build_turn_order({"p1": warrior, "e1": goblin}, SeededRNG(42), 20)

    assert order[0] == "p1"
