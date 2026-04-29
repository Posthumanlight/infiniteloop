from dataclasses import replace
import asyncio
from types import SimpleNamespace

import numpy as np
import pytest

import agents.env as env_module
from agents.action_space import (
    build_run_action_mask,
    build_run_action_space_spec,
    decode_run_action,
)
from agents.env import (
    EnvPlayerConfig,
    InfiniteloopEnvConfig,
    InfiniteloopRunEnv,
    TrainingCharacterRepository,
)
from agents.observation import (
    DECISION_TYPE_IDS,
    ObservationCatalog,
    RunObservationCatalog,
    RunObservationSpec,
    SESSION_PHASE_IDS,
    build_observation_spec,
    build_run_observation,
    build_run_observation_spec,
)
from game.core.data_loader import LocationOption
from game.core.enums import (
    EventPhase,
    EventType,
    ExplorationPhase,
    LevelRewardType,
    LocationType,
    SessionEndReason,
    SessionPhase,
)
from game.events.models import ChoiceDef, EventDef, EventStageDef, EventState
from game.session.models import PendingReward, PendingRewardQueue, RunStats, SessionState
from game.world.models import ExplorationState

from tests.unit.conftest import make_warrior


def _run_spec() -> RunObservationSpec:
    combat_spec = build_observation_spec(
        catalog=ObservationCatalog(
            skill_ids=("slash",),
            effect_ids=(),
            passive_ids=("battle_master",),
            class_ids=("warrior",),
            enemy_ids=("goblin",),
            summon_ids=(),
            location_ids=("test_location",),
            location_status_ids=("dim_light",),
        ),
        max_team_slots=0,
        max_enemy_slots=1,
        max_effect_slots=1,
    )
    return build_run_observation_spec(
        combat_spec=combat_spec,
        catalog=RunObservationCatalog(
            combat=combat_spec.catalog,
            modifier_ids=("slash_power",),
            event_ids=("test_event",),
            event_stage_ids=("test_event:start",),
            location_tag_ids=("forest",),
        ),
        max_location_choices=2,
        max_event_choices=2,
        max_reward_choices=2,
    )


def _player():
    return replace(
        make_warrior("1"),
        skills=("slash",),
        passive_skills=("battle_master",),
    )


def _location_option(index: int = 0) -> LocationOption:
    return LocationOption(
        location_id=f"loc_{index}",
        name=f"Location {index}",
        location_type=LocationType.COMBAT,
        tags=("forest",),
        enemy_ids=("goblin",),
        status_ids=("dim_light",),
    )


def _exploring_session(**kwargs) -> SessionState:
    defaults = {
        "session_id": "sid",
        "players": (_player(),),
        "phase": SessionPhase.EXPLORING,
        "exploration": ExplorationState(
            session_id="sid",
            depth=1,
            phase=ExplorationPhase.CHOOSING,
            player_ids=("1",),
            current_options=(_location_option(0), _location_option(1)),
        ),
    }
    defaults.update(kwargs)
    return SessionState(**defaults)


def _event_state() -> EventState:
    event_def = EventDef(
        event_id="test_event",
        name="Test Event",
        event_type=EventType.MULTIPLAYER,
        initial_stage_id="start",
        stages={
            "start": EventStageDef(
                stage_id="start",
                title="Start",
                description="Choose",
                choices=(
                    ChoiceDef(index=0, label="A", description="A"),
                    ChoiceDef(index=1, label="B", description="B"),
                ),
            ),
        },
    )
    return EventState(
        event_id="runtime-event",
        session_id="sid",
        event_def=event_def,
        phase=EventPhase.PRESENTING,
        player_ids=("1",),
        current_stage_id="start",
    )


def _reward_session() -> SessionState:
    return _exploring_session(
        pending_rewards={
            "1": PendingRewardQueue(
                entries=(
                    PendingReward(
                        reward_type=LevelRewardType.MODIFIER,
                        offer=("modifier:slash_power",),
                    ),
                ),
            ),
        },
    )


def _unrolled_reward_session() -> SessionState:
    return _exploring_session(
        pending_rewards={
            "1": PendingRewardQueue(
                entries=(PendingReward(reward_type=LevelRewardType.MODIFIER),),
            ),
        },
    )


def test_run_observation_shape_and_decision_type_for_exploration():
    spec = _run_spec()
    obs = build_run_observation(_exploring_session(), "1", spec)
    decision_start = (
        spec.slices["run_global"].start
        + 12
        + len(SESSION_PHASE_IDS)
    )

    assert obs.dtype == np.float32
    assert obs.shape == (spec.vector_size,)
    assert obs[spec.slices["locations"].start] == 1.0
    assert obs[decision_start + DECISION_TYPE_IDS.index("location")] == 1.0


def test_run_action_mask_prioritizes_rewards_over_location_choices():
    spec = build_run_action_space_spec(_run_spec())
    mask = build_run_action_mask(_reward_session(), "1", spec)

    assert mask.sum() == 1
    assert mask[spec.reward_offset]
    assert not mask[spec.location_offset]


def test_unrolled_pending_reward_blocks_location_choices():
    spec = build_run_action_space_spec(_run_spec())
    mask = build_run_action_mask(_unrolled_reward_session(), "1", spec)

    assert not mask.any()


def test_resolved_exploration_options_do_not_enable_location_choices():
    spec = build_run_action_space_spec(_run_spec())
    state = _exploring_session(
        exploration=ExplorationState(
            session_id="sid",
            depth=1,
            phase=ExplorationPhase.RESOLVING,
            player_ids=("1",),
            current_options=(_location_option(0),),
        ),
    )
    mask = build_run_action_mask(state, "1", spec)

    assert not mask.any()


def test_run_action_mask_and_decode_for_location_and_event():
    spec = build_run_action_space_spec(_run_spec())
    location_mask = build_run_action_mask(_exploring_session(), "1", spec)
    event_session = _exploring_session(
        phase=SessionPhase.IN_EVENT,
        exploration=None,
        event=_event_state(),
    )
    event_mask = build_run_action_mask(event_session, "1", spec)

    assert location_mask[spec.location_offset]
    assert location_mask[spec.location_offset + 1]
    assert decode_run_action(spec.location_offset + 1, spec).kind == "location"
    assert decode_run_action(spec.location_offset + 1, spec).choice_index == 1
    assert event_mask[spec.event_offset]
    assert event_mask[spec.event_offset + 1]
    assert decode_run_action(spec.event_offset, spec).kind == "event"


def test_env_reset_step_and_terminal_save(monkeypatch):
    pytest.importorskip("gymnasium")
    spec = _run_spec()
    player = _player()

    class FakeLobby:
        def __init__(self, repo):
            self.repo = repo
            self.state = None
            self.closed = False

        def set_view_builder(self, _builder):
            return None

        async def create_lobby(self, session_id, tg_user_id, display_name):
            self.session_id = session_id
            self.tg_user_id = tg_user_id
            self.display_name = display_name

        def choose_saved_character(self, session_id, tg_user_id, character_id):
            self.character_id = character_id

        async def launch_run(self, session_id):
            self.state = _exploring_session()

        def get_active_session(self, session_id):
            return SimpleNamespace(state=self.state)

        def has_active_session(self, session_id):
            return self.state is not None and not self.closed

        def has_lobby(self, session_id):
            return False

        def close_session(self, session_id):
            self.closed = True

    class FakeGame:
        def __init__(self, sessions):
            self.sessions = sessions
            self.location_votes = []

        def consume_pending_loot(self, session_id):
            return None

        def consume_reward_notices(self, session_id):
            return ()

        def submit_location_vote(self, session_id, player_id, location_index):
            self.location_votes.append((player_id, location_index))

        def resolve_location_choice(self, session_id):
            self.sessions.state = replace(
                self.sessions.state,
                phase=SessionPhase.ENDED,
                end_reason=SessionEndReason.MAX_DEPTH,
                run_stats=RunStats(rooms_explored=1),
            )
            return SessionPhase.ENDED

        def continue_exploration(self, session_id):
            return None

    monkeypatch.setattr(env_module, "LobbyService", FakeLobby)
    monkeypatch.setattr(env_module, "GameService", FakeGame)
    monkeypatch.setattr(env_module, "build_player", lambda *_args, **_kwargs: player)

    config = InfiniteloopEnvConfig(
        player=EnvPlayerConfig(character_id=1, tg_user_id=1),
        max_env_steps=5,
    )
    training_env = InfiniteloopRunEnv(config=config, obs_spec=spec)
    obs, info = training_env.reset(seed=123)

    assert obs.shape == (spec.vector_size,)
    assert info["phase"] == SessionPhase.EXPLORING.value
    assert training_env.action_masks()[training_env.action_spec.location_offset]
    assert training_env.sample_valid_action() in {
        training_env.action_spec.location_offset,
        training_env.action_spec.location_offset + 1,
    }

    obs, reward, terminated, truncated, info = training_env.step(
        training_env.action_spec.location_offset,
    )

    assert terminated is True
    assert truncated is False
    assert reward == pytest.approx(info["reward_total"])
    assert training_env.repository.saved_progress[-1]["character_id"] == 1


def test_training_repository_snapshot_and_restore(monkeypatch):
    player = _player()
    monkeypatch.setattr(env_module, "build_player", lambda *_args, **_kwargs: player)
    config = EnvPlayerConfig(character_id=7, tg_user_id=77, character_name="Agent")
    repo = TrainingCharacterRepository()
    repo.ensure_saved_character(config)
    snapshot = repo.snapshot()

    asyncio.run(repo.save_character_progress(
        character_id=7,
        character_name="Mutated",
        class_id="warrior",
        level=5,
        xp=123,
        skills=("slash",),
        passive_skills=("battle_master",),
        skill_modifiers=(),
        inventory=player.inventory,
        flags={},
    ))

    restored = TrainingCharacterRepository()
    restored.restore(snapshot)
    record = asyncio.run(restored.get_character(7))

    assert record.character_name == "Agent"
    assert record.level == player.level
    assert restored.saved_progress == []
