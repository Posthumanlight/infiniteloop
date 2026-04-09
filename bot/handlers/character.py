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
    entity_id = str(message.from_user.id)

    if not game_service.has_session(sid):
        await message.answer("No active game. Use /newgame to start one.")
        return

    try:
        sheet = game_service.get_character_sheet(sid, entity_id)
    except ValueError as e:
        await message.answer(str(e))
        return

    await message.answer(render_character_sheet(sheet))
