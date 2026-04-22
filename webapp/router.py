"""FastAPI routes for the Telegram Mini App."""

from fastapi import APIRouter, HTTPException, Request

from bot.tools.character_renderer import render_character_sheet
from config import settings
from db.queries.users_namespace import UserCurrenciesDB
from game.core.data_loader import load_item_dissolve_constants
from game.items.dissolve import dissolve_currency_name
from webapp.auth import parse_telegram_init_data
from webapp.links import WebAppEntry, parse_char_session_id, parse_webapp_entry
from webapp.schemas import (
    CharacterBootstrapIn,
    CharacterBootstrapOut,
    CharacterSheetOut,
    CurrencyBalanceOut,
    InventoryDissolveIn,
    InventoryDissolveOut,
    InventoryMoveIn,
    InventoryMoveOut,
    InventoryOut,
    SavedCharacterOut,
    WebAppTargetIn,
    WebAppBootstrapIn,
    WebAppBootstrapOut,
)
from lobby_service import CharacterTarget, LobbyService

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


def _get_lobby_service(request: Request) -> LobbyService:
    return request.app.state.lobby_service


def _target_from_payload(
    lobby_service: LobbyService,
    init_data: object,
    target: WebAppTargetIn,
) -> CharacterTarget:
    if target.kind == "session":
        if target.session_id is None:
            raise HTTPException(status_code=400, detail="Mini App session payload is missing")
        resolved = lobby_service.target_for_session_user(
            target.session_id,
            init_data.user.id,
        )
        if resolved is None:
            raise HTTPException(status_code=403, detail="You are not in the current game")
        return resolved

    if target.kind == "saved":
        if target.character_id is None:
            raise HTTPException(status_code=400, detail="Character id is missing")
        return CharacterTarget(
            kind="saved",
            tg_user_id=init_data.user.id,
            character_id=target.character_id,
        )

    raise HTTPException(status_code=400, detail="Unsupported character target")


async def _selection_response(
    lobby_service: LobbyService,
    target: CharacterTarget,
    *,
    initial_view: str,
) -> WebAppBootstrapOut:
    selection = await lobby_service.get_character_selection(target)
    response_target = (
        WebAppTargetIn(kind="saved", character_id=target.character_id)
        if target.kind == "saved"
        else WebAppTargetIn(kind="session", session_id=target.session_id)
    )
    return WebAppBootstrapOut(
        mode="loaded",
        initial_view=initial_view,
        target=response_target,
        sheet=CharacterSheetOut.from_domain(selection.sheet),
        inventory=InventoryOut.from_domain(selection.inventory),
        legacy_text=render_character_sheet(selection.sheet),
    )


@router.post("/bootstrap", response_model=WebAppBootstrapOut)
async def bootstrap_webapp(
    payload: WebAppBootstrapIn,
    request: Request,
) -> WebAppBootstrapOut:
    init_data, entry = _parse_entry(payload.init_data)
    lobby_service = _get_lobby_service(request)

    if payload.target is not None:
        target = _target_from_payload(lobby_service, init_data, payload.target)
        try:
            return await _selection_response(
                lobby_service,
                target,
                initial_view=entry.initial_view,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if entry.mode == "browser":
        characters = await lobby_service.list_user_characters(init_data.user.id)
        return WebAppBootstrapOut(
            mode="chooser",
            initial_view=entry.initial_view,
            characters=[
                SavedCharacterOut.from_domain(character)
                for character in characters
            ],
        )

    if entry.session_id is None:
        raise HTTPException(status_code=400, detail="Mini App session payload is missing")

    target = lobby_service.target_for_session_user(entry.session_id, init_data.user.id)
    if target is None:
        raise HTTPException(status_code=403, detail="You are not in the current game")

    try:
        return await _selection_response(
            lobby_service,
            target,
            initial_view=entry.initial_view,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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

    lobby_service = _get_lobby_service(request)
    target = lobby_service.target_for_session_user(session_id, init_data.user.id)
    if target is None:
        raise HTTPException(status_code=403, detail="You are not in the current game")

    try:
        sheet = await lobby_service.get_character_sheet(target)
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
    lobby_service = _get_lobby_service(request)
    target = _target_from_payload(lobby_service, init_data, payload.target)

    try:
        current_inventory = await lobby_service.get_inventory(target)
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
                await lobby_service.unequip_item(target, payload.instance_id)
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
                await lobby_service.equip_item(
                    target,
                    payload.instance_id,
                    relic_slot=relic_slot,
                )
        else:
            raise HTTPException(status_code=400, detail="Unsupported destination")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    selection = await lobby_service.get_character_selection(target)
    return InventoryMoveOut(
        sheet=CharacterSheetOut.from_domain(selection.sheet),
        inventory=InventoryOut.from_domain(selection.inventory),
    )


@router.post("/inventory/dissolve", response_model=InventoryDissolveOut)
async def dissolve_inventory_items(
    payload: InventoryDissolveIn,
    request: Request,
) -> InventoryDissolveOut:
    init_data, entry = _parse_entry(payload.init_data)
    lobby_service = _get_lobby_service(request)
    target = _target_from_payload(lobby_service, init_data, payload.target)

    instance_ids = tuple(payload.instance_ids)
    if not instance_ids:
        raise HTTPException(status_code=400, detail="No items selected")

    try:
        dissolved_preview, payout = await lobby_service.preview_dissolve_inventory_items(
            target,
            instance_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Item is not in your inventory") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    currency_name = dissolve_currency_name(load_item_dissolve_constants())
    try:
        currency = await UserCurrenciesDB(
            request.app.state.db_pool,
        ).add_currency(
            init_data.user.id,
            currency_name,
            payout,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Failed to grant dissolve currency",
        ) from exc

    try:
        _player, dissolved_items, confirmed_payout = await lobby_service.dissolve_inventory_items(
            target,
            instance_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Item is not in your inventory") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    selection = await lobby_service.get_character_selection(target)
    dissolved_ids = [
        item.instance_id
        for item in dissolved_items
    ]
    if not dissolved_ids:
        dissolved_ids = [item.instance_id for item in dissolved_preview]

    return InventoryDissolveOut(
        sheet=CharacterSheetOut.from_domain(selection.sheet),
        inventory=InventoryOut.from_domain(selection.inventory),
        dissolved_item_ids=dissolved_ids,
        currency_delta=confirmed_payout,
        currency=CurrencyBalanceOut(
            currency_name=currency.currency_name,
            current_value=currency.current_value,
        ),
    )
