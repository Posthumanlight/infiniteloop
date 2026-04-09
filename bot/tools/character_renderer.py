"""Renders a character sheet into a formatted Telegram message.

Pure functions — no aiogram imports. Takes service-layer DTOs, returns strings.
"""

from game.core.game_models import CharacterSheet, EffectInfo


def _format_minor_stat_key(key: str) -> str:
    """Convert 'arcane_dmg_pct' -> 'Arcane DMG' or 'slashing_def_pct' -> 'Slashing DEF'."""
    parts = key.rsplit("_", 2)  # e.g. ['arcane', 'dmg', 'pct']
    if len(parts) == 3:
        element = parts[0].replace("_", " ").title()
        stat_type = parts[1].upper()
        return f"{element} {stat_type}"
    return key.replace("_", " ").title()


def _format_minor_stats(minor_stats: dict[str, float]) -> str:
    entries = []
    for key, val in minor_stats.items():
        if val == 0.0:
            continue
        label = _format_minor_stat_key(key)
        sign = "+" if val > 0 else ""
        entries.append(f"{label} {sign}{val:.0%}")
    return "  ".join(entries) if entries else "(none)"


def _format_effect(effect: EffectInfo) -> str:
    tag = "buff" if effect.is_buff else "debuff"
    stacks = f" x{effect.stack_count}" if effect.stack_count > 1 else ""
    return f"{effect.name}{stacks} ({effect.remaining_duration}t) [{tag}]"


def _format_target_type(value: str) -> str:
    return value.replace("_", " ")


def render_character_sheet(sheet: CharacterSheet) -> str:
    lines: list[str] = []

    # Header
    lines.append(f"--- {sheet.class_name} (Lv.{sheet.level}) ---")
    lines.append(sheet.display_name)
    lines.append("")

    # HP / Energy
    lines.append(
        f"HP: {sheet.current_hp}/{sheet.max_hp}  "
        f"Energy: {sheet.current_energy}/{sheet.max_energy}"
    )
    if sheet.xp > 0:
        lines.append(f"XP: {sheet.xp}")
    lines.append("")

    # Major stats
    ms = sheet.major_stats
    lines.append("-- Stats --")
    lines.append(
        f"ATK: {ms.get('attack', 0):.0f}  "
        f"SPD: {ms.get('speed', 0):.0f}  "
        f"RES: {ms.get('resistance', 0):.0f}"
    )
    crit = ms.get("crit_chance", 0)
    crit_dmg = ms.get("crit_dmg", 0)
    lines.append(
        f"CRIT: {crit:.0%} (x{crit_dmg:.2f})  "
        f"MST: {ms.get('mastery', 0):.0f}"
    )
    lines.append("")

    # Minor stats
    minor_text = _format_minor_stats(sheet.minor_stats)
    if minor_text != "(none)":
        lines.append("-- Damage Bonuses --")
        lines.append(minor_text)
        lines.append("")

    # Skills
    lines.append("-- Skills --")
    if sheet.skills:
        for sk in sheet.skills:
            cost = f" ({sk.energy_cost} energy)" if sk.energy_cost > 0 else ""
            dmg = f", {sk.damage_type}" if sk.damage_type else ""
            target = _format_target_type(sk.target_type.value)
            lines.append(f"{sk.name}{cost} - {target}{dmg}")
    else:
        lines.append("(none)")
    lines.append("")

    # Passives
    if sheet.passives:
        lines.append("-- Passives --")
        for ps in sheet.passives:
            trigger = ps.trigger.replace("_", " ")
            lines.append(f"{ps.name} - {trigger}")
        lines.append("")

    # Modifiers
    if sheet.modifiers:
        lines.append("-- Modifiers --")
        for mod in sheet.modifiers:
            stacks = f" x{mod.stack_count}" if mod.stack_count > 1 else ""
            lines.append(f"{mod.name}{stacks}")
        lines.append("")

    # Active effects
    lines.append("-- Active Effects --")
    if sheet.active_effects:
        for eff in sheet.active_effects:
            lines.append(_format_effect(eff))
    else:
        lines.append("(none)")

    return "\n".join(lines)
