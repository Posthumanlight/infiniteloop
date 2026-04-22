"""Renders game state and combat results into formatted Telegram messages.

Pure functions — no aiogram imports. Takes service-layer DTOs, returns strings.
"""

from game.combat.models import ActionResult
from game.core.enums import EntityType
from game.core.game_models import (
    CombatSnapshot,
    EntitySnapshot,
    LootResolutionSnapshot,
    PlayerInfo,
    TurnBatch,
)


def _entity_icon(entity_type: EntityType) -> str:
    match entity_type:
        case EntityType.PLAYER:
            return "\U0001f9d1"  # person
        case EntityType.ALLY:
            return "\U0001f43e"  # paw prints
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
    if snap.entity_type in {EntityType.PLAYER, EntityType.ALLY}:
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
    ally_snaps = [
        snapshot.entities[eid]
        for eid in snapshot.turn_order
        if snapshot.entities[eid].entity_type == EntityType.ALLY
    ]
    enemy_snaps = [
        snapshot.entities[eid]
        for eid in snapshot.turn_order
        if snapshot.entities[eid].entity_type == EntityType.ENEMY
    ]

    for snap in player_snaps:
        lines.append(_entity_line(snap))
    for snap in ally_snaps:
        lines.append(_entity_line(snap))
    for snap in enemy_snaps:
        lines.append(_entity_line(snap))

    # Turn order
    names = [snapshot.entities[eid].name for eid in snapshot.turn_order]
    turn_separator = " \u2192 "
    lines.append(f"\nTurn order: {turn_separator.join(names)}")

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
    default_skill = result.action.skill_id or "attack"

    for summon in result.summons_created:
        lines.append(
            f"\u2728 {actor_name} summons {summon.name}!"
        )

    triggered_pieces: list[str] = []
    for child in result.triggered_actions:
        child_actor = entities.get(child.actor_id)
        child_name = child_actor.name if child_actor else child.actor_id

        for hit in child.hits:
            target = entities.get(hit.target_id)
            target_name = target.name if target else hit.target_id
            if hit.damage is not None:
                triggered_pieces.append(
                    f"{child_name} hits {target_name} for {hit.damage.amount}"
                )

    if result.triggered_actions:
        if triggered_pieces:
            lines.append(
                f"\u2728 {actor_name} uses {default_skill}: " + "; ".join(triggered_pieces)
            )
        else:
            lines.append(
                f"\u2728 {actor_name} uses {default_skill}, but no summons can act."
            )

    for hit in result.hits:
        target = entities.get(hit.target_id)
        target_name = target.name if target else hit.target_id
        skill_name = hit.skill_id or default_skill

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


def _batch_round_number(batch: TurnBatch) -> int | None:
    for result in reversed(batch.results):
        if result.round_number is not None:
            return result.round_number
    return None


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
    lines: list[str] = []
    recap = render_turn_batch(batch, players)
    if recap:
        title = "\u2694\ufe0f Final round recap"
        round_number = _batch_round_number(batch)
        if round_number is not None:
            title += f" - Round {round_number}"
        lines.extend([title, recap, ""])

    if batch.victory:
        player_snaps = [
            s for s in batch.entities.values()
            if s.entity_type == EntityType.PLAYER
        ]
        survivor_lines = [
            f"  {s.name}: {s.current_hp}/{s.max_hp} HP"
            for s in player_snaps if s.is_alive
        ]
        lines.extend(["\U0001f3c6 Victory!", "", "Survivors:"])
        lines.extend(survivor_lines)
        return "\n".join(lines)

    lines.append("\U0001f480 Defeat! Your party has fallen.")
    return "\n".join(lines)


def _chunk_text_blocks(blocks: list[str], max_length: int = 3500) -> list[str]:
    chunks: list[str] = []
    current = ""

    for block in blocks:
        candidate = block if not current else f"{current}\n\n{block}"
        if len(candidate) <= max_length:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = block

    if current:
        chunks.append(current)
    return chunks


def render_loot_resolution(
    loot: LootResolutionSnapshot,
    player_names: dict[str, str],
) -> list[str]:
    if not loot.awards:
        return []

    blocks: list[str] = ["\U0001f381 Loot rolls:"]

    for award in loot.awards:
        lines = [
            (
                f"{award.item_name} [Q{award.quality}] "
                f"from {award.source_enemy_id}"
            ),
        ]
        if award.copy_number > 1:
            lines[0] += f" #{award.copy_number}"

        for round_info in award.rounds:
            roll_text = ", ".join(
                f"{player_names.get(roll.player_id, roll.player_id)} {roll.roll}"
                for roll in round_info.rolls
            )
            lines.append(f"Round {round_info.round_index}: {roll_text}")

        winner_name = player_names.get(award.winner_id, award.winner_id)
        lines.append(f"Winner: {winner_name}")
        blocks.append("\n".join(lines))

    return _chunk_text_blocks(blocks)


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
