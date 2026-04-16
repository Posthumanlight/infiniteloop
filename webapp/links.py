"""Mini App link helpers shared by the bot and backend."""

from dataclasses import dataclass
from urllib.parse import quote


CHAR_START_PARAM_PREFIX = "char_"
INVENTORY_START_PARAM_PREFIX = "inventory_"


@dataclass(frozen=True)
class WebAppEntry:
    session_id: str
    initial_view: str


def build_char_start_param(session_id: str) -> str:
    return f"{CHAR_START_PARAM_PREFIX}{session_id}"


def build_inventory_start_param(session_id: str) -> str:
    return f"{INVENTORY_START_PARAM_PREFIX}{session_id}"


def parse_webapp_entry(start_param: str | None) -> WebAppEntry:
    if not start_param:
        raise ValueError("Mini App session payload is missing")
    if start_param.startswith(CHAR_START_PARAM_PREFIX):
        session_id = start_param.removeprefix(CHAR_START_PARAM_PREFIX)
        if not session_id:
            raise ValueError("Mini App session payload is empty")
        return WebAppEntry(session_id=session_id, initial_view="character")
    if start_param.startswith(INVENTORY_START_PARAM_PREFIX):
        session_id = start_param.removeprefix(INVENTORY_START_PARAM_PREFIX)
        if not session_id:
            raise ValueError("Mini App session payload is empty")
        return WebAppEntry(session_id=session_id, initial_view="inventory")
    raise ValueError("Unsupported Mini App entrypoint")


def parse_char_session_id(start_param: str | None) -> str:
    entry = parse_webapp_entry(start_param)
    if entry.initial_view != "character":
        raise ValueError("Unsupported Mini App entrypoint")
    return entry.session_id


def build_direct_mini_app_link(bot_username: str, start_param: str) -> str:
    if not bot_username:
        raise ValueError("Bot username is required for Mini App links")
    encoded = quote(start_param, safe="")
    return f"https://t.me/{bot_username}?startapp={encoded}"
