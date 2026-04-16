from dataclasses import dataclass
from typing import TYPE_CHECKING

from game.character.stats import MajorStats, MinorStats
from game.core.enums import EntityType

if TYPE_CHECKING:
    from game.combat.skill_modifiers import ModifierInstance


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
    passive_skills: tuple[str, ...] = ()
    skill_modifiers: tuple[ModifierInstance, ...] = ()  # type: ignore[type-arg]
