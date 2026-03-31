from game.character.base_entity import BaseEntity
from dataclasses import dataclass

@dataclass
class PlayerCharacter(BaseEntity):
    player_class: str
    items: dict
    skills : dict

