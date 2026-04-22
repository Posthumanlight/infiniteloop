"""Bot-side helper to map a Telegram user ID to the player's entity_id."""
from lobby_service import LobbyService


def entity_id_for_tg_user(
    lobby_service: LobbyService, session_id: str, tg_user_id: int,
) -> str | None:
    """Return the entity_id of the player matching tg_user_id in this session."""
    if not lobby_service.has_active_session(session_id):
        return None
    for player in lobby_service.get_session_players(session_id):
        if player.tg_user_id == tg_user_id:
            return player.entity_id
    return None
