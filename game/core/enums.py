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
    ON_TAKE_DAMAGE = "on_take_damage"
    ON_COMBAT_START = "on_combat_start"
    ON_KILL = "on_kill"
    ON_ALLY_DEATH = "on_ally_death"


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


class LocationType(Enum):
    COMBAT = "combat"
    EVENT = "event"


class ExplorationPhase(Enum):
    CHOOSING = "choosing"
    RESOLVING = "resolving"


class SessionPhase(Enum):
    EXPLORING = "exploring"
    IN_COMBAT = "in_combat"
    IN_EVENT = "in_event"
    ENDED = "ended"


class SessionEndReason(Enum):
    PARTY_WIPED = "party_wiped"
    RETREAT = "retreat"
    MAX_DEPTH = "max_depth"


class UsageLimit(Enum):
    UNLIMITED = "unlimited"
    ONCE_PER_TURN = "once_per_turn"
    ONCE_PER_COMBAT = "once_per_combat"
    TWICE_PER_COMBAT = "twice_per_combat"
    N_PER_COMBAT = "n_per_combat"


class PassiveAction(Enum):
    APPLY_EFFECT = "apply_effect"
    DAMAGE = "damage"
    HEAL = "heal"
    MODIFY_STAT = "modify_stat"
    BONUS_DAMAGE = "bonus_damage"


class ModifierPhase(Enum):
    PRE_HIT = "pre_hit"
    POST_HIT = "post_hit"
