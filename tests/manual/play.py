"""Manual console play: exploration loop with combat and events.

Run with: python -m tests.manual.play
"""

import random

from game.character.enemy import Enemy
from game.character.inventory import Inventory
from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats, MinorStats
from game.combat.engine import get_available_actions, start_combat, submit_action
from game.combat.models import ActionRequest
from game.core.data_loader import (
    LocationOption,
    clear_cache,
    load_class,
    load_enemy,
    load_event,
)
from game.core.enums import (
    ActionType,
    CombatPhase,
    EntityType,
    LocationType,
    OutcomeAction,
)
from game.events.engine import resolve_event, start_event, submit_vote
from game.world.world_run import (
    compute_power,
    generate_choices,
    resolve_location_choice,
    start_run,
    submit_location_vote,
)
from game.world.models import GenerationConfig


# ---------------------------------------------------------------------------
# Character creation from TOML data
# ---------------------------------------------------------------------------

def make_player_from_class(class_id: str, entity_id: str = "p1") -> PlayerCharacter:
    """Build a PlayerCharacter from TOML class data."""
    cls = load_class(class_id)
    major = MajorStats(
        attack=int(cls.major_stats["attack"]),
        hp=int(cls.major_stats["hp"]),
        speed=int(cls.major_stats["speed"]),
        crit_chance=cls.major_stats["crit_chance"],
        crit_dmg=cls.major_stats["crit_dmg"],
        resistance=int(cls.major_stats["resistance"]),
        energy=int(cls.major_stats["energy"]),
        mastery=int(cls.major_stats["mastery"]),
    )
    minor = MinorStats(values={k: v for k, v in cls.minor_stats.items()})
    return PlayerCharacter(
        entity_id=entity_id,
        entity_name=cls.name,
        entity_type=EntityType.PLAYER,
        major_stats=major,
        minor_stats=minor,
        current_hp=int(cls.major_stats["hp"]),
        current_energy=int(cls.major_stats["energy"]),
        player_class=class_id,
        skills=cls.starting_skills,
        inventory=Inventory(),
    )


def make_enemy_from_data(enemy_id: str, index: int) -> Enemy:
    """Build an Enemy from TOML enemy data."""
    edata = load_enemy(enemy_id)
    major = MajorStats(
        attack=int(edata.major_stats["attack"]),
        hp=int(edata.major_stats["hp"]),
        speed=int(edata.major_stats["speed"]),
        crit_chance=edata.major_stats["crit_chance"],
        crit_dmg=edata.major_stats["crit_dmg"],
        resistance=int(edata.major_stats["resistance"]),
        energy=int(edata.major_stats["energy"]),
        mastery=int(edata.major_stats["mastery"]),
    )
    minor = MinorStats(values={k: v for k, v in edata.minor_stats.items()})
    return Enemy(
        entity_id=f"e{index}",
        entity_name=f"{edata.name} #{index}",
        entity_type=EntityType.ENEMY,
        major_stats=major,
        minor_stats=minor,
        current_hp=int(edata.major_stats["hp"]),
        current_energy=int(edata.major_stats["energy"]),
        skills=edata.skills,
    )


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def hp_bar(current: int, maximum: int, width: int = 20) -> str:
    ratio = max(0, current / maximum)
    filled = int(ratio * width)
    return f"[{'#' * filled}{'.' * (width - filled)}] {current}/{maximum}"


def print_status(state):
    print("\n--- Battlefield ---")
    for eid in state.turn_order:
        e = state.entities[eid]
        marker = " <<" if eid == state.turn_order[state.current_turn_index] else ""
        tag = "PLAYER" if e.entity_type == EntityType.PLAYER else "ENEMY "
        bar = hp_bar(e.current_hp, e.major_stats.hp)
        effects = ""
        if e.active_effects:
            names = [f.effect_id for f in e.active_effects]
            effects = f"  [{', '.join(names)}]"
        print(f"  {tag} {e.entity_name:15s} HP {bar}  E:{e.current_energy}{effects}{marker}")
    print()


def print_combat_result(result, state):
    actor = state.entities.get(result.actor_id)
    name = actor.entity_name if actor else result.actor_id

    if result.skipped:
        print(f"  {name} is stunned! Turn skipped.")
        return

    for hit in result.hits:
        target = state.entities.get(hit.target_id)
        tname = target.entity_name if target else hit.target_id
        if hit.damage:
            crit = " CRITICAL!" if hit.damage.is_crit else ""
            print(f"  {name} hits {tname} for {hit.damage.amount} {hit.damage.damage_type.value} damage!{crit}")
        if hit.heal_amount:
            print(f"  {name} heals {tname} for {hit.heal_amount} HP!")
        if hit.effects_applied:
            print(f"    Applied: {', '.join(hit.effects_applied)}")


# ---------------------------------------------------------------------------
# Combat loop
# ---------------------------------------------------------------------------

def player_turn(state, actor_id):
    skills = get_available_actions(state, actor_id)

    enemies_alive = [
        eid for eid in state.turn_order
        if state.entities[eid].entity_type == EntityType.ENEMY
        and state.entities[eid].current_hp > 0
    ]

    print(f"  Your skills:")
    for i, s in enumerate(skills):
        cost = f" (energy: {s.energy_cost})" if s.energy_cost > 0 else ""
        print(f"    [{i + 1}] {s.name}{cost}")

    while True:
        try:
            choice = input("  Pick skill [1]: ").strip()
            idx = int(choice) - 1 if choice else 0
            skill = skills[idx]
            break
        except (ValueError, IndexError):
            print("  Invalid choice, try again.")

    target_id = None
    if skill.target_type.value == "single_enemy":
        print(f"  Targets:")
        for i, eid in enumerate(enemies_alive):
            e = state.entities[eid]
            print(f"    [{i + 1}] {e.entity_name} ({e.current_hp}/{e.major_stats.hp} HP)")
        while True:
            try:
                tc = input("  Pick target [1]: ").strip()
                ti = int(tc) - 1 if tc else 0
                target_id = enemies_alive[ti]
                break
            except (ValueError, IndexError):
                print("  Invalid target, try again.")

    action = ActionRequest(
        actor_id=actor_id,
        action_type=ActionType.ACTION,
        skill_id=skill.skill_id,
        target_id=target_id,
    )
    return submit_action(state, action)


def enemy_turn(state, actor_id):
    """AI: use first skill on a random alive player."""
    entity = state.entities[actor_id]
    players_alive = [
        eid for eid in state.turn_order
        if state.entities[eid].entity_type == EntityType.PLAYER
        and state.entities[eid].current_hp > 0
    ]
    target = players_alive[0]
    skill_id = entity.skills[0] if entity.skills else "slash"

    action = ActionRequest(
        actor_id=actor_id,
        action_type=ActionType.ACTION,
        skill_id=skill_id,
        target_id=target,
    )
    return submit_action(state, action)


def run_combat(player: PlayerCharacter, location: LocationOption, seed: int) -> bool:
    """Run a combat encounter. Returns True if player survives."""
    enemies = []
    for i, enemy_id in enumerate(location.enemy_ids):
        enemies.append(make_enemy_from_data(enemy_id, i + 1))

    if not enemies:
        print("  No enemies here. Moving on...")
        return True

    enemy_names = ", ".join(e.entity_name for e in enemies)
    print(f"\n{'=' * 50}")
    print(f"  COMBAT: {location.name}")
    print(f"  Enemies: {enemy_names}")
    if location.status_ids:
        print(f"  Location effects: {', '.join(location.status_ids)}")
    print(f"{'=' * 50}")

    state = start_combat("console", [player], enemies, seed=seed)

    turn_num = 0
    while state.phase != CombatPhase.ENDED:
        turn_num += 1
        current_id = state.turn_order[state.current_turn_index]
        entity = state.entities[current_id]

        print_status(state)
        print(f"-- Round {state.round_number}, Turn {turn_num}: {entity.entity_name} --")

        if entity.entity_type == EntityType.PLAYER:
            state, result = player_turn(state, current_id)
        else:
            state, result = enemy_turn(state, current_id)

        print_combat_result(result, state)

    print_status(state)

    player_alive = state.entities[player.entity_id].current_hp > 0
    if player_alive:
        print("  VICTORY!")
    else:
        print("  DEFEAT...")
    print(f"{'=' * 50}")
    return player_alive


# ---------------------------------------------------------------------------
# Event handling
# ---------------------------------------------------------------------------

def run_event(player: PlayerCharacter, location: LocationOption, seed: int):
    """Run an event encounter."""
    if not location.event_id:
        print("  Empty event. Moving on...")
        return

    event_def = load_event(location.event_id)

    print(f"\n{'=' * 50}")
    print(f"  EVENT: {event_def.name}")
    print(f"  {event_def.description}")
    print(f"{'=' * 50}")

    event_state = start_event("console", event_def, [player.entity_id], seed)

    print("\n  Choices:")
    for choice in event_def.choices:
        print(f"    [{choice.index + 1}] {choice.label}")
        print(f"        {choice.description}")

    while True:
        try:
            raw = input(f"  Pick choice [1-{len(event_def.choices)}]: ").strip()
            choice_idx = int(raw) - 1 if raw else 0
            if 0 <= choice_idx < len(event_def.choices):
                break
            print("  Invalid choice.")
        except ValueError:
            print("  Invalid choice.")

    event_state = submit_vote(event_state, player.entity_id, choice_idx)
    event_state, resolution = resolve_event(event_state, [player])

    print(f"\n  You chose: {resolution.winning_choice_label}")
    if resolution.outcomes:
        for outcome in resolution.outcomes:
            _print_outcome(outcome)
    else:
        print("  Nothing happens.")


def _print_outcome(outcome):
    """Display a single outcome result."""
    match outcome.action:
        case OutcomeAction.HEAL:
            print(f"  -> Healed for {outcome.amount} HP")
        case OutcomeAction.DAMAGE:
            print(f"  -> Took {outcome.amount} damage")
        case OutcomeAction.RESTORE_ENERGY:
            print(f"  -> Restored {outcome.amount} energy")
        case OutcomeAction.DRAIN_ENERGY:
            print(f"  -> Lost {outcome.amount} energy")
        case OutcomeAction.GIVE_GOLD:
            print(f"  -> Gained {outcome.amount} gold")
        case OutcomeAction.TAKE_GOLD:
            print(f"  -> Lost {outcome.amount} gold")
        case OutcomeAction.GIVE_XP:
            print(f"  -> Gained {outcome.amount} XP")
        case OutcomeAction.GIVE_ITEM:
            print(f"  -> Received item: {outcome.item_id}")
        case OutcomeAction.APPLY_EFFECT:
            print(f"  -> Effect applied: {outcome.effect_id}")
        case OutcomeAction.START_COMBAT:
            enemies = ", ".join(outcome.enemy_group) if outcome.enemy_group else "unknown"
            print(f"  -> Ambush! Enemies: {enemies}")


# ---------------------------------------------------------------------------
# Exploration loop
# ---------------------------------------------------------------------------

def run_exploration():
    clear_cache()
    seed = random.randint(1, 999999)

    player = make_player_from_class("warrior")
    power = compute_power([player])
    config = GenerationConfig(count_min=2, count_max=4, combat_weight=0.6)

    print("=" * 50)
    print(f"  EXPLORATION START  (seed: {seed})")
    print(f"  Class: {player.entity_name}  HP: {player.current_hp}  Power: {power}")
    print("=" * 50)

    exploration = start_run("console", [player.entity_id], seed)

    while True:
        # Generate location choices
        exploration = generate_choices(exploration, power, [player], config)
        options = exploration.current_options

        print(f"\n--- Depth {exploration.depth + 1} ---")
        print("  Where do you want to go?\n")
        for i, loc in enumerate(options):
            loc_type = loc.location_type.value.upper()
            details = ""
            if loc.location_type == LocationType.COMBAT and loc.enemy_ids:
                details = f" (enemies: {', '.join(loc.enemy_ids)})"
            elif loc.location_type == LocationType.EVENT and loc.event_id:
                details = f" (event: {loc.event_id})"
            print(f"    [{i + 1}] [{loc_type}] {loc.name}{details}")

        # Player picks a location
        while True:
            try:
                raw = input(f"\n  Choose location [1-{len(options)}]: ").strip()
                loc_idx = int(raw) - 1 if raw else 0
                if 0 <= loc_idx < len(options):
                    break
                print("  Invalid choice.")
            except ValueError:
                print("  Invalid choice.")

        exploration = submit_location_vote(exploration, player.entity_id, loc_idx)
        exploration, picked = resolve_location_choice(exploration)

        print(f"\n  >> Entering: {picked.name}")

        # Resolve the location
        location_seed = seed + exploration.depth
        if picked.location_type == LocationType.COMBAT:
            alive = run_combat(player, picked, location_seed)
            if not alive:
                print("\n  Your adventure ends here.")
                break
        elif picked.location_type == LocationType.EVENT:
            run_event(player, picked, location_seed)

        # Continue?
        again = input("\n  Continue exploring? [Y/n]: ").strip().lower()
        if again == "n":
            print(f"\n  You retreat after exploring {exploration.depth} rooms.")
            break

    print("\n  Thanks for playing!")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    run_exploration()
