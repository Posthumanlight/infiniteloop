import uuid
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

from game.character.player_character import PlayerCharacter
from game.core.dice import SeededRNG
from game.core.enums import EventPhase, EventType
from game.events.models import EventDef, EventResolution, EventState, Vote
from game.events.outcomes import resolve_outcomes

if TYPE_CHECKING:
    from game.world.difficulty import RoomDifficultyModifier


def start_event(
    session_id: str,
    event_def: EventDef,
    player_ids: list[str],
    seed: int,
    room_difficulty: "RoomDifficultyModifier | None" = None,
) -> EventState:
    """Create a new event and return the initial state.

    For solo events, player_ids must contain exactly one player.
    """
    if event_def.event_type == EventType.SOLO and len(player_ids) != 1:
        raise ValueError(
            f"Solo events require exactly 1 player, got {len(player_ids)}"
        )
    if not player_ids:
        raise ValueError("At least one player is required")

    rng = SeededRNG(seed)
    return EventState(
        event_id=uuid.uuid4().hex,
        session_id=session_id,
        event_def=event_def,
        phase=EventPhase.PRESENTING,
        player_ids=tuple(player_ids),
        rng_state=rng.get_state(),
        room_difficulty=room_difficulty,
    )


def submit_vote(
    state: EventState,
    player_id: str,
    choice_index: int,
) -> EventState:
    """Record a player's vote. Returns updated state."""
    if state.phase != EventPhase.PRESENTING:
        raise ValueError("Event is not in PRESENTING phase")
    if player_id not in state.player_ids:
        raise ValueError(f"Player {player_id} is not part of this event")
    if any(v.player_id == player_id for v in state.votes):
        raise ValueError(f"Player {player_id} has already voted")
    if choice_index < 0 or choice_index >= len(state.event_def.choices):
        raise ValueError(
            f"Invalid choice index {choice_index}, "
            f"event has {len(state.event_def.choices)} choices"
        )

    vote = Vote(player_id=player_id, choice_index=choice_index)
    return replace(state, votes=state.votes + (vote,))


def resolve_event(
    state: EventState,
    players: list[PlayerCharacter],
) -> tuple[EventState, EventResolution]:
    """Tally votes, determine winner, resolve outcomes.

    Requires at least one vote. Ties are broken by SeededRNG.
    """
    if state.phase != EventPhase.PRESENTING:
        raise ValueError("Event is not in PRESENTING phase")
    if not state.votes:
        raise ValueError("Cannot resolve event with no votes")

    rng = SeededRNG(0)
    rng.set_state(state.rng_state)

    # Tally votes
    vote_counts: dict[int, int] = dict(
        Counter(v.choice_index for v in state.votes)
    )

    # Find winner(s)
    max_count = max(vote_counts.values())
    tied = [idx for idx, count in vote_counts.items() if count == max_count]

    was_tie = len(tied) > 1
    if was_tie:
        winner_index = tied[rng.d(len(tied)) - 1]
    else:
        winner_index = tied[0]

    winning_choice = state.event_def.choices[winner_index]

    # Resolve outcomes
    outcomes = resolve_outcomes(winning_choice, players, rng)

    resolution = EventResolution(
        winning_choice_index=winner_index,
        winning_choice_label=winning_choice.label,
        was_tie=was_tie,
        vote_counts=vote_counts,
        outcomes=outcomes,
    )

    new_state = replace(
        state,
        phase=EventPhase.RESOLVED,
        resolution=resolution,
        rng_state=rng.get_state(),
    )
    return new_state, resolution


def select_event(
    available_events: list[EventDef],
    depth: int,
    party: list[PlayerCharacter],
    rng: SeededRNG,
) -> EventDef | None:
    """Pick an eligible event using weighted random selection.

    Filters by depth range and requirements. Returns None if nothing eligible.
    """
    min_level = min(p.level for p in party) if party else 0
    party_classes = {p.player_class for p in party}

    eligible: list[EventDef] = []
    for event in available_events:
        if not (event.min_depth <= depth <= event.max_depth):
            continue
        req = event.requirements
        if min_level < req.min_level or min_level > req.max_level:
            continue
        if req.required_classes and not party_classes & set(req.required_classes):
            continue
        eligible.append(event)

    if not eligible:
        return None

    # Weighted random selection
    total_weight = sum(e.weight for e in eligible)
    roll = rng.uniform(0.0, float(total_weight))
    cumulative = 0.0
    for event in eligible:
        cumulative += event.weight
        if roll <= cumulative:
            return event

    # Fallback (shouldn't reach here due to floating point, but be safe)
    return eligible[-1]
