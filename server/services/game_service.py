from dataclasses import dataclass

from game.combat.models import ActionRequest, ActionResult
from game.core.enums import ActionType, EntityType
from game.session.factories import build_player
from game.session.session_manager import SessionManager
from game.session.models import SessionState
from server.services.game_models import (
    CombatSnapshot,
    EntitySnapshot,
    PlayerInfo,
    TurnBatch,
)


@dataclass
class _ActiveSession:
    session_id: str
    players: dict[str, PlayerInfo]  # entity_id -> PlayerInfo
    manager: SessionManager
    state: SessionState


class GameService:
    """In-memory game orchestrator. One instance per server process.

    Knows nothing about Telegram — takes generic IDs, returns dataclasses.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _ActiveSession] = {}

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, session_id: str, creator: PlayerInfo) -> None:
        if session_id in self._sessions:
            raise ValueError("Session already exists for this chat")

        manager = SessionManager(seed=hash(session_id) & 0x7FFFFFFF)
        self._sessions[session_id] = _ActiveSession(
            session_id=session_id,
            players={creator.entity_id: creator},
            manager=manager,
            state=None,  # type: ignore[arg-type] — set on start_combat
        )

    def join_session(self, session_id: str, player: PlayerInfo) -> None:
        session = self._get_session(session_id)
        if player.entity_id in session.players:
            raise ValueError("Player already in session")
        session.players[player.entity_id] = player

    def get_session_players(self, session_id: str) -> list[PlayerInfo]:
        session = self._get_session(session_id)
        return list(session.players.values())

    def has_session(self, session_id: str) -> bool:
        return session_id in self._sessions

    def is_in_combat(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        return session is not None and session.state is not None and session.state.combat is not None

    def remove_session(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------

    def start_combat(
        self,
        session_id: str,
        enemy_ids: tuple[str, ...],
    ) -> CombatSnapshot:
        session = self._get_session(session_id)
        if not session.players:
            raise ValueError("No players in session")

        # Build PlayerCharacter instances (default class: warrior)
        players = [
            build_player("warrior", entity_id=pid)
            for pid in session.players
        ]

        # Initialize run and directly enter combat (skip exploration)
        session.state = session.manager.start_run(session_id, players)
        session.state = session.manager._node.enter_combat(
            session.state, enemy_ids,
        )

        # Auto-play any leading enemy turns
        if self._current_entity_type(session) == EntityType.ENEMY:
            self._auto_play_enemies(session)

        return self._build_combat_snapshot(session)

    def submit_player_action(
        self,
        session_id: str,
        action: ActionRequest,
    ) -> TurnBatch:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        results: list[ActionResult] = []

        # 1. Submit the player's action (capture result before potential finalize)
        self._submit_and_capture(session, action, results)

        # 2. Auto-play enemy turns until next player or combat end
        self._auto_play_enemies(session, results)

        return self._build_turn_batch(session, tuple(results))

    def skip_player_turn(
        self,
        session_id: str,
        actor_id: str,
    ) -> TurnBatch:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        results: list[ActionResult] = []

        # Build a skip action and submit it
        action = ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id=None,
        )
        self._submit_and_capture(session, action, results, skip=True)

        self._auto_play_enemies(session, results)

        return self._build_turn_batch(session, tuple(results))

    def get_combat_snapshot(self, session_id: str) -> CombatSnapshot:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        return self._build_combat_snapshot(session)

    def get_available_skills(self, session_id: str, actor_id: str) -> list:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        return session.manager.get_combat_actions(session.state, actor_id)

    def get_alive_enemies(self, session_id: str) -> list[EntitySnapshot]:
        session = self._get_session(session_id)
        self._assert_in_combat(session)
        return [
            self._entity_to_snapshot(e)
            for e in session.state.combat.entities.values()
            if e.entity_type == EntityType.ENEMY and e.current_hp > 0
        ]

    def get_whose_turn(self, session_id: str) -> str | None:
        session = self._sessions.get(session_id)
        if session is None or session.state is None or session.state.combat is None:
            return None
        return self._current_turn_id(session)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_session(self, session_id: str) -> _ActiveSession:
        session = self._sessions.get(session_id)
        if session is None:
            raise ValueError("No active session")
        return session

    @staticmethod
    def _assert_in_combat(session: _ActiveSession) -> None:
        if session.state is None or session.state.combat is None:
            raise ValueError("Not in combat")

    def _submit_and_capture(
        self,
        session: _ActiveSession,
        action: ActionRequest,
        results: list[ActionResult],
        *,
        skip: bool = False,
    ) -> None:
        """Submit an action and capture the ActionResult before finalize can clear it."""
        log_len = len(session.state.combat.action_log)

        if skip:
            session.state = session.manager.skip_combat_turn(
                session.state, action.actor_id,
            )
        else:
            session.state = session.manager.submit_combat_action(
                session.state, action,
            )

        # If combat still active, grab new results from the log
        if session.state.combat is not None:
            results.extend(session.state.combat.action_log[log_len:])
        # If combat ended, the log was lost during finalize.
        # The TurnBatch.combat_ended flag tells the renderer what happened.

    def _auto_play_enemies(
        self,
        session: _ActiveSession,
        results: list[ActionResult] | None = None,
    ) -> None:
        """Process all consecutive enemy turns, capturing results."""
        while (
            session.state.combat is not None
            and self._current_entity_type(session) == EntityType.ENEMY
        ):
            enemy_action = self._build_enemy_action(session)
            if results is not None:
                self._submit_and_capture(session, enemy_action, results)
            else:
                session.state = session.manager.submit_combat_action(
                    session.state, enemy_action,
                )

    @staticmethod
    def _build_enemy_action(session: _ActiveSession) -> ActionRequest:
        """MVP enemy AI: first skill on first alive player."""
        combat = session.state.combat
        current_id = combat.turn_order[combat.current_turn_index]
        enemy = combat.entities[current_id]
        skill_id = enemy.skills[0]

        alive_players = [
            eid
            for eid in combat.turn_order
            if combat.entities[eid].entity_type == EntityType.PLAYER
            and combat.entities[eid].current_hp > 0
        ]
        target = alive_players[0] if alive_players else None

        return ActionRequest(
            actor_id=current_id,
            action_type=ActionType.ACTION,
            skill_id=skill_id,
            target_id=target,
        )

    @staticmethod
    def _current_turn_id(session: _ActiveSession) -> str | None:
        combat = session.state.combat
        if combat is None:
            return None
        return combat.turn_order[combat.current_turn_index]

    @staticmethod
    def _current_entity_type(session: _ActiveSession) -> EntityType | None:
        combat = session.state.combat
        if combat is None:
            return None
        current_id = combat.turn_order[combat.current_turn_index]
        return combat.entities[current_id].entity_type

    def _build_turn_batch(
        self,
        session: _ActiveSession,
        results: tuple[ActionResult, ...],
    ) -> TurnBatch:
        combat_ended = session.state.combat is None
        return TurnBatch(
            results=results,
            entities=self._build_entity_map(session),
            whose_turn=self._current_turn_id(session) if not combat_ended else None,
            combat_ended=combat_ended,
            victory=self._check_victory(session) if combat_ended else False,
        )

    def _check_victory(self, session: _ActiveSession) -> bool:
        """Victory = at least one player alive after combat ends."""
        return any(p.current_hp > 0 for p in session.state.players)

    def _build_combat_snapshot(self, session: _ActiveSession) -> CombatSnapshot:
        combat = session.state.combat
        return CombatSnapshot(
            entities=self._build_entity_map(session),
            turn_order=combat.turn_order,
            whose_turn=combat.turn_order[combat.current_turn_index],
            round_number=combat.round_number,
        )

    def _build_entity_map(
        self,
        session: _ActiveSession,
    ) -> dict[str, EntitySnapshot]:
        if session.state.combat is not None:
            return {
                eid: self._entity_to_snapshot(e)
                for eid, e in session.state.combat.entities.items()
            }
        # Combat ended — build from session players only
        return {
            p.entity_id: EntitySnapshot(
                entity_id=p.entity_id,
                name=p.entity_name,
                entity_type=p.entity_type,
                current_hp=p.current_hp,
                max_hp=p.major_stats.hp,
                current_energy=p.current_energy,
                max_energy=p.major_stats.energy,
                is_alive=p.current_hp > 0,
            )
            for p in session.state.players
        }

    @staticmethod
    def _entity_to_snapshot(entity: object) -> EntitySnapshot:
        return EntitySnapshot(
            entity_id=entity.entity_id,
            name=entity.entity_name,
            entity_type=entity.entity_type,
            current_hp=entity.current_hp,
            max_hp=entity.major_stats.hp,
            current_energy=entity.current_energy,
            max_energy=entity.major_stats.energy,
            is_alive=entity.current_hp > 0,
        )
