"""Character sheet handler: /char command."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.tools.character_renderer import render_character_sheet
from game_service import GameService

router = Router(name="character_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


@router.message(Command("char"))
async def cmd_char(
    message: Message,
    game_service: GameService,
) -> None:
    sid = _session_id(message.chat.id)

    if not game_service.has_session(sid):
        await message.answer("No active game. Use /newgame to start one.")
        return

    tg_id = message.from_user.id
    session_players = game_service.get_session_players(sid)
    entity_id = next(
        (p.entity_id for p in session_players if p.tg_user_id == tg_id),
        None,
    )
    if entity_id is None:
        await message.answer("You are not in the current game.")
        return

    try:
        sheet = game_service.get_character_sheet(sid, entity_id)
    except ValueError as e:
        await message.answer(str(e))
        return

    await message.answer(render_character_sheet(sheet))
