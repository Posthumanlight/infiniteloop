"""Tests for skill resolution."""

import pytest

from game.combat.skill_resolver import resolve_skill
from game.core.data_loader import clear_cache, load_skill
from game.core.dice import SeededRNG
from game.session.factories import build_player

from tests.unit.conftest import make_combat_state, make_goblin


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


CONSTANTS = {"min_damage": 0}


def test_slash_deals_damage():
    state = make_combat_state()
    skill = load_skill("slash")
    rng = SeededRNG(42)

    initial_hp = state.entities["e1"].current_hp
    state, hits = resolve_skill(state, "p1", skill, ["e1"], rng, CONSTANTS)

    assert len(hits) == 1
    assert hits[0].target_id == "e1"
    assert hits[0].damage.amount > 0
    assert state.entities["e1"].current_hp == initial_hp - hits[0].damage.amount


def test_slash_deterministic():
    skill = load_skill("slash")

    state1 = make_combat_state()
    _, hits1 = resolve_skill(state1, "p1", skill, ["e1"], SeededRNG(42), CONSTANTS)

    state2 = make_combat_state()
    _, hits2 = resolve_skill(state2, "p1", skill, ["e1"], SeededRNG(42), CONSTANTS)

    assert hits1[0].damage.amount == hits2[0].damage.amount


def test_skill_skips_dead_target():
    """If target dies mid-hit sequence, remaining hits on that target stop."""
    from dataclasses import replace

    state = make_combat_state()
    # Set goblin HP very low so it dies on first hit
    goblin = state.entities["e1"]
    goblin = replace(goblin, current_hp=1)
    state = replace(state, entities={**state.entities, "e1": goblin})

    skill = load_skill("slash")
    rng = SeededRNG(42)

    state, hits = resolve_skill(state, "p1", skill, ["e1"], rng, CONSTANTS)
    assert state.entities["e1"].current_hp == 0


def test_arcane_prowess_applies_empowered_arcane_on_hit():
    mage = build_player("mage", entity_id="p1")
    goblin = make_goblin("e1")
    state = make_combat_state(
        players=[mage],
        enemies=[goblin],
        turn_order=("p1", "e1"),
    )
    skill = load_skill("arcane_bolt")
    rng = SeededRNG(42)

    state, _ = resolve_skill(state, "p1", skill, ["e1"], rng, CONSTANTS)

    empowered = [
        eff for eff in state.entities["p1"].active_effects
        if eff.effect_id == "empowered_arcane"
    ]
    assert len(empowered) == 1
    assert empowered[0].stack_count == 2
