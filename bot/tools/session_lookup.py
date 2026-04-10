"""Bot-side helper to map a Telegram user ID to the player's entity_id."""
from game_service import GameService


def entity_id_for_tg_user(
    game_service: GameService, session_id: str, tg_user_id: int,
) -> str | None:
    """Return the entity_id of the player matching tg_user_id in this session."""
    if not game_service.has_session(session_id):
        return None
    for player in game_service.get_session_players(session_id):
        if player.tg_user_id == tg_user_id:
            return player.entity_id
    return None
