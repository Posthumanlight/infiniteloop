from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
try:
    import gymnasium as gym
except ModuleNotFoundError:  # pragma: no cover - depends on local training deps
    gym = None

from agents.action_space import (
    RunAction,
    RunActionSpaceSpec,
    action_index_to_request,
    build_run_action_mask,
    build_run_action_space,
    build_run_action_space_spec,
    decode_run_action,
)
from agents.observation import (
    RunObservationSpec,
    build_run_observation,
    build_run_observation_space,
    build_run_observation_spec,
)
from agents.reward import RewardConfig, calculate_reward
from game.character.flags import CharacterFlag
from game.character.inventory import Inventory
from game.combat.skill_modifiers import ModifierInstance
from game.combat.targeting import is_ai_controlled
from game.core.enums import ExplorationPhase, SessionEndReason, SessionPhase
from game.session.factories import build_player
from game.session.lobby_manager import (
    CharacterRecord,
    CharacterRepository,
    SavedCharacterSummary,
)
from game.session.models import SessionState
from game_service import GameService
from lobby_service import LobbyService


_EnvBase = gym.Env if gym is not None else object


@dataclass(frozen=True)
class EnvPlayerConfig:
    tg_user_id: int = 1
    display_name: str = "Agent"
    class_id: str = "warrior"
    character_id: int = 1
    character_name: str = "Training Agent"


@dataclass(frozen=True)
class InfiniteloopEnvConfig:
    player: EnvPlayerConfig = field(default_factory=EnvPlayerConfig)
    max_env_steps: int = 500
    reward_config: RewardConfig = field(default_factory=RewardConfig)


@dataclass(frozen=True)
class TrainingRepositorySnapshot:
    records: dict[int, CharacterRecord]


class TrainingCharacterRepository(CharacterRepository):
    """In-memory saved-character store for training episodes."""

    def __init__(self) -> None:
        self._records: dict[int, CharacterRecord] = {}
        self.saved_progress: list[dict[str, Any]] = []
        self.created_characters: list[CharacterRecord] = []

    def snapshot(self) -> TrainingRepositorySnapshot:
        return TrainingRepositorySnapshot(records=copy.deepcopy(self._records))

    def restore(self, snapshot: TrainingRepositorySnapshot) -> None:
        self._records = copy.deepcopy(snapshot.records)
        self.saved_progress.clear()
        self.created_characters.clear()

    def ensure_saved_character(self, config: EnvPlayerConfig) -> None:
        if config.character_id in self._records:
            return
        player = build_player(
            config.class_id,
            entity_id=str(config.character_id),
        )
        self._records[config.character_id] = CharacterRecord(
            character_id=config.character_id,
            tg_id=config.tg_user_id,
            character_name=config.character_name,
            class_id=player.player_class,
            level=player.level,
            xp=player.xp,
            skills=player.skills,
            passive_skills=player.passive_skills,
            skill_modifiers=player.skill_modifiers,
            inventory=player.inventory,
            flags=dict(player.flags),
        )

    async def get_user_characters(self, tg_id: int) -> list[SavedCharacterSummary]:
        return [
            SavedCharacterSummary(
                character_id=record.character_id,
                character_name=record.character_name,
                class_id=record.class_id,
                level=record.level,
                xp=record.xp,
            )
            for record in self._records.values()
            if record.tg_id == tg_id
        ]

    async def get_character(self, character_id: int) -> CharacterRecord:
        try:
            return self._records[character_id]
        except KeyError as exc:
            raise ValueError(f"Unknown training character: {character_id}") from exc

    async def create_saved_character(
        self,
        tg_id: int,
        character_name: str,
        class_id: str,
        skills: tuple[str, ...],
        passive_skills: tuple[str, ...] = (),
        level: int = 1,
        xp: int = 0,
        skill_modifiers: tuple[ModifierInstance, ...] = (),
        inventory: Inventory | None = None,
        flags: dict[str, CharacterFlag] | None = None,
    ) -> CharacterRecord:
        character_id = max(self._records, default=0) + 1
        record = CharacterRecord(
            character_id=character_id,
            tg_id=tg_id,
            character_name=character_name,
            class_id=class_id,
            level=level,
            xp=xp,
            skills=skills,
            passive_skills=passive_skills,
            skill_modifiers=skill_modifiers,
            inventory=inventory or Inventory(),
            flags=dict(flags or {}),
        )
        self._records[character_id] = record
        self.created_characters.append(record)
        return record

    async def character_name_exists(
        self,
        character_name: str,
        exclude_character_id: int | None = None,
    ) -> bool:
        normalized_name = character_name.strip().casefold()
        return any(
            record.character_id != exclude_character_id
            and (record.character_name or "").strip().casefold() == normalized_name
            for record in self._records.values()
        )

    async def save_character_progress(
        self,
        character_id: int,
        character_name: str,
        class_id: str | None,
        level: int,
        xp: int,
        skills: tuple[str, ...],
        passive_skills: tuple[str, ...],
        skill_modifiers: tuple[ModifierInstance, ...],
        inventory: Inventory | None = None,
        flags: dict[str, CharacterFlag] | None = None,
    ) -> None:
        existing = await self.get_character(character_id)
        updated = replace(
            existing,
            character_name=character_name,
            class_id=class_id or existing.class_id,
            level=level,
            xp=xp,
            skills=skills,
            passive_skills=passive_skills,
            skill_modifiers=skill_modifiers,
            inventory=inventory or Inventory(),
            flags=dict(flags or {}),
        )
        self._records[character_id] = updated
        self.saved_progress.append({
            "character_id": character_id,
            "character_name": character_name,
            "class_id": class_id,
            "level": level,
            "xp": xp,
            "skills": skills,
            "passive_skills": passive_skills,
            "skill_modifiers": skill_modifiers,
            "inventory": inventory,
            "flags": flags,
        })


class InfiniteloopRunEnv(_EnvBase):
    metadata = {"render_modes": []}

    def __init__(
        self,
        config: InfiniteloopEnvConfig = InfiniteloopEnvConfig(),
        *,
        obs_spec: RunObservationSpec | None = None,
        repository: TrainingCharacterRepository | None = None,
    ) -> None:
        if gym is None:
            raise ModuleNotFoundError("gymnasium is required to build the env")
        super().__init__()
        self.config = config
        self.obs_spec = obs_spec or build_run_observation_spec()
        self.action_spec = build_run_action_space_spec(self.obs_spec)
        self.observation_space = build_run_observation_space(self.obs_spec)
        self.action_space = build_run_action_space(self.action_spec)
        self._repo = repository or TrainingCharacterRepository()
        self._episode_index = 0
        self._step_count = 0
        self._session_id: str | None = None
        self._actor_id = str(config.player.character_id)
        self._terminal_persisted = False
        self.lobby: LobbyService | None = None
        self.game: GameService | None = None

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ):
        super().reset(seed=seed)
        self._close_active_session()
        self._episode_index += 1
        self._step_count = 0
        self._terminal_persisted = False
        seed_part = 0 if seed is None else seed
        self._session_id = f"ppo:{self._episode_index}:{seed_part}"
        self._actor_id = str(self.config.player.character_id)

        self._repo.ensure_saved_character(self.config.player)
        self.lobby = LobbyService(self._repo)
        self.game = GameService(sessions=self.lobby)
        self.lobby.set_view_builder(self.game)

        self._run_async(self.lobby.create_lobby(
            self._session_id,
            self.config.player.tg_user_id,
            self.config.player.display_name,
        ))
        self.lobby.choose_saved_character(
            self._session_id,
            self.config.player.tg_user_id,
            self.config.player.character_id,
        )
        self._run_async(self.lobby.launch_run(self._session_id))

        self._advance_non_decisions()
        return self._obs(), self._info()

    def step(self, action_index: int):
        self._require_active()
        before = copy.deepcopy(self._state())
        mask = self.action_masks()
        if action_index < 0 or action_index >= self.action_spec.action_count:
            raise ValueError(f"Run action index out of range: {action_index}")
        if not mask[int(action_index)]:
            raise ValueError(f"Action index is not valid now: {action_index}")

        action = decode_run_action(int(action_index), self.action_spec)
        self._submit_action(action)
        self._step_count += 1
        self._advance_non_decisions()

        after = self._state()
        reward = calculate_reward(
            before,
            after,
            self._actor_id,
            self.config.reward_config,
        )
        terminated = after.phase == SessionPhase.ENDED
        truncated = self._step_count >= self.config.max_env_steps
        if terminated:
            self._persist_terminal_progress(after)

        info = self._info()
        info["reward"] = reward.components
        info["reward_total"] = reward.total
        info["is_alive"] = reward.is_alive
        info["average_damage_per_round"] = reward.average_damage_per_round
        info["difficulty_modifier"] = reward.difficulty_modifier
        return self._obs(), reward.total, terminated, truncated, info

    def action_masks(self) -> np.ndarray:
        if self._session_id is None or self.lobby is None:
            return np.zeros(self.action_spec.action_count, dtype=bool)
        return build_run_action_mask(
            self._state(),
            self._actor_id,
            self.action_spec,
        )

    def sample_valid_action(self) -> int:
        mask = self.action_masks()
        valid = np.flatnonzero(mask)
        if len(valid) == 0:
            raise ValueError("No valid actions are available")
        return int(self.np_random.choice(valid))

    def close(self) -> None:
        self._close_active_session()

    @property
    def repository(self) -> TrainingCharacterRepository:
        return self._repo

    @property
    def session_id(self) -> str | None:
        return self._session_id

    @property
    def actor_id(self) -> str:
        return self._actor_id

    def _submit_action(self, action: RunAction) -> None:
        game = self._require_game()
        session_id = self._require_session_id()
        state = self._state()

        if action.kind == "combat":
            if state.combat is None:
                raise ValueError("Combat action submitted outside combat")
            request = action_index_to_request(
                action.action_index,
                state.combat,
                self._actor_id,
                self.obs_spec.combat,
                self.action_spec.combat,
            )
            game.submit_player_action(session_id, request)
            return

        if action.kind == "location":
            game.submit_location_vote(session_id, self._actor_id, action.choice_index)
            game.resolve_location_choice(session_id)
            return

        if action.kind == "event":
            game.submit_event_vote(session_id, self._actor_id, action.choice_index)
            game.resolve_event(session_id)
            return

        if action.kind == "reward":
            reward_key = self._current_reward_key(action.choice_index)
            game.submit_reward_choice(session_id, self._actor_id, reward_key)
            return

        raise ValueError(f"Unknown run action kind: {action.kind}")

    def _advance_non_decisions(self) -> None:
        game = self._require_game()
        session_id = self._require_session_id()

        while True:
            state = self._state()
            game.consume_pending_loot(session_id)
            game.consume_reward_notices(session_id)

            if state.phase == SessionPhase.ENDED:
                return

            if self.action_masks().any():
                return

            state = self._state()
            if state.phase == SessionPhase.EXPLORING:
                queue = state.pending_rewards.get(self._actor_id)
                if queue is not None and queue.pending_count > 0 and not queue.current_offer:
                    game.continue_exploration(session_id)
                    continue
                if (
                    state.exploration is None
                    or state.exploration.phase != ExplorationPhase.CHOOSING
                    or not state.exploration.current_options
                ):
                    game.continue_exploration(session_id)
                    continue
                return

            if state.phase == SessionPhase.IN_COMBAT and state.combat is not None:
                current_id = self._current_turn_id(state)
                if current_id == self._actor_id:
                    game.skip_player_turn(session_id, self._actor_id)
                    continue
                entity = state.combat.entities.get(current_id)
                if entity is not None and is_ai_controlled(entity):
                    session = self._require_lobby().get_active_session(session_id)
                    game._auto_play_ai_entities(session)
                    continue
                return

            return

    def _current_reward_key(self, choice_index: int) -> str:
        queue = self._state().pending_rewards.get(self._actor_id)
        if queue is None or not queue.current_offer:
            raise ValueError("No pending reward offer")
        try:
            return queue.current_offer[choice_index]
        except IndexError as exc:
            raise ValueError(f"Reward choice out of range: {choice_index}") from exc

    def _persist_terminal_progress(self, state: SessionState) -> None:
        if self._terminal_persisted:
            return
        if state.end_reason not in {
            SessionEndReason.MAX_DEPTH,
            SessionEndReason.PARTY_WIPED,
            SessionEndReason.RETREAT,
        }:
            return
        player = next(
            (candidate for candidate in state.players if candidate.entity_id == self._actor_id),
            None,
        )
        if player is None:
            return
        self._run_async(self._repo.save_character_progress(
            character_id=self.config.player.character_id,
            character_name=self.config.player.character_name,
            class_id=player.player_class,
            level=player.level,
            xp=player.xp,
            skills=player.skills,
            passive_skills=player.passive_skills,
            skill_modifiers=player.skill_modifiers,
            inventory=player.inventory,
            flags=player.flags,
        ))
        self._terminal_persisted = True

    def _obs(self) -> np.ndarray:
        return build_run_observation(self._state(), self._actor_id, self.obs_spec)

    def _info(self) -> dict[str, Any]:
        state = self._state()
        return {
            "session_id": self._session_id,
            "actor_id": self._actor_id,
            "phase": state.phase.value,
            "end_reason": state.end_reason.value if state.end_reason else None,
            "step_count": self._step_count,
            "action_mask": self.action_masks(),
        }

    def _state(self) -> SessionState:
        lobby = self._require_lobby()
        session_id = self._require_session_id()
        session = lobby.get_active_session(session_id)
        if session.state is None:
            raise ValueError("Active training session has no state")
        return session.state

    def _current_turn_id(self, state: SessionState) -> str | None:
        combat = state.combat
        if combat is None or not combat.turn_order:
            return None
        if combat.current_turn_index >= len(combat.turn_order):
            return None
        return combat.turn_order[combat.current_turn_index]

    def _close_active_session(self) -> None:
        if self.lobby is not None and self._session_id is not None:
            if (
                self.lobby.has_active_session(self._session_id)
                or self.lobby.has_lobby(self._session_id)
            ):
                self.lobby.close_session(self._session_id)

    def _require_active(self) -> None:
        self._require_game()
        self._require_session_id()

    def _require_game(self) -> GameService:
        if self.game is None:
            raise ValueError("Environment has not been reset")
        return self.game

    def _require_lobby(self) -> LobbyService:
        if self.lobby is None:
            raise ValueError("Environment has not been reset")
        return self.lobby

    def _require_session_id(self) -> str:
        if self._session_id is None:
            raise ValueError("Environment has not been reset")
        return self._session_id

    @staticmethod
    def _run_async(coro):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        raise RuntimeError(
            "InfiniteloopRunEnv is synchronous and cannot run inside an active event loop",
        )
