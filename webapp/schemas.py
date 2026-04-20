"""Pydantic schemas for the Mini App API."""

from pydantic import BaseModel

from game.core.game_models import CharacterSheet, InventorySnapshot


class CharacterBootstrapIn(BaseModel):
    init_data: str


class WebAppBootstrapIn(BaseModel):
    init_data: str


class SkillHitOut(BaseModel):
    target_type: str
    damage_type: str | None


class SkillSummaryPartOut(BaseModel):
    kind: str
    value: str


class SkillEffectDetailOut(BaseModel):
    effect_id: str
    name: str
    summary: str
    chance: float | None = None


class SkillHitDetailOut(BaseModel):
    index: int
    target_type: str
    damage_type: str | None
    preview_damage_non_crit: int | None
    preview_damage_crit: int | None
    formula: str
    on_hit_effects: list[SkillEffectDetailOut]
    shared_with: int | None = None


class SkillOut(BaseModel):
    skill_id: str
    name: str
    energy_cost: int
    hits: list[SkillHitOut]
    temporary: bool
    summary_parts: list[SkillSummaryPartOut]
    preview_note: str
    hit_details: list[SkillHitDetailOut]
    self_effects: list[SkillEffectDetailOut]


class PassiveOut(BaseModel):
    skill_id: str
    name: str
    triggers: list[str]
    action: str


class ModifierOut(BaseModel):
    modifier_id: str
    name: str
    stack_count: int


class EffectOut(BaseModel):
    effect_id: str
    name: str
    remaining_duration: int
    stack_count: int
    is_buff: bool
    granted_skills: list[str]
    blocked_skills: list[str]


class CharacterSheetOut(BaseModel):
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
    skills: list[SkillOut]
    passives: list[PassiveOut]
    modifiers: list[ModifierOut]
    active_effects: list[EffectOut]
    in_combat: bool

    @classmethod
    def from_domain(cls, sheet: CharacterSheet) -> "CharacterSheetOut":
        return cls(
            entity_id=sheet.entity_id,
            display_name=sheet.display_name,
            class_id=sheet.class_id,
            class_name=sheet.class_name,
            level=sheet.level,
            xp=sheet.xp,
            current_hp=sheet.current_hp,
            max_hp=sheet.max_hp,
            current_energy=sheet.current_energy,
            max_energy=sheet.max_energy,
            major_stats=sheet.major_stats,
            minor_stats=sheet.minor_stats,
            skills=[
                SkillOut(
                    skill_id=skill.skill_id,
                    name=skill.name,
                    energy_cost=skill.energy_cost,
                    temporary=skill.temporary,
                    summary_parts=[
                        SkillSummaryPartOut(kind=part.kind, value=part.value)
                        for part in skill.summary_parts
                    ],
                    preview_note=skill.preview_note,
                    hits=[
                        SkillHitOut(
                            target_type=hit.target_type.value,
                            damage_type=hit.damage_type,
                        )
                        for hit in skill.hits
                    ],
                    hit_details=[
                        SkillHitDetailOut(
                            index=detail.index,
                            target_type=detail.target_type.value,
                            damage_type=detail.damage_type,
                            preview_damage_non_crit=detail.preview_damage_non_crit,
                            preview_damage_crit=detail.preview_damage_crit,
                            formula=detail.formula,
                            on_hit_effects=[
                                SkillEffectDetailOut(
                                    effect_id=effect.effect_id,
                                    name=effect.name,
                                    summary=effect.summary,
                                    chance=effect.chance,
                                )
                                for effect in detail.on_hit_effects
                            ],
                            shared_with=detail.shared_with,
                        )
                        for detail in skill.hit_details
                    ],
                    self_effects=[
                        SkillEffectDetailOut(
                            effect_id=effect.effect_id,
                            name=effect.name,
                            summary=effect.summary,
                            chance=effect.chance,
                        )
                        for effect in skill.self_effects
                    ],
                )
                for skill in sheet.skills
            ],
            passives=[
                PassiveOut(
                    skill_id=passive.skill_id,
                    name=passive.name,
                    triggers=list(passive.triggers),
                    action=passive.action,
                )
                for passive in sheet.passives
            ],
            modifiers=[
                ModifierOut(
                    modifier_id=modifier.modifier_id,
                    name=modifier.name,
                    stack_count=modifier.stack_count,
                )
                for modifier in sheet.modifiers
            ],
            active_effects=[
                EffectOut(
                    effect_id=effect.effect_id,
                    name=effect.name,
                    remaining_duration=effect.remaining_duration,
                    stack_count=effect.stack_count,
                    is_buff=effect.is_buff,
                    granted_skills=list(effect.granted_skills),
                    blocked_skills=list(effect.blocked_skills),
                )
                for effect in sheet.active_effects
            ],
            in_combat=sheet.in_combat,
        )


class ItemEffectOut(BaseModel):
    effect_type: str
    stat: str | None = None
    value: float | None = None
    skill_id: str | None = None
    passive_id: str | None = None


class ItemOut(BaseModel):
    instance_id: str
    blueprint_id: str
    name: str
    item_type: str
    quality: int
    equipped_slot: str | None
    equipped_index: int | None
    effects: list[ItemEffectOut]
    item_sets: list[str]
    item_set_names: list[str]
    unique: bool


class EquipmentSlotOut(BaseModel):
    slot_type: str
    slot_index: int | None
    label: str
    accepts_item_type: str
    item: ItemOut | None


class ItemSetBonusOut(BaseModel):
    required_count: int
    active: bool
    effects: list[ItemEffectOut]


class ItemSetOut(BaseModel):
    set_id: str
    name: str
    equipped_count: int
    bonuses: list[ItemSetBonusOut]


class InventoryOut(BaseModel):
    items: list[ItemOut]
    unequipped_items: list[ItemOut]
    equipment_slots: list[EquipmentSlotOut]
    item_sets: list[ItemSetOut]
    can_manage_equipment: bool
    equipment_lock_reason: str | None

    @classmethod
    def from_domain(cls, snapshot: InventorySnapshot) -> "InventoryOut":
        item_lookup = {
            item.instance_id: ItemOut(
                instance_id=item.instance_id,
                blueprint_id=item.blueprint_id,
                name=item.name,
                item_type=item.item_type,
                quality=item.quality,
                equipped_slot=item.equipped_slot,
                equipped_index=item.equipped_index,
                effects=[
                    ItemEffectOut(
                        effect_type=effect.effect_type,
                        stat=effect.stat,
                        value=effect.value,
                        skill_id=effect.skill_id,
                        passive_id=effect.passive_id,
                    )
                    for effect in item.effects
                ],
                item_sets=list(item.item_sets),
                item_set_names=list(item.item_set_names),
                unique=item.unique,
            )
            for item in snapshot.items
        }
        return cls(
            items=list(item_lookup.values()),
            unequipped_items=[
                item_lookup[item.instance_id]
                for item in snapshot.unequipped_items
            ],
            equipment_slots=[
                EquipmentSlotOut(
                    slot_type=slot.slot_type,
                    slot_index=slot.slot_index,
                    label=slot.label,
                    accepts_item_type=slot.accepts_item_type,
                    item=(
                        item_lookup[slot.item.instance_id]
                        if slot.item is not None else None
                    ),
                )
                for slot in snapshot.equipment_slots
            ],
            item_sets=[
                ItemSetOut(
                    set_id=item_set.set_id,
                    name=item_set.name,
                    equipped_count=item_set.equipped_count,
                    bonuses=[
                        ItemSetBonusOut(
                            required_count=bonus.required_count,
                            active=bonus.active,
                            effects=[
                                ItemEffectOut(
                                    effect_type=effect.effect_type,
                                    stat=effect.stat,
                                    value=effect.value,
                                    skill_id=effect.skill_id,
                                    passive_id=effect.passive_id,
                                )
                                for effect in bonus.effects
                            ],
                        )
                        for bonus in item_set.bonuses
                    ],
                )
                for item_set in snapshot.item_sets
            ],
            can_manage_equipment=snapshot.can_manage_equipment,
            equipment_lock_reason=snapshot.equipment_lock_reason,
        )


class CharacterBootstrapOut(BaseModel):
    sheet: CharacterSheetOut
    legacy_text: str


class WebAppBootstrapOut(BaseModel):
    initial_view: str
    sheet: CharacterSheetOut
    inventory: InventoryOut
    legacy_text: str


class InventoryMoveIn(BaseModel):
    init_data: str
    instance_id: str
    destination_kind: str
    slot_type: str | None = None
    slot_index: int | None = None


class InventoryMoveOut(BaseModel):
    sheet: CharacterSheetOut
    inventory: InventoryOut
