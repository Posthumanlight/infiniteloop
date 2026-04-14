"""FastAPI routes for the Telegram Mini App."""

from fastapi import APIRouter, HTTPException, Request

from bot.tools.character_renderer import render_character_sheet
from bot.tools.session_lookup import entity_id_for_tg_user
from config import settings
from webapp.auth import parse_telegram_init_data
from webapp.links import parse_char_session_id
from webapp.schemas import (
    CharacterBootstrapIn,
    CharacterBootstrapOut,
    CharacterSheetOut,
)

router = APIRouter(prefix="/api/webapp", tags=["webapp"])


@router.post("/char/bootstrap", response_model=CharacterBootstrapOut)
async def bootstrap_character(
    payload: CharacterBootstrapIn,
    request: Request,
) -> CharacterBootstrapOut:
    try:
        init_data = parse_telegram_init_data(
            token=settings.telegram_bot_token,
            init_data=payload.init_data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Telegram init data") from exc

    if init_data.user is None:
        raise HTTPException(status_code=401, detail="Telegram user is missing")

    try:
        session_id = parse_char_session_id(init_data.start_param)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    game_service = request.app.state.game_service
    if not game_service.has_session(session_id):
        raise HTTPException(status_code=404, detail="No active game for this chat")

    entity_id = entity_id_for_tg_user(game_service, session_id, init_data.user.id)
    if entity_id is None:
        raise HTTPException(status_code=403, detail="You are not in the current game")

    try:
        sheet = game_service.get_character_sheet(session_id, entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CharacterBootstrapOut(
        sheet=CharacterSheetOut.from_domain(sheet),
        legacy_text=render_character_sheet(sheet),
    )
