import uuid
from typing import TYPE_CHECKING

from game.combat.skill_modifiers import ModifierInstance
from game.character.enemy import Enemy
from game.character.inventory import Inventory
from game.character.player_character import PlayerCharacter
from game.character.progression import _apply_stat_gains
from game.character.stats import MajorStats, MinorStats
from game.core.data_loader import ProgressionConfig
from game.core.data_loader import load_class, load_enemy
from game.core.enums import EntityType
from game.world.difficulty import RoomDifficultyModifier, apply_room_difficulty

if TYPE_CHECKING:
    from game.session.lobby_manager import CharacterRecord


def build_enemy(
    enemy_id: str,
    room_difficulty: RoomDifficultyModifier | None = None,
) -> Enemy:
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
    major = apply_room_difficulty(major, room_difficulty)
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
        passive_skills=data.passives,
    )


def build_enemies(
    enemy_ids: tuple[str, ...] | list[str],
    room_difficulty: RoomDifficultyModifier | None = None,
) -> list[Enemy]:
    """Build a list of Enemy instances from TOML IDs."""
    return [build_enemy(eid, room_difficulty=room_difficulty) for eid in enemy_ids]


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
        passive_skills=cls.starting_passives,
        inventory=Inventory(),
    )


def build_player_from_saved(
    record: "CharacterRecord",
    progression: ProgressionConfig,
    base_stats: dict[str, MajorStats],
) -> PlayerCharacter:
    player = build_player(record.class_id, entity_id=str(record.character_id))
    scaling = progression.level_scaling.get(record.class_id)
    stat_gains = scaling.stat_gains if scaling else {}
    scaled_major = _apply_stat_gains(
        base_stats[record.class_id],
        stat_gains,
        max(0, record.level - 1),
    )

    return PlayerCharacter(
        entity_id=player.entity_id,
        entity_name=player.entity_name,
        entity_type=player.entity_type,
        major_stats=scaled_major,
        minor_stats=player.minor_stats,
        current_hp=scaled_major.hp,
        current_energy=scaled_major.energy,
        player_class=player.player_class,
        skills=record.skills,
        passive_skills=player.passive_skills,
        active_effects=player.active_effects,
        skill_modifiers=tuple(
            ModifierInstance(
                modifier_id=modifier.modifier_id,
                stack_count=modifier.stack_count,
            )
            for modifier in record.skill_modifiers
        ),
        inventory=record.inventory,
        level=record.level,
        xp=record.xp,
    )
