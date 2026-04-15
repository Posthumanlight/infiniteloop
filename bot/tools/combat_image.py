import asyncio
import logging

from aiogram.types import CallbackQuery, FSInputFile

from game_service import GameService
from resources.merger import generate_battle_scene

logger = logging.getLogger("telegram_bot")
logger.setLevel(logging.DEBUG)


async def send_combat_image(
    callback: CallbackQuery,
    game_service: GameService,
    session_id: str,
) -> None:
    """Збирає дані про мобів, генерує картинку та відправляє її в чат."""
    logger.info(f"[{session_id}] Початок підготовки генерації картинки бою для сесії.")
    try:
        enemies_snaps = game_service.get_alive_enemies(session_id)
        logger.debug(f"[{session_id}] Отримано {len(enemies_snaps)} живих ворогів.")
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
            room_number = session.state.run_stats.rooms_explored + 1
            logger.debug(f"[{session_id}] Визначено номер поточної кімнати: {room_number}.")
        except AttributeError:
            room_number = 1
            logger.debug(f"[{session_id}] Не вдалося отримати rooms_explored, використано значення за замовчуванням (1).")
        
        logger.info(f"[{session_id}] Передача процесу генерації у тредпул (generate_battle_scene)...")
        image_path = await asyncio.to_thread(
            generate_battle_scene, session_id, room_number, enemies_data
        )
        logger.info(f"[{session_id}] Зображення успішно згенеровано: {image_path}. Відправка у чат...")
        
        await callback.message.answer_photo(photo=FSInputFile(image_path))
        logger.info(f"[{session_id}] Зображення бою успішно відправлено.")
    except Exception as e:
        logger.error(f"[{session_id}] Помилка під час генерації або відправки картинки бою: {e}", exc_info=True)