from dataclasses import dataclass

from game.character.base_entity import BaseEntity

@dataclass(frozen=True)
class Enemy(BaseEntity):
    enemy_template_id: str = ""
    skills: tuple[str, ...] = ()
    base_xp_reward: int = 0
    xp_formula: str | None = None
    # passive_skills inherited from BaseEntity
