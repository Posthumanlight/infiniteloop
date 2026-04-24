from dataclasses import dataclass
from typing import Iterable, Sequence

from game.character.enemy import Enemy
from game.character.player_character import PlayerCharacter
from game.core.formula_eval import evaluate_expr
from game.world.difficulty import RoomDifficultyModifier


DEFAULT_ENEMY_XP_FORMULA = "base_xp_reward * difficulty_modifier"


@dataclass(frozen=True)
class CombatXpAward:
    total_enemy_xp: int
    per_player: dict[str, int]

    @property
    def total_awarded_xp(self) -> int:
        return sum(self.per_player.values())


def enemy_xp_reward(
    enemy: Enemy,
    room_difficulty: RoomDifficultyModifier | None,
) -> int:
    formula = enemy.xp_formula or DEFAULT_ENEMY_XP_FORMULA
    difficulty_modifier = room_difficulty.scalar if room_difficulty else 1.0
    raw = evaluate_expr(formula, {
        "base_xp_reward": enemy.base_xp_reward,
        "difficulty_modifier": difficulty_modifier,
    })
    return max(0, round(float(raw)))


def build_combat_xp_award(
    defeated_enemies: Iterable[Enemy],
    players: Sequence[PlayerCharacter],
    room_difficulty: RoomDifficultyModifier | None,
) -> CombatXpAward:
    total = sum(
        enemy_xp_reward(enemy, room_difficulty)
        for enemy in defeated_enemies
    )
    if not players:
        return CombatXpAward(total_enemy_xp=total, per_player={})

    share = total // len(players)
    return CombatXpAward(
        total_enemy_xp=total,
        per_player={player.entity_id: share for player in players},
    )
