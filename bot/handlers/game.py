import asyncpg
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.bot_state import GameStates
from bot.tools.combat_renderer import (
    render_combat_start,
    render_status,
)
from bot.tools.exploration_renderer import (
    render_class_prompt,
    render_exploration_choices,
    render_run_summary,
)
from bot.tools.keyboards import (
    class_select_keyboard,
    lobby_keyboard,
    location_keyboard,
    skill_keyboard,
)
from db.queries.users_namespace import UserСharactersData
from game.core.game_models import PlayerInfo
from game_service import GameService

router = Router(name="game_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


async def _player_info(user, db_pool: asyncpg.Pool) -> PlayerInfo:
    tg_id = user.id
    chars_db = UserСharactersData(pool=db_pool)
    last_char = await chars_db.get_last_user_character(tg_id)

    if last_char is None:
        entity_id = str(tg_id) + "000"
    else:
        entity_id = str(int(last_char["character_id"]) + 1)

    return PlayerInfo(
        entity_id=entity_id,
        tg_user_id=tg_id,
        display_name=user.first_name or "Player",
    )


async def _persist_characters(
    game_service: GameService, session_id: str, db_pool: asyncpg.Pool,
) -> None:
    """Save all session players to game_characters after a run ends."""
    if not game_service.has_session(session_id):
        return
    chars_db = UserСharactersData(pool=db_pool)
    for player in game_service.get_session_players(session_id):
        await chars_db.add_user_character(
            tg_id=player.tg_user_id, character_id=player.entity_id,
        )


@router.message(Command("run"))
async def cmd_newgame(
    message: Message,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(message.chat.id)

    if game_service.has_session(sid):
        await message.answer("A game session already exists in this chat.")
        return

    creator = await _player_info(message.from_user, db_pool)
    game_service.create_session(sid, creator)

    players = game_service.get_session_players(sid)
    names = ", ".join(p.display_name for p in players)

    classes = game_service.get_available_classes()
    await message.answer(
        f"\u2694\ufe0f New game started!\n\nPlayers: {names}\n\n"
        "Press Join to enter, pick your class, then Start Run!",
        reply_markup=lobby_keyboard(),
    )
    await message.answer(
        render_class_prompt(classes, {p.entity_id: p for p in players}),
        reply_markup=class_select_keyboard(classes),
    )
    await state.set_state(GameStates.class_select)


# ------------------------------------------------------------------
# /join and g:join callback
# ------------------------------------------------------------------

@router.message(Command("join"))
async def cmd_join(
    message: Message,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(message.chat.id)
    if not game_service.has_session(sid):
        await message.answer("No active game. Use /newgame to start one.")
        return
    if game_service.is_in_combat(sid):
        await message.answer("Combat is already in progress. Can't join now.")
        return

    player = await _player_info(message.from_user, db_pool)
    try:
        game_service.join_session(sid, player)
    except ValueError as e:
        await message.answer(str(e))
        return

    players = game_service.get_session_players(sid)
    names = ", ".join(p.display_name for p in players)
    classes = game_service.get_available_classes()

    await message.answer(f"\u2694\ufe0f {player.display_name} joined!\n\nPlayers: {names}")
    await message.answer(
        render_class_prompt(classes, {p.entity_id: p for p in players}),
        reply_markup=class_select_keyboard(classes),
    )
    await state.set_state(GameStates.class_select)


@router.callback_query(F.data == "g:join")
async def cb_join(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    if not game_service.has_session(sid):
        await callback.answer("No active game.", show_alert=True)
        return
    if game_service.is_in_combat(sid):
        await callback.answer("Combat already in progress.", show_alert=True)
        return

    player = await _player_info(callback.from_user, db_pool)
    try:
        game_service.join_session(sid, player)
    except ValueError:
        await callback.answer("Already joined!", show_alert=True)
        return

    players = game_service.get_session_players(sid)
    names = ", ".join(p.display_name for p in players)
    classes = game_service.get_available_classes()

    await callback.message.edit_text(
        f"\u2694\ufe0f Game lobby\n\nPlayers: {names}\n\n"
        "Press Join to enter, pick your class, then Start Run!",
        reply_markup=lobby_keyboard(),
    )
    await callback.message.answer(
        render_class_prompt(classes, {p.entity_id: p for p in players}),
        reply_markup=class_select_keyboard(classes),
    )
    await callback.answer(f"{player.display_name} joined!")
    await state.set_state(GameStates.class_select)


# ------------------------------------------------------------------
# Class selection — g:class:{class_id}
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("g:class:"))
async def cb_class_select(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
) -> None:
    sid = _session_id(callback.message.chat.id)
    if not game_service.has_session(sid):
        await callback.answer("No active game.", show_alert=True)
        return

    tg_id = callback.from_user.id
    class_id = callback.data[8:]  # strip "g:class:"

    session_players = game_service.get_session_players(sid)
    entity_id = next(
        (p.entity_id for p in session_players if p.tg_user_id == tg_id),
        None,
    )
    if entity_id is None:
        await callback.answer("Join the game first!", show_alert=True)
        return

    try:
        game_service.select_class(sid, entity_id, class_id)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    classes = game_service.get_available_classes()
    class_name = classes[class_id].name
    await callback.answer(f"You chose {class_name}!")

    players = game_service.get_session_players(sid)
    player_map = {p.entity_id: p for p in players}

    await callback.message.edit_text(
        render_class_prompt(classes, player_map),
        reply_markup=class_select_keyboard(classes),
    )

    if game_service.all_players_ready(sid):
        await callback.message.answer(
            "\u2705 All players ready! Press Start Run to begin.",
            reply_markup=lobby_keyboard(),
        )


# ------------------------------------------------------------------
# /start and g:start callback — begin exploration run
# ------------------------------------------------------------------

async def _start_run(
    message: Message,
    game_service: GameService,
    state: FSMContext,
) -> None:
    sid = _session_id(message.chat.id)
    if not game_service.has_session(sid):
        await message.answer("No active game. Use /newgame to start one.")
        return
    if not game_service.all_players_ready(sid):
        await message.answer("Not all players have chosen a class yet!")
        return

    game_service.start_exploration_run(sid)

    players = game_service.get_session_players(sid)
    player_map = {p.entity_id: p for p in players}
    options = game_service.get_exploration_choices(sid)

    await message.answer(
        render_exploration_choices(options, (), player_map),
        reply_markup=location_keyboard(options),
    )
    await state.set_state(GameStates.exploring)


@router.callback_query(F.data == "g:start")
async def cb_start(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
) -> None:
    await callback.answer()
    await _start_run(callback.message, game_service, state)


# ------------------------------------------------------------------
# /status
# ------------------------------------------------------------------

@router.message(Command("combat"))
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

@router.message(Command("leave"))
async def cmd_flee(
    message: Message,
    game_service: GameService,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(message.chat.id)
    if not game_service.has_session(sid):
        await message.answer("No active game.")
        return

    stats = game_service.get_run_stats(sid) if game_service.get_session_phase(sid) is not None else None
    await _persist_characters(game_service, sid, db_pool)
    game_service.remove_session(sid)

    if stats is not None:
        summary = render_run_summary(stats, victory=False)
        await message.answer(f"\U0001f3c3 The party flees!\n\n{summary}")
    else:
        await message.answer("\U0001f3c3 The party flees! Session ended.")
