"""FastAPI routes for the Telegram Mini App."""

from fastapi import APIRouter, HTTPException, Request

from bot.tools.character_renderer import render_character_sheet
from bot.tools.session_lookup import entity_id_for_tg_user
from config import settings
from webapp.auth import parse_telegram_init_data
from webapp.links import WebAppEntry, parse_char_session_id, parse_webapp_entry
from webapp.schemas import (
    CharacterBootstrapIn,
    CharacterBootstrapOut,
    CharacterSheetOut,
    InventoryMoveIn,
    InventoryMoveOut,
    InventoryOut,
    WebAppBootstrapIn,
    WebAppBootstrapOut,
)

router = APIRouter(prefix="/api/webapp", tags=["webapp"])


def _parse_entry(payload_init_data: str) -> tuple[object, WebAppEntry]:
    try:
        init_data = parse_telegram_init_data(
            token=settings.telegram_bot_token,
            init_data=payload_init_data,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid Telegram init data") from exc

    if init_data.user is None:
        raise HTTPException(status_code=401, detail="Telegram user is missing")

    try:
        entry = parse_webapp_entry(init_data.start_param)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return init_data, entry


def _resolve_entity_id(
    request: Request,
    init_data: object,
    session_id: str,
) -> tuple[object, str]:
    game_service = request.app.state.game_service
    if not game_service.has_session(session_id):
        raise HTTPException(status_code=404, detail="No active game for this chat")

    entity_id = entity_id_for_tg_user(game_service, session_id, init_data.user.id)
    if entity_id is None:
        raise HTTPException(status_code=403, detail="You are not in the current game")
    return game_service, entity_id


@router.post("/bootstrap", response_model=WebAppBootstrapOut)
async def bootstrap_webapp(
    payload: WebAppBootstrapIn,
    request: Request,
) -> WebAppBootstrapOut:
    init_data, entry = _parse_entry(payload.init_data)
    game_service, entity_id = _resolve_entity_id(request, init_data, entry.session_id)

    try:
        sheet = game_service.get_character_sheet(entry.session_id, entity_id)
        inventory = game_service.get_inventory(entry.session_id, entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return WebAppBootstrapOut(
        initial_view=entry.initial_view,
        sheet=CharacterSheetOut.from_domain(sheet),
        inventory=InventoryOut.from_domain(inventory),
        legacy_text=render_character_sheet(sheet),
    )


@router.post("/char/bootstrap", response_model=CharacterBootstrapOut)
async def bootstrap_character(
    payload: CharacterBootstrapIn,
    request: Request,
) -> CharacterBootstrapOut:
    init_data, _entry = _parse_entry(payload.init_data)

    try:
        session_id = parse_char_session_id(init_data.start_param)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    game_service, entity_id = _resolve_entity_id(request, init_data, session_id)

    try:
        sheet = game_service.get_character_sheet(session_id, entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CharacterBootstrapOut(
        sheet=CharacterSheetOut.from_domain(sheet),
        legacy_text=render_character_sheet(sheet),
    )


@router.post("/inventory/move", response_model=InventoryMoveOut)
async def move_inventory_item(
    payload: InventoryMoveIn,
    request: Request,
) -> InventoryMoveOut:
    init_data, entry = _parse_entry(payload.init_data)
    game_service, entity_id = _resolve_entity_id(request, init_data, entry.session_id)

    try:
        current_inventory = game_service.get_inventory(entry.session_id, entity_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    current_item = next(
        (item for item in current_inventory.items if item.instance_id == payload.instance_id),
        None,
    )
    if current_item is None:
        raise HTTPException(status_code=404, detail="Item is not in your inventory")

    try:
        if payload.destination_kind == "inventory":
            if current_item.equipped_slot is not None:
                game_service.unequip_item(entry.session_id, entity_id, payload.instance_id)
        elif payload.destination_kind == "equipment":
            if payload.slot_type not in {"weapon", "armor", "relic"}:
                raise HTTPException(status_code=400, detail="Unsupported equipment slot")
            if payload.slot_type != current_item.item_type:
                raise HTTPException(status_code=400, detail="Item does not match that equipment slot")
            current_slot_index = current_item.equipped_index if current_item.equipped_slot == "relic" else None
            if current_item.equipped_slot == payload.slot_type and current_slot_index == payload.slot_index:
                pass
            else:
                relic_slot = payload.slot_index if payload.slot_type == "relic" else None
                game_service.equip_item(
                    entry.session_id,
                    entity_id,
                    payload.instance_id,
                    relic_slot=relic_slot,
                )
        else:
            raise HTTPException(status_code=400, detail="Unsupported destination")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sheet = game_service.get_character_sheet(entry.session_id, entity_id)
    inventory = game_service.get_inventory(entry.session_id, entity_id)
    return InventoryMoveOut(
        sheet=CharacterSheetOut.from_domain(sheet),
        inventory=InventoryOut.from_domain(inventory),
    )
