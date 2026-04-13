"""Tests for skill resolution."""

import pytest
from dataclasses import replace

import game.combat.passives as combat_passives
import game.combat.skill_modifiers as combat_skill_modifiers
from game.combat.action_resolver import resolve_action
from game.combat.effects import apply_effect, expire_effects
from game.combat.passives import check_passives
from game.combat.models import ActionRequest
from game.combat.skill_modifiers import ModifierInstance
from game.combat.skill_resolver import resolve_skill
from game.core.data_loader import PassiveSkillData, SkillModifierData, clear_cache, load_skill
from game.core.dice import SeededRNG
from game.core.enums import ActionType, ModifierPhase, PassiveAction, TriggerType, UsageLimit
from game.session.factories import build_player

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


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
    state, hits = resolve_skill(state, "p1", skill, {0: "e1"}, rng, CONSTANTS)

    assert len(hits) == 1
    assert hits[0].target_id == "e1"
    assert hits[0].damage.amount > 0
    assert state.entities["e1"].current_hp == initial_hp - hits[0].damage.amount


def test_slash_deterministic():
    skill = load_skill("slash")

    state1 = make_combat_state()
    _, hits1 = resolve_skill(state1, "p1", skill, {0: "e1"}, SeededRNG(42), CONSTANTS)

    state2 = make_combat_state()
    _, hits2 = resolve_skill(state2, "p1", skill, {0: "e1"}, SeededRNG(42), CONSTANTS)

    assert hits1[0].damage.amount == hits2[0].damage.amount


def test_skill_skips_dead_target():
    state = make_combat_state()
    goblin = state.entities["e1"]
    goblin = replace(goblin, current_hp=1)
    state = replace(state, entities={**state.entities, "e1": goblin})

    skill = load_skill("slash")
    rng = SeededRNG(42)

    state, _ = resolve_skill(state, "p1", skill, {0: "e1"}, rng, CONSTANTS)
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

    state, _ = resolve_skill(state, "p1", skill, {0: "e1"}, rng, CONSTANTS)

    empowered = [
        eff for eff in state.entities["p1"].active_effects
        if eff.effect_id == "empowered_arcane"
    ]
    assert len(empowered) == 1
    assert empowered[0].stack_count == 2


def test_arcane_rupture_passive_casts_without_target_map_crash():
    mage = build_player("mage", entity_id="p1")
    goblin = replace(make_goblin("e1"), current_hp=500)
    state = make_combat_state(
        players=[replace(mage, skills=("arcane_bolt",), current_energy=100)],
        enemies=[goblin],
        turn_order=("p1", "e1"),
    )

    for _ in range(5):
        action = ActionRequest(
            actor_id="p1",
            action_type=ActionType.ACTION,
            skill_id="arcane_bolt",
            target_ids=((0, "e1"),),
        )
        state, _ = resolve_action(state, action, SeededRNG(42), CONSTANTS)

    empowered = [
        eff for eff in state.entities["p1"].active_effects
        if eff.effect_id == "empowered_arcane"
    ]
    assert empowered == []
    assert state.entities["e1"].current_hp < goblin.current_hp


def test_enlightenment_buff_increases_spell_damage_restores_energy_and_expires():
    mage = replace(build_player("mage", entity_id="p1"), current_energy=100)
    baseline_state = make_combat_state(
        players=[replace(build_player("mage", entity_id="p1"), current_energy=100)],
        enemies=[make_goblin("e1")],
        turn_order=("p1", "e1"),
    )
    state = make_combat_state(
        players=[mage],
        enemies=[make_goblin("e1")],
        turn_order=("p1", "e1"),
    )

    enlightenment = load_skill("enlightenment")
    annihilation = load_skill("annihilation")

    state, buff_hits = resolve_skill(state, "p1", enlightenment, {}, SeededRNG(1), CONSTANTS)

    assert buff_hits == []
    assert state.entities["p1"].current_energy == 115
    assert any(eff.effect_id == "enlightenment" for eff in state.entities["p1"].active_effects)

    _, baseline_hits = resolve_skill(
        baseline_state,
        "p1",
        annihilation,
        {0: "e1"},
        SeededRNG(42),
        CONSTANTS,
    )
    state, buffed_hits = resolve_skill(
        state,
        "p1",
        annihilation,
        {0: "e1"},
        SeededRNG(42),
        CONSTANTS,
    )

    assert buffed_hits[0].damage.amount > baseline_hits[0].damage.amount

    for _ in range(3):
        state = expire_effects(state, "p1")

    assert all(eff.effect_id != "enlightenment" for eff in state.entities["p1"].active_effects)

    expired_state = make_combat_state(
        players=[replace(state.entities["p1"], active_effects=())],
        enemies=[make_goblin("e1")],
        turn_order=("p1", "e1"),
    )
    _, expired_hits = resolve_skill(
        expired_state,
        "p1",
        annihilation,
        {0: "e1"},
        SeededRNG(42),
        CONSTANTS,
    )

    assert expired_hits[0].damage.amount == baseline_hits[0].damage.amount


def test_passive_context_sees_effective_major_stats(monkeypatch):
    def fake_load_passive(passive_id: str) -> PassiveSkillData:
        if passive_id != "mastery_guard":
            raise KeyError(passive_id)
        return PassiveSkillData(
            skill_id="mastery_guard",
            name="Mastery Guard",
            trigger=TriggerType.ON_TURN_START,
            condition="attacker.mastery >= 20",
            action=PassiveAction.HEAL,
            expr="attacker.mastery",
            usage_limit=UsageLimit.UNLIMITED,
        )

    monkeypatch.setattr(combat_passives, "load_passive", fake_load_passive)

    warrior = replace(make_warrior(), current_hp=80, passive_skills=("mastery_guard",))
    state = make_combat_state(players=[warrior])
    state = apply_effect(state, "p1", "enlightenment", "p1")

    state, hits = check_passives(state, "p1", TriggerType.ON_TURN_START)

    assert hits[0].heal_amount == 25
    assert state.entities["p1"].current_hp == 105


def test_modifier_context_sees_effective_major_stats(monkeypatch):
    def fake_load_modifier(modifier_id: str) -> SkillModifierData:
        if modifier_id != "mastery_vamp":
            raise KeyError(modifier_id)
        return SkillModifierData(
            modifier_id="mastery_vamp",
            name="Mastery Vamp",
            phase=ModifierPhase.POST_HIT,
            stackable=False,
            expr="attacker.mastery",
            action="vampirism",
        )

    monkeypatch.setattr(combat_skill_modifiers, "load_modifier", fake_load_modifier)

    warrior = replace(
        make_warrior(),
        current_hp=50,
        skill_modifiers=(ModifierInstance("mastery_vamp"),),
    )
    state = make_combat_state(players=[warrior])
    state = apply_effect(state, "p1", "enlightenment", "p1")

    slash = load_skill("slash")
    state, hits = resolve_skill(state, "p1", slash, {0: "e1"}, SeededRNG(42), CONSTANTS)

    heal_hits = [hit for hit in hits if hit.heal_amount > 0]
    assert heal_hits[0].heal_amount == 25
    assert state.entities["p1"].current_hp == 75
