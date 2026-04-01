from dataclasses import dataclass

from game.character.base_entity import BaseEntity
from game.character.inventory import Inventory


@dataclass(frozen=True)
class PlayerCharacter(BaseEntity):
    player_class: str = ""
    skills: tuple[str, ...] = ()
    inventory: Inventory = None  # type: ignore[assignment] — caller must provide
    level: int = 1
    xp: int = 0
