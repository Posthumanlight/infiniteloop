import os
import random
from PIL import Image

def get_random_png(folder_path):
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Масив можливих шляхів пошуку
    search_paths = [
        os.path.join(script_dir, folder_path),
        os.path.join(script_dir, "Locations", folder_path),
        os.path.join(script_dir, "Mobs", folder_path),
        os.path.join(script_dir, "Mobs", "goblins"),
        os.path.join(script_dir, "Mobs", "wolfs")
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

def generate_battle_scene():
    # 1. Налаштування позицій (центри) для 5 ворогів
    placement_pool = [(330, 960), (885, 1130), (1395, 876), (1820, 1150), (2450, 1080)]
    
    # 2. Логіка формування загону
    # Визначаємо кількість вовків (1 або 2)
    num_wolves = random.randint(1, 2)
    # Решта — гобліни (до 5 ворогів загалом)
    num_goblins = 5 - num_wolves
    
    # Створюємо список типів мобів та їх параметрів (папка, розмір)
    mobs_to_spawn = []
    for _ in range(num_wolves):
        mobs_to_spawn.append({"folder": "wolfs", "size": 710})
    for _ in range(num_goblins):
        mobs_to_spawn.append({"folder": "goblins", "size": 600}) # залишаємо 600 для гоблінів, як було

    # Перемішуємо список, щоб вовки не завжди були на перших позиціях
    random.shuffle(mobs_to_spawn)

    # 3. Відкриваємо фон
    bg_path = get_random_png("cave1")
    background = Image.open(bg_path).convert("RGBA")
    
    print(f"Генерація: {num_wolves} вовків та {num_goblins} гоблінів.")

    # 4. Проходимо по списку мобів та позиціях
    for i, mob in enumerate(mobs_to_spawn):
        cx, cy = placement_pool[i]
        
        # Отримуємо випадкову картинку для конкретного типу моба
        mob_img_path = get_random_png(mob["folder"])
        overlay = Image.open(mob_img_path).convert("RGBA")
        
        # Змінюємо розмір згідно з типом моба
        size = mob["size"]
        overlay = overlay.resize((size, size), Image.Resampling.LANCZOS)
        
        # Рахуємо координати (центрування)
        x = cx - (size // 2)
        y = cy - (size // 2)
        
        # Вклеюємо
        background.paste(overlay, (x, y), overlay)

    # 5. Збереження
    final_result = background.convert("RGB")
    output_name = f"battle_{num_wolves}w_{num_goblins}g_{random.randint(100,999)}.jpg"
    final_result.save(output_name)
    print(f"Готово! Файл збережено як {output_name}")

if __name__ == "__main__":
    generate_battle_scene()