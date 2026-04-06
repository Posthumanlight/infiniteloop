import uuid

from game.character.enemy import Enemy
from game.character.inventory import Inventory
from game.character.player_character import PlayerCharacter
from game.character.stats import MajorStats, MinorStats
from game.core.data_loader import load_class, load_enemy
from game.core.enums import EntityType


def build_enemy(enemy_id: str) -> Enemy:
    """Load TOML enemy data and construct a runtime Enemy entity."""
    data = load_enemy(enemy_id)
    major = MajorStats(
        attack=int(data.major_stats["attack"]),
        hp=int(data.major_stats["hp"]),
        speed=int(data.major_stats["speed"]),
        crit_chance=data.major_stats.get("crit_chance", 0.05),
        crit_dmg=data.major_stats.get("crit_dmg", 1.5),
        resistance=int(data.major_stats.get("resistance", 0)),
        energy=int(data.major_stats.get("energy", 50)),
        mastery=int(data.major_stats.get("mastery", 0)),
    )
    minor = MinorStats(values=dict(data.minor_stats))
    return Enemy(
        entity_id=f"{enemy_id}_{uuid.uuid4().hex[:8]}",
        entity_name=data.name,
        entity_type=EntityType.ENEMY,
        major_stats=major,
        minor_stats=minor,
        current_hp=major.hp,
        current_energy=major.energy,
        skills=data.skills,
        xp_reward=data.xp_reward,
    )


def build_enemies(enemy_ids: tuple[str, ...] | list[str]) -> list[Enemy]:
    """Build a list of Enemy instances from TOML IDs."""
    return [build_enemy(eid) for eid in enemy_ids]


def build_player(class_id: str, entity_id: str = "p1") -> PlayerCharacter:
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
    minor = MinorStats(values=dict(cls.minor_stats))
    return PlayerCharacter(
        entity_id=entity_id,
        entity_name=cls.name,
        entity_type=EntityType.PLAYER,
        major_stats=major,
        minor_stats=minor,
        current_hp=major.hp,
        current_energy=major.energy,
        player_class=class_id,
        skills=cls.starting_skills,
        inventory=Inventory(),
    )
