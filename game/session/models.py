from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from game.character.player_character import PlayerCharacter
from game.combat.models import ActionResult, CombatState
from game.core.data_loader import CombatLocation
from game.core.game_models import LootResolutionSnapshot
from game.core.enums import LevelRewardType, SessionEndReason, SessionPhase
from game.events.models import EventState
from game.core.game_models import PlayerInfo
from game.world.models import ExplorationState

if TYPE_CHECKING:
    from game.session.session_manager import SessionManager


@dataclass(frozen=True)
class PendingReward:
    """One queued level-up reward awaiting the player's pick.

    `offer` lists the rolled typed reward keys (for example `modifier:foo`,
    `skill:slash`, `passive:battle_master`). Empty tuple means the roll has
    not been performed yet.
    """

    reward_type: LevelRewardType
    offer: tuple[str, ...] = ()


@dataclass(frozen=True)
class PendingRewardQueue:
    entries: tuple[PendingReward, ...] = ()

    @property
    def pending_count(self) -> int:
        return len(self.entries)

    @property
    def current_offer(self) -> tuple[str, ...]:
        return self.entries[0].offer if self.entries else ()

    @property
    def current_type(self) -> LevelRewardType | None:
        return self.entries[0].reward_type if self.entries else None


@dataclass(frozen=True)
class RewardNotice:
    """Informational notice that a queued reward was skipped (empty pool)."""

    player_id: str
    reward_type: LevelRewardType
    skipped_count: int = 1


@dataclass(frozen=True)
class RunStats:
    combats_completed: int = 0
    events_completed: int = 0
    enemies_defeated: int = 0
    total_damage_dealt: int = 0
    total_damage_taken: int = 0
    total_healing: int = 0
    total_xp_gained: int = 0
    rooms_explored: int = 0


@dataclass(frozen=True)
class CompletedCombat:
    combat_id: str
    final_round_number: int
    action_log: tuple[ActionResult, ...]
    entities: dict[str, object]
    location: CombatLocation


@dataclass(frozen=True)
class SessionState:
    session_id: str
    players: tuple[PlayerCharacter, ...]   # authoritative player state between encounters
    phase: SessionPhase
    exploration: ExplorationState | None = None
    combat: CombatState | None = None
    last_combat: CompletedCombat | None = None
    event: EventState | None = None
    pending_rewards: dict[str, PendingRewardQueue] = field(default_factory=dict)
    reward_notices: tuple[RewardNotice, ...] = ()
    pending_loot: LootResolutionSnapshot | None = None
    run_stats: RunStats = RunStats()
    end_reason: SessionEndReason | None = None
    max_depth: int = 10


@dataclass
class ActiveSession:
    session_id: str
    players: dict[str, PlayerInfo]
    manager: "SessionManager"
    state: SessionState | None
    save_origins: dict[str, object] = field(default_factory=dict)
