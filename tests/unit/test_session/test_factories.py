import pytest

from game.combat.skill_modifiers import ModifierInstance
from game.character.flags import CharacterFlag
from game.core.data_loader import load_classes, load_progression
from game.core.data_loader import clear_cache
from game.core.enums import EntityType
from game.items.item_generator import generate_item_from_blueprint_id
from game.session.factories import (
    build_enemy,
    build_enemies,
    build_player,
    build_player_from_saved,
)
from game.session.lobby_manager import CharacterRecord
from game.character.stats import MajorStats
from game.character.inventory import Inventory


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


def test_build_enemy_from_toml():
    enemy = build_enemy("goblin")
    assert enemy.entity_type == EntityType.ENEMY
    assert enemy.entity_name == "Goblin"
    assert enemy.current_hp == enemy.major_stats.hp
    assert enemy.current_energy == enemy.major_stats.energy
    assert "slash" in enemy.skills


def test_build_enemy_unique_ids():
    e1 = build_enemy("goblin")
    e2 = build_enemy("goblin")
    assert e1.entity_id != e2.entity_id


def test_build_enemy_unknown_raises():
    with pytest.raises(KeyError):
        build_enemy("nonexistent_monster")


def test_build_enemies_list():
    enemies = build_enemies(("goblin", "skeleton"))
    assert len(enemies) == 2
    assert enemies[0].entity_name == "Goblin"
    assert enemies[1].entity_name == "Skeleton"


def test_build_player_from_toml():
    player = build_player("warrior", "p1")
    assert player.entity_type == EntityType.PLAYER
    assert player.entity_name == "Warrior"
    assert player.entity_id == "p1"
    assert player.player_class == "warrior"
    assert player.current_hp == player.major_stats.hp
    assert "slash" in player.skills


def test_build_player_from_saved_restores_progression_and_modifiers():
    classes = load_classes()
    progression = load_progression()
    base_stats = {
        class_id: MajorStats(
            attack=int(cls.major_stats["attack"]),
            hp=int(cls.major_stats["hp"]),
            speed=int(cls.major_stats["speed"]),
            crit_chance=cls.major_stats["crit_chance"],
            crit_dmg=cls.major_stats["crit_dmg"],
            resistance=int(cls.major_stats.get("resistance", 0)),
            energy=int(cls.major_stats.get("energy", 50)),
            mastery=int(cls.major_stats.get("mastery", 0)),
        )
        for class_id, cls in classes.items()
    }
    sword = generate_item_from_blueprint_id("long_sword", quality=2, instance_id="s1")
    inventory = Inventory().add_item(sword).equip("s1")

    record = CharacterRecord(
        character_id=42,
        tg_id=1001,
        character_name="Aragorn",
        class_id="warrior",
        level=3,
        xp=250,
        skills=("slash", "cleave", "battle_cry"),
        skill_modifiers=(
            ModifierInstance("slash_power", 2),
            ModifierInstance("battle_hardened", 1),
        ),
        inventory=inventory,
        flags={
            "event_choice": CharacterFlag(
                "event_choice",
                {"event": 313, "option": 2},
                True,
            ),
        },
    )

    player = build_player_from_saved(record, progression, base_stats)

    assert player.entity_id == "42"
    assert player.level == 3
    assert player.xp == 250
    assert player.skills == ("slash", "cleave", "battle_cry")
    assert [(mod.modifier_id, mod.stack_count) for mod in player.skill_modifiers] == [
        ("slash_power", 2),
        ("battle_hardened", 1),
    ]
    assert "s1" in player.inventory.items
    assert player.inventory.equipment.weapon_id == "s1"
    assert player.flags == record.flags
    assert player.flags is not record.flags
