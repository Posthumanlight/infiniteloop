"""Renders game state and combat results into formatted Telegram messages.

Pure functions — no aiogram imports. Takes service-layer DTOs, returns strings.
"""

from game.combat.models import ActionResult
from game.core.enums import EntityType
from server.services.game_models import (
    CombatSnapshot,
    EntitySnapshot,
    PlayerInfo,
    TurnBatch,
)


def _entity_icon(entity_type: EntityType) -> str:
    match entity_type:
        case EntityType.PLAYER:
            return "\U0001f9d1"  # person
        case EntityType.ENEMY:
            return "\U0001f47a"  # goblin


def _hp_bar(current: int, maximum: int, width: int = 10) -> str:
    ratio = max(0, min(current / maximum, 1.0)) if maximum > 0 else 0
    filled = round(ratio * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def _entity_line(snap: EntitySnapshot) -> str:
    icon = _entity_icon(snap.entity_type)
    bar = _hp_bar(snap.current_hp, snap.max_hp)
    line = f"{icon} {snap.name} {bar} {snap.current_hp}/{snap.max_hp}"
    if snap.entity_type == EntityType.PLAYER:
        line += f"  \u26a1{snap.current_energy}"
    if not snap.is_alive:
        line += " \U0001f480"
    return line


def render_combat_start(
    snapshot: CombatSnapshot,
    players: dict[str, PlayerInfo],
) -> str:
    lines = ["\u2694\ufe0f Combat begins!\n"]

    # Entity status lines — players first, then enemies
    player_snaps = [
        snapshot.entities[eid]
        for eid in snapshot.turn_order
        if snapshot.entities[eid].entity_type == EntityType.PLAYER
    ]
    enemy_snaps = [
        snapshot.entities[eid]
        for eid in snapshot.turn_order
        if snapshot.entities[eid].entity_type == EntityType.ENEMY
    ]

    for snap in player_snaps:
        lines.append(_entity_line(snap))
    for snap in enemy_snaps:
        lines.append(_entity_line(snap))

    # Turn order
    names = [snapshot.entities[eid].name for eid in snapshot.turn_order]
    lines.append(f"\nTurn order: {' \u2192 '.join(names)}")

    return "\n".join(lines)


def render_action_result(
    result: ActionResult,
    entities: dict[str, EntitySnapshot],
) -> str:
    actor = entities.get(result.actor_id)
    actor_name = actor.name if actor else result.actor_id

    if result.skipped:
        return f"\u23ed\ufe0f {actor_name} skips their turn."

    lines: list[str] = []
    skill_name = result.action.skill_id or "attack"

    for hit in result.hits:
        target = entities.get(hit.target_id)
        target_name = target.name if target else hit.target_id

        if hit.damage is not None:
            crit_mark = " \U0001f4a5CRIT" if hit.damage.is_crit else ""
            lines.append(
                f"\U0001f5e1\ufe0f {actor_name} uses {skill_name} on "
                f"{target_name} for {hit.damage.amount} damage!{crit_mark}"
            )
            # Check if target was killed
            if target and not target.is_alive:
                lines.append(f"\U0001f480 {target_name} is defeated!")

        if hit.heal_amount > 0:
            lines.append(
                f"\U0001f49a {actor_name} heals {target_name} "
                f"for {hit.heal_amount} HP!"
            )

    return "\n".join(lines) if lines else f"{actor_name} acts."


def render_turn_batch(
    batch: TurnBatch,
    players: dict[str, PlayerInfo],
) -> str:
    lines: list[str] = []

    for result in batch.results:
        line = render_action_result(result, batch.entities)
        if line:
            lines.append(line)

    return "\n".join(lines)


def render_turn_prompt(
    entity_id: str,
    snapshot: EntitySnapshot,
    players: dict[str, PlayerInfo],
) -> str:
    player = players.get(entity_id)
    name = player.display_name if player else snapshot.name
    return (
        f"\u2694\ufe0f {name}'s turn!\n"
        f"\u2764\ufe0f {snapshot.current_hp}/{snapshot.max_hp}  "
        f"\u26a1 {snapshot.current_energy}/{snapshot.max_energy}"
    )


def render_combat_end(
    batch: TurnBatch,
    players: dict[str, PlayerInfo],
) -> str:
    if batch.victory:
        player_snaps = [
            s for s in batch.entities.values()
            if s.entity_type == EntityType.PLAYER
        ]
        survivor_lines = [
            f"  {s.name}: {s.current_hp}/{s.max_hp} HP"
            for s in player_snaps if s.is_alive
        ]
        return "\U0001f3c6 Victory!\n\nSurvivors:\n" + "\n".join(survivor_lines)

    return "\U0001f480 Defeat! Your party has fallen."


def render_status(
    snapshot: CombatSnapshot,
    players: dict[str, PlayerInfo],
) -> str:
    lines = [f"\u2694\ufe0f Combat \u2014 Round {snapshot.round_number}\n"]

    for eid in snapshot.turn_order:
        snap = snapshot.entities[eid]
        marker = " \u25c0" if eid == snapshot.whose_turn else ""
        lines.append(f"{_entity_line(snap)}{marker}")

    current = snapshot.entities[snapshot.whose_turn]
    lines.append(f"\nWaiting for: {current.name}")

    return "\n".join(lines)
