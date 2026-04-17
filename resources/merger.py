import os
import random
import json
import logging
from PIL import Image, ImageDraw, ImageFont
from bot.logging.bot_log import setup_telegram_logging

logger, _ = setup_telegram_logging()
logger.setLevel(logging.DEBUG)

def get_random_png(folder_path):
    logger.debug(f"Шукаю випадковий PNG файл у папці: '{folder_path}'")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Масив можливих шляхів пошуку
    search_paths = [
        os.path.join(script_dir, folder_path),
        os.path.join(script_dir, "Locations", folder_path),
        os.path.join(script_dir, "Mobs", folder_path),
    ]
    
    actual_path = None
    for p in search_paths:
        if os.path.exists(p):
            actual_path = p
            break
            
    if not actual_path:
        logger.error(f"Папку '{folder_path}' не знайдено! Перевірені шляхи: {search_paths}")
        raise FileNotFoundError(f"Папку '{folder_path}' не знайдено!")

    png_files = [f for f in os.listdir(actual_path) if f.lower().endswith('.png')]
    if not png_files:
        logger.error(f"У знайдений папці '{actual_path}' немає PNG файлів.")
        raise FileNotFoundError(f"У папці '{actual_path}' немає PNG файлів")
    
    selected_png = random.choice(png_files)
    logger.debug(f"Обрано файл: '{selected_png}' з директорії '{actual_path}'")
    return os.path.join(actual_path, selected_png)

def get_sekuya_font(size):
    logger.debug(f"Спроба завантажити шрифт 'Sekuya' розміром {size}")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(script_dir, "Fonts", "Sekuya")
    if os.path.exists(font_dir):
        for f in os.listdir(font_dir):
            if f.lower().endswith('.ttf') or f.lower().endswith('.otf'):
                logger.debug(f"Шрифт знайдено і підвантажено: {f}")
                return ImageFont.truetype(os.path.join(font_dir, f), size)
    
    logger.warning(f"Шрифт Sekuya не знайдено в '{font_dir}', спроба підвантажити стандартний 'arial.ttf'")
    try:
        return ImageFont.truetype("arial.ttf", size)
    except IOError:
        logger.warning("Шрифт 'arial.ttf' також не знайдено. Завантажено дефолтний шрифт PIL.")
        return ImageFont.load_default()

def generate_battle_scene(session_id: str, room_number: int, enemies_data: list[dict]) -> str:
    logger.info(f"[{session_id}] Початок 'generate_battle_scene' (кімната {room_number}). Вхідна кількість ворогів: {len(enemies_data)}")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Конфігурація мобів. Легко розширювати, просто додаючи нові словники.
    MOB_CONFIG = [
        {"keys": ["wolf", "вовк"], "folder": "wolfs", "size": (710, 532)},
        {"keys": ["goblin", "гоблін"], "folder": "goblins", "size": (600, 600)},
        {"keys": ["skeleton", "скелет"], "folder": "skeletons", "size": (600, 600)},
        {"keys": ["imp", "імп"], "folder": "fire_imps", "size": (500, 500)},
        {"keys": ["bandit", "бандит"], "folder": "bandits", "size": (700, 700)},
        {"keys": ["crocodile", "крокодил"], "folder": "crocodile", "size": (710, 532)},
        {"keys": ["draugr", "драугр"], "folder": "draugrs", "size": (700, 700)},
        {"keys": ["bayayamshiks", "баяямшикс"], "folder": "EXPLICIT_BOSS", "size": (800, 800), "explicit_path": os.path.join(script_dir, "Mobs", "bosses", "Bayayamshiks.png"), "is_boss": True},
    ]

    # 1. Налаштування позицій (центри) для 5 ворогів
    placement_pool = [(330, 960), (885, 1110), (1395, 876), (1820, 1070), (2450, 1080)]
    
    # 2. Створення папки для поточної сесії та кімнати
    session_dir = os.path.join(script_dir, "sessions scenes", str(session_id), str(room_number))
    os.makedirs(session_dir, exist_ok=True)
    logger.debug(f"[{session_id}] Директорію для сцени створено/перевірено: {session_dir}")
    
    # 3. Файл стану кімнати (зберігає фон і прив'язку мобів до їхніх картинок/позицій)
    state_file = os.path.join(session_dir, "room_state.json")
    room_state = {"bg_path": None, "entities": {}, "used_positions": []}
    
    if os.path.exists(state_file):
        logger.debug(f"[{session_id}] Виявлено файл стану кімнати: {state_file}")
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                loaded_state = json.load(f)
                if isinstance(loaded_state, dict):
                    room_state.update(loaded_state)
        except json.JSONDecodeError:
            logger.warning(f"[{session_id}] Помилка декодування JSON із файлу стану кімнати. Буде використано порожній стан.")
            pass # Fallback to default room_state if the file is corrupted
            
    if not room_state.get("bg_path"):
        room_state["bg_path"] = get_random_png("cave")
        logger.debug(f"[{session_id}] Згенеровано новий фон: {room_state['bg_path']}")
    else:
        logger.debug(f"[{session_id}] Використовується збережений фон: {room_state['bg_path']}")
    
    mobs_to_spawn = []
    
    for enemy in enemies_data[:5]: # Обмежуємо до 5 позицій на екрані
        name = enemy.get("name", "")
        entity_id = enemy.get("entity_id", name + str(random.randint(1000, 9999)))
        hp = enemy.get("current_hp", 100)
        max_hp = enemy.get("max_hp", 100)
        name_lower = name.lower()
        
        matched = False
        for config in MOB_CONFIG:
            if any(k in name_lower for k in config["keys"]):
                mob_data = {
                    "entity_id": entity_id,
                    "name": name,
                    "folder": config["folder"],
                    "size": config["size"],
                    "hp": hp,
                    "max_hp": max_hp
                }
                if config.get("is_boss"):
                    mob_data["is_boss"] = True
                    mob_data["explicit_path"] = config["explicit_path"]
                mobs_to_spawn.append(mob_data)
                matched = True
                break
                
        if not matched:
            mobs_to_spawn.append({"entity_id": entity_id, "name": name, "folder": "ERROR_TEXT", "size": (400, 400), "hp": hp, "max_hp": max_hp})
            logger.warning(f"[{session_id}] Невідомий тип моба '{name}', буде підставлено заглушку (ERROR_TEXT).")
            
    # Оновлюємо та зберігаємо стан кімнати
    # Сортуємо: спочатку боси, щоб їм гарантовано дістались центральні позиції
    mobs_to_spawn.sort(key=lambda m: not m.get("is_boss", False))
    
    # Перераховуємо зайняті позиції тільки для актуальних мобів (щоб позиції мертвих мобів звільнялися)
    active_used_positions = []
    for mob in mobs_to_spawn:
        eid = mob["entity_id"]
        if eid in room_state["entities"]:
            active_used_positions.append(room_state["entities"][eid]["pos_idx"])
            
    for mob in mobs_to_spawn:
        eid = mob["entity_id"]
        if eid not in room_state["entities"]:
            # Шукаємо вільну позицію
            if mob.get("is_boss"):
                avail_pos = [i for i in [1, 2, 3] if i not in active_used_positions]
            else:
                avail_pos = [i for i in range(len(placement_pool)) if i not in active_used_positions]
                
            if not avail_pos:
                avail_pos = [i for i in range(len(placement_pool)) if i not in active_used_positions]
                if not avail_pos:
                    avail_pos = [i for i in range(len(placement_pool))] # Фолбек
            chosen_pos = random.choice(avail_pos)
            active_used_positions.append(chosen_pos)
            
            # Обираємо випадкову картинку для цього моба на весь бій
            if mob["folder"] == "ERROR_TEXT":
                img_path = "NONE"
                logger.debug(f"[{session_id}] Для моба '{mob['name']}' (ID: {eid}) встановлено відсутність картинки (NONE).")
            elif mob["folder"] == "EXPLICIT_BOSS":
                img_path = mob["explicit_path"]
                logger.debug(f"[{session_id}] Для боса '{mob['name']}' (ID: {eid}) прив'язано картинку: {img_path}")
            else:
                img_path = get_random_png(mob["folder"])
                logger.debug(f"[{session_id}] Для моба '{mob['name']}' (ID: {eid}) прив'язано картинку: {img_path}")
            room_state["entities"][eid] = {"pos_idx": chosen_pos, "img_path": img_path}
            
    room_state["used_positions"] = active_used_positions
    
    # Очищуємо старих мобів з entities, яких вже немає, щоб JSON файл стану не розростався
    active_eids = {mob["entity_id"] for mob in mobs_to_spawn}
    room_state["entities"] = {k: v for k, v in room_state["entities"].items() if k in active_eids}

    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(room_state, f, ensure_ascii=False, indent=4)
    logger.debug(f"[{session_id}] Стан кімнати успішно оновлено та записано у {state_file}")
    
    logger.info(f"[{session_id}] Використовується файл заднього фону: {room_state.get('bg_path')}")
    for mob in mobs_to_spawn:
        eid = mob["entity_id"]
        pos_idx = room_state["entities"].get(eid, {}).get("pos_idx")
        if pos_idx is not None:
            logger.info(f"[{session_id}] Ворог '{mob['name']}' (ID: {eid}) отримав позицію {pos_idx} {placement_pool[pos_idx]}")

    # 4. Відкриваємо збережений фон
    background = Image.open(room_state["bg_path"]).convert("RGBA")
    
    draw = ImageDraw.Draw(background)
    font_name = get_sekuya_font(40)
    font_hp = get_sekuya_font(30)
    
    logger.info(f"[{session_id}] Генерація візуалу бою для мобів: {[m['folder'] for m in mobs_to_spawn]}")

    # 5. Проходимо по мобах, беремо їх збережені позиції і картинки
    for mob in mobs_to_spawn:
        eid = mob["entity_id"]
        saved_data = room_state["entities"].get(eid)
        if not saved_data:
            logger.error(f"[{session_id}] Моб із ID {eid} не знайдений у стані кімнати, пропускаємо відмальовку!")
            continue
            
        cx, cy = placement_pool[saved_data["pos_idx"]]
        
        # Відкриваємо закріплену за мобом картинку
        mob_img_path = saved_data["img_path"]
        
        # Змінюємо розмір згідно з типом моба
        width, height = mob["size"]
        is_boss = mob.get("is_boss", False)
        
        if mob_img_path == "NONE":
            # Малюємо великий червоний текст ERROR замість картинки
            font_error = get_sekuya_font(80)
            try:
                bbox_err = draw.textbbox((0, 0), "ERROR", font=font_error)
                tw_err = bbox_err[2] - bbox_err[0]
                th_err = bbox_err[3] - bbox_err[1]
            except AttributeError:
                tw_err, th_err = 250, 80
            draw.text((cx - tw_err // 2, cy - th_err // 2), "ERROR", font=font_error, fill="red", stroke_width=4, stroke_fill="black")
            logger.warning(f"[{session_id}] Увага: Не вдалося знайти зображення для моба '{mob.get('name')}'. Намальовано ERROR.")
        else:
            overlay = Image.open(mob_img_path).convert("RGBA")
            overlay = overlay.resize((width, height), Image.Resampling.LANCZOS)
            x = cx - (width // 2)
            y = cy - (height // 2)
            background.paste(overlay, (x, y), overlay)
        
        # ----------------------------------------------------
        # Малюємо ім'я моба
        # ----------------------------------------------------
        name_text = mob.get("name", "Unknown")
        try:
            bbox_name = draw.textbbox((0, 0), name_text, font=font_name)
            tw_name = bbox_name[2] - bbox_name[0]
        except AttributeError:
            tw_name = 150
            
        nx = cx - tw_name // 2
        
        if is_boss:
            ny = cy - (height // 2) - 200 # Піднімаємо ім'я вище ще на 50px
        else:
            ny = cy - (height // 2) - 50
        
        try:
            draw.text((nx, ny), name_text, font=font_name, fill="red", stroke_width=3, stroke_fill="black")
        except TypeError: # Фолбек, якщо шрифт не підтримує обводку
            draw.text((nx, ny), name_text, font=font_name, fill="red")
            
        # ----------------------------------------------------
        # Малюємо смужку здоров'я (HP bar)
        # ----------------------------------------------------
        if is_boss:
            bar_w, bar_h = 300, 40
            bx = cx - bar_w // 2
            by = ny + 94 # Смужку ХП піднято на 16px відносно старої позиції
            frame_by = by + 16 # Зберігаємо стару Y координату, щоб рамка і текст не зсунулися
        else:
            bar_w, bar_h = 160, 24
            bx = cx - bar_w // 2
            by = cy + (height // 2)
            frame_by = by
        
        # Тло і обводка (біла)
        draw.rectangle([bx, by, bx + bar_w, by + bar_h], fill=(40, 40, 40), outline="white", width=3)
        
        # Поточне ХП (червоне)
        hp = mob.get("hp", 0)
        max_hp = mob.get("max_hp", 1)
        ratio = max(0.0, min(1.0, hp / max_hp))
        if ratio > 0:
            draw.rectangle([bx, by, bx + (bar_w * ratio), by + bar_h], fill="red")
            
        # Повторюємо обводку, щоб червона заливка не перекривала її
        draw.rectangle([bx, by, bx + bar_w, by + bar_h], outline="white", width=3)
        
        if is_boss:
            boss_bar_path = os.path.join(script_dir, "Mobs", "bosses", "Boss_bar.png")
            if os.path.exists(boss_bar_path):
                try:
                    boss_bar_img = Image.open(boss_bar_path).convert("RGBA")
                    boss_bar_img = boss_bar_img.resize((372, 267), Image.Resampling.LANCZOS)
                    bb_x = cx - 372 // 2
                    bb_y = frame_by + bar_h // 2 - 267 // 2
                    background.paste(boss_bar_img, (bb_x, bb_y), boss_bar_img)
                except Exception as e:
                    logger.error(f"[{session_id}] Failed to paste Boss_bar: {e}")

        # ----------------------------------------------------
        # Малюємо текст ХП
        # ----------------------------------------------------
        hp_text = f"{hp}/{max_hp}"
        try:
            bbox_hp = draw.textbbox((0, 0), hp_text, font=font_hp)
            tw_hp = bbox_hp[2] - bbox_hp[0]
        except AttributeError:
            tw_hp = 80
            
        hx = cx - tw_hp // 2
        hy = frame_by + bar_h + 8
        
        try:
            draw.text((hx, hy), hp_text, font=font_hp, fill="white", stroke_width=2, stroke_fill="black")
        except TypeError:
            draw.text((hx, hy), hp_text, font=font_hp, fill="white")

    logger.debug(f"[{session_id}] Усіх мобів та елементи інтерфейсу відмальовано. Перетворення кольорів та збереження...")
    # 5. Збереження
    final_result = background.convert("RGB")
    
    # Визначаємо порядковий номер картинки у поточній кімнаті
    next_index = 1
    if os.path.exists(session_dir):
        existing_images = [f for f in os.listdir(session_dir) if f.lower().endswith('.jpg')]
        next_index = len(existing_images) + 1
        
    output_name = f"{session_id}_{room_number}_{next_index}.jpg"
    output_path = os.path.join(session_dir, output_name)
    final_result.save(output_path)
    logger.info(f"[{session_id}] Готово! Картинку сцени бою збережено як {output_path}")
    return output_path

if __name__ == "__main__":
    print("Для запуску необхідно передати session_id, room_number та список enemies_data.")