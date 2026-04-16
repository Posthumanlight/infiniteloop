"""Pydantic schemas for the Mini App API."""

from pydantic import BaseModel

from game.core.game_models import CharacterSheet


class CharacterBootstrapIn(BaseModel):
    init_data: str


class SkillHitOut(BaseModel):
    target_type: str
    damage_type: str | None


class SkillOut(BaseModel):
    skill_id: str
    name: str
    energy_cost: int
    hits: list[SkillHitOut]
    temporary: bool


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
                    hits=[
                        SkillHitOut(
                            target_type=hit.target_type.value,
                            damage_type=hit.damage_type,
                        )
                        for hit in skill.hits
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


class CharacterBootstrapOut(BaseModel):
    sheet: CharacterSheetOut
    legacy_text: str
