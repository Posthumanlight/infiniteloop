"""Manual console combat: Warrior vs Goblin. Run with: python play.py"""

from game.character.enemy import Enemy
from game.character.inventory import Inventory
from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats, MinorStats
from game.combat.engine import get_available_actions, start_combat, submit_action
from game.combat.models import ActionRequest
from game.core.enums import ActionType, CombatPhase, EntityType


def make_warrior() -> PlayerCharacter:
    return PlayerCharacter(
        entity_id="p1",
        entity_name="Warrior",
        entity_type=EntityType.PLAYER,
        major_stats=MajorStats(
            attack=15, hp=120, speed=10,
            crit_chance=0.05, crit_dmg=1.5,
            resistance=8, energy=100, mastery=5,
        ),
        minor_stats=MinorStats(values={"slashing_dmg_pct": 0.1}),
        current_hp=120,
        current_energy=100,
        player_class="warrior",
        skills=("slash",),
        inventory=Inventory(),
    )


def make_goblin(idx: int) -> Enemy:
    return Enemy(
        entity_id=f"e{idx}",
        entity_name=f"Goblin #{idx}",
        entity_type=EntityType.ENEMY,
        major_stats=MajorStats(
            attack=8, hp=40, speed=14,
            crit_chance=0.08, crit_dmg=1.3,
            resistance=3, energy=50, mastery=2,
        ),
        minor_stats=MinorStats(values={}),
        current_hp=40,
        current_energy=50,
        skills=("slash",),
    )


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


def player_turn(state, actor_id):
    entity = state.entities[actor_id]
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
    """AI: slash a random alive player."""
    players_alive = [
        eid for eid in state.turn_order
        if state.entities[eid].entity_type == EntityType.PLAYER
        and state.entities[eid].current_hp > 0
    ]
    target = players_alive[0]

    action = ActionRequest(
        actor_id=actor_id,
        action_type=ActionType.ACTION,
        skill_id="slash",
        target_id=target,
    )
    return submit_action(state, action)


def print_result(result, state):
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


def main():
    import random
    seed = random.randint(1, 999999)

    warrior = make_warrior()
    goblins = [make_goblin(i + 1) for i in range(2)]

    print("=" * 50)
    print("  COMBAT START!")
    print(f"  Warrior vs {len(goblins)} Goblins  (seed: {seed})")
    print("=" * 50)

    state = start_combat("console", [warrior], goblins, seed=seed)

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

        print_result(result, state)

    print_status(state)
    print("=" * 50)

    player_alive = state.entities["p1"].current_hp > 0
    if player_alive:
        print("  VICTORY! The warrior stands triumphant.")
    else:
        print("  DEFEAT... The warrior has fallen.")
    print("=" * 50)


if __name__ == "__main__":
    main()
