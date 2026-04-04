from dataclasses import replace

from game.character.player_character import PlayerCharacter
from game.core.data_loader import LocationOption
from game.core.enums import LocationType
from game.session.models import SessionState
from game.world.models import GenerationConfig
from game.world.world_run import WorldManager


class LocationManager:
    """Determines where the party goes next.

    Sole responsibility: exploration state, location generation, voting,
    and resolving which location the party enters.
    """

    def __init__(self, world: WorldManager):
        self._world = world

    def start_exploration(
        self,
        session_id: str,
        player_ids: list[str],
    ):
        """Initialize exploration state for a new run."""
        return self._world.start_run(session_id, player_ids)

    def generate_choices(
        self,
        state: SessionState,
        config: GenerationConfig | None = None,
    ) -> SessionState:
        if config is None:
            config = GenerationConfig()

        power = self._world.compute_power(list(state.players))
        exploration = self._world.generate_choices(
            state.exploration, power, list(state.players), config,
        )
        return replace(state, exploration=exploration)

    def submit_vote(
        self,
        state: SessionState,
        player_id: str,
        location_index: int,
    ) -> SessionState:
        exploration = self._world.submit_location_vote(
            state.exploration, player_id, location_index,
        )
        return replace(state, exploration=exploration)

    def resolve_choice(
        self,
        state: SessionState,
    ) -> tuple[SessionState, LocationOption]:
        """Tally votes, pick winning location, advance depth.

        Returns updated state and the chosen location.
        """
        exploration, location = self._world.resolve_location_choice(
            state.exploration,
        )
        state = replace(
            state,
            exploration=exploration,
            run_stats=replace(
                state.run_stats,
                rooms_explored=state.run_stats.rooms_explored + 1,
            ),
        )
        return state, location
