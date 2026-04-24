"""Shared fixtures for unit tests."""

import pytest

from game.character.base_entity import BaseEntity
from game.character.enemy import Enemy
from game.character.inventory import Inventory
from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats, MinorStats
from game.combat.models import CombatState
from game.core.enums import CombatPhase, EntityType


def make_warrior(entity_id: str = "p1") -> PlayerCharacter:
    return PlayerCharacter(
        entity_id=entity_id,
        entity_name="TestWarrior",
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


def make_goblin(entity_id: str = "e1") -> Enemy:
    return Enemy(
        entity_id=entity_id,
        entity_name="TestGoblin",
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
        base_xp_reward=15,
    )


def make_combat_state(
    players: list[PlayerCharacter] | None = None,
    enemies: list[Enemy] | None = None,
    turn_order: tuple[str, ...] | None = None,
) -> CombatState:
    if players is None:
        players = [make_warrior()]
    if enemies is None:
        enemies = [make_goblin()]

    entities: dict[str, BaseEntity] = {}
    for p in players:
        entities[p.entity_id] = p
    for e in enemies:
        entities[e.entity_id] = e

    if turn_order is None:
        turn_order = tuple(entities.keys())

    return CombatState(
        combat_id="test-combat",
        session_id="test-session",
        round_number=1,
        turn_order=turn_order,
        current_turn_index=0,
        entities=entities,
        phase=CombatPhase.ACTING,
    )
