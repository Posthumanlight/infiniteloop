from dataclasses import replace

import pytest

import game.combat.passives as combat_passives
from game.combat.effects import apply_effect, tick_effects
from game.combat.passives import PassiveEvent, check_passives
from game.combat.skill_resolver import resolve_skill
from game.combat.summons import SummonEntity
from game.core.data_loader import (
    PassiveSkillData,
    clear_cache,
    load_constants,
    load_passives,
    load_skill,
)
from game.core.dice import SeededRNG
from game.core.enums import PassiveAction, TriggerType, UsageLimit

from tests.unit.conftest import make_combat_state, make_goblin, make_warrior


CONSTANTS = {"min_damage": 0}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def _patch_passives(monkeypatch, mapping: dict[str, PassiveSkillData]) -> None:
    def fake_load_passive(passive_id: str) -> PassiveSkillData:
        if passive_id not in mapping:
            raise KeyError(passive_id)
        return mapping[passive_id]

    monkeypatch.setattr(combat_passives, "load_passive", fake_load_passive)


def test_load_passives_accepts_on_death_trigger():
    passives = load_passives()

    assert "blaze_of_glory" in passives
    assert TriggerType.ON_DEATH in passives["blaze_of_glory"].triggers


def test_on_death_heal_revives_and_blocks_kill_chain(monkeypatch):
    _patch_passives(monkeypatch, {
        "second_wind": PassiveSkillData(
            skill_id="second_wind",
            name="Second Wind",
            triggers=(TriggerType.ON_DEATH,),
            condition="",
            action=PassiveAction.HEAL,
            expr="25",
            usage_limit=UsageLimit.UNLIMITED,
        ),
        "killer_reward": PassiveSkillData(
            skill_id="killer_reward",
            name="Killer Reward",
            triggers=(TriggerType.ON_KILL,),
            condition="",
            action=PassiveAction.GRANT_ENERGY,
            expr="7",
            usage_limit=UsageLimit.UNLIMITED,
        ),
        "ally_mourn": PassiveSkillData(
            skill_id="ally_mourn",
            name="Ally Mourn",
            triggers=(TriggerType.ON_ALLY_DEATH,),
            condition="",
            action=PassiveAction.GRANT_ENERGY,
            expr="9",
            usage_limit=UsageLimit.UNLIMITED,
        ),
    })

    victim = replace(
        make_warrior(),
        current_hp=1,
        current_energy=0,
        passive_skills=("second_wind",),
    )
    ally = replace(
        make_warrior("p2"),
        current_energy=0,
        passive_skills=("ally_mourn",),
    )
    killer = replace(
        make_goblin("e1"),
        current_energy=0,
        passive_skills=("killer_reward",),
    )
    state = make_combat_state(
        players=[victim, ally],
        enemies=[killer],
        turn_order=("e1", "p1", "p2"),
    )

    state, hits, _ = resolve_skill(
        state,
        "e1",
        load_skill("slash"),
        {0: "p1"},
        SeededRNG(1),
        CONSTANTS,
    )

    assert state.entities["p1"].current_hp > 0
    assert state.entities["e1"].current_energy == 0
    assert state.entities["p2"].current_energy == 0
    assert any(hit.target_id == "p1" and hit.heal_amount > 0 for hit in hits)


def test_on_death_from_effect_tick_runs_kill_and_ally_death(monkeypatch):
    _patch_passives(monkeypatch, {
        "death_reward": PassiveSkillData(
            skill_id="death_reward",
            name="Death Reward",
            triggers=(TriggerType.ON_DEATH,),
            condition="",
            action=PassiveAction.GRANT_ENERGY,
            expr="11",
            usage_limit=UsageLimit.UNLIMITED,
        ),
        "killer_reward": PassiveSkillData(
            skill_id="killer_reward",
            name="Killer Reward",
            triggers=(TriggerType.ON_KILL,),
            condition="",
            action=PassiveAction.GRANT_ENERGY,
            expr="7",
            usage_limit=UsageLimit.UNLIMITED,
        ),
        "ally_mourn": PassiveSkillData(
            skill_id="ally_mourn",
            name="Ally Mourn",
            triggers=(TriggerType.ON_ALLY_DEATH,),
            condition="",
            action=PassiveAction.GRANT_ENERGY,
            expr="9",
            usage_limit=UsageLimit.UNLIMITED,
        ),
    })

    victim = replace(
        make_warrior(),
        current_hp=2,
        current_energy=0,
        passive_skills=("death_reward",),
    )
    ally = replace(
        make_warrior("p2"),
        current_energy=0,
        passive_skills=("ally_mourn",),
    )
    killer = replace(
        make_goblin("e1"),
        current_energy=0,
        passive_skills=("killer_reward",),
    )
    state = make_combat_state(players=[victim, ally], enemies=[killer])
    state = apply_effect(state, "p1", "bleed", "e1")

    state, _ = tick_effects(state, "p1", TriggerType.ON_TURN_START, SeededRNG(2))

    assert state.entities["p1"].current_hp == 0
    assert state.entities["p1"].current_energy == 11
    assert state.entities["e1"].current_energy == 7
    assert state.entities["p2"].current_energy == 9


def test_self_inflicted_passive_death_does_not_fire_on_kill(monkeypatch):
    _patch_passives(monkeypatch, {
        "self_destruct": PassiveSkillData(
            skill_id="self_destruct",
            name="Self Destruct",
            triggers=(TriggerType.ON_TURN_START,),
            condition="",
            action=PassiveAction.DAMAGE,
            expr="999",
            usage_limit=UsageLimit.UNLIMITED,
        ),
        "death_reward": PassiveSkillData(
            skill_id="death_reward",
            name="Death Reward",
            triggers=(TriggerType.ON_DEATH,),
            condition="",
            action=PassiveAction.GRANT_ENERGY,
            expr="13",
            usage_limit=UsageLimit.UNLIMITED,
        ),
        "killer_reward": PassiveSkillData(
            skill_id="killer_reward",
            name="Killer Reward",
            triggers=(TriggerType.ON_KILL,),
            condition="",
            action=PassiveAction.GRANT_ENERGY,
            expr="7",
            usage_limit=UsageLimit.UNLIMITED,
        ),
    })

    victim = replace(
        make_warrior(),
        current_hp=5,
        current_energy=0,
        passive_skills=("self_destruct", "death_reward"),
    )
    enemy = replace(
        make_goblin("e1"),
        current_energy=0,
        passive_skills=("killer_reward",),
    )
    state = make_combat_state(players=[victim], enemies=[enemy])

    state, hits = check_passives(
        state,
        "p1",
        PassiveEvent(trigger=TriggerType.ON_TURN_START),
        rng=SeededRNG(3),
        constants=CONSTANTS,
    )

    assert state.entities["p1"].current_hp == 0
    assert state.entities["p1"].current_energy == 13
    assert state.entities["e1"].current_energy == 0
    assert any(hit.target_id == "p1" and hit.damage is not None for hit in hits)


def test_on_death_spawned_summon_is_removed_with_dead_owner(monkeypatch):
    _patch_passives(monkeypatch, {
        "death_summon": PassiveSkillData(
            skill_id="death_summon",
            name="Death Summon",
            triggers=(TriggerType.ON_DEATH,),
            condition="",
            action=PassiveAction.CAST_SKILL,
            cast_skill_id="summon_familiar",
            expr="0",
            usage_limit=UsageLimit.UNLIMITED,
        ),
    })

    victim = replace(
        make_warrior(),
        current_hp=1,
        current_energy=100,
        skills=("summon_familiar",),
        passive_skills=("death_summon",),
    )
    killer = make_goblin("e1")
    state = make_combat_state(players=[victim], enemies=[killer], turn_order=("e1", "p1"))

    state, _, _ = resolve_skill(
        state,
        "e1",
        load_skill("slash"),
        {0: "p1"},
        SeededRNG(4),
        load_constants(),
    )

    assert state.entities["p1"].current_hp == 0
    assert not any(
        isinstance(entity, SummonEntity) and entity.owner_id == "p1"
        for entity in state.entities.values()
    )
