import os
import random
import json
from PIL import Image, ImageDraw, ImageFont

def get_random_png(folder_path):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Масив можливих шляхів пошуку
    search_paths = [
        os.path.join(script_dir, folder_path),
        os.path.join(script_dir, "Locations", folder_path),
        os.path.join(script_dir, "Mobs", folder_path),
        os.path.join(script_dir, "Mobs", "goblins"),
        os.path.join(script_dir, "Mobs", "wolfs"),
        os.path.join(script_dir, "Mobs", "skeletons"),
        os.path.join(script_dir, "Mobs", "fire_imps"),
        os.path.join(script_dir, "Mobs", "bandits")
    ]
    
    actual_path = None
    for p in search_paths:
        if os.path.exists(p):
            actual_path = p
            break
            
    if not actual_path:
        raise FileNotFoundError(f"Папку '{folder_path}' не знайдено!")

    png_files = [f for f in os.listdir(actual_path) if f.lower().endswith('.png')]
    if not png_files:
        raise FileNotFoundError(f"У папці '{actual_path}' немає PNG файлів")
    
    return os.path.join(actual_path, random.choice(png_files))

def get_sekuya_font(size):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_dir = os.path.join(script_dir, "Fonts", "Sekuya")
    if os.path.exists(font_dir):
        for f in os.listdir(font_dir):
            if f.lower().endswith('.ttf') or f.lower().endswith('.otf'):
                return ImageFont.truetype(os.path.join(font_dir, f), size)
    
    try:
        return ImageFont.truetype("arial.ttf", size)
    except IOError:
        return ImageFont.load_default()

def generate_battle_scene(session_id: str = "default_session", room_number: int = 1, enemies_data: list[dict] = None) -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 1. Налаштування позицій (центри) для 5 ворогів
    placement_pool = [(330, 960), (885, 1110), (1395, 876), (1820, 1070), (2450, 1080)]
    
    # 2. Створення папки для поточної сесії та кімнати
    session_dir = os.path.join(script_dir, "sessions scenes", str(session_id), str(room_number))
    os.makedirs(session_dir, exist_ok=True)
    
    # 3. Файл стану кімнати (зберігає фон і прив'язку мобів до їхніх картинок/позицій)
    state_file = os.path.join(session_dir, "room_state.json")
    room_state = {"bg_path": None, "entities": {}, "used_positions": []}
    
    if os.path.exists(state_file):
        with open(state_file, "r", encoding="utf-8") as f:
            room_state = json.load(f)
            
    if not room_state.get("bg_path"):
        room_state["bg_path"] = get_random_png("cave1")
    
    mobs_to_spawn = []
    
    if enemies_data is not None:
        for enemy in enemies_data[:5]: # Обмежуємо до 5 позицій на екрані
            name = enemy.get("name", "")
            entity_id = enemy.get("entity_id", name + str(random.randint(1000, 9999)))
            hp = enemy.get("current_hp", 100)
            max_hp = enemy.get("max_hp", 100)
            name_lower = name.lower()
            
            if "wolf" in name_lower or "вовк" in name_lower:
                mobs_to_spawn.append({"entity_id": entity_id, "name": name, "folder": "wolfs", "size": (710, 532), "hp": hp, "max_hp": max_hp})
            elif "goblin" in name_lower or "гоблін" in name_lower:
                mobs_to_spawn.append({"entity_id": entity_id, "name": name, "folder": "goblins", "size": (600, 600), "hp": hp, "max_hp": max_hp})
            elif "skeleton" in name_lower or "скелет" in name_lower:
                mobs_to_spawn.append({"entity_id": entity_id, "name": name, "folder": "skeletons", "size": (600, 600), "hp": hp, "max_hp": max_hp})
            elif "imp" in name_lower or "імп" in name_lower:
                mobs_to_spawn.append({"entity_id": entity_id, "name": name, "folder": "fire_imps", "size": (500, 500), "hp": hp, "max_hp": max_hp})
            elif "bandit" in name_lower or "бандит" in name_lower:
                mobs_to_spawn.append({"entity_id": entity_id, "name": name, "folder": "bandits", "size": (700, 700), "hp": hp, "max_hp": max_hp})
            else:
                mobs_to_spawn.append({"entity_id": entity_id, "name": name, "folder": "goblins", "size": (600, 600), "hp": hp, "max_hp": max_hp})
    else:
        # Для випадкової генерації обираємо типи мобів зі списку
        enemy_types = [
            {"name": "Wolf", "folder": "wolfs", "size": (710, 532), "max_hp": 30},
            {"name": "Goblin", "folder": "goblins", "size": (600, 600), "max_hp": 40},
            {"name": "Skeleton", "folder": "skeletons", "size": (600, 600), "max_hp": 35},
            {"name": "Fire Imp", "folder": "fire_imps", "size": (500, 500), "max_hp": 25},
            {"name": "Bandit", "folder": "bandits", "size": (700, 700), "max_hp": 45}
        ]
        
        num_enemies = random.randint(1, 5)
        for _ in range(num_enemies):
            chosen = random.choice(enemy_types)
            mobs_to_spawn.append({"entity_id": f"random_mob_{random.randint(100,9999)}", "name": chosen["name"], "folder": chosen["folder"], "size": chosen["size"], "hp": random.randint(1, chosen["max_hp"]), "max_hp": chosen["max_hp"]})
            
    # Оновлюємо та зберігаємо стан кімнати
    for mob in mobs_to_spawn:
        eid = mob["entity_id"]
        if eid not in room_state["entities"]:
            # Шукаємо вільну позицію
            avail_pos = [i for i in range(len(placement_pool)) if i not in room_state["used_positions"]]
            if not avail_pos:
                avail_pos = [0] # Фолбек
            chosen_pos = random.choice(avail_pos)
            room_state["used_positions"].append(chosen_pos)
            
            # Обираємо випадкову картинку для цього моба на весь бій
            img_path = get_random_png(mob["folder"])
            room_state["entities"][eid] = {"pos_idx": chosen_pos, "img_path": img_path}
            
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(room_state, f, ensure_ascii=False, indent=4)

    # 4. Відкриваємо збережений фон
    background = Image.open(room_state["bg_path"]).convert("RGBA")
    
    draw = ImageDraw.Draw(background)
    font_name = get_sekuya_font(40)
    font_hp = get_sekuya_font(30)
    
    print(f"Генерація бою для: {[m['folder'] for m in mobs_to_spawn]}")

    # 5. Проходимо по мобах, беремо їх збережені позиції і картинки
    for mob in mobs_to_spawn:
        eid = mob["entity_id"]
        saved_data = room_state["entities"].get(eid)
        if not saved_data:
            continue
            
        cx, cy = placement_pool[saved_data["pos_idx"]]
        
        # Відкриваємо закріплену за мобом картинку
        mob_img_path = saved_data["img_path"]
        overlay = Image.open(mob_img_path).convert("RGBA")
        
        # Змінюємо розмір згідно з типом моба
        width, height = mob["size"]
        overlay = overlay.resize((width, height), Image.Resampling.LANCZOS)
        
        # Рахуємо координати (центрування)
        x = cx - (width // 2)
        y = cy - (height // 2)
        
        # Вклеюємо
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
        ny = cy - (height // 2) - 50
        
        try:
            draw.text((nx, ny), name_text, font=font_name, fill="red", stroke_width=3, stroke_fill="black")
        except TypeError: # Фолбек, якщо шрифт не підтримує обводку
            draw.text((nx, ny), name_text, font=font_name, fill="red")
            
        # ----------------------------------------------------
        # Малюємо смужку здоров'я (HP bar)
        # ----------------------------------------------------
        bar_w = 160
        bar_h = 24
        bx = cx - bar_w // 2
        by = cy + (height // 2)
        
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
        hy = by + bar_h + 8
        
        try:
            draw.text((hx, hy), hp_text, font=font_hp, fill="white", stroke_width=2, stroke_fill="black")
        except TypeError:
            draw.text((hx, hy), hp_text, font=font_hp, fill="white")

    # 5. Збереження
    final_result = background.convert("RGB")
    output_name = f"battle_turn_{random.randint(1000,9999)}.jpg"
    output_path = os.path.join(session_dir, output_name)
    final_result.save(output_path)
    print(f"Готово! Файл збережено як {output_path}")
    return output_path

if __name__ == "__main__":
    generate_battle_scene()