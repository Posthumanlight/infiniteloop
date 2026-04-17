from dataclasses import replace

import pytest

from game.core.data_loader import clear_cache
from game.core.enums import LevelRewardType
from game.core.game_models import build_reward_key
from game.session.factories import build_player
from game.session.models import PendingReward, PendingRewardQueue
from game.session.session_manager import SessionManager


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_enqueue_level_rewards_uses_ability_for_skill_reward_levels():
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])

    state = mgr._node._enqueue_level_rewards(state, {"p1": [3, 4]})

    entries = state.pending_rewards["p1"].entries
    assert entries[0].reward_type == LevelRewardType.ABILITY
    assert entries[1].reward_type == LevelRewardType.MODIFIER


def test_eligible_ability_keys_use_typed_refs_for_colliding_ids(monkeypatch):
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")

    monkeypatch.setattr(
        mgr._node,
        "_eligible_skill_ids",
        lambda _player: ["arcane_rupture"],
    )
    monkeypatch.setattr(
        mgr._node,
        "_eligible_passive_ids",
        lambda _player: ["arcane_rupture"],
    )

    pool = mgr._node._eligible_ability_keys(player)

    assert pool == [
        "skill:arcane_rupture",
        "passive:arcane_rupture",
    ]


def test_apply_ability_reward_to_player_supports_skills_and_passives():
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")

    updated_skill = mgr._node._apply_reward_to_player(
        player,
        LevelRewardType.ABILITY,
        build_reward_key("skill", "deep_wounds"),
    )
    assert "deep_wounds" in updated_skill.skills

    updated_passive = mgr._node._apply_reward_to_player(
        player,
        LevelRewardType.ABILITY,
        build_reward_key("passive", "arcane_prowess"),
    )
    assert "arcane_prowess" in updated_passive.passive_skills

    with pytest.raises(ValueError, match="Passive already known"):
        mgr._node._apply_reward_to_player(
            player,
            LevelRewardType.ABILITY,
            build_reward_key("passive", "battle_master"),
        )


def test_submit_reward_choice_handles_skill_passive_id_collision():
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])
    state = replace(
        state,
        pending_rewards={
            "p1": PendingRewardQueue(entries=(
                PendingReward(
                    reward_type=LevelRewardType.ABILITY,
                    offer=(
                        "skill:arcane_rupture",
                        "passive:arcane_rupture",
                    ),
                ),
            )),
        },
    )

    state = mgr.submit_reward_choice(state, "p1", "passive:arcane_rupture")

    updated = next(p for p in state.players if p.entity_id == "p1")
    assert "arcane_rupture" in updated.passive_skills
    assert "arcane_rupture" not in updated.skills
