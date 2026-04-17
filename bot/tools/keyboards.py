from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, WebAppInfo
from bot.tools.location_labels import location_display_label

if TYPE_CHECKING:
    from game.core.data_loader import ClassData, LocationOption, SkillData
    from game.events.models import ChoiceDef
    from game.core.game_models import EntitySnapshot, RewardOfferInfo


SKILLS_PER_PAGE = 5


@dataclass(frozen=True)
class SkillPage:
    page_index: int
    total_pages: int
    skills: tuple[tuple[SkillData, int], ...]
    show_skip: bool


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
    *,
    page: int = 0,
) -> InlineKeyboardMarkup:
    pages = build_skill_pages(skills)
    current_page = pages[normalize_skill_page(skills, page)]
    rows: list[list[InlineKeyboardButton]] = []

    for skill, cd in current_page.skills:
        rows.append([InlineKeyboardButton(
            text=_skill_button_text(skill, cd, current_energy),
            callback_data=f"g:sk:{skill.skill_id}",
        )])

    if current_page.show_skip:
        rows.append([InlineKeyboardButton(text="\u23ed\ufe0f Skip", callback_data="g:skip")])

    pager = _skill_pager_row(current_page)
    if pager:
        rows.append(pager)

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_skill_pages(
    skills: list[tuple[SkillData, int]],
) -> tuple[SkillPage, ...]:
    pages: list[SkillPage] = []
    index = 0

    while len(skills) - index > SKILLS_PER_PAGE - 1:
        pages.append(SkillPage(
            page_index=len(pages),
            total_pages=0,
            skills=tuple(skills[index:index + SKILLS_PER_PAGE]),
            show_skip=False,
        ))
        index += SKILLS_PER_PAGE

    pages.append(SkillPage(
        page_index=len(pages),
        total_pages=0,
        skills=tuple(skills[index:index + (SKILLS_PER_PAGE - 1)]),
        show_skip=True,
    ))

    total_pages = len(pages)
    return tuple(
        SkillPage(
            page_index=page.page_index,
            total_pages=total_pages,
            skills=page.skills,
            show_skip=page.show_skip,
        )
        for page in pages
    )


def normalize_skill_page(
    skills: list[tuple[SkillData, int]],
    page: int,
) -> int:
    pages = build_skill_pages(skills)
    return min(max(page, 0), len(pages) - 1)


def _skill_button_text(
    skill: SkillData,
    cooldown: int,
    current_energy: int | None,
) -> str:
    if cooldown > 0:
        return f"{skill.name} (CD: {cooldown})"
    if current_energy is not None and current_energy < skill.energy_cost:
        return f"{skill.name} (\u26a1{skill.energy_cost}, no energy)"
    if skill.energy_cost > 0:
        return f"{skill.name} (\u26a1{skill.energy_cost})"
    return skill.name


def _skill_pager_row(page: SkillPage) -> list[InlineKeyboardButton]:
    row: list[InlineKeyboardButton] = []
    if page.page_index > 0:
        row.append(InlineKeyboardButton(
            text="\u2190 Prev",
            callback_data=f"g:skpg:{page.page_index - 1}",
        ))
    if page.page_index < page.total_pages - 1:
        row.append(InlineKeyboardButton(
            text="Next \u2192",
            callback_data=f"g:skpg:{page.page_index + 1}",
        ))
    return row


def target_keyboard(
    enemies: list[EntitySnapshot],
    *,
    back_page: int,
) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            text=f"{e.name} ({e.current_hp}/{e.max_hp} HP)",
            callback_data=f"g:tg:{e.entity_id}",
        )]
        for e in enemies
        if e.is_alive
    ]
    rows.append([
        InlineKeyboardButton(
            text="Back",
            callback_data=f"g:back:skills:{back_page}",
        ),
    ])
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
            text=(
                f"{offer.name} ({offer.reward_kind.title()})"
                if offer.reward_kind != "modifier"
                else offer.name
            ),
            callback_data=f"g:rwd:{offer.reward_key}",
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
