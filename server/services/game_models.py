from dataclasses import dataclass

from game.combat.models import ActionResult
from game.core.enums import EntityType


@dataclass(frozen=True)
class PlayerInfo:
    """Identity mapping between Telegram user and game entity."""

    entity_id: str  # str(tg_user_id)
    tg_user_id: int
    display_name: str  # Telegram first_name


@dataclass(frozen=True)
class EntitySnapshot:
    """Minimal view of an entity for display purposes."""

    entity_id: str
    name: str
    entity_type: EntityType
    current_hp: int
    max_hp: int
    current_energy: int
    max_energy: int
    is_alive: bool


@dataclass(frozen=True)
class TurnBatch:
    """Result of a player submitting an action.

    Contains the player's action result plus any auto-played enemy actions
    that followed before the next player turn.
    """

    results: tuple[ActionResult, ...]
    entities: dict[str, EntitySnapshot]
    whose_turn: str | None  # None if combat ended
    combat_ended: bool
    victory: bool


@dataclass(frozen=True)
class CombatSnapshot:
    """Full combat state for /status or initial render."""

    entities: dict[str, EntitySnapshot]
    turn_order: tuple[str, ...]
    whose_turn: str
    round_number: int
