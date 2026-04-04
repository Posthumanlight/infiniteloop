from dataclasses import replace

from game.character.player_character import PlayerCharacter
from game.combat.models import ActionRequest
from game.core.dice import SeededRNG
from game.core.enums import (
    LocationType,
    SessionEndReason,
    SessionPhase,
)
from game.session.location_manager import LocationManager
from game.session.models import SessionState
from game.session.node_manager import NodeManager
from game.world.models import GenerationConfig
from game.world.world_run import WorldManager


class SessionManager:
    """Orchestrates a single dungeon run.

    Delegates location selection to LocationManager and encounter
    resolution to NodeManager. Owns lifecycle and phase transitions.
    """

    def __init__(self, seed: int, max_depth: int = 10):
        rng = SeededRNG(seed)
        world = WorldManager(seed)
        self._location = LocationManager(world)
        self._node = NodeManager(rng)
        self._max_depth = max_depth

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_phase(state: SessionState, expected: SessionPhase) -> None:
        if state.phase != expected:
            raise ValueError(
                f"Expected phase {expected.value}, got {state.phase.value}"
            )

    @staticmethod
    def _check_party_alive(players: tuple[PlayerCharacter, ...]) -> bool:
        return any(p.current_hp > 0 for p in players)

    def _check_end_conditions(self, state: SessionState) -> SessionState:
        """Transition to ENDED if party wiped or max depth reached."""
        if not self._check_party_alive(state.players):
            return replace(
                state,
                phase=SessionPhase.ENDED,
                end_reason=SessionEndReason.PARTY_WIPED,
            )
        if state.exploration is not None and state.exploration.depth >= state.max_depth:
            return replace(
                state,
                phase=SessionPhase.ENDED,
                end_reason=SessionEndReason.MAX_DEPTH,
            )
        return replace(state, phase=SessionPhase.EXPLORING)

    # ------------------------------------------------------------------
    # Run lifecycle
    # ------------------------------------------------------------------

    def start_run(
        self,
        session_id: str,
        players: list[PlayerCharacter],
    ) -> SessionState:
        if not players:
            raise ValueError("At least one player is required")

        exploration = self._location.start_exploration(
            session_id, [p.entity_id for p in players],
        )
        return SessionState(
            session_id=session_id,
            players=tuple(players),
            phase=SessionPhase.EXPLORING,
            exploration=exploration,
            max_depth=self._max_depth,
        )

    def generate_choices(
        self,
        state: SessionState,
        config: GenerationConfig | None = None,
    ) -> SessionState:
        self._assert_phase(state, SessionPhase.EXPLORING)
        return self._location.generate_choices(state, config)

    def submit_location_vote(
        self,
        state: SessionState,
        player_id: str,
        location_index: int,
    ) -> SessionState:
        self._assert_phase(state, SessionPhase.EXPLORING)
        return self._location.submit_vote(state, player_id, location_index)

    def resolve_location_choice(self, state: SessionState) -> SessionState:
        self._assert_phase(state, SessionPhase.EXPLORING)

        state, location = self._location.resolve_choice(state)

        match location.location_type:
            case LocationType.COMBAT:
                return self._node.enter_combat(state, location.enemy_ids)
            case LocationType.EVENT:
                if location.event_id is None:
                    raise ValueError(
                        f"Event location {location.location_id} has no event_id"
                    )
                return self._node.enter_event(state, location.event_id)
            case _:
                raise ValueError(
                    f"Unknown location type: {location.location_type}"
                )

    def retreat(self, state: SessionState) -> SessionState:
        self._assert_phase(state, SessionPhase.EXPLORING)
        return replace(
            state,
            phase=SessionPhase.ENDED,
            end_reason=SessionEndReason.RETREAT,
        )

    # ------------------------------------------------------------------
    # Combat delegation
    # ------------------------------------------------------------------

    def submit_combat_action(
        self,
        state: SessionState,
        action: ActionRequest,
    ) -> SessionState:
        self._assert_phase(state, SessionPhase.IN_COMBAT)
        state = self._node.submit_combat_action(state, action)
        if state.combat is None:
            return self._check_end_conditions(state)
        return state

    def skip_combat_turn(
        self,
        state: SessionState,
        actor_id: str,
    ) -> SessionState:
        self._assert_phase(state, SessionPhase.IN_COMBAT)
        state = self._node.skip_combat_turn(state, actor_id)
        if state.combat is None:
            return self._check_end_conditions(state)
        return state

    def get_combat_actions(
        self,
        state: SessionState,
        actor_id: str,
    ) -> list:
        self._assert_phase(state, SessionPhase.IN_COMBAT)
        return self._node.get_combat_actions(state, actor_id)

    # ------------------------------------------------------------------
    # Event delegation
    # ------------------------------------------------------------------

    def submit_event_vote(
        self,
        state: SessionState,
        player_id: str,
        choice_index: int,
    ) -> SessionState:
        self._assert_phase(state, SessionPhase.IN_EVENT)
        return self._node.submit_event_vote(state, player_id, choice_index)

    def resolve_event(self, state: SessionState) -> SessionState:
        self._assert_phase(state, SessionPhase.IN_EVENT)

        state, combat_enemy_ids = self._node.resolve_event(state)

        # Chain into combat if START_COMBAT outcome triggered
        if combat_enemy_ids:
            if not self._check_party_alive(state.players):
                return replace(
                    state,
                    phase=SessionPhase.ENDED,
                    end_reason=SessionEndReason.PARTY_WIPED,
                )
            return self._node.enter_combat(state, combat_enemy_ids)

        return self._check_end_conditions(state)
