from dataclasses import replace

import pytest

from game.combat.skill_modifiers import add_modifier
from game.core.data_loader import clear_cache
from game.core.enums import OutcomeAction
from game.events.models import OutcomeResult
from game.session.factories import build_player
from game.session.models import ModifierRewardNotice, PendingModifierChoice
from game.session.session_manager import SessionManager
from game.world.models import GenerationConfig


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


PREDETERMINED_CONFIG = GenerationConfig(predetermined_set_id="dark_cave_intro")


def test_modifier_eligibility_uses_skill_or_class_or_global():
    mgr = SessionManager(seed=42)
    warrior = build_player("warrior", "p1")
    mage = build_player("mage", "p2")

    warrior_eligible = mgr._node._eligible_modifier_ids(warrior)
    assert "slash_power" in warrior_eligible
    assert "warrior_training" in warrior_eligible
    assert "battle_hardened" in warrior_eligible
    assert "arcane_bolt_power" not in warrior_eligible

    mage_eligible = mgr._node._eligible_modifier_ids(mage)
    assert "arcane_bolt_power" in mage_eligible
    assert "battle_hardened" in mage_eligible
    assert "warrior_training" not in mage_eligible


def test_non_stackable_owned_modifier_is_not_eligible():
    mgr = SessionManager(seed=42)
    warrior = build_player("warrior", "p1")
    warrior = add_modifier(warrior, "fire_brand")

    eligible = mgr._node._eligible_modifier_ids(warrior)
    assert "fire_brand" not in eligible
    assert "slash_power" in eligible


def test_level_ups_enqueue_pending_modifier_picks():
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])

    outcome = OutcomeResult(
        player_id="p1",
        action=OutcomeAction.GIVE_XP,
        amount=300,
    )
    state = mgr._node._apply_event_outcomes(state, (outcome,))

    pending = state.pending_modifier_choices["p1"]
    assert pending.pending_count == 3
    assert pending.current_offer == ()


def test_prepare_modifier_choices_caps_offer_to_two(monkeypatch):
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])
    state = replace(
        state,
        pending_modifier_choices={"p1": PendingModifierChoice(pending_count=1)},
    )

    monkeypatch.setattr(
        mgr._node,
        "_eligible_modifier_ids",
        lambda _player: ["a", "b", "c"],
    )

    state = mgr._node.prepare_modifier_choices(state)
    offer = state.pending_modifier_choices["p1"].current_offer
    assert len(offer) == 2
    assert len(set(offer)) == 2


def test_prepare_modifier_choices_uses_single_option_when_pool_is_one(monkeypatch):
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])
    state = replace(
        state,
        pending_modifier_choices={"p1": PendingModifierChoice(pending_count=1)},
    )

    monkeypatch.setattr(
        mgr._node,
        "_eligible_modifier_ids",
        lambda _player: ["only_one"],
    )

    state = mgr._node.prepare_modifier_choices(state)
    assert state.pending_modifier_choices["p1"].current_offer == ("only_one",)


def test_prepare_modifier_choices_skips_when_no_eligible(monkeypatch):
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])
    state = replace(
        state,
        pending_modifier_choices={"p1": PendingModifierChoice(pending_count=1)},
    )

    monkeypatch.setattr(
        mgr._node,
        "_eligible_modifier_ids",
        lambda _player: [],
    )

    state = mgr._node.prepare_modifier_choices(state)
    assert "p1" not in state.pending_modifier_choices
    assert len(state.modifier_reward_notices) == 1
    assert state.modifier_reward_notices[0].player_id == "p1"
    assert state.modifier_reward_notices[0].skipped_count == 1


def test_pending_modifier_blocks_only_that_players_vote():
    mgr = SessionManager(seed=42)
    p1 = build_player("warrior", "p1")
    p2 = build_player("warrior", "p2")
    state = mgr.start_run("test-session", [p1, p2])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)
    state = replace(
        state,
        pending_modifier_choices={"p1": PendingModifierChoice(pending_count=1)},
    )

    state = mgr.submit_location_vote(state, "p2", 0)
    assert len(state.exploration.votes) == 1

    with pytest.raises(ValueError, match="level-up modifier"):
        mgr.submit_location_vote(state, "p1", 0)


def test_submit_modifier_choice_applies_modifier_and_clears_pending():
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)
    state = replace(
        state,
        pending_modifier_choices={
            "p1": PendingModifierChoice(
                pending_count=1,
                current_offer=("slash_power", "battle_hardened"),
            ),
        },
    )

    state = mgr.submit_modifier_choice(state, "p1", "slash_power")
    updated = next(p for p in state.players if p.entity_id == "p1")
    assert any(mod.modifier_id == "slash_power" for mod in updated.skill_modifiers)
    assert "p1" not in state.pending_modifier_choices


def test_submit_modifier_choice_rejects_modifier_not_in_offer():
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])
    state = mgr.generate_choices(state, PREDETERMINED_CONFIG)
    state = replace(
        state,
        pending_modifier_choices={
            "p1": PendingModifierChoice(
                pending_count=1,
                current_offer=("slash_power", "battle_hardened"),
            ),
        },
    )

    with pytest.raises(ValueError, match="current offer"):
        mgr.submit_modifier_choice(state, "p1", "arcane_bolt_power")


def test_consume_modifier_notices_clears_state():
    mgr = SessionManager(seed=42)
    player = build_player("warrior", "p1")
    state = mgr.start_run("test-session", [player])
    state = replace(
        state,
        modifier_reward_notices=(
            ModifierRewardNotice(player_id="p1", skipped_count=2),
            ModifierRewardNotice(player_id="p1", skipped_count=1),
        ),
    )

    state, notices = mgr.consume_modifier_notices(state)
    assert len(notices) == 2
    assert notices[0].player_id == "p1"
    assert state.modifier_reward_notices == ()
