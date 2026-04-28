from dataclasses import dataclass


_VALID_REWARD_KINDS = frozenset({"modifier", "skill", "passive"})


def build_reward_key(reward_kind: str, reward_id: str) -> str:
    if reward_kind not in _VALID_REWARD_KINDS:
        raise ValueError(f"Unknown reward kind: {reward_kind}")
    if not reward_id:
        raise ValueError("Reward id must be non-empty")
    return f"{reward_kind}:{reward_id}"


def parse_reward_key(reward_key: str) -> tuple[str, str]:
    reward_kind, separator, reward_id = reward_key.partition(":")
    if separator != ":" or reward_kind not in _VALID_REWARD_KINDS or not reward_id:
        raise ValueError(f"Invalid reward key: {reward_key}")
    return reward_kind, reward_id

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
class LocationStatusInfo:
    """Display-ready combat location status."""

    status_id: str
    name: str
    description: str


@dataclass(frozen=True)
class CombatSnapshot:
    """Full combat state for /status or initial render."""

    entities: dict[str, EntitySnapshot]
    turn_order: tuple[str, ...]
    whose_turn: str
    round_number: int
    location_name: str
    location_statuses: tuple[LocationStatusInfo, ...] = ()


# ------------------------------------------------------------------
# Character sheet DTOs
# ------------------------------------------------------------------


@dataclass(frozen=True)
class SkillHitInfo:
    """Display-ready per-hit summary."""

    target_type: TargetType
    damage_type: str | None


@dataclass(frozen=True)
class SkillSummaryPart:
    kind: str
    value: str


@dataclass(frozen=True)
class SkillEffectDetail:
    effect_id: str
    name: str
    summary: str
    chance: float | None = None


@dataclass(frozen=True)
class SkillHitDetail:
    index: int
    target_type: TargetType
    damage_type: str | None
    preview_damage_non_crit: int | None
    preview_damage_crit: int | None
    formula: str
    on_hit_effects: tuple[SkillEffectDetail, ...] = ()
    shared_with: int | None = None


@dataclass(frozen=True)
class SkillInfo:
    """Display-ready skill data."""

    skill_id: str
    name: str
    energy_cost: int
    hits: tuple[SkillHitInfo, ...]
    temporary: bool = False
    summary_parts: tuple[SkillSummaryPart, ...] = ()
    preview_note: str = ""
    hit_details: tuple[SkillHitDetail, ...] = ()
    self_effects: tuple[SkillEffectDetail, ...] = ()


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
    """One selectable level-up reward option (modifier, skill, or passive)."""

    reward_key: str
    reward_kind: str
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
    rarity: str
    quality: int
    equipped_slot: str | None
    equipped_index: int | None
    effects: tuple[ItemEffectInfo, ...]
    item_sets: tuple[str, ...] = ()
    item_set_names: tuple[str, ...] = ()
    unique: bool = False


@dataclass(frozen=True)
class ItemSetBonusInfo:
    required_count: int
    active: bool
    effects: tuple[ItemEffectInfo, ...]


@dataclass(frozen=True)
class ItemSetInfo:
    set_id: str
    name: str
    equipped_count: int
    bonuses: tuple[ItemSetBonusInfo, ...]


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
    item_sets: tuple[ItemSetInfo, ...] = ()
    dissolve_currency_name: str = "Fortuna Motes"
    dissolve_rarity_values: dict[str, int] | None = None


@dataclass(frozen=True)
class LootRollInfo:
    player_id: str
    roll: int


@dataclass(frozen=True)
class LootRoundInfo:
    round_index: int
    rolls: tuple[LootRollInfo, ...]


@dataclass(frozen=True)
class LootAwardInfo:
    source_enemy_id: str
    item_blueprint_id: str
    item_name: str
    quality: int
    winner_id: str
    winner_item_instance_id: str
    copy_number: int
    rounds: tuple[LootRoundInfo, ...]


@dataclass(frozen=True)
class LootResolutionSnapshot:
    awards: tuple[LootAwardInfo, ...]
