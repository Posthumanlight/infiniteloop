from dataclasses import replace

from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats
from game.combat.models import ActionRequest
from game.core.data_loader import (
    load_class_catalog,
    load_progression,
    load_restoration_constants,
)
from game.core.dice import SeededRNG
from game.core.enums import (
    LocationType,
    SessionEndReason,
    SessionPhase,
)
from game.session.location_manager import LocationManager
from game.session.models import PendingRewardQueue, RewardNotice, SessionState
from game.session.node_manager import NodeManager
from game.world.combat_locations import combat_location_from_option
from game.world.models import GenerationConfig
from game.world.world_run import WorldManager


def _build_base_stats_map() -> dict[str, MajorStats]:
    """Build a map of class_id -> level-1 MajorStats from TOML class data."""
    catalog = load_class_catalog()
    classes = {
        **catalog.base_classes,
        **{
            class_id: hero.to_class_data()
            for class_id, hero in catalog.hero_classes.items()
        },
    }
    result: dict[str, MajorStats] = {}
    for cid, cls in classes.items():
        result[cid] = MajorStats(
            attack=int(cls.major_stats["attack"]),
            hp=int(cls.major_stats["hp"]),
            speed=int(cls.major_stats["speed"]),
            crit_chance=cls.major_stats["crit_chance"],
            crit_dmg=cls.major_stats["crit_dmg"],
            resistance=int(cls.major_stats.get("resistance", 0)),
            energy=int(cls.major_stats.get("energy", 50)),
            mastery=int(cls.major_stats.get("mastery", 0)),
        )
    return result


class SessionManager:
    """Orchestrates a single dungeon run.

    Delegates location selection to LocationManager and encounter
    resolution to NodeManager. Owns lifecycle and phase transitions.
    """

    def __init__(self, seed: int, max_depth: int = 10):
        rng = SeededRNG(seed)
        world = WorldManager(seed)
        progression = load_progression()
        base_stats = _build_base_stats_map()
        restoration_formula = load_restoration_constants()["formula"]
        self._location = LocationManager(world)
        self._node = NodeManager(rng, progression, base_stats, restoration_formula)
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
        state = self._location.generate_choices(state, config)
        return self._node.prepare_reward_choices(state)

    def submit_location_vote(
        self,
        state: SessionState,
        player_id: str,
        location_index: int,
    ) -> SessionState:
        self._assert_phase(state, SessionPhase.EXPLORING)
        if self._node.has_pending_reward(state, player_id):
            raise ValueError("Choose your level-up reward first.")
        return self._location.submit_vote(state, player_id, location_index)

    def submit_reward_choice(
        self,
        state: SessionState,
        player_id: str,
        reward_id: str,
    ) -> SessionState:
        self._assert_phase(state, SessionPhase.EXPLORING)
        return self._node.apply_reward_choice(state, player_id, reward_id)

    def get_pending_rewards(
        self,
        state: SessionState,
    ) -> dict[str, PendingRewardQueue]:
        return state.pending_rewards

    def consume_reward_notices(
        self,
        state: SessionState,
    ) -> tuple[SessionState, tuple[RewardNotice, ...]]:
        notices = state.reward_notices
        return self._node.clear_reward_notices(state), notices

    def resolve_location_choice(self, state: SessionState) -> SessionState:
        self._assert_phase(state, SessionPhase.EXPLORING)

        state, location = self._location.resolve_choice(state)

        match location.location_type:
            case LocationType.COMBAT:
                return self._node.enter_combat(
                    state,
                    location.enemy_ids,
                    location=combat_location_from_option(location),
                    room_difficulty=location.room_difficulty,
                )
            case LocationType.EVENT:
                if location.event_id is None:
                    raise ValueError(
                        f"Event location {location.location_id} has no event_id"
                    )
                return self._node.enter_event(
                    state,
                    location.event_id,
                    room_difficulty=location.room_difficulty,
                )
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

        (
            state,
            combat_enemy_ids,
            room_difficulty,
            combat_location,
        ) = self._node.resolve_event(state)

        if state.event is not None:
            if not self._check_party_alive(state.players):
                return replace(
                    state,
                    phase=SessionPhase.ENDED,
                    event=None,
                    end_reason=SessionEndReason.PARTY_WIPED,
                )
            return state

        # Chain into combat if START_COMBAT outcome triggered
        if combat_enemy_ids:
            if not self._check_party_alive(state.players):
                return replace(
                    state,
                    phase=SessionPhase.ENDED,
                    end_reason=SessionEndReason.PARTY_WIPED,
                )
            return self._node.enter_combat(
                state,
                combat_enemy_ids,
                location=combat_location,
                room_difficulty=room_difficulty,
            )

        return self._check_end_conditions(state)
