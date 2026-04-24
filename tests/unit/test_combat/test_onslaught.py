from dataclasses import replace

import pytest

from game.character.stats import MajorStats, MinorStats
from game.combat.models import CombatState
from game.combat.skill_resolver import resolve_skill
from game.combat.summons import SummonEntity
from game.core.data_loader import clear_cache, load_skill
from game.core.dice import SeededRNG
from game.core.enums import EntityType
from game.session.factories import build_enemy, build_player

from tests.unit.conftest import make_combat_state


CONSTANTS = {"min_damage": 0}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _summon(entity_id: str, *, owner_id: str = "p1", attack: int = 5) -> SummonEntity:
    return SummonEntity(
        entity_id=entity_id,
        entity_name="Familiar",
        entity_type=EntityType.ALLY,
        major_stats=MajorStats(
            attack=attack,
            hp=40,
            speed=20,
            crit_chance=0,
            crit_dmg=1.5,
            resistance=0,
            energy=40,
            mastery=0,
        ),
        minor_stats=MinorStats(values={}),
        current_hp=40,
        current_energy=40,
        owner_id=owner_id,
        summon_template_id="familiar",
        source_skill_id="summon_familiar",
        skills=("generic_enemy_attack",),
    )


def _enemy(entity_id: str, hp: int = 1000):
    enemy = build_enemy("goblin")
    return replace(
        enemy,
        entity_id=entity_id,
        major_stats=replace(enemy.major_stats, hp=hp, resistance=0),
        current_hp=hp,
    )


def _onslaught_state(
    *,
    enemy_hp: int = 1000,
    second_enemy: bool = False,
    summon_attack: int = 5,
) -> CombatState:
    summoner = build_player("summoner", entity_id="p1")
    summoner = replace(
        summoner,
        skills=(),
        passive_skills=("onslaught",),
        current_energy=0,
        major_stats=replace(summoner.major_stats, attack=20, crit_chance=0),
    )
    enemies = [_enemy("e1", hp=enemy_hp)]
    if second_enemy:
        enemies.append(_enemy("e2", hp=enemy_hp))

    state = make_combat_state(
        players=[summoner],
        enemies=enemies,
        turn_order=("p1", "s1", *tuple(enemy.entity_id for enemy in enemies)),
    )
    return replace(
        state,
        entities={
            **state.entities,
            "s1": _summon("s1", attack=summon_attack),
        },
    )


def _summon_hit(
    state: CombatState,
    target_id: str = "e1",
    *,
    seed: int = 1,
):
    return resolve_skill(
        state,
        "s1",
        load_skill("generic_enemy_attack"),
        {0: target_id},
        SeededRNG(seed),
        CONSTANTS,
    )


def _has_onslaught_hit(hits) -> bool:
    return any(hit.skill_id == "onslaught" for hit in hits)


def test_fourth_owned_summon_hit_procs_hidden_onslaught_from_summoner():
    state = _onslaught_state()

    for seed in range(1, 4):
        state, hits, _ = _summon_hit(state, seed=seed)
        assert not _has_onslaught_hit(hits)

    assert state.tracker_counts[("p1", "onslaught", "e1")] == 3

    state, hits, _ = _summon_hit(state, seed=4)

    assert any(
        hit.skill_id == "onslaught" and hit.target_id == "e1"
        for hit in hits
    )
    assert state.tracker_counts[("p1", "onslaught", "e1")] == 0


def test_onslaught_tracks_each_enemy_target_separately():
    state = _onslaught_state(second_enemy=True)

    for target_id, seed in (("e1", 1), ("e2", 2), ("e1", 3), ("e2", 4)):
        state, hits, _ = _summon_hit(state, target_id, seed=seed)
        assert not _has_onslaught_hit(hits)

    assert state.tracker_counts[("p1", "onslaught", "e1")] == 2
    assert state.tracker_counts[("p1", "onslaught", "e2")] == 2


def test_onslaught_needs_four_new_hits_after_proc():
    state = _onslaught_state()

    for seed in range(1, 5):
        state, _, _ = _summon_hit(state, seed=seed)

    for seed in range(5, 8):
        state, hits, _ = _summon_hit(state, seed=seed)
        assert not _has_onslaught_hit(hits)

    assert state.tracker_counts[("p1", "onslaught", "e1")] == 3

    state, hits, _ = _summon_hit(state, seed=8)

    assert _has_onslaught_hit(hits)
    assert state.tracker_counts[("p1", "onslaught", "e1")] == 0


def test_onslaught_resets_but_skips_cast_when_fourth_hit_kills_target():
    state = _onslaught_state(enemy_hp=1, summon_attack=10)
    state = replace(
        state,
        tracker_counts={("p1", "onslaught", "e1"): 3},
    )

    state, hits, _ = _summon_hit(state)

    assert state.entities["e1"].current_hp == 0
    assert not _has_onslaught_hit(hits)
    assert state.tracker_counts[("p1", "onslaught", "e1")] == 0
