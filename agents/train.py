from __future__ import annotations

import json
import pickle
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agents.action_space import build_run_action_space_spec
from agents.env import (
    InfiniteloopEnvConfig,
    InfiniteloopRunEnv,
    TrainingCharacterRepository,
    TrainingRepositorySnapshot,
)
from agents.observation import build_run_observation_spec
from game.core import data_loader

try:
    from sb3_contrib import MaskablePPO
    from sb3_contrib.common.maskable.callbacks import MaskableEvalCallback
    from sb3_contrib.common.maskable.utils import is_masking_supported
    from stable_baselines3.common.callbacks import BaseCallback, CallbackList, CheckpointCallback
    from stable_baselines3.common.monitor import Monitor
    from stable_baselines3.common.vec_env import DummyVecEnv, VecMonitor
except ModuleNotFoundError:  # pragma: no cover - Poetry training deps
    MaskablePPO = None
    MaskableEvalCallback = None
    is_masking_supported = None
    BaseCallback = None
    CallbackList = None
    CheckpointCallback = None
    Monitor = None
    DummyVecEnv = None
    VecMonitor = None


TOTAL_TIMESTEPS = 10_000
SEED = 7
ARTIFACT_ROOT = Path("agents/runs")
MAX_ENV_STEPS = 500
CHECKPOINT_FREQ = 2_000
EVAL_FREQ = 2_000
N_EVAL_EPISODES = 3
SMOKE_STEPS = 50
RESUME_MODEL_PATH: Path | None = None
RESUME_STATE_PATH: Path | None = None


def validate_training_ready() -> None:
    data_loader.clear_cache()
    data_loader.load_enemies()
    data_loader.load_skills()
    data_loader.load_events()
    data_loader.load_combat_locations()
    spec = build_run_observation_spec()
    action_spec = build_run_action_space_spec(spec)
    if spec.vector_size <= 0:
        raise RuntimeError("Run observation spec has no features")
    if action_spec.action_count <= 0:
        raise RuntimeError("Run action space has no actions")


def save_env_state(
    repo: TrainingCharacterRepository,
    path: Path,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as file:
        pickle.dump(repo.snapshot(), file)


def load_env_state(path: Path) -> TrainingCharacterRepository:
    with path.open("rb") as file:
        snapshot = pickle.load(file)
    if not isinstance(snapshot, TrainingRepositorySnapshot):
        raise TypeError(f"Unexpected env state payload: {type(snapshot)!r}")
    repo = TrainingCharacterRepository()
    repo.restore(snapshot)
    return repo


def smoke_rollout(env: InfiniteloopRunEnv, steps: int) -> None:
    env.reset(seed=SEED)
    for _ in range(steps):
        mask = env.action_masks()
        if not mask.any():
            raise RuntimeError("No valid action mask during smoke rollout")
        action = int(env.np_random.choice(np.flatnonzero(mask)))
        _obs, _reward, terminated, truncated, _info = env.step(action)
        if terminated or truncated:
            env.reset()


def _require_training_deps() -> None:
    missing = [
        name
        for name, value in {
            "sb3-contrib": MaskablePPO,
            "stable-baselines3": BaseCallback,
        }.items()
        if value is None
    ]
    if missing:
        raise ModuleNotFoundError(
            "Training dependencies are missing. Run through Poetry, for example: "
            "`poetry run python agents/train.py`.",
        )


if BaseCallback is not None:

    class EnvStateCheckpointCallback(BaseCallback):
        def __init__(
            self,
            repo: TrainingCharacterRepository,
            checkpoint_dir: Path,
            save_freq: int,
            verbose: int = 0,
        ) -> None:
            super().__init__(verbose=verbose)
            self.repo = repo
            self.checkpoint_dir = checkpoint_dir
            self.save_freq = save_freq

        def _on_step(self) -> bool:
            if self.n_calls % self.save_freq == 0:
                save_env_state(
                    self.repo,
                    self.checkpoint_dir / f"env_state_{self.num_timesteps}.pkl",
                )
            return True

else:

    class EnvStateCheckpointCallback:  # pragma: no cover - dependency guard
        def __init__(self, *_args, **_kwargs) -> None:
            _require_training_deps()


def make_env(seed: int, repo: TrainingCharacterRepository):
    _require_training_deps()

    def _factory():
        env = InfiniteloopRunEnv(
            InfiniteloopEnvConfig(max_env_steps=MAX_ENV_STEPS),
            repository=repo,
        )
        env.reset(seed=seed)
        return Monitor(env)

    return _factory


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _metadata(run_dir: Path, env_config: InfiniteloopEnvConfig) -> dict[str, Any]:
    return {
        "run_dir": str(run_dir),
        "total_timesteps": TOTAL_TIMESTEPS,
        "seed": SEED,
        "max_env_steps": env_config.max_env_steps,
        "checkpoint_freq": CHECKPOINT_FREQ,
        "eval_freq": EVAL_FREQ,
        "n_eval_episodes": N_EVAL_EPISODES,
        "smoke_steps": SMOKE_STEPS,
        "resume_model_path": str(RESUME_MODEL_PATH) if RESUME_MODEL_PATH else None,
        "resume_state_path": str(RESUME_STATE_PATH) if RESUME_STATE_PATH else None,
    }


def _write_metadata(run_dir: Path, env_config: InfiniteloopEnvConfig) -> None:
    with (run_dir / "metadata.json").open("w", encoding="utf-8") as file:
        json.dump(_metadata(run_dir, env_config), file, indent=2)


def main() -> None:
    _require_training_deps()
    validate_training_ready()

    run_dir = ARTIFACT_ROOT / _timestamp()
    checkpoint_dir = run_dir / "checkpoints"
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    env_config = InfiniteloopEnvConfig(max_env_steps=MAX_ENV_STEPS)
    _write_metadata(run_dir, env_config)

    train_repo = (
        load_env_state(RESUME_STATE_PATH)
        if RESUME_STATE_PATH is not None
        else TrainingCharacterRepository()
    )
    eval_repo = TrainingCharacterRepository()

    smoke_env = InfiniteloopRunEnv(env_config, repository=train_repo)
    smoke_rollout(smoke_env, SMOKE_STEPS)
    smoke_env.close()

    train_env = DummyVecEnv([make_env(SEED, train_repo)])
    train_env = VecMonitor(train_env)
    eval_env = DummyVecEnv([make_env(SEED + 1, eval_repo)])
    eval_env = VecMonitor(eval_env)

    if not is_masking_supported(train_env):
        raise RuntimeError("Training env does not expose action_masks()")
    if not is_masking_supported(eval_env):
        raise RuntimeError("Eval env does not expose action_masks()")

    if RESUME_MODEL_PATH is not None:
        model = MaskablePPO.load(
            str(RESUME_MODEL_PATH),
            env=train_env,
            tensorboard_log=str(run_dir / "tensorboard"),
            device="auto",
        )
    else:
        model = MaskablePPO(
            "MlpPolicy",
            train_env,
            learning_rate=3e-4,
            n_steps=512,
            batch_size=64,
            gamma=0.99,
            gae_lambda=0.95,
            ent_coef=0.01,
            clip_range=0.2,
            vf_coef=0.5,
            max_grad_norm=0.5,
            verbose=1,
            seed=SEED,
            tensorboard_log=str(run_dir / "tensorboard"),
            device="auto",
        )

    callbacks = CallbackList([
        CheckpointCallback(
            save_freq=CHECKPOINT_FREQ,
            save_path=str(checkpoint_dir),
            name_prefix="model",
        ),
        EnvStateCheckpointCallback(
            train_repo,
            checkpoint_dir,
            CHECKPOINT_FREQ,
        ),
        MaskableEvalCallback(
            eval_env,
            best_model_save_path=str(run_dir / "best_model"),
            log_path=str(run_dir / "eval"),
            eval_freq=EVAL_FREQ,
            n_eval_episodes=N_EVAL_EPISODES,
            deterministic=True,
            render=False,
        ),
    ])

    model.learn(
        total_timesteps=TOTAL_TIMESTEPS,
        callback=callbacks,
        progress_bar=False,
    )
    model.save(str(run_dir / "model_final"))
    save_env_state(train_repo, run_dir / "env_state_final.pkl")
    train_env.close()
    eval_env.close()


if __name__ == "__main__":
    main()
