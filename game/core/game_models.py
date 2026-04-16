from dataclasses import dataclass

from game.combat.models import ActionResult
from game.core.enums import EntityType, LevelRewardType, TargetType


@dataclass(frozen=True)
class PlayerInfo:
    """Identity mapping between Telegram user and game entity."""

    entity_id: str  # str(tg_user_id)
    tg_user_id: int
    display_name: str  # Telegram first_name
    class_id: str | None = None


@dataclass(frozen=True)
class EntitySnapshot:
    """Minimal view of an entity for display purposes."""

    entity_id: str
    name: str
    entity_type: EntityType
    current_hp: int
    max_hp: int
    current_energy: int
    max_energy: int
    is_alive: bool


@dataclass(frozen=True)
class TurnBatch:
    """Result of a player submitting an action.

    Contains the player's action result plus any auto-played enemy actions
    that followed before the next player turn.
    """

    results: tuple[ActionResult, ...]
    entities: dict[str, EntitySnapshot]
    whose_turn: str | None  # None if combat ended
    combat_ended: bool
    victory: bool


@dataclass(frozen=True)
class CombatSnapshot:
    """Full combat state for /status or initial render."""

    entities: dict[str, EntitySnapshot]
    turn_order: tuple[str, ...]
    whose_turn: str
    round_number: int


# ------------------------------------------------------------------
# Character sheet DTOs
# ------------------------------------------------------------------


@dataclass(frozen=True)
class SkillHitInfo:
    """Display-ready per-hit summary."""

    target_type: TargetType
    damage_type: str | None


@dataclass(frozen=True)
class SkillInfo:
    """Display-ready skill data."""

    skill_id: str
    name: str
    energy_cost: int
    hits: tuple[SkillHitInfo, ...]
    temporary: bool = False


@dataclass(frozen=True)
class PassiveInfo:
    """Display-ready passive skill data."""

    skill_id: str
    name: str
    triggers: tuple[str, ...]
    action: str


@dataclass(frozen=True)
class ModifierInfo:
    """Display-ready skill modifier data."""

    modifier_id: str
    name: str
    stack_count: int


@dataclass(frozen=True)
class RewardOfferInfo:
    """One selectable level-up reward option (modifier or skill)."""

    reward_id: str
    name: str
    description: str = ""


@dataclass(frozen=True)
class PendingRewardInfo:
    """Current pending level-up reward for a player."""

    player_id: str
    reward_type: LevelRewardType
    pending_count: int
    offers: tuple[RewardOfferInfo, ...]


@dataclass(frozen=True)
class RewardNoticeInfo:
    """Informational message about skipped pending picks."""

    player_id: str
    reward_type: LevelRewardType
    skipped_count: int


@dataclass(frozen=True)
class EffectInfo:
    """Display-ready status effect data."""

    effect_id: str
    name: str
    remaining_duration: int
    stack_count: int
    is_buff: bool
    granted_skills: tuple[str, ...] = ()
    blocked_skills: tuple[str, ...] = ()


@dataclass(frozen=True)
class CharacterSheet:
    """Full character state for display."""

    entity_id: str
    display_name: str
    class_id: str
    class_name: str
    level: int
    xp: int
    current_hp: int
    max_hp: int
    current_energy: int
    max_energy: int
    major_stats: dict[str, float]
    minor_stats: dict[str, float]
    skills: tuple[SkillInfo, ...]
    passives: tuple[PassiveInfo, ...]
    modifiers: tuple[ModifierInfo, ...]
    active_effects: tuple[EffectInfo, ...]
    in_combat: bool


@dataclass(frozen=True)
class ItemEffectInfo:
    effect_type: str
    stat: str | None = None
    value: float | None = None
    skill_id: str | None = None
    passive_id: str | None = None


@dataclass(frozen=True)
class ItemInfo:
    instance_id: str
    blueprint_id: str
    name: str
    item_type: str
    quality: int
    equipped_slot: str | None
    equipped_index: int | None
    effects: tuple[ItemEffectInfo, ...]


@dataclass(frozen=True)
class EquipmentSlotInfo:
    slot_type: str
    slot_index: int | None
    label: str
    accepts_item_type: str
    item: ItemInfo | None


@dataclass(frozen=True)
class InventorySnapshot:
    items: tuple[ItemInfo, ...]
    unequipped_items: tuple[ItemInfo, ...]
    equipment_slots: tuple[EquipmentSlotInfo, ...]
    can_manage_equipment: bool
    equipment_lock_reason: str | None = None
