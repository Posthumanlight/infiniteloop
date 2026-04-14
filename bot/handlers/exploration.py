"""Exploration and event callback handlers.

Handles location voting (g:loc:*), event choice voting (g:evt:*),
and level-up reward picks (g:rwd:*).
"""

import asyncpg
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.bot_state import GameStates
from bot.tools.combat_renderer import render_combat_start, render_turn_prompt
from bot.tools.exploration_renderer import (
    render_event,
    render_exploration_choices,
    render_reward_choices,
    render_reward_notice,
    render_run_summary,
)
from bot.tools.keyboards import (
    event_choice_keyboard,
    location_keyboard,
    reward_choice_keyboard,
    skill_keyboard,
)
from bot.tools.run_persistence import persist_victory_progress
from bot.tools.session_lookup import entity_id_for_tg_user
from game.core.enums import SessionEndReason, SessionPhase
from game_service import GameService

router = Router(name="exploration_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


# ------------------------------------------------------------------
# Location voting — g:loc:{index}
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("g:loc:"))
async def cb_location_vote(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    player_id = entity_id_for_tg_user(game_service, sid, callback.from_user.id)
    if player_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return
    location_index = int(callback.data[6:])  # strip "g:loc:"

    try:
        game_service.submit_location_vote(sid, player_id, location_index)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.answer("Vote recorded!")

    if not game_service.all_players_voted(sid):
        # Update message to show current vote status
        players = {p.entity_id: p for p in game_service.get_session_players(sid)}
        options = game_service.get_exploration_choices(sid)
        exploration = game_service._get_session(sid).state.exploration
        await callback.message.edit_text(
            render_exploration_choices(options, exploration.votes, players),
            reply_markup=location_keyboard(options),
        )
        return

    # All votes in — resolve
    phase = game_service.resolve_location_choice(sid)
    await _handle_phase_transition(callback, game_service, sid, phase, state, db_pool)


# ------------------------------------------------------------------
# Event voting — g:evt:{index}
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("g:evt:"))
async def cb_event_vote(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    player_id = entity_id_for_tg_user(game_service, sid, callback.from_user.id)
    if player_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return
    choice_index = int(callback.data[6:])  # strip "g:evt:"

    try:
        game_service.submit_event_vote(sid, player_id, choice_index)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.answer("Vote recorded!")

    if not game_service.all_event_votes_in(sid):
        # Update message with current vote status
        players = {p.entity_id: p for p in game_service.get_session_players(sid)}
        event_state = game_service.get_event_state(sid)
        await callback.message.edit_text(
            render_event(event_state, players),
            reply_markup=event_choice_keyboard(event_state.event_def.choices),
        )
        return

    # All votes in — resolve event
    phase = game_service.resolve_event(sid)
    await _handle_phase_transition(callback, game_service, sid, phase, state, db_pool)


@router.callback_query(F.data.startswith("g:rwd:"))
async def cb_reward_choice(
    callback: CallbackQuery,
    game_service: GameService,
) -> None:
    sid = _session_id(callback.message.chat.id)
    player_id = entity_id_for_tg_user(game_service, sid, callback.from_user.id)
    if player_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return
    reward_id = callback.data[6:]  # strip "g:rwd:"

    try:
        game_service.submit_reward_choice(sid, player_id, reward_id)
    except ValueError as e:
        await callback.answer(str(e), show_alert=True)
        return

    await callback.answer("Reward selected!")

    players = {p.entity_id: p for p in game_service.get_session_players(sid)}
    for notice in game_service.consume_reward_notices(sid):
        player_name = (
            players[notice.player_id].display_name
            if notice.player_id in players
            else notice.player_id
        )
        await callback.message.answer(
            render_reward_notice(player_name, notice.reward_type, notice.skipped_count),
        )

    pending_choices = {
        choice.player_id: choice
        for choice in game_service.get_pending_rewards(sid)
    }
    pending = pending_choices.get(player_id)
    if pending is None:
        await callback.message.edit_text("Reward selected.")
        return

    player_name = (
        players[player_id].display_name if player_id in players else player_id
    )
    await callback.message.edit_text(
        render_reward_choices(
            player_name, pending.reward_type, pending.pending_count, pending.offers,
        ),
        reply_markup=reward_choice_keyboard(pending.offers),
    )


async def _send_reward_prompts(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
) -> None:
    players = {p.entity_id: p for p in game_service.get_session_players(session_id)}

    for notice in game_service.consume_reward_notices(session_id):
        player_name = (
            players[notice.player_id].display_name
            if notice.player_id in players
            else notice.player_id
        )
        await callback.message.answer(
            render_reward_notice(player_name, notice.reward_type, notice.skipped_count),
        )

    for pending in game_service.get_pending_rewards(session_id):
        player_name = (
            players[pending.player_id].display_name
            if pending.player_id in players
            else pending.player_id
        )
        await callback.message.answer(
            render_reward_choices(
                player_name, pending.reward_type, pending.pending_count, pending.offers,
            ),
            reply_markup=reward_choice_keyboard(pending.offers),
        )


# ------------------------------------------------------------------
# Shared phase transition handler
# ------------------------------------------------------------------

async def _handle_phase_transition(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
    phase: SessionPhase,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    """Route to the correct UI based on the new session phase."""
    players = {p.entity_id: p for p in game_service.get_session_players(session_id)}

    match phase:
        case SessionPhase.IN_COMBAT:
            snapshot = game_service.get_combat_snapshot(session_id)
            text = render_combat_start(snapshot, players)
            await callback.message.answer(text)

            whose_turn = game_service.get_whose_turn(session_id)
            if whose_turn is not None:
                turn_snap = snapshot.entities[whose_turn]
                skills = game_service.get_available_skills(session_id, whose_turn)
                prompt = render_turn_prompt(whose_turn, turn_snap, players)
                await callback.message.answer(prompt, reply_markup=skill_keyboard(skills))
            await state.set_state(GameStates.combat_idle)

        case SessionPhase.IN_EVENT:
            event_state = game_service.get_event_state(session_id)
            await callback.message.answer(
                render_event(event_state, players),
                reply_markup=event_choice_keyboard(event_state.event_def.choices),
            )
            await state.set_state(GameStates.event_voting)

        case SessionPhase.EXPLORING:
            game_service.continue_exploration(session_id)
            options = game_service.get_exploration_choices(session_id)
            await callback.message.answer(
                render_exploration_choices(options, (), players),
                reply_markup=location_keyboard(options),
            )
            await _send_reward_prompts(callback, game_service, session_id)
            await state.set_state(GameStates.exploring)

        case SessionPhase.ENDED:
            stats = game_service.get_run_stats(session_id)
            session = game_service._get_session(session_id)
            victory = session.state.end_reason == SessionEndReason.MAX_DEPTH
            await callback.message.answer(render_run_summary(stats, victory))
            await persist_victory_progress(game_service, session_id, db_pool)
            game_service.remove_session(session_id)
            await state.set_state(GameStates.run_ended)
