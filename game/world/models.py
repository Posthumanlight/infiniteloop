from dataclasses import dataclass, field

from game.core.enums import CombatLocationType, ExplorationPhase, LocationType


@dataclass(frozen=True)
class GenerationConfig:
    """Flags that control random location generation."""

    tags: tuple[str, ...] = ()
    count_min: int = 1
    count_max: int = 5
    combat_weight: float = 0.6
    predetermined_set_id: str | None = None
    combat_type_weights: dict[CombatLocationType, float] = field(
        default_factory=lambda: {
            CombatLocationType.NORMAL: 10.0,
            CombatLocationType.ELITE: 3.0,
            CombatLocationType.SWARM: 2.0,
            CombatLocationType.SOLO_BOSS: 1.0,
            CombatLocationType.BOSS_GROUP: 1.0,
        },
    )


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
