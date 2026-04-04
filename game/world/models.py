from dataclasses import dataclass

from game.core.enums import ExplorationPhase, LocationType


@dataclass(frozen=True)
class GenerationConfig:
    """Flags that control random location generation."""

    tags: tuple[str, ...] = ()
    count_min: int = 1
    count_max: int = 5
    combat_weight: float = 0.6
    predetermined_set_id: str | None = None


@dataclass(frozen=True)
class LocationVote:
    """A player's vote for which location to visit."""

    player_id: str
    location_index: int


@dataclass(frozen=True)
class ExplorationState:
    """Tracks an exploration run. Analogous to CombatState / EventState."""

    session_id: str
    depth: int
    phase: ExplorationPhase
    player_ids: tuple[str, ...]
    current_options: tuple = ()  # tuple[LocationOption, ...] — avoids circular import
    votes: tuple[LocationVote, ...] = ()
    history: tuple[str, ...] = ()  # location_ids of picked locations
    rng_state: tuple | None = None
