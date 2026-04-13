import asyncpg
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.bot_state import GameStates
from bot.tools.combat_renderer import render_status
from bot.tools.exploration_renderer import render_exploration_choices, render_run_summary
from bot.tools.keyboards import class_select_keyboard, lobby_keyboard, location_keyboard
from db.queries.users_namespace import UserРЎharactersData
from game.session.lobby_manager import LobbyManager, LobbyPlayer, LobbySelectionMode, LobbySession
from game_service import GameService

router = Router(name="game_router")
_LOBBY_MANAGERS: dict[int, LobbyManager] = {}


def _session_id(chat_id: int) -> str:
    return str(chat_id)


def _get_lobby_manager(db_pool: asyncpg.Pool) -> LobbyManager:
    key = id(db_pool)
    manager = _LOBBY_MANAGERS.get(key)
    if manager is None:
        manager = LobbyManager(UserРЎharactersData(pool=db_pool))
        _LOBBY_MANAGERS[key] = manager
    return manager


def _class_name_map(game_service: GameService) -> dict[str, str]:
    return {
        class_id: class_data.name
        for class_id, class_data in game_service.get_available_classes().items()
    }


def _player_status(player: LobbyPlayer, class_names: dict[str, str]) -> str:
    if (
        player.selection_mode == LobbySelectionMode.SAVED
        and player.selected_character_id is not None
    ):
        selected = next(
            (
                char
                for char in player.available_characters
                if char.character_id == player.selected_character_id
            ),
            None,
        )
        if selected is None:
            return "choosing character..."
        class_name = class_names.get(selected.class_id, selected.class_id)
        return f"saved: {class_name} Lv.{selected.level}"

    if player.selection_mode == LobbySelectionMode.NEW:
        if player.selected_class_id is None:
            return "creating new..."
        class_name = class_names.get(player.selected_class_id, player.selected_class_id)
        return f"new: {class_name}"

    return "choosing character..."


def _render_lobby(lobby: LobbySession, class_names: dict[str, str]) -> str:
    lines = ["Game lobby", "", "Players:"]
    for player in lobby.players.values():
        lines.append(f"  - {player.display_name}: {_player_status(player, class_names)}")
    lines.append("")
    lines.append("Press Join, then choose a saved character or create a new one.")
    return "\n".join(lines)


def _render_character_prompt(player: LobbyPlayer, class_names: dict[str, str]) -> str:
    lines = [f"Choose character for {player.display_name}:", ""]

    if player.available_characters:
        lines.append("Saved characters:")
        for char in player.available_characters:
            class_name = class_names.get(char.class_id, char.class_id)
            marker = " [selected]" if player.selected_character_id == char.character_id else ""
            lines.append(
                f"  - #{char.character_id}: {class_name} Lv.{char.level} (XP {char.xp}){marker}",
            )
    else:
        lines.append("No saved characters found.")

    if player.selection_mode == LobbySelectionMode.NEW:
        if player.selected_class_id is None:
            lines.append("\nCreating a new character...")
        else:
            class_name = class_names.get(player.selected_class_id, player.selected_class_id)
            lines.append(f"\nNew character selected: {class_name}")

    return "\n".join(lines)


def _character_choice_keyboard(
    player: LobbyPlayer,
    class_names: dict[str, str],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for char in player.available_characters:
        class_name = class_names.get(char.class_id, char.class_id)
        rows.append([
            InlineKeyboardButton(
                text=f"Load {class_name} Lv.{char.level}",
                callback_data=f"g:char:{char.character_id}",
            ),
        ])
    rows.append([
        InlineKeyboardButton(
            text="Create New Character",
            callback_data="g:newchar",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_lobby_status(
    message: Message,
    lobby: LobbySession,
    game_service: GameService,
) -> None:
    class_names = _class_name_map(game_service)
    await message.answer(_render_lobby(lobby, class_names), reply_markup=lobby_keyboard())


async def _send_character_prompt(
    message: Message,
    player: LobbyPlayer,
    game_service: GameService,
) -> None:
    class_names = _class_name_map(game_service)
    await message.answer(
        _render_character_prompt(player, class_names),
        reply_markup=_character_choice_keyboard(player, class_names),
    )


async def _persist_characters(
    game_service: GameService,
    session_id: str,
    db_pool: asyncpg.Pool,
) -> None:
    if not game_service.has_session(session_id):
        return
    chars_db = UserРЎharactersData(pool=db_pool)
    for player in game_service.get_session_players(session_id):
        await chars_db.add_user_character(
            tg_id=player.tg_user_id,
            character_id=player.entity_id,
        )


@router.message(Command("run"))
async def cmd_newgame(
    message: Message,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(message.chat.id)
    lobby_manager = _get_lobby_manager(db_pool)

    if game_service.has_session(sid):
        await message.answer("A game session already exists in this chat.")
        return
    if lobby_manager.has_lobby(sid):
        await message.answer("A game lobby already exists in this chat.")
        return

    lobby = await lobby_manager.create_lobby(
        sid,
        message.from_user.id,
        message.from_user.first_name or "Player",
    )
    await _send_lobby_status(message, lobby, game_service)
    await _send_character_prompt(message, lobby.players[message.from_user.id], game_service)
    await state.set_state(GameStates.lobby)


@router.message(Command("join"))
async def cmd_join(
    message: Message,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(message.chat.id)
    lobby_manager = _get_lobby_manager(db_pool)

    if game_service.has_session(sid):
        await message.answer("The run has already started in this chat.")
        return
    if not lobby_manager.has_lobby(sid):
        await message.answer("No active game lobby. Use /run to start one.")
        return

    try:
        lobby = await lobby_manager.join_lobby(
            sid,
            message.from_user.id,
            message.from_user.first_name or "Player",
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(f"{message.from_user.first_name or 'Player'} joined the lobby!")
    await _send_lobby_status(message, lobby, game_service)
    await _send_character_prompt(message, lobby.players[message.from_user.id], game_service)
    await state.set_state(GameStates.lobby)


@router.callback_query(F.data == "g:join")
async def cb_join(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    lobby_manager = _get_lobby_manager(db_pool)

    if game_service.has_session(sid):
        await callback.answer("The run has already started.", show_alert=True)
        return
    if not lobby_manager.has_lobby(sid):
        await callback.answer("No active game lobby.", show_alert=True)
        return

    try:
        lobby = await lobby_manager.join_lobby(
            sid,
            callback.from_user.id,
            callback.from_user.first_name or "Player",
        )
    except ValueError:
        await callback.answer("Already joined!", show_alert=True)
        return

    class_names = _class_name_map(game_service)
    await callback.answer(f"{callback.from_user.first_name or 'Player'} joined!")
    await callback.message.edit_text(
        _render_lobby(lobby, class_names),
        reply_markup=lobby_keyboard(),
    )
    await callback.message.answer(
        _render_character_prompt(lobby.players[callback.from_user.id], class_names),
        reply_markup=_character_choice_keyboard(lobby.players[callback.from_user.id], class_names),
    )
    await state.set_state(GameStates.lobby)


@router.callback_query(F.data.startswith("g:char:"))
async def cb_character_select(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    lobby_manager = _get_lobby_manager(db_pool)
    if not lobby_manager.has_lobby(sid):
        await callback.answer("No active game lobby.", show_alert=True)
        return

    character_id = int(callback.data[7:])
    try:
        lobby_manager.choose_saved_character(sid, callback.from_user.id, character_id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    lobby = lobby_manager.get_lobby(sid)
    player = lobby.players[callback.from_user.id]
    class_names = _class_name_map(game_service)
    await callback.message.edit_text(
        _render_character_prompt(player, class_names),
        reply_markup=_character_choice_keyboard(player, class_names),
    )
    await callback.answer("Saved character selected!")
    await callback.message.answer(_render_lobby(lobby, class_names), reply_markup=lobby_keyboard())
    if lobby_manager.all_players_ready(sid):
        await callback.message.answer(
            "All players ready! Press Start Run to begin.",
            reply_markup=lobby_keyboard(),
        )
    await state.set_state(GameStates.lobby)


@router.callback_query(F.data == "g:newchar")
async def cb_new_character(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    lobby_manager = _get_lobby_manager(db_pool)
    if not lobby_manager.has_lobby(sid):
        await callback.answer("No active game lobby.", show_alert=True)
        return

    try:
        lobby_manager.choose_create_new(sid, callback.from_user.id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.message.edit_text(
        "Choose a class for your new character:",
        reply_markup=class_select_keyboard(game_service.get_available_classes()),
    )
    await callback.answer()
    await state.set_state(GameStates.class_select)


@router.callback_query(F.data.startswith("g:class:"))
async def cb_class_select(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    lobby_manager = _get_lobby_manager(db_pool)
    if not lobby_manager.has_lobby(sid):
        await callback.answer("No active game lobby.", show_alert=True)
        return

    class_id = callback.data[8:]
    try:
        lobby_manager.choose_new_class(sid, callback.from_user.id, class_id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    lobby = lobby_manager.get_lobby(sid)
    player = lobby.players[callback.from_user.id]
    class_names = _class_name_map(game_service)
    await callback.message.edit_text(_render_character_prompt(player, class_names))
    await callback.answer(f"You chose {class_names.get(class_id, class_id)}!")
    await callback.message.answer(_render_lobby(lobby, class_names), reply_markup=lobby_keyboard())
    if lobby_manager.all_players_ready(sid):
        await callback.message.answer(
            "All players ready! Press Start Run to begin.",
            reply_markup=lobby_keyboard(),
        )
    await state.set_state(GameStates.lobby)


async def _start_run(
    message: Message,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(message.chat.id)
    lobby_manager = _get_lobby_manager(db_pool)
    if not lobby_manager.has_lobby(sid):
        await message.answer("No active game lobby. Use /run to start one.")
        return
    if not lobby_manager.all_players_ready(sid):
        await message.answer("Not all players have chosen a character yet!")
        return

    try:
        await lobby_manager.launch_game(sid, game_service)
    except NotImplementedError as exc:
        await message.answer(str(exc))
        return
    except Exception as exc:
        await message.answer(f"Failed to start run: {exc}")
        return

    lobby_manager.remove_lobby(sid)
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
    db_pool: asyncpg.Pool,
) -> None:
    await callback.answer()
    await _start_run(callback.message, game_service, state, db_pool)


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


@router.message(Command("leave"))
async def cmd_flee(
    message: Message,
    game_service: GameService,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(message.chat.id)
    lobby_manager = _get_lobby_manager(db_pool)

    if lobby_manager.has_lobby(sid):
        lobby_manager.remove_lobby(sid)
        await message.answer("The lobby is closed.")
        return

    if not game_service.has_session(sid):
        await message.answer("No active game.")
        return

    stats = game_service.get_run_stats(sid) if game_service.get_session_phase(sid) is not None else None
    await _persist_characters(game_service, sid, db_pool)
    game_service.remove_session(sid)

    if stats is not None:
        summary = render_run_summary(stats, victory=False)
        await message.answer(f"The party flees!\n\n{summary}")
    else:
        await message.answer("The party flees! Session ended.")
