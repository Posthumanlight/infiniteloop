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
    render_loot_resolution,
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
    normalize_skill_page,
    reward_choice_keyboard,
    skill_keyboard,
    target_keyboard,
)
from bot.tools.session_lookup import entity_id_for_tg_user
from game.combat.skill_targeting import (
    ActionTargetRef,
    ManualTargetRequirement,
    TargetOwnerKind,
    iter_manual_target_requirements,
)
from game.combat.models import ActionRequest
from game.combat.summons import commandable_summons_for_skill
from game.core.enums import ActionType, SessionEndReason, SessionPhase, TargetType
from game_service import GameService
from lobby_service import LobbyService

router = Router(name="combat_router")


def _session_id(chat_id: int) -> str:
    return str(chat_id)


async def _show_skill_prompt(
    callback: CallbackQuery,
    game_service: GameService,
    lobby_service: LobbyService,
    session_id: str,
    state: FSMContext,
    *,
    page: int,
    edit: bool,
) -> None:
    whose_turn = game_service.get_whose_turn(session_id)
    if whose_turn is None:
        return

    snapshot = game_service.get_combat_snapshot(session_id)
    turn_snap = snapshot.entities.get(whose_turn)
    if turn_snap is None:
        return

    players = {p.entity_id: p for p in lobby_service.get_session_players(session_id)}
    skills = game_service.get_available_skills(session_id, whose_turn)
    resolved_page = normalize_skill_page(skills, page)
    prompt = render_turn_prompt(whose_turn, turn_snap, players)

    await state.update_data(combat_skill_page=resolved_page)
    await state.set_state(GameStates.combat_idle)

    markup = skill_keyboard(
        skills,
        turn_snap.current_energy,
        page=resolved_page,
    )
    if edit:
        await callback.message.edit_text(prompt, reply_markup=markup)
    else:
        await callback.message.answer(prompt, reply_markup=markup)


def _parse_skill_page(callback_data: str, prefix: str) -> int | None:
    if not callback_data.startswith(prefix):
        return None
    try:
        return max(0, int(callback_data.removeprefix(prefix)))
    except ValueError:
        return None


def _serialize_target_requirement(
    requirement: ManualTargetRequirement,
) -> dict[str, object]:
    return {
        "owner_kind": requirement.owner_kind.value,
        "owner_index": requirement.owner_index,
        "nested_index": requirement.nested_index,
        "target_type": requirement.target_type.value,
    }


def _deserialize_target_requirement(payload: dict[str, object]) -> ManualTargetRequirement:
    return ManualTargetRequirement(
        owner_kind=TargetOwnerKind(str(payload["owner_kind"])),
        owner_index=int(payload["owner_index"]),
        nested_index=int(payload["nested_index"]),
        target_type=TargetType(str(payload["target_type"])),
    )


def _target_candidates_for_requirement(
    game_service: GameService,
    session_id: str,
    requirement: ManualTargetRequirement,
):
    return (
        game_service.get_alive_enemies(session_id)
        if requirement.target_type == TargetType.SINGLE_ENEMY
        else game_service.get_alive_allies(session_id)
    )


# ------------------------------------------------------------------
# Skill selection — g:sk:{skill_id}
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("g:skpg:"))
async def cb_skill_page(
    callback: CallbackQuery,
    game_service: GameService,
    lobby_service: LobbyService,
    state: FSMContext,
) -> None:
    sid = _session_id(callback.message.chat.id)
    actor_id = entity_id_for_tg_user(lobby_service, sid, callback.from_user.id)
    if actor_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return

    whose_turn = game_service.get_whose_turn(sid)
    if whose_turn != actor_id:
        await callback.answer("Not your turn!", show_alert=True)
        return

    page = _parse_skill_page(callback.data, "g:skpg:")
    if page is None:
        await callback.answer("Invalid page.", show_alert=True)
        return

    await _clear_pending_combat_selection(state)
    await _show_skill_prompt(
        callback,
        game_service,
        lobby_service,
        sid,
        state,
        page=page,
        edit=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("g:sk:"))
async def cb_skill(
    callback: CallbackQuery,
    game_service: GameService,
    lobby_service: LobbyService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    actor_id = entity_id_for_tg_user(lobby_service, sid, callback.from_user.id)
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

    data = await state.get_data()
    current_page = int(data.get("combat_skill_page", 0) or 0)
    if skill.summon_commands:
        combat_state = game_service._get_session(sid).state.combat
        if combat_state is not None and not commandable_summons_for_skill(
            combat_state,
            actor_id,
            skill,
        ):
            await callback.answer(
                "You have no eligible summons for this command.",
                show_alert=True,
            )
            return

    pending_requirements = list(iter_manual_target_requirements(skill))

    if not pending_requirements:
        # No target selection needed — submit immediately
        action = ActionRequest(
            actor_id=actor_id,
            action_type=ActionType.ACTION,
            skill_id=skill_id,
            target_refs=(),
        )
        await _submit_action(
            callback,
            game_service,
            lobby_service,
            sid,
            action,
            state,
            db_pool,
        )
        return

    await state.update_data(
        pending_skill=skill_id,
        pending_target_requirements=[
            _serialize_target_requirement(requirement)
            for requirement in pending_requirements
        ],
        collected_target_refs=[],
        pending_skill_page=current_page,
    )
    await state.set_state(GameStates.combat_target)
    first_requirement = pending_requirements[0]
    candidates = _target_candidates_for_requirement(
        game_service,
        sid,
        first_requirement,
    )
    prompt = _target_prompt(skill.name, 0, len(pending_requirements))
    await callback.message.edit_text(
        prompt,
        reply_markup=target_keyboard(candidates, back_page=current_page),
    )
    await callback.answer()


def _target_prompt(skill_name: str, target_index: int, total_targets: int) -> str:
    if total_targets <= 1:
        return f"Pick a target for {skill_name}:"
    return f"Pick a target for {skill_name} ({target_index + 1}/{total_targets}):"


# ------------------------------------------------------------------
# Target selection — g:tg:{entity_id}
# ------------------------------------------------------------------

@router.callback_query(F.data.startswith("g:back:skills:"))
async def cb_back_to_skills(
    callback: CallbackQuery,
    game_service: GameService,
    lobby_service: LobbyService,
    state: FSMContext,
) -> None:
    sid = _session_id(callback.message.chat.id)
    actor_id = entity_id_for_tg_user(lobby_service, sid, callback.from_user.id)
    if actor_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return

    whose_turn = game_service.get_whose_turn(sid)
    if whose_turn != actor_id:
        await callback.answer("Not your turn!", show_alert=True)
        return

    page = _parse_skill_page(callback.data, "g:back:skills:")
    if page is None:
        await callback.answer("Invalid page.", show_alert=True)
        return

    await _clear_pending_combat_selection(state)
    await _show_skill_prompt(
        callback,
        game_service,
        lobby_service,
        sid,
        state,
        page=page,
        edit=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("g:tg:"))
async def cb_target(
    callback: CallbackQuery,
    game_service: GameService,
    lobby_service: LobbyService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    actor_id = entity_id_for_tg_user(lobby_service, sid, callback.from_user.id)
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
    pending_requirements = [
        _deserialize_target_requirement(payload)
        for payload in (data.get("pending_target_requirements") or [])
    ]
    collected_payloads: list[dict[str, object]] = list(
        data.get("collected_target_refs") or [],
    )
    if skill_id is None or not pending_requirements:
        await callback.answer("No skill selected. Pick a skill first.", show_alert=True)
        return

    skills = game_service.get_available_skills(sid, actor_id)
    skill_match = next(((s, cd) for s, cd in skills if s.skill_id == skill_id), None)
    if skill_match is None:
        await _restore_skill_prompt(callback, game_service, lobby_service, sid, state)
        await callback.answer("Skill no longer available.", show_alert=True)
        return
    skill, cd = skill_match
    if cd > 0:
        await _restore_skill_prompt(callback, game_service, lobby_service, sid, state)
        await callback.answer(f"Skill on cooldown ({cd} turns)!", show_alert=True)
        return

    current_energy = _get_actor_energy(game_service, sid, actor_id)
    if current_energy is not None and current_energy < skill.energy_cost:
        await _restore_skill_prompt(callback, game_service, lobby_service, sid, state)
        await callback.answer(
            _not_enough_energy_message(current_energy, skill.energy_cost),
            show_alert=True,
        )
        return

    current_requirement = pending_requirements.pop(0)
    collected_payloads.append({
        "owner_kind": current_requirement.owner_kind.value,
        "owner_index": current_requirement.owner_index,
        "nested_index": current_requirement.nested_index,
        "entity_id": target_id,
    })
    current_page = int(
        data.get("pending_skill_page", data.get("combat_skill_page", 0)) or 0,
    )

    if pending_requirements:
        next_requirement = pending_requirements[0]
        candidates = _target_candidates_for_requirement(
            game_service,
            sid,
            next_requirement,
        )
        completed = len(collected_payloads)
        total = completed + len(pending_requirements)
        prompt = _target_prompt(skill.name, completed, total)
        await state.update_data(
            pending_target_requirements=[
                _serialize_target_requirement(requirement)
                for requirement in pending_requirements
            ],
            collected_target_refs=collected_payloads,
        )
        await callback.message.edit_text(
            prompt,
            reply_markup=target_keyboard(candidates, back_page=current_page),
        )
        await callback.answer()
        return

    action = ActionRequest(
        actor_id=actor_id,
        action_type=ActionType.ACTION,
        skill_id=skill_id,
        target_refs=tuple(
            ActionTargetRef(
                owner_kind=TargetOwnerKind(str(payload["owner_kind"])),
                owner_index=int(payload["owner_index"]),
                nested_index=int(payload["nested_index"]),
                entity_id=str(payload["entity_id"]),
            )
            for payload in collected_payloads
        ),
    )
    await state.update_data(
        pending_skill=None,
        pending_target_requirements=[],
        collected_target_refs=[],
    )
    await _submit_action(
        callback,
        game_service,
        lobby_service,
        sid,
        action,
        state,
        db_pool,
    )


# ------------------------------------------------------------------
# Skip — g:skip
# ------------------------------------------------------------------

@router.callback_query(F.data == "g:skip")
async def cb_skip(
    callback: CallbackQuery,
    game_service: GameService,
    lobby_service: LobbyService,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    sid = _session_id(callback.message.chat.id)
    actor_id = entity_id_for_tg_user(lobby_service, sid, callback.from_user.id)
    if actor_id is None:
        await callback.answer("You are not in this game.", show_alert=True)
        return

    whose_turn = game_service.get_whose_turn(sid)
    if whose_turn != actor_id:
        await callback.answer("Not your turn!", show_alert=True)
        return

    batch = game_service.skip_player_turn(sid, actor_id)
    players = {p.entity_id: p for p in lobby_service.get_session_players(sid)}

    await _render_batch_and_prompt(
        callback,
        game_service,
        lobby_service,
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
    lobby_service: LobbyService,
    session_id: str,
) -> None:
    players = {p.entity_id: p for p in lobby_service.get_session_players(session_id)}

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
    lobby_service: LobbyService,
    session_id: str,
    action: ActionRequest,
    state: FSMContext,
    db_pool: asyncpg.Pool,
) -> None:
    """Submit action, render results, prompt next turn."""
    try:
        batch = game_service.submit_player_action(session_id, action)
    except ValueError as exc:
        await _restore_skill_prompt(
            callback,
            game_service,
            lobby_service,
            session_id,
            state,
        )
        await callback.answer(str(exc), show_alert=True)
        return
    players = {p.entity_id: p for p in lobby_service.get_session_players(session_id)}

    await _render_batch_and_prompt(
        callback,
        game_service,
        lobby_service,
        session_id,
        batch,
        players,
        state,
        db_pool,
    )


async def _render_batch_and_prompt(
    callback: CallbackQuery,
    game_service: GameService,
    lobby_service: LobbyService,
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

        loot = game_service.consume_pending_loot(session_id)
        if loot is not None and loot.awards:
            player_names = {
                player.entity_id: player.display_name
                for player in lobby_service.get_session_players(session_id)
            }
            for text in render_loot_resolution(loot, player_names):
                await callback.message.answer(text)

        # Check what comes next in the exploration loop
        phase = game_service.get_session_phase(session_id)
        if phase == SessionPhase.EXPLORING:
            game_service.continue_exploration(session_id)
            options = game_service.get_exploration_choices(session_id)
            await callback.message.answer(
                render_exploration_choices(options, (), players),
                reply_markup=location_keyboard(options),
            )
            await _send_reward_prompts(
                callback,
                game_service,
                lobby_service,
                session_id,
            )
            await state.set_state(GameStates.exploring)
        elif phase == SessionPhase.ENDED:
            stats = game_service.get_run_stats(session_id)
            session = game_service._get_session(session_id)
            victory = session.state.end_reason == SessionEndReason.MAX_DEPTH
            await callback.message.answer(render_run_summary(stats, victory))
            if victory:
                await start_victory_save_flow(
                    callback.message,
                    lobby_service,
                    session_id,
                )
                await state.set_state(GameStates.save_decision)
            else:
                lobby_service.close_session(session_id)
                await state.set_state(GameStates.run_ended)
        else:
            lobby_service.close_session(session_id)
    else:
        # Prompt next player
        whose_turn = batch.whose_turn
        if whose_turn is not None and whose_turn in batch.entities:
            # Відправляємо оновлену картинку з актуальним HP перед наступним ходом
            await send_combat_image(callback, game_service, session_id)
            
            await _show_skill_prompt(
                callback,
                game_service,
                lobby_service,
                session_id,
                state,
                page=0,
                edit=False,
            )


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
        pending_target_requirements=[],
        collected_target_refs=[],
        pending_skill_page=None,
    )


async def _restore_skill_prompt(
    callback: CallbackQuery,
    game_service: GameService,
    lobby_service: LobbyService,
    session_id: str,
    state: FSMContext,
) -> None:
    previous_state = await state.get_state()
    data = await state.get_data()
    page = int(data.get("pending_skill_page", data.get("combat_skill_page", 0)) or 0)
    await _clear_pending_combat_selection(state)

    if previous_state != GameStates.combat_target.state:
        return
    if (
        not lobby_service.has_active_session(session_id)
        or not game_service.is_in_combat(session_id)
    ):
        return
    await _show_skill_prompt(
        callback,
        game_service,
        lobby_service,
        session_id,
        state,
        page=page,
        edit=True,
    )


