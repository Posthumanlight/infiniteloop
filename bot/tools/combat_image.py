import asyncio

from aiogram.types import CallbackQuery, FSInputFile

from game_service import GameService
from resources.merger import generate_battle_scene


async def send_combat_image(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
) -> None:
    """Збирає дані про мобів, генерує картинку та відправляє її в чат."""
    try:
        enemies_snaps = game_service.get_alive_enemies(session_id)
        enemies_data = [
            {
                "entity_id": e.entity_id,
                "name": e.name,
                "current_hp": e.current_hp,
                "max_hp": e.max_hp
            }
            for e in enemies_snaps
        ]
        
        # Отримуємо номер кімнати. Використовувати round_number не можна, бо він міняється щоходу.
        # Спробуємо дістати кількість пройдених кімнат з run_stats, або за замовчуванням 1
        session = game_service._get_session(session_id)
        try:
            room_number = session.state.run_stats.locations_visited
        except AttributeError:
            room_number = 1
        
        image_path = await asyncio.to_thread(
            generate_battle_scene, session_id, room_number, enemies_data
        )
        
        await callback.message.answer_photo(photo=FSInputFile(image_path))
    except Exception as e:
        print(f"Помилка під час генерації або відправки картинки бою: {e}")