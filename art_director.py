# -*- coding: utf-8 -*-
import os
import time
import json
import re
from typing import Dict, Any

from PIL import Image, UnidentifiedImageError
import google.generativeai as genai

# ================================
# PATHS
# ================================
WORK_DIR = "C:/CC4_Pipeline/"
REF_IMG = os.path.join(WORK_DIR, "ref.jpg")
CUR_IMG = os.path.join(WORK_DIR, "current.jpg")
TODO_FILE = os.path.join(WORK_DIR, "todo.json")
CONFIG_FILE = os.path.join(WORK_DIR, "config.json")

# ================================
# DEFAULT TUNING
# ================================
DEFAULT_STEP_LIMIT = 30
DEFAULT_MAX_ITERS = 12
DEFAULT_MIN_DELTA = 1.0
DEFAULT_MAX_KEYS_PER_STEP = 3

# ================================
# MORPH DICTIONARIES (BODY vs FACE)
# ================================
BODY_KEYS = {
    "Waist_Width", "Waist_Depth",
    "Hip_Width", "Hip_Scale", "Hip_Length", "Hip_LoveHandles",
    "Chest_Scale", "Chest_Height", "Chest_Width", "Chest_Depth",
    "Breast_Scale", "Breast_Proximity", "Chest_Size",
    "Leg_Length", "Shoulder_Width", "Shoulder_Scale",
}

# Самые влиятельные морфы из дерева CC4 для портретного сходства
FACE_KEYS = {
    "Head_Scale", "Head_Width", "Head_Length",
    "Face_Width", "Face_Length",
    "Jaw_Width", "Jaw_Angle", "Jaw_Height", "Jaw_Depth",
    "Chin_Width", "Chin_Length", "Chin_Depth",
    "Cheek_Bones_Width", "Cheek_Bones_Depth", "Cheek_Width",
    "Eye_Scale", "Eye_Width", "Eye_Height", "Eye_Depth", "Eye_Spacing",
    "Nose_Scale", "Nose_Length", "Nose_Width", "Nose_Depth", "Nose_Bridge_Depth",
    "Mouth_Width", "Mouth_Height", "Mouth_Depth",
    "Lip_Thickness", "Lip_Upper_Thickness", "Lip_Lower_Thickness"
}

# ================================
# CONFIG
# ================================
def load_config() -> Dict[str, Any]:
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"[CONFIG] Нет config.json: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def apply_proxy(cfg: dict) -> None:
    proxy = cfg.get("proxy") or {}
    if not proxy or proxy.get("enabled") is False:
        return
    host, port = proxy.get("host") or proxy.get("ip"), proxy.get("port")
    user, pwd = proxy.get("user"), proxy.get("pass")
    if not host or not port:
        return
    proxy_url = f"http://{user}:{pwd}@{host}:{port}" if user and pwd else f"http://{host}:{port}"
    os.environ["HTTP_PROXY"] = os.environ["HTTPS_PROXY"] = proxy_url
    print(f"[PROXY] включен: {host}:{port}")

# ================================
# HELPERS
# ================================
def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def extract_json(text: str) -> Dict[str, Any]:
    if not text: return {}
    m = re.search(r"\{[\s\S]*\}", text)
    if not m: return {}
    blob = m.group(0).strip()
    try:
        return json.loads(blob)
    except Exception:
        try: return json.loads(blob.replace("'", '"'))
        except Exception: return {}

def sanitize_changes(data: Dict[str, Any], allowed_keys: set, step_limit: float, min_delta: float, max_keys: int) -> Dict[str, float]:
    if not isinstance(data, dict): return {}
    out = {}
    for k, v in data.items():
        if k not in allowed_keys: continue
        try: dv = float(v)
        except Exception: continue
        if abs(dv) < min_delta: continue
        dv = clamp(dv, -step_limit, step_limit)
        dv = float(int(round(dv))) if abs(dv - round(dv)) < 1e-6 else round(dv, 3)
        out[k] = dv
    if len(out) > max_keys:
        out = dict(sorted(out.items(), key=lambda kv: abs(kv[1]), reverse=True)[:max_keys])
    return out

def wait_for_file(path: str, label: str) -> None:
    print(f"[ART] Жду {label}: {path}")
    while not os.path.exists(path): time.sleep(0.5)

def wait_todo_consumed(timeout_sec: float = 120.0) -> bool:
    t0 = time.time()
    while os.path.exists(TODO_FILE):
        if (time.time() - t0) > timeout_sec: return False
        time.sleep(0.2)
    return True

def wait_current_updated(prev_mtime: float, timeout_sec: float = 180.0) -> float:
    t0 = time.time()
    while True:
        if (time.time() - t0) > timeout_sec: return prev_mtime
        try:
            mt = os.path.getmtime(CUR_IMG)
            if mt != prev_mtime: return mt
        except Exception: pass
        time.sleep(0.2)

def wait_image_ready(path: str, timeout_sec: float = 30.0) -> None:
    t0, last_size, stable_hits = time.time(), -1, 0
    while True:
        if (time.time() - t0) > timeout_sec: raise TimeoutError(f"Image not ready: {path}")
        if not os.path.exists(path):
            time.sleep(0.2); continue
        try: size = os.path.getsize(path)
        except Exception:
            time.sleep(0.2); continue
        
        if size > 0 and size == last_size: stable_hits += 1
        else: stable_hits = 0
        last_size = size

        if stable_hits < 2:
            time.sleep(0.2); continue
            
        try:
            with Image.open(path) as im: im.verify()
            return
        except Exception:
            time.sleep(0.25); continue

def open_image_safe(path: str) -> Image.Image:
    wait_image_ready(path, timeout_sec=45.0)
    with Image.open(path) as im:
        im.load()
        return im.copy()

# ================================
# GEMINI
# ================================
def get_instruction(model: genai.GenerativeModel, iteration: int, step_limit: float, cfg: dict, target_mode: str) -> Dict[str, float]:
    
    # Выбираем активный словарь и промпт в зависимости от настроек
    if target_mode == "face":
        active_keys = FACE_KEYS
        sys_prompt = f"""
Ты — Lead 3D Character Facial Modeler. Твоя цель: добиться максимального портретного сходства костной структуры 3D модели с референсом.
Текстура кожи уже готова, работай только с пропорциями: ширина челюсти, посадка глаз, длина носа, объем губ.
ВАЖНО:
- Меняй ТОЛЬКО параметры из списка: {sorted(list(active_keys))}
- Верни ТОЛЬКО JSON, без текста.
- Значения — ДЕЛЬТА ЗА ШАГ. Работай аккуратно, диапазон -{step_limit}..{step_limit}.
- Избегай осцилляции.
Пример: {{"Jaw_Width": -3, "Nose_Length": 2, "Eye_Scale": 1.5}}
Итерация: {iteration}
"""
    else:
        active_keys = BODY_KEYS
        sys_prompt = f"""
Ты — Senior Character Silhouette Designer (реалистичная анатомия). Твоя цель: приблизить силуэт тела current к ref.
Приоритеты: талия/бедра, грудь, длина ног.
ВАЖНО:
- Меняй ТОЛЬКО эти параметры: {sorted(list(active_keys))}
- Верни ТОЛЬКО JSON, без текста.
- Значения — ДЕЛЬТА ЗА ШАГ, диапазон -{step_limit}..{step_limit}.
Пример: {{"Waist_Width": -10, "Hip_Width": 10, "Chest_Size": 5}}
Итерация: {iteration}
"""

    ref = open_image_safe(REF_IMG)
    cur = open_image_safe(CUR_IMG)

    print(f"[GEMINI] -> Режим: {target_mode.upper()}. Отправляю запрос...")
    t0 = time.time()
    response = model.generate_content([sys_prompt.strip(), ref, cur])
    dt = time.time() - t0
    print(f"[GEMINI] <- ответ получен за {dt:.2f}s")

    text = (getattr(response, "text", "") or "").strip()
    data = extract_json(text)

    limits = cfg.get("limits") or {}
    min_delta = float(limits.get("min_delta", DEFAULT_MIN_DELTA))
    max_keys = int(limits.get("max_keys_per_step", DEFAULT_MAX_KEYS_PER_STEP))
    
    return sanitize_changes(data, allowed_keys=active_keys, step_limit=step_limit, min_delta=min_delta, max_keys=max_keys)

# ================================
# MAIN LOOP
# ================================
def main() -> None:
    print(">>> ART DIRECTOR V4 (BODY & FACE) <<<")

    if not os.path.exists(REF_IMG):
        print(f"[ERROR] Нет ref.jpg: {REF_IMG}")
        return

    wait_for_file(CUR_IMG, "current.jpg (стартовый)")

    cfg = load_config()
    apply_proxy(cfg)

    api_key = (cfg.get("gemini_api_key") or "").strip()
    if not api_key:
        print("[ERROR] В config.json пустой gemini_api_key")
        return

    genai.configure(api_key=api_key, transport="rest")
    model_name = (cfg.get("model") or "gemini-3.0-flash").strip()
    target_mode = (cfg.get("target") or "body").strip().lower() # Читаем режим из конфига
    
    print(f"[GEMINI] model = {model_name} | TARGET = {target_mode.upper()}")

    limits = cfg.get("limits") or {}
    step_limit = float(limits.get("step_limit", DEFAULT_STEP_LIMIT))
    max_iters = int(limits.get("max_iters", DEFAULT_MAX_ITERS))

    model = genai.GenerativeModel(model_name)

    try:
        wait_image_ready(CUR_IMG, timeout_sec=60.0)
    except Exception as e:
        print(f"[ERROR] current.jpg не готов/битый на старте: {e}")
        return

    cur_mtime = os.path.getmtime(CUR_IMG)

    for i in range(1, max_iters + 1):
        print(f"\n[ART] Итерация {i}/{max_iters}")

        try:
            changes = get_instruction(model, i, step_limit=step_limit, cfg=cfg, target_mode=target_mode)
        except Exception as e:
            print(f"[ERROR] Gemini запрос упал: {type(e).__name__}: {e}")
            return

        if not changes:
            print("[ART] Нет валидных правок. Сходство достигнуто!")
            break

        with open(TODO_FILE, "w", encoding="utf-8") as f:
            json.dump(changes, f, ensure_ascii=False, indent=2)

        print(f"[ART] Отправил в CC4: {changes}")
        print("[ART] Жду применения + обновления current.jpg...")

        if not wait_todo_consumed(timeout_sec=180.0):
            print("[ERROR] todo.json не был потреблён (таймаут).")
            return

        new_mtime = wait_current_updated(cur_mtime, timeout_sec=240.0)
        if new_mtime == cur_mtime:
            print("[ERROR] current.jpg не обновился (таймаут).")
            return

        try:
            wait_image_ready(CUR_IMG, timeout_sec=60.0)
        except Exception as e:
            print(f"[ERROR] current.jpg обновился, но файл битый: {e}")
            return

        cur_mtime = new_mtime
        print("[ART] current.jpg обновлён.")

    print("\n>>> ГОТОВО <<<")

if __name__ == "__main__":
    main()