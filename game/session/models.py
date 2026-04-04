from dataclasses import dataclass

from game.character.player_character import PlayerCharacter
from game.combat.models import CombatState
from game.core.enums import SessionEndReason, SessionPhase
from game.events.models import EventState
from game.world.models import ExplorationState



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
class SessionState:
    session_id: str
    players: tuple[PlayerCharacter, ...]   # authoritative player state between encounters
    phase: SessionPhase
    exploration: ExplorationState | None = None
    combat: CombatState | None = None
    event: EventState | None = None
    run_stats: RunStats = RunStats()
    end_reason: SessionEndReason | None = None
    max_depth: int = 10