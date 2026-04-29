from types import SimpleNamespace

import numpy as np
import pytest

import agents.train as train


def test_validate_training_ready_calls_catalog_loaders(monkeypatch):
    calls: list[str] = []

    for name in (
        "clear_cache",
        "load_enemies",
        "load_skills",
        "load_events",
        "load_combat_locations",
    ):
        monkeypatch.setattr(
            train.data_loader,
            name,
            lambda name=name: calls.append(name),
        )
    monkeypatch.setattr(
        train,
        "build_run_observation_spec",
        lambda: SimpleNamespace(vector_size=10),
    )
    monkeypatch.setattr(
        train,
        "build_run_action_space_spec",
        lambda _spec: SimpleNamespace(action_count=5),
    )

    train.validate_training_ready()

    assert calls == [
        "clear_cache",
        "load_enemies",
        "load_skills",
        "load_events",
        "load_combat_locations",
    ]


def test_validate_training_ready_preserves_loader_failure(monkeypatch):
    monkeypatch.setattr(train.data_loader, "clear_cache", lambda: None)
    monkeypatch.setattr(train.data_loader, "load_enemies", lambda: None)
    monkeypatch.setattr(train.data_loader, "load_skills", lambda: None)

    def fail_events():
        raise ValueError("broken events")

    monkeypatch.setattr(train.data_loader, "load_events", fail_events)

    with pytest.raises(ValueError, match="broken events"):
        train.validate_training_ready()


def test_smoke_rollout_uses_valid_masks_and_resets_on_terminal():
    class FakeEnv:
        def __init__(self):
            self.np_random = np.random.default_rng(1)
            self.reset_count = 0
            self.actions = []

        def reset(self, seed=None):
            self.reset_count += 1
            return np.zeros(2), {}

        def action_masks(self):
            return np.asarray([False, True, False])

        def step(self, action):
            self.actions.append(action)
            terminated = len(self.actions) == 2
            return np.zeros(2), 0.0, terminated, False, {}

    env = FakeEnv()

    train.smoke_rollout(env, 3)

    assert env.actions == [1, 1, 1]
    assert env.reset_count == 2


def test_smoke_rollout_fails_when_no_action_is_valid():
    class NoActionEnv:
        np_random = np.random.default_rng(1)

        def reset(self, seed=None):
            return np.zeros(2), {}

        def action_masks(self):
            return np.asarray([False, False])

    with pytest.raises(RuntimeError, match="No valid action mask"):
        train.smoke_rollout(NoActionEnv(), 1)
