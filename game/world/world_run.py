from collections import Counter
from dataclasses import replace

from game.character.player_character import PlayerCharacter
from game.core.dice import SeededRNG
from game.core.enums import ExplorationPhase
from game.world.generator import WorldGenerator
from game.core.data_loader import LocationOption
from game.world.models import (
    ExplorationState,
    GenerationConfig,
    LocationVote,
)

class WorldManager():
    def __init__(self, seed : int = 0):
        self.generator = WorldGenerator()
        self.rng = SeededRNG(seed)


    def start_run(self, session_id: str,player_ids: list[str]) -> ExplorationState:
        if not player_ids:
            raise ValueError("At least one player is required")

        return ExplorationState(
            session_id=session_id,
            depth=0,
            phase=ExplorationPhase.CHOOSING,
            player_ids=tuple(player_ids),
            rng_state=self.rng.get_state(),
        )


    def generate_choices(self, state: ExplorationState, power: int, players: list[PlayerCharacter], 
                         config: GenerationConfig,) -> ExplorationState:


        options = self.generator.generate_locations(power, players,  config, state.depth)

        return replace(
            state,
            phase=ExplorationPhase.CHOOSING,
            current_options=options,
            votes=(),
            rng_state=self.rng.get_state(),
        )


    def submit_location_vote(self, state: ExplorationState,player_id: str,location_index: int,
    ) -> ExplorationState:
        """Record a player's vote for a location."""
        if state.phase != ExplorationPhase.CHOOSING:
            raise ValueError("Not in CHOOSING phase")
        if player_id not in state.player_ids:
            raise ValueError(f"Player {player_id} is not part of this exploration")
        if any(v.player_id == player_id for v in state.votes):
            raise ValueError(f"Player {player_id} has already voted")
        if location_index < 0 or location_index >= len(state.current_options):
            raise ValueError(
                f"Invalid location index {location_index}, "
                f"have {len(state.current_options)} options"
            )

        vote = LocationVote(player_id=player_id, location_index=location_index)
        return replace(state, votes=state.votes + (vote,))


    def resolve_location_choice(self,
        state: ExplorationState,
    ) -> tuple[ExplorationState, LocationOption]:
        """Tally votes, pick the winning location, advance depth.

        Solo (1 player): their vote wins.
        Multiplayer: majority wins, ties broken by RNG.
        """
        if state.phase != ExplorationPhase.CHOOSING:
            raise ValueError("Not in CHOOSING phase")
        if not state.votes:
            raise ValueError("Cannot resolve with no votes")

        # Tally
        vote_counts = Counter(v.location_index for v in state.votes)
        max_count = max(vote_counts.values())
        tied = [idx for idx, count in vote_counts.items() if count == max_count]

        if len(tied) > 1:
            winner_index = tied[self.rng.d(len(tied)) - 1]
        else:
            winner_index = tied[0]

        picked = state.current_options[winner_index]

        new_state = replace(
            state,
            depth=state.depth + 1,
            phase=ExplorationPhase.RESOLVING,
            history=state.history + (picked.location_id,),
            rng_state=self.rng.get_state(),
        )
        return new_state, picked


    def compute_power(self, players: list[PlayerCharacter]) -> int:
        """Compute party power rating: num_players * average_level."""
        if not players:
            return 0
        total_level = sum(p.level for p in players)
        return len(players) * (total_level // len(players))
