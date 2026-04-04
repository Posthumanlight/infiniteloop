"""Session lifecycle handlers: /newgame, /join, /fight, /status, /flee."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.bot_state import GameStates
from bot.tools.combat_renderer import (
    render_combat_start,
    render_turn_batch,
    render_turn_prompt,
    render_combat_end,
    render_status,
)
from bot.tools.keyboards import lobby_keyboard, skill_keyboard
from server.services.game_models import PlayerInfo
from server.services.game_service import GameService

router = Router(name="game_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


def _player_info(user) -> PlayerInfo:
    return PlayerInfo(
        entity_id=str(user.id),
        tg_user_id=user.id,
        display_name=user.first_name or "Player",
    )


# ------------------------------------------------------------------
# /newgame
# ------------------------------------------------------------------

@router.message(Command("newgame"))
async def cmd_newgame(
    message: Message,
    game_service: GameService,
    state: FSMContext,
) -> None:
    sid = _session_id(message.chat.id)

    if game_service.has_session(sid):
        await message.answer("A game session already exists in this chat.")
        return

    creator = _player_info(message.from_user)
    game_service.create_session(sid, creator)

    players = game_service.get_session_players(sid)
    names = ", ".join(p.display_name for p in players)

    await message.answer(
        f"\u2694\ufe0f New game started!\n\nPlayers: {names}\n\n"
        "Press Join to enter, then Fight to begin!",
        reply_markup=lobby_keyboard(),
    )
    await state.set_state(GameStates.lobby)


# ------------------------------------------------------------------
# /join and g:join callback
# ------------------------------------------------------------------

@router.message(Command("join"))
async def cmd_join(
    message: Message,
    game_service: GameService,
    state: FSMContext,
) -> None:
    sid = _session_id(message.chat.id)
    if not game_service.has_session(sid):
        await message.answer("No active game. Use /newgame to start one.")
        return
    if game_service.is_in_combat(sid):
        await message.answer("Combat is already in progress. Can't join now.")
        return

    player = _player_info(message.from_user)
    try:
        game_service.join_session(sid, player)
    except ValueError as e:
        await message.answer(str(e))
        return

    players = game_service.get_session_players(sid)
    names = ", ".join(p.display_name for p in players)
    await message.answer(f"\u2694\ufe0f {player.display_name} joined!\n\nPlayers: {names}")
    await state.set_state(GameStates.lobby)


@router.callback_query(F.data == "g:join")
async def cb_join(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
) -> None:
    sid = _session_id(callback.message.chat.id)
    if not game_service.has_session(sid):
        await callback.answer("No active game.", show_alert=True)
        return
    if game_service.is_in_combat(sid):
        await callback.answer("Combat already in progress.", show_alert=True)
        return

    player = _player_info(callback.from_user)
    try:
        game_service.join_session(sid, player)
    except ValueError:
        await callback.answer("Already joined!", show_alert=True)
        return

    players = game_service.get_session_players(sid)
    names = ", ".join(p.display_name for p in players)

    await callback.message.edit_text(
        f"\u2694\ufe0f Game lobby\n\nPlayers: {names}\n\n"
        "Press Join to enter, then Fight to begin!",
        reply_markup=lobby_keyboard(),
    )
    await callback.answer(f"{player.display_name} joined!")
    await state.set_state(GameStates.lobby)


# ------------------------------------------------------------------
# /fight and g:fight callback
# ------------------------------------------------------------------

async def _start_fight(
    message: Message,
    game_service: GameService,
) -> None:
    sid = _session_id(message.chat.id)
    if not game_service.has_session(sid):
        await message.answer("No active game. Use /newgame to start one.")
        return
    if game_service.is_in_combat(sid):
        await message.answer("Already in combat!")
        return

    snapshot = game_service.start_combat(sid, ("goblin", "goblin"))
    players = {p.entity_id: p for p in game_service.get_session_players(sid)}

    # Render initial combat state
    text = render_combat_start(snapshot, players)
    await message.answer(text)

    # Prompt the first player's turn
    whose_turn = game_service.get_whose_turn(sid)
    if whose_turn is not None:
        turn_snap = snapshot.entities[whose_turn]
        skills = game_service.get_available_skills(sid, whose_turn)
        prompt = render_turn_prompt(whose_turn, turn_snap)
        await message.answer(prompt, reply_markup=skill_keyboard(skills))


@router.message(Command("fight"))
async def cmd_fight(
    message: Message,
    game_service: GameService,
) -> None:
    await _start_fight(message, game_service)


@router.callback_query(F.data == "g:fight")
async def cb_fight(
    callback: CallbackQuery,
    game_service: GameService,
) -> None:
    await callback.answer()
    await _start_fight(callback.message, game_service)


# ------------------------------------------------------------------
# /status
# ------------------------------------------------------------------

@router.message(Command("status"))
async def cmd_status(
    message: Message,
    game_service: GameService,
) -> None:
    sid = _session_id(message.chat.id)
    if not game_service.is_in_combat(sid):
        await message.answer("No combat in progress.")
        return

    snapshot = game_service.get_combat_snapshot(sid)
    players = {p.entity_id: p for p in game_service.get_session_players(sid)}
    await message.answer(render_status(snapshot, players))


# ------------------------------------------------------------------
# /flee
# ------------------------------------------------------------------

@router.message(Command("flee"))
async def cmd_flee(
    message: Message,
    game_service: GameService,
) -> None:
    sid = _session_id(message.chat.id)
    if not game_service.has_session(sid):
        await message.answer("No active game.")
        return

    game_service.remove_session(sid)
    await message.answer("\U0001f3c3 The party flees! Session ended.")
