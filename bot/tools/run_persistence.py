import asyncpg

from db.queries.users_namespace import UserCharactersData
from game.core.enums import SessionEndReason
from game_service import GameService


async def persist_victory_progress(
    game_service: GameService,
    session_id: str,
    db_pool: asyncpg.Pool,
) -> None:
    if not game_service.has_session(session_id):
        return

    session = game_service._get_session(session_id)
    if (
        session.state is None
        or session.state.end_reason != SessionEndReason.MAX_DEPTH
    ):
        return

    chars_db = UserCharactersData(pool=db_pool)
    origins = session.save_origins or {}
    for player in session.state.players:
        origin = origins.get(player.entity_id)
        character_id = getattr(origin, "character_id", None)
        if character_id is None:
            continue
        character_name = getattr(origin, "character_name", None)
        if character_name is None:
            character_name = f"character_{character_id}"
        await chars_db.save_character_progress(
            character_id=int(character_id),
            character_name=character_name,
            level=player.level,
            xp=player.xp,
            skills=player.skills,
            skill_modifiers=player.skill_modifiers,
        )
