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
    ON_APPLY = "on_apply"
    ON_TURN_START = "on_turn_start"
    ON_TURN_END = "on_turn_end"
    ON_CAST = "on_cast"
    ON_HIT = "on_hit"
    ON_DAMAGE_CALC = "on_damage_calc"
    ON_ROUND_START = "on_round_start"
    ON_TAKE_DAMAGE = "on_take_damage"
    ON_COMBAT_START = "on_combat_start"
    ON_KILL = "on_kill"
    ON_ALLY_DEATH = "on_ally_death"


class EffectActionType(Enum):
    DAMAGE = "damage"
    HEAL = "heal"
    SKIP_TURN = "skip_turn"
    DAMAGE_DEALT_MULT = "damage_dealt_mult"
    DAMAGE_TAKEN_MULT = "damage_taken_mult"
    STAT_MODIFY = "stat_modify"
    GRANT_ENERGY = "grant_energy"


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
    CONSUME_EFFECT = "consume_effect"


class OutcomeTarget(Enum):
    VOTER = "voter"
    ALL = "all"
    RANDOM_ONE = "random_one"


class LocationType(Enum):
    COMBAT = "combat"
    EVENT = "event"


class EnemyCombatType(Enum):
    NORMAL = "normal"
    ELITE = "elite"
    BOSS = "boss"


class CombatLocationType(Enum):
    NORMAL = "normal"
    ELITE = "elite"
    SWARM = "swarm"
    SOLO_BOSS = "solo_boss"
    BOSS_GROUP = "boss_group"


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
    N_PER_TURN = "n_per_turn"
    N_PER_COMBAT = "n_per_combat"


class PassiveAction(Enum):
    APPLY_EFFECT = "apply_effect"
    DAMAGE = "damage"
    HEAL = "heal"
    MODIFY_STAT = "modify_stat"
    CAST_SKILL = "cast_skill"
    CONSUME_EFFECT = "consume_effect"
    GRANT_ENERGY = "grant_energy"


class ModifierPhase(Enum):
    PRE_HIT = "pre_hit"
    POST_HIT = "post_hit"


class LevelRewardType(Enum):
    MODIFIER = "modifier"
    SKILL = "skill"
