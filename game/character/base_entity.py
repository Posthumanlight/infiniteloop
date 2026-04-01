from dataclasses import dataclass

from game.character.stats import MajorStats, MinorStats
from game.core.enums import EntityType


@dataclass(frozen=True)
class BaseEntity:
    entity_id: str
    entity_name: str
    entity_type: EntityType
    major_stats: MajorStats
    minor_stats: MinorStats
    current_hp: int
    current_energy: int
    active_effects: tuple = ()  # tuple[StatusEffectInstance, ...] — forward ref
