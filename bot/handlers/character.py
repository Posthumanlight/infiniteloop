"""Character sheet handler: /char command."""

from aiogram import Bot
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.tools.session_lookup import entity_id_for_tg_user
from game_service import GameService
from webapp.links import build_char_start_param, build_direct_mini_app_link

router = Router(name="character_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


@router.message(Command("char"))
async def cmd_char(
    message: Message,
    bot: Bot,
    game_service: GameService,
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
        game_service.get_character_sheet(sid, entity_id)
    except ValueError as e:
        await message.answer(str(e))
        return

    me = await bot.me()
    if me.username is None:
        await message.answer("Bot username is unavailable, so the Mini App link could not be built.")
        return

    url = build_direct_mini_app_link(
        bot_username=me.username,
        start_param=build_char_start_param(sid),
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Open Character Sheet",
                    url=url,
                ),
            ],
        ],
    )
    await message.answer("Open your character sheet in the Mini App.", reply_markup=keyboard)
