"""Combat inline keyboard callback handlers.

Handles skill selection (g:sk:*), target selection (g:tg:*), and skip (g:skip).
"""

import asyncpg
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.bot_state import GameStates
from bot.tools.combat_renderer import (
    render_turn_batch,
    render_turn_prompt,
    render_combat_end,
)
from bot.tools.exploration_renderer import (
    render_exploration_choices,
    render_modifier_choices,
    render_modifier_notice,
    render_run_summary,
)
from bot.tools.keyboards import (
    location_keyboard,
    modifier_choice_keyboard,
    skill_keyboard,
    target_keyboard,
)
from bot.tools.session_lookup import entity_id_for_tg_user
from db.queries.users_namespace import UserСharactersData
from game.combat.models import ActionRequest
from game.core.enums import ActionType, SessionPhase, TargetType
from game_service import GameService

router = Router(name="combat_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


# ------------------------------------------------------------------
# Skill selection — g:sk:{skill_id}
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("g:sk:"))
async def cb_skill(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
) -> None:
    sid = _session_id(callback.message.chat.id)
    actor_id = entity_id_for_tg_user(game_service, sid, callback.from_user.id)
    if actor_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return
    skill_id = callback.data[5:]  # strip "g:sk:"

    # Validate it's this player's turn
    whose_turn = game_service.get_whose_turn(sid)
    if whose_turn != actor_id:
        await callback.answer("Not your turn!", show_alert=True)
        return

    # Get skill info to determine target type
    skills = game_service.get_available_skills(sid, actor_id)
    skill_match = next(((s, cd) for s, cd in skills if s.skill_id == skill_id), None)
    if skill_match is None:
        await callback.answer("Unknown skill.", show_alert=True)
        return
    skill, cd = skill_match

    if cd > 0:
        await callback.answer(f"Skill on cooldown ({cd} turns)!", show_alert=True)
        return

    match skill.target_type:
        case TargetType.SINGLE_ENEMY:
            # Need target selection — store skill_id and show target picker
            await state.update_data(pending_skill=skill_id)
            await state.set_state(GameStates.combat_target)
            enemies = game_service.get_alive_enemies(sid)
            await callback.message.edit_text(
                f"Pick a target for {skill.name}:",
                reply_markup=target_keyboard(enemies),
            )
            await callback.answer()

        case TargetType.ALL_ENEMIES | TargetType.SELF | TargetType.ALL_ALLIES | TargetType.SINGLE_ALLY:
            # No target selection needed — submit immediately
            action = ActionRequest(
                actor_id=actor_id,
                action_type=ActionType.ACTION,
                skill_id=skill_id,
                target_id=None,
            )
            await _submit_action(callback, game_service, sid, action)


# ------------------------------------------------------------------
# Target selection — g:tg:{entity_id}
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("g:tg:"))
async def cb_target(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
) -> None:
    sid = _session_id(callback.message.chat.id)
    actor_id = entity_id_for_tg_user(game_service, sid, callback.from_user.id)
    if actor_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return
    target_id = callback.data[5:]  # strip "g:tg:"

    # Validate turn
    whose_turn = game_service.get_whose_turn(sid)
    if whose_turn != actor_id:
        await callback.answer("Not your turn!", show_alert=True)
        return

    # Retrieve the pending skill from FSM state data
    data = await state.get_data()
    skill_id = data.get("pending_skill")
    if skill_id is None:
        await callback.answer("No skill selected. Pick a skill first.", show_alert=True)
        return

    action = ActionRequest(
        actor_id=actor_id,
        action_type=ActionType.ACTION,
        skill_id=skill_id,
        target_id=target_id,
    )
    await state.update_data(pending_skill=None)
    await _submit_action(callback, game_service, sid, action)


# ------------------------------------------------------------------
# Skip — g:skip
# ------------------------------------------------------------------

@router.callback_query(F.data == "g:skip")
async def cb_skip(
    callback: CallbackQuery,
    game_service: GameService,
) -> None:
    sid = _session_id(callback.message.chat.id)
    actor_id = entity_id_for_tg_user(game_service, sid, callback.from_user.id)
    if actor_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return

    whose_turn = game_service.get_whose_turn(sid)
    if whose_turn != actor_id:
        await callback.answer("Not your turn!", show_alert=True)
        return

    batch = game_service.skip_player_turn(sid, actor_id)
    players = {p.entity_id: p for p in game_service.get_session_players(sid)}

    await _render_batch_and_prompt(callback, game_service, sid, batch, players)


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

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


async def _send_modifier_prompts(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
) -> None:
    players = {p.entity_id: p for p in game_service.get_session_players(session_id)}

    for notice in game_service.consume_modifier_choice_notices(session_id):
        player_name = (
            players[notice.player_id].display_name
            if notice.player_id in players
            else notice.player_id
        )
        await callback.message.answer(
            render_modifier_notice(player_name, notice.skipped_count),
        )

    for pending in game_service.get_pending_modifier_choices(session_id):
        player_name = (
            players[pending.player_id].display_name
            if pending.player_id in players
            else pending.player_id
        )
        await callback.message.answer(
            render_modifier_choices(player_name, pending.pending_count, pending.offers),
            reply_markup=modifier_choice_keyboard(pending.offers),
        )


async def _submit_action(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
    action: ActionRequest,
) -> None:
    """Submit action, render results, prompt next turn."""
    batch = game_service.submit_player_action(session_id, action)
    players = {p.entity_id: p for p in game_service.get_session_players(session_id)}

    await _render_batch_and_prompt(callback, game_service, session_id, batch, players)


async def _render_batch_and_prompt(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
    batch,
    players: dict,
) -> None:
    """Render turn batch results and either prompt next turn or show combat end."""
    await callback.answer()

    # Render action results
    results_text = render_turn_batch(batch, players)
    if results_text:
        await callback.message.answer(results_text)

    if batch.combat_ended:
        # Show combat end summary
        end_text = render_combat_end(batch, players)
        await callback.message.answer(end_text)

        # Check what comes next in the exploration loop
        phase = game_service.get_session_phase(session_id)
        if phase == SessionPhase.EXPLORING:
            game_service.continue_exploration(session_id)
            options = game_service.get_exploration_choices(session_id)
            await callback.message.answer(
                render_exploration_choices(options, (), players),
                reply_markup=location_keyboard(options),
            )
            await _send_modifier_prompts(callback, game_service, session_id)
        elif phase == SessionPhase.ENDED:
            stats = game_service.get_run_stats(session_id)
            session = game_service._get_session(session_id)
            victory = any(p.current_hp > 0 for p in session.state.players)
            await callback.message.answer(render_run_summary(stats, victory))
            game_service.remove_session(session_id)
        else:
            game_service.remove_session(session_id)
    else:
        # Prompt next player
        whose_turn = batch.whose_turn
        if whose_turn is not None and whose_turn in batch.entities:
            turn_snap = batch.entities[whose_turn]
            skills = game_service.get_available_skills(session_id, whose_turn)
            prompt = render_turn_prompt(whose_turn, turn_snap, players)
            await callback.message.answer(prompt, reply_markup=skill_keyboard(skills))
