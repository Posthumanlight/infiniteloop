from enum import Enum


class DamageType(Enum):
    SLASHING = "slashing"
    PIERCING = "piercing"
    ARCANE = "arcane"
    FIRE = 'fire'
    ICE = 'ice'
    



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


class EventType(Enum):
    SOLO = "solo"
    MULTIPLAYER = "multiplayer"


class EventPhase(Enum):
    PRESENTING = "presenting"
    RESOLVED = "resolved"


class OutcomeAction(Enum):
    HEAL = "heal"
    DAMAGE = "damage"
    RESTORE_ENERGY = "restore_energy"
    DRAIN_ENERGY = "drain_energy"
    GIVE_ITEM = "give_item"
    GIVE_GOLD = "give_gold"
    TAKE_GOLD = "take_gold"
    APPLY_EFFECT = "apply_effect"
    START_COMBAT = "start_combat"
    GIVE_XP = "give_xp"


class OutcomeTarget(Enum):
    VOTER = "voter"
    ALL = "all"
    RANDOM_ONE = "random_one"
