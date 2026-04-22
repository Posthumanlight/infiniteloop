from dataclasses import dataclass
from typing import TYPE_CHECKING

from game.core.enums import EventPhase, EventType, OutcomeAction, OutcomeTarget

if TYPE_CHECKING:
    from game.world.difficulty import RoomDifficultyModifier


# ---------------------------------------------------------------------------
# Data definitions (loaded from TOML)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OutcomeDef:
    """A single outcome effect from a choice."""

    action: OutcomeAction
    target: OutcomeTarget
    expr: str | None = None
    value: int | None = None
    item_id: str | None = None
    effect_id: str | None = None
    enemy_group: tuple[str, ...] = ()


@dataclass(frozen=True)
class ChoiceDef:
    """One choosable option within an event."""

    index: int
    label: str
    description: str
    outcomes: tuple[OutcomeDef, ...] = ()
    next_stage: str | None = None


@dataclass(frozen=True)
class EventStageDef:
    """One screen/stage within an event."""

    stage_id: str
    title: str
    description: str
    choices: tuple[ChoiceDef, ...]


@dataclass(frozen=True)
class EventRequirements:
    """Optional conditions for an event to be eligible."""

    min_level: int = 0
    max_level: int = 999
    required_classes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventDef:
    """Data-driven event definition loaded from TOML."""

    event_id: str
    name: str
    event_type: EventType
    stages: dict[str, EventStageDef]
    initial_stage_id: str = "start"
    min_depth: int = 0
    max_depth: int = 999
    weight: int = 10
    requirements: EventRequirements = EventRequirements()


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Vote:
    """A single player's vote."""

    player_id: str
    choice_index: int


@dataclass(frozen=True)
class OutcomeResult:
    """One resolved outcome effect applied to a specific player."""

    player_id: str
    action: OutcomeAction
    amount: int = 0
    item_id: str | None = None
    effect_id: str | None = None
    enemy_group: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventStageResolution:
    """The result of resolving a single event stage after voting."""

    stage_id: str
    winning_choice_index: int
    winning_choice_label: str
    was_tie: bool
    vote_counts: dict[int, int]
    outcomes: tuple[OutcomeResult, ...]
    next_stage: str | None = None


EventResolution = EventStageResolution


@dataclass(frozen=True)
class EventState:
    """Tracks an active event. Analogous to CombatState."""

    event_id: str
    session_id: str
    event_def: EventDef
    phase: EventPhase
    player_ids: tuple[str, ...]
    current_stage_id: str
    votes: tuple[Vote, ...] = ()
    history: tuple[EventStageResolution, ...] = ()
    resolution: EventStageResolution | None = None
    rng_state: tuple | None = None
    room_difficulty: "RoomDifficultyModifier | None" = None

    @property
    def current_stage(self) -> EventStageDef:
        return self.event_def.stages[self.current_stage_id]
