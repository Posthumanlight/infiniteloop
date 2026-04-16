"""Character sheet handler: /char command."""

from aiogram import Bot
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.tools.session_lookup import entity_id_for_tg_user
from game_service import GameService
from webapp.links import (
    build_char_start_param,
    build_direct_mini_app_link,
    build_inventory_start_param,
)

router = Router(name="character_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


async def _open_webapp(
    message: Message,
    bot: Bot,
    game_service: GameService,
    *,
    start_param: str,
    button_text: str,
    prompt_text: str,
    preload: str,
) -> None:
    sid = _session_id(message.chat.id)

    if not game_service.has_session(sid):
        await message.answer("No active game. Use /newgame to start one.")
        return

    entity_id = entity_id_for_tg_user(game_service, sid, message.from_user.id)
    if entity_id is None:
        await message.answer("You are not in the current game.")
        return

    try:
        if preload == "character":
            game_service.get_character_sheet(sid, entity_id)
        else:
            game_service.get_inventory(sid, entity_id)
    except ValueError as exc:
        await message.answer(str(exc))
        return

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
    await message.answer(prompt_text, reply_markup=keyboard)


@router.message(Command("char"))
async def cmd_char(
    message: Message,
    bot: Bot,
    game_service: GameService,
) -> None:
    await _open_webapp(
        message,
        bot,
        game_service,
        start_param=build_char_start_param(_session_id(message.chat.id)),
        button_text="Open Character Sheet",
        prompt_text="Open your character sheet in the Mini App.",
        preload="character",
    )


@router.message(Command("inventory"))
async def cmd_inventory(
    message: Message,
    bot: Bot,
    game_service: GameService,
) -> None:
    await _open_webapp(
        message,
        bot,
        game_service,
        start_param=build_inventory_start_param(_session_id(message.chat.id)),
        button_text="Open Inventory",
        prompt_text="Open your inventory in the Mini App.",
        preload="inventory",
    )
