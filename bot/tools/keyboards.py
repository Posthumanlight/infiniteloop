from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from settings.config import settings

if TYPE_CHECKING:
    from game.core.data_loader import SkillData
    from server.services.game_models import EntitySnapshot


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
                InlineKeyboardButton(text="\U0001f5e1\ufe0f Fight!", callback_data="g:fight"),
            ],
        ]
    )


def skill_keyboard(skills: list[SkillData]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{skill.name} (\u26a1{skill.energy_cost})" if skill.energy_cost > 0 else skill.name,
            callback_data=f"g:sk:{skill.skill_id}",
        )]
        for skill in skills
    ]
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