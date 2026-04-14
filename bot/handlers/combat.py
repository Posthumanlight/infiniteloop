"""Combat inline keyboard callback handlers.

Handles skill selection (g:sk:*), target selection (g:tg:*), and skip (g:skip).
"""

import asyncpg
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.fsm.context import FSMContext

from bot.bot_state import GameStates
from bot.handlers.game import start_victory_save_flow
from bot.tools.combat_renderer import (
    render_turn_batch,
    render_turn_prompt,
    render_combat_end,
)
from bot.tools.exploration_renderer import (
    render_exploration_choices,
    render_reward_choices,
    render_reward_notice,
    render_run_summary,
)
from bot.tools.combat_image import send_combat_image
from bot.tools.keyboards import (
    location_keyboard,
    reward_choice_keyboard,
    skill_keyboard,
    target_keyboard,
)
from bot.tools.session_lookup import entity_id_for_tg_user
from game.combat.models import ActionRequest
from game.core.enums import ActionType, SessionEndReason, SessionPhase, TargetType
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
    db_pool: asyncpg.Pool,
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

    current_energy = _get_actor_energy(game_service, sid, actor_id)
    if current_energy is not None and current_energy < skill.energy_cost:
        await callback.answer(
            _not_enough_energy_message(current_energy, skill.energy_cost),
            show_alert=True,
        )
        return

    # Build queue of hit indices that need single-target selection.
    pending_hits: list[int] = [
        idx for idx, hit in enumerate(skill.hits)
        if hit.share_with is None
        and hit.target_type in (TargetType.SINGLE_ENEMY, TargetType.SINGLE_ALLY)
    ]

    if not pending_hits:
        # No target selection needed — submit immediately
        action = ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id=skill_id,
            target_ids=(),
        )
        await _submit_action(callback, game_service, sid, action, state, db_pool)
        return

    # Need target selection — store skill_id and show target picker for first pending hit
    await state.update_data(
        pending_skill=skill_id,
        pending_hit_queue=pending_hits,
        collected_targets=[],
    )
    await state.set_state(GameStates.combat_target)
    first_hit_index = pending_hits[0]
    first_hit = skill.hits[first_hit_index]
    candidates = (
        game_service.get_alive_enemies(sid)
        if first_hit.target_type == TargetType.SINGLE_ENEMY
        else game_service.get_alive_allies(sid)
    )
    prompt = _target_prompt(skill.name, first_hit_index, len(skill.hits))
    await callback.message.edit_text(
        prompt,
        reply_markup=target_keyboard(candidates),
    )
    await callback.answer()


def _target_prompt(skill_name: str, hit_index: int, total_hits: int) -> str:
    if total_hits <= 1:
        return f"Pick a target for {skill_name}:"
    return f"Pick a target for {skill_name} (hit {hit_index + 1}/{total_hits}):"


# ------------------------------------------------------------------
# Target selection — g:tg:{entity_id}
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("g:tg:"))
async def cb_target(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
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
    pending_hit_queue: list[int] = list(data.get("pending_hit_queue") or [])
    collected: list[list] = list(data.get("collected_targets") or [])
    if skill_id is None or not pending_hit_queue:
        await callback.answer("No skill selected. Pick a skill first.", show_alert=True)
        return

    skills = game_service.get_available_skills(sid, actor_id)
    skill_match = next(((s, cd) for s, cd in skills if s.skill_id == skill_id), None)
    if skill_match is None:
        await _restore_skill_prompt(callback, game_service, sid, state)
        await callback.answer("Skill no longer available.", show_alert=True)
        return
    skill, cd = skill_match
    if cd > 0:
        await _restore_skill_prompt(callback, game_service, sid, state)
        await callback.answer(f"Skill on cooldown ({cd} turns)!", show_alert=True)
        return

    current_energy = _get_actor_energy(game_service, sid, actor_id)
    if current_energy is not None and current_energy < skill.energy_cost:
        await _restore_skill_prompt(callback, game_service, sid, state)
        await callback.answer(
            _not_enough_energy_message(current_energy, skill.energy_cost),
            show_alert=True,
        )
        return

    current_hit_index = pending_hit_queue.pop(0)
    collected.append([current_hit_index, target_id])

    if pending_hit_queue:
        # Still more hits to target — show next picker
        next_hit_index = pending_hit_queue[0]
        next_hit = skill.hits[next_hit_index]
        candidates = (
            game_service.get_alive_enemies(sid)
            if next_hit.target_type == TargetType.SINGLE_ENEMY
            else game_service.get_alive_allies(sid)
        )
        prompt = _target_prompt(skill.name, next_hit_index, len(skill.hits))
        await state.update_data(
            pending_hit_queue=pending_hit_queue,
            collected_targets=collected,
        )
        await callback.message.edit_text(prompt, reply_markup=target_keyboard(candidates))
        await callback.answer()
        return

    # All targets collected — submit action
    action = ActionRequest(
        actor_id=actor_id,
        action_type=ActionType.ACTION,
        skill_id=skill_id,
        target_ids=tuple((idx, tid) for idx, tid in collected),
    )
    await state.update_data(
        pending_skill=None, pending_hit_queue=[], collected_targets=[],
    )
    await _submit_action(callback, game_service, sid, action, state, db_pool)


# ------------------------------------------------------------------
# Skip — g:skip
# ------------------------------------------------------------------

@router.callback_query(F.data == "g:skip")
async def cb_skip(
    callback: CallbackQuery,
    game_service: GameService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
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

    await _render_batch_and_prompt(
        callback,
        game_service,
        sid,
        batch,
        players,
        state,
        db_pool,
    )


# ------------------------------------------------------------------
# Shared helpers
# ------------------------------------------------------------------

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


async def _submit_action(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
    action: ActionRequest,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    """Submit action, render results, prompt next turn."""
    try:
        batch = game_service.submit_player_action(session_id, action)
    except ValueError as exc:
        await _restore_skill_prompt(callback, game_service, session_id, state)
        await callback.answer(str(exc), show_alert=True)
        return
    players = {p.entity_id: p for p in game_service.get_session_players(session_id)}

    await _render_batch_and_prompt(
        callback, game_service, session_id, batch, players, state, db_pool,
    )


async def _render_batch_and_prompt(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
    batch,
    players: dict,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    """Render turn batch results and either prompt next turn or show combat end."""
    await _clear_pending_combat_selection(state)
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
            await _send_reward_prompts(callback, game_service, session_id)
            await state.set_state(GameStates.exploring)
        elif phase == SessionPhase.ENDED:
            stats = game_service.get_run_stats(session_id)
            session = game_service._get_session(session_id)
            victory = session.state.end_reason == SessionEndReason.MAX_DEPTH
            await callback.message.answer(render_run_summary(stats, victory))
            if victory:
                await start_victory_save_flow(
                    callback.message,
                    game_service,
                    session_id,
                )
                await state.set_state(GameStates.save_decision)
            else:
                game_service.remove_session(session_id)
                await state.set_state(GameStates.run_ended)
        else:
            game_service.remove_session(session_id)
    else:
        # Prompt next player
        whose_turn = batch.whose_turn
        if whose_turn is not None and whose_turn in batch.entities:
            # Відправляємо оновлену картинку з актуальним HP перед наступним ходом
            await send_combat_image(callback, game_service, session_id)
            
            turn_snap = batch.entities[whose_turn]
            skills = game_service.get_available_skills(session_id, whose_turn)
            prompt = render_turn_prompt(whose_turn, turn_snap, players)
            await callback.message.answer(
                prompt,
                reply_markup=skill_keyboard(skills, turn_snap.current_energy),
            )
            await state.set_state(GameStates.combat_idle)


def _get_actor_energy(
    game_service: GameService,
    session_id: str,
    actor_id: str,
) -> int | None:
    snapshot = game_service.get_combat_snapshot(session_id)
    actor = snapshot.entities.get(actor_id)
    if actor is None:
        return None
    return actor.current_energy


def _not_enough_energy_message(current_energy: int, energy_cost: int) -> str:
    return f"Not enough energy: have {current_energy}, need {energy_cost}"


async def _clear_pending_combat_selection(state: FSMContext) -> None:
    await state.update_data(
        pending_skill=None,
        pending_hit_queue=[],
        collected_targets=[],
    )


async def _restore_skill_prompt(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
    state: FSMContext,
) -> None:
    previous_state = await state.get_state()
    await _clear_pending_combat_selection(state)
    await state.set_state(GameStates.combat_idle)

    if previous_state != GameStates.combat_target.state:
        return
    if not game_service.has_session(session_id) or not game_service.is_in_combat(session_id):
        return

    whose_turn = game_service.get_whose_turn(session_id)
    if whose_turn is None:
        return

    snapshot = game_service.get_combat_snapshot(session_id)
    turn_snap = snapshot.entities.get(whose_turn)
    if turn_snap is None:
        return

    players = {p.entity_id: p for p in game_service.get_session_players(session_id)}
    skills = game_service.get_available_skills(session_id, whose_turn)
    prompt = render_turn_prompt(whose_turn, turn_snap, players)
    await callback.message.edit_text(
        prompt,
        reply_markup=skill_keyboard(skills, turn_snap.current_energy),
    )
