from dataclasses import replace

import pytest

from game.character.stats import MajorStats, MinorStats
from game.combat.skill_resolver import resolve_skill
from game.combat.summons import SummonEntity
from game.core.data_loader import SkillData, SkillHitData, clear_cache
from game.core.dice import SeededRNG
from game.core.enums import ActionType, DamageType, EntityType, TargetType

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


CONSTANTS = {"min_damage": 0}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _make_familiar(owner_id: str = "p1") -> SummonEntity:
    return SummonEntity(
        entity_id="ally_familiar_test",
        entity_name="Familiar",
        entity_type=EntityType.ALLY,
        major_stats=MajorStats(
            attack=6,
            hp=20,
            speed=12,
            crit_chance=0.0,
            crit_dmg=1.5,
            resistance=0,
            energy=20,
            mastery=0,
        ),
        minor_stats=MinorStats(values={}),
        current_hp=20,
        current_energy=20,
        summon_template_id="familiar",
        owner_id=owner_id,
        source_skill_id="summon_familiar",
        skills=("generic_enemy_attack",),
    )


def _make_all_enemies_skill(*, share_follow_up: bool = False) -> SkillData:
    hits = [
        SkillHitData(
            target_type=TargetType.ALL_ENEMIES,
            damage_type=DamageType.SLASHING,
            formula="attacker.attack + base_power",
            base_power=0,
            variance=0.0,
        ),
    ]
    if share_follow_up:
        hits.append(
            SkillHitData(
                target_type=TargetType.ALL_ENEMIES,
                damage_type=DamageType.SLASHING,
                formula="attacker.attack + base_power",
                base_power=0,
                variance=0.0,
                share_with=0,
            ),
        )

    return SkillData(
        skill_id="test_multi_target",
        name="Test Multi Target",
        energy_cost=0,
        action_type=ActionType.ACTION,
        hits=tuple(hits),
        self_effects=(),
        summary="test",
    )


def test_multi_target_skill_skips_summon_removed_by_owner_death():
    player = replace(make_warrior(), current_hp=1)
    enemy = replace(
        make_goblin("e1"),
        major_stats=replace(make_goblin("e1").major_stats, attack=10),
    )
    summon = _make_familiar(owner_id="p1")
    state = make_combat_state(players=[player], enemies=[enemy], turn_order=("e1", "p1", summon.entity_id))
    state = replace(
        state,
        entities={**state.entities, summon.entity_id: summon},
        turn_order=("e1", "p1", summon.entity_id),
    )

    state, hits, _ = resolve_skill(
        state,
        "e1",
        _make_all_enemies_skill(),
        {},
        SeededRNG(1),
        CONSTANTS,
    )

    assert state.entities["p1"].current_hp == 0
    assert summon.entity_id not in state.entities
    assert [hit.target_id for hit in hits if hit.damage is not None] == ["p1"]


def test_share_with_cached_targets_skip_removed_entities():
    player = replace(make_warrior(), current_hp=1)
    enemy = replace(
        make_goblin("e1"),
        major_stats=replace(make_goblin("e1").major_stats, attack=10),
    )
    summon = _make_familiar(owner_id="p1")
    state = make_combat_state(players=[player], enemies=[enemy], turn_order=("e1", "p1", summon.entity_id))
    state = replace(
        state,
        entities={**state.entities, summon.entity_id: summon},
        turn_order=("e1", "p1", summon.entity_id),
    )

    state, hits, _ = resolve_skill(
        state,
        "e1",
        _make_all_enemies_skill(share_follow_up=True),
        {},
        SeededRNG(2),
        CONSTANTS,
    )

    assert state.entities["p1"].current_hp == 0
    assert summon.entity_id not in state.entities
    assert [hit.target_id for hit in hits if hit.damage is not None] == ["p1"]
