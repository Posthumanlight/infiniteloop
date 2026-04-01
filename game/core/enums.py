from enum import Enum


class DamageType(Enum):
    SLASHING = "slashing"


class TargetType(Enum):
    SINGLE_ENEMY = "single_enemy"
    ALL_ENEMIES = "all_enemies"
    SINGLE_ALLY = "single_ally"
    ALL_ALLIES = "all_allies"
    SELF = "self"


class ActionType(Enum):
    ACTION = "action"
    ITEM = "item"


class TriggerType(Enum):
    ON_TURN_START = "on_turn_start"
    ON_TURN_END = "on_turn_end"
    ON_HIT = "on_hit"
    ON_DAMAGE_CALC = "on_damage_calc"
    ON_ROUND_START = "on_round_start"


class EffectAction(Enum):
    DAMAGE = "damage"
    HEAL = "heal"
    BUFF = "buff"
    DEBUFF = "debuff"


class CombatPhase(Enum):
    ACTING = "acting"
    ROUND_END = "round_end"
    ENDED = "ended"


class EntityType(Enum):
    PLAYER = "player"
    ENEMY = "enemy"
