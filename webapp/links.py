"""Mini App link helpers shared by the bot and backend."""

from urllib.parse import quote


CHAR_START_PARAM_PREFIX = "char_"


def build_char_start_param(session_id: str) -> str:
    return f"{CHAR_START_PARAM_PREFIX}{session_id}"


def parse_char_session_id(start_param: str | None) -> str:
    if not start_param:
        raise ValueError("Mini App session payload is missing")
    if not start_param.startswith(CHAR_START_PARAM_PREFIX):
        raise ValueError("Unsupported Mini App entrypoint")

    session_id = start_param.removeprefix(CHAR_START_PARAM_PREFIX)
    if not session_id:
        raise ValueError("Mini App session payload is empty")
    return session_id


def build_direct_mini_app_link(bot_username: str, start_param: str) -> str:
    if not bot_username:
        raise ValueError("Bot username is required for Mini App links")
    encoded = quote(start_param, safe="")
    return f"https://t.me/{bot_username}?startapp={encoded}"
