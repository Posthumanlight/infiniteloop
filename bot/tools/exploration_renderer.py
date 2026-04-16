"""Renders exploration, class selection, events, and run summary into Telegram messages.

Pure functions — no aiogram imports. Takes service-layer DTOs, returns strings.
"""
from typing import TYPE_CHECKING

from bot.tools.location_labels import location_display_label
from game.core.enums import LevelRewardType, LocationType

if TYPE_CHECKING:
    from game.core.data_loader import ClassData, LocationOption
    from game.events.models import EventState
    from game.session.models import RunStats, SessionState
    from game.world.models import LocationVote
    from game.core.game_models import PlayerInfo, RewardOfferInfo


def render_class_prompt(
    classes: dict[str, ClassData],
    players: dict[str, PlayerInfo],
) -> str:
    """Show available classes and each player's current choice."""
    lines = ["\U0001f3ad Choose your class!\n"]

    for cls in classes.values():
        lines.append(f"  \u2022 {cls.name} — {cls.description}")

    lines.append("")
    for player in players.values():
        if player.class_id is not None:
            cls_name = classes.get(player.class_id)
            name = cls_name.name if cls_name else player.class_id
            lines.append(f"\u2705 {player.display_name}: {name}")
        else:
            lines.append(f"\u23f3 {player.display_name}: choosing...")

    return "\n".join(lines)


def render_exploration_choices(
    options: tuple[LocationOption, ...],
    votes: tuple[LocationVote, ...],
    players: dict[str, PlayerInfo],
) -> str:
    """Show location options with vote status."""
    icons = {LocationType.COMBAT: "\u2694\ufe0f", LocationType.EVENT: "\U0001f4dc"}
    lines = ["\U0001f5fa\ufe0f Choose your path!\n"]

    for i, opt in enumerate(options):
        icon = icons.get(opt.location_type, "\u2753")
        vote_count = sum(1 for v in votes if v.location_index == i)
        label = location_display_label(opt)
        lines.append(f"  {icon} {i + 1}. {label} [{vote_count} votes]")

    voted_ids = {v.player_id for v in votes}
    waiting = [
        p.display_name for p in players.values()
        if p.entity_id not in voted_ids
    ]
    if waiting:
        lines.append(f"\nWaiting for: {', '.join(waiting)}")
    else:
        lines.append("\nAll votes in!")

    return "\n".join(lines)


def render_event(
    event_state: EventState,
    players: dict[str, PlayerInfo],
) -> str:
    """Show event description and choices."""
    event_def = event_state.event_def
    lines = [
        f"\U0001f4dc {event_def.name}\n",
        event_def.description,
        "",
    ]

    for choice in event_def.choices:
        vote_count = sum(
            1 for v in event_state.votes if v.choice_index == choice.index
        )
        lines.append(f"  {choice.index + 1}. {choice.label} [{vote_count} votes]")
        lines.append(f"     {choice.description}")

    voted_ids = {v.player_id for v in event_state.votes}
    waiting = [
        p.display_name for p in players.values()
        if p.entity_id not in voted_ids
    ]
    if waiting:
        lines.append(f"\nWaiting for: {', '.join(waiting)}")

    return "\n".join(lines)


def render_reward_choices(
    player_name: str,
    reward_type: LevelRewardType,
    pending_count: int,
    offers: tuple[RewardOfferInfo, ...],
) -> str:
    """Show level-up reward choices for a single player."""
    if reward_type == LevelRewardType.SKILL:
        header_label = "new skill"
    else:
        header_label = "modifier"
    lines = [
        f"\u2b50 Level-up reward for {player_name}",
        f"Pick 1 {header_label} ({pending_count} pick(s) remaining):",
        "",
    ]
    for i, offer in enumerate(offers, start=1):
        if offer.description:
            lines.append(f"  {i}. {offer.name} — {offer.description}")
        else:
            lines.append(f"  {i}. {offer.name}")
    return "\n".join(lines)


def render_reward_notice(
    player_name: str, reward_type: LevelRewardType, skipped_count: int,
) -> str:
    suffix = "pick" if skipped_count == 1 else "picks"
    pool_label = "skills" if reward_type == LevelRewardType.SKILL else "modifiers"
    return (
        f"\u2139\ufe0f {player_name}: {skipped_count} level-up {suffix} "
        f"had no eligible {pool_label} and was skipped."
    )


def render_run_summary(
    stats: RunStats,
    victory: bool,
) -> str:
    """Show end-of-run statistics."""
    if victory:
        header = "\U0001f3c6 Run Complete!"
    else:
        header = "\U0001f480 Run Over — Party Wiped!"

    lines = [
        header,
        "",
        f"  Rooms explored: {stats.rooms_explored}",
        f"  Combats completed: {stats.combats_completed}",
        f"  Events completed: {stats.events_completed}",
        f"  Enemies defeated: {stats.enemies_defeated}",
        f"  Damage dealt: {stats.total_damage_dealt}",
        f"  Damage taken: {stats.total_damage_taken}",
        f"  Healing done: {stats.total_healing}",
        f"  XP gained: {stats.total_xp_gained}",
    ]
    return "\n".join(lines)
