"""Character sheet handler: /char command."""

from aiogram import Bot
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from lobby_service import LobbyService
from webapp.links import (
    build_char_browser_start_param,
    build_char_start_param,
    build_direct_mini_app_link,
    build_inventory_browser_start_param,
    build_inventory_start_param,
)

router = Router(name="character_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


async def _open_webapp(
    message: Message,
    bot: Bot,
    lobby_service: LobbyService,
    *,
    session_start_param: str,
    browser_start_param: str,
    button_text: str,
    prompt_text: str,
    browser_prompt_text: str,
    preload: str,
) -> None:
    sid = _session_id(message.chat.id)
    target = lobby_service.target_for_session_user(sid, message.from_user.id)

    start_param = browser_start_param
    resolved_prompt = browser_prompt_text

    if target is not None:
        try:
            if preload == "character":
                await lobby_service.get_character_sheet(target)
            else:
                await lobby_service.get_inventory(target)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        start_param = session_start_param
        resolved_prompt = prompt_text

    me = await bot.me()
    if me.username is None:
        await message.answer("Bot username is unavailable, so the Mini App link could not be built.")
        return

    url = build_direct_mini_app_link(
        bot_username=me.username,
        start_param=start_param,
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button_text,
                    url=url,
                ),
            ],
        ],
    )
    await message.answer(resolved_prompt, reply_markup=keyboard)


@router.message(Command("char"))
async def cmd_char(
    message: Message,
    bot: Bot,
    lobby_service: LobbyService,
) -> None:
    await _open_webapp(
        message,
        bot,
        lobby_service,
        session_start_param=build_char_start_param(_session_id(message.chat.id)),
        browser_start_param=build_char_browser_start_param(),
        button_text="Open Character Sheet",
        prompt_text="Open your character sheet in the Mini App.",
        browser_prompt_text="Choose a character to inspect in the Mini App.",
        preload="character",
    )


@router.message(Command("inventory"))
async def cmd_inventory(
    message: Message,
    bot: Bot,
    lobby_service: LobbyService,
) -> None:
    await _open_webapp(
        message,
        bot,
        lobby_service,
        session_start_param=build_inventory_start_param(_session_id(message.chat.id)),
        browser_start_param=build_inventory_browser_start_param(),
        button_text="Open Inventory",
        prompt_text="Open your inventory in the Mini App.",
        browser_prompt_text="Choose a character inventory to inspect in the Mini App.",
        preload="inventory",
    )
