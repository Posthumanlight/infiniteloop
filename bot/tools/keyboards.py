from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from bot.tools.location_labels import location_display_label

if TYPE_CHECKING:
    from game.core.data_loader import ClassData, LocationOption, SkillData
    from game.events.models import ChoiceDef
    from game.core.game_models import EntitySnapshot, RewardOfferInfo


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\u2699\ufe0f \u041d\u0430\u043b\u0430\u0448\u0442\u0443\u0432\u0430\u043d\u043d\u044f", callback_data="open_settings"),
            ],
        ]
    )

def confirm_keyboard(yes_callback: str, no_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\u2705 \u0422\u0430\u043a", callback_data=yes_callback),
                InlineKeyboardButton(text="\u274c \u041d\u0456", callback_data=no_callback),
            ]
        ]
    )


# ------------------------------------------------------------------
# Game keyboards
# ------------------------------------------------------------------

def join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="\u2694\ufe0f Join", callback_data="g:join")],
        ]
    )


def lobby_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="\u2694\ufe0f Join", callback_data="g:join"),
                InlineKeyboardButton(text="\U0001f5e1\ufe0f Start Run", callback_data="g:start"),
            ],
        ]
    )


def skill_keyboard(
    skills: list[tuple[SkillData, int]],
    current_energy: int | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for skill, cd in skills:
        if cd > 0:
            text = f"{skill.name} (CD: {cd})"
        elif current_energy is not None and current_energy < skill.energy_cost:
            text = f"{skill.name} (\u26a1{skill.energy_cost}, no energy)"
        elif skill.energy_cost > 0:
            text = f"{skill.name} (\u26a1{skill.energy_cost})"
        else:
            text = skill.name
        rows.append([InlineKeyboardButton(
            text=text,
            callback_data=f"g:sk:{skill.skill_id}",
        )])
    rows.append([InlineKeyboardButton(text="\u23ed\ufe0f Skip", callback_data="g:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def target_keyboard(enemies: list[EntitySnapshot]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{e.name} ({e.current_hp}/{e.max_hp} HP)",
            callback_data=f"g:tg:{e.entity_id}",
        )]
        for e in enemies
        if e.is_alive
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def class_select_keyboard(classes: dict[str, ClassData]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{cls.name} — {cls.description}",
            callback_data=f"g:class:{cls.class_id}",
        )]
        for cls in classes.values()
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def location_keyboard(options: tuple[LocationOption, ...]) -> InlineKeyboardMarkup:
    from game.core.enums import LocationType
    icons = {LocationType.COMBAT: "\u2694\ufe0f", LocationType.EVENT: "\U0001f4dc"}
    unknown_icon = "\u2753"
    rows = [
        [InlineKeyboardButton(
            text=f"{icons.get(opt.location_type, unknown_icon)} {location_display_label(opt)}",
            callback_data=f"g:loc:{i}",
        )]
        for i, opt in enumerate(options)
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def event_choice_keyboard(choices: tuple[ChoiceDef, ...]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=choice.label,
            callback_data=f"g:evt:{choice.index}",
        )]
        for choice in choices
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def reward_choice_keyboard(
    offers: tuple[RewardOfferInfo, ...],
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=offer.name,
            callback_data=f"g:rwd:{offer.reward_id}",
        )]
        for offer in offers
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def save_decision_keyboard(entity_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Save",
                callback_data=f"g:save:yes:{entity_id}",
            ),
            InlineKeyboardButton(
                text="Don't Save",
                callback_data=f"g:save:no:{entity_id}",
            ),
        ]],
    )
