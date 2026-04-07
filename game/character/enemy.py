from dataclasses import dataclass

from game.character.base_entity import BaseEntity

@dataclass(frozen=True)
class Enemy(BaseEntity):
    skills: tuple[str, ...] = ()
    xp_reward: int = 0
    # passive_skills inherited from BaseEntity
