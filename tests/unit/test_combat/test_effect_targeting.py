from dataclasses import replace

import pytest

from game.character.stats import MajorStats, MinorStats
from game.combat.effect_targeting import (
    EffectApplicationTargetContext,
    EffectTargetRelation,
    EffectTargetSelect,
    EffectTargetSpec,
    resolve_effect_targets,
)
from game.combat.effects import get_effective_major_stat
from game.combat.skill_resolver import resolve_skill
from game.combat.summons import SummonEntity
from game.core.data_loader import OnHitEffectData, SkillData, SkillHitData
from game.core.dice import SeededRNG
from game.core.enums import ActionType, DamageType, EntityType, TargetType

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


CONSTANTS = {"min_damage": 0}


def _summon(entity_id: str, owner_id: str) -> SummonEntity:
    return SummonEntity(
        entity_id=entity_id,
        entity_name="Test Summon",
        entity_type=EntityType.ALLY,
        major_stats=MajorStats(
            attack=5,
            hp=30,
            speed=20,
            crit_chance=0,
            crit_dmg=1.5,
            resistance=0,
            energy=40,
            mastery=0,
        ),
        minor_stats=MinorStats(values={}),
        current_hp=30,
        current_energy=40,
        owner_id=owner_id,
        skills=("generic_enemy_attack",),
    )


def _state():
    owner = make_warrior("p1")
    ally = make_warrior("p2")
    enemy_a = replace(make_goblin("e1"), current_hp=100)
    enemy_b = replace(make_goblin("e2"), current_hp=40)
    state = make_combat_state(
        players=[owner, ally],
        enemies=[enemy_a, enemy_b],
        turn_order=("p1", "p2", "s1", "s2", "e1", "e2"),
    )
    return replace(
        state,
        entities={
            **state.entities,
            "s1": _summon("s1", "p1"),
            "s2": _summon("s2", "p2"),
        },
    )


def test_resolver_dedupes_multiple_target_specs_in_order():
    state = _state()
    context = EffectApplicationTargetContext(
        source_id="p1",
        hit_target_id="e1",
        damage_dealt=10,
        damage_type=DamageType.SLASHING,
    )

    targets = resolve_effect_targets(
        state,
        context,
        (
            EffectTargetSpec(EffectTargetRelation.HIT_TARGET, EffectTargetSelect.SINGLE),
            EffectTargetSpec(EffectTargetRelation.SELF, EffectTargetSelect.SINGLE),
            EffectTargetSpec(EffectTargetRelation.ENEMIES, EffectTargetSelect.ALL),
            EffectTargetSpec(EffectTargetRelation.HIT_TARGET, EffectTargetSelect.SINGLE),
        ),
    )

    assert targets == ("e1", "p1", "e2")


def test_resolver_filters_candidates_with_conditions():
    state = _state()
    context = EffectApplicationTargetContext(
        source_id="p1",
        hit_target_id="e1",
        damage_dealt=10,
        damage_type=DamageType.SLASHING,
    )

    targets = resolve_effect_targets(
        state,
        context,
        (
            EffectTargetSpec(
                EffectTargetRelation.ENEMIES,
                EffectTargetSelect.ALL,
                condition="candidate.current_hp >= 80",
            ),
        ),
    )

    assert targets == ("e1",)


def test_resolver_single_uses_stable_combat_order():
    state = replace(_state(), turn_order=("p1", "e2", "e1", "p2", "s1", "s2"))
    context = EffectApplicationTargetContext(
        source_id="p1",
        hit_target_id="e1",
        damage_dealt=10,
        damage_type=DamageType.SLASHING,
    )

    targets = resolve_effect_targets(
        state,
        context,
        (EffectTargetSpec(EffectTargetRelation.ENEMIES, EffectTargetSelect.SINGLE),),
    )

    assert targets == ("e2",)


def test_resolver_summons_uses_owner_for_player_or_summon_source():
    state = _state()
    player_context = EffectApplicationTargetContext(
        source_id="p1",
        hit_target_id="e1",
        damage_dealt=10,
        damage_type=DamageType.SLASHING,
    )
    summon_context = EffectApplicationTargetContext(
        source_id="s1",
        hit_target_id="e1",
        damage_dealt=10,
        damage_type=DamageType.SLASHING,
    )
    specs = (EffectTargetSpec(EffectTargetRelation.SUMMONS, EffectTargetSelect.ALL),)

    assert resolve_effect_targets(state, player_context, specs) == ("s1",)
    assert resolve_effect_targets(state, summon_context, specs) == ("s1",)


def test_skill_on_hit_effect_can_target_self_as_separate_hit_result():
    state = make_combat_state()
    skill = SkillData(
        skill_id="self_bleed_hit",
        name="Self Bleed Hit",
        energy_cost=0,
        action_type=ActionType.ACTION,
        hits=(
            SkillHitData(
                target_type=TargetType.SINGLE_ENEMY,
                formula="0",
                base_power=0,
                damage_type=DamageType.SLASHING,
                variance=0.0,
                on_hit_effects=(
                    OnHitEffectData(
                        effect_id="bleed",
                        chance=1.0,
                        targets=(
                            EffectTargetSpec(
                                EffectTargetRelation.SELF,
                                EffectTargetSelect.SINGLE,
                            ),
                        ),
                    ),
                ),
            ),
        ),
        self_effects=(),
    )

    state, hits, _ = resolve_skill(
        state,
        "p1",
        skill,
        {0: "e1"},
        SeededRNG(42),
        CONSTANTS,
    )

    assert hits[0].target_id == "e1"
    assert hits[0].effects_applied == ()
    assert any(
        hit.target_id == "p1" and hit.effects_applied == ("bleed",)
        for hit in hits[1:]
    )
    assert any(
        effect.effect_id == "bleed"
        for effect in state.entities["p1"].active_effects
    )


def test_underdweller_inversion_targets_hit_player_and_reduces_max_hp():
    player = make_warrior("p1")
    enemy = replace(
        make_goblin("e1"),
        passive_skills=("underdweller_inversion",),
        current_hp=100,
    )
    state = make_combat_state(
        players=[player],
        enemies=[enemy],
        turn_order=("e1", "p1"),
    )
    skill = SkillData(
        skill_id="underdweller_test_hit",
        name="Underdweller Test Hit",
        energy_cost=0,
        action_type=ActionType.ACTION,
        hits=(
            SkillHitData(
                target_type=TargetType.SINGLE_ENEMY,
                formula="0",
                base_power=0,
                damage_type=DamageType.SLASHING,
                variance=0.0,
            ),
        ),
        self_effects=(),
    )

    state, hits, _ = resolve_skill(
        state,
        "e1",
        skill,
        {0: "p1"},
        SeededRNG(42),
        CONSTANTS,
    )

    assert any(
        effect.effect_id == "underdweller_inversion"
        for effect in state.entities["p1"].active_effects
    )
    assert all(
        effect.effect_id != "underdweller_inversion"
        for effect in state.entities["e1"].active_effects
    )
    assert get_effective_major_stat(state, "p1", "hp") == pytest.approx(96)
    assert hits[0].target_id == "p1"
    assert "underdweller_inversion" in hits[0].effects_applied
