# -*- coding: utf-8 -*-
import os
import re
import json
import traceback
import RLPy

WORK_DIR = "C:/CC4_Pipeline/"
TODO_FILE = os.path.join(WORK_DIR, "todo.json")
TREE_FILE = os.path.join(WORK_DIR, "cc4_morph_tree.txt")
LOG_FILE  = os.path.join(WORK_DIR, "cc4_log.txt")

# delta в todo.json трактуем как "шаги": 100 => +1.0
DELTA_TO_WEIGHT = 0.01
CLAMP_MIN = -1.0
CLAMP_MAX =  1.0

# -----------------------------
# KEY -> MORPH_ID (из твоего DIAG)
# -----------------------------
KEY_TO_ID = {
    # Legs
    "Leg_Length": "cc embed morphs/embed_leg1",

    # Shoulder
    "Shoulder_Width": "cc embed morphs/embed_arm102",
    "Shoulder_Scale": "cc embed morphs/embed_arm101",

    # Chest / Breast
    "Chest_Scale": "cc embed morphs/embed_torso104",
    "Chest_Height": "cc embed morphs/embed_torso112",
    "Chest_Width": "cc embed morphs/embed_torso105",
    "Chest_Depth": "cc embed morphs/embed_torso103",
    "Breast_Scale": "cc embed morphs/embed_torso102",       # Breast Scale B
    "Breast_Proximity": "cc embed morphs/embed_torso101",

    # Waist / Abdomen (в DIAG нет 'Waist Width', поэтому используем Abdomen Scale как основной "waist")
    "Waist_Width": "cc embed morphs/embed_torso113",        # Abdomen Scale
    "Waist_Depth": "cc embed morphs/embed_torso111",        # Abdomen Depth

    # Hip
    "Hip_Width": "2018-09-14-22-09-23_pelvis width",        # Hip Width A
    "Hip_Scale": "cc embed morphs/embed_torso2",
    "Hip_Length": "cc embed morphs/embed_torso4",
    "Hip_LoveHandles": "cc embed morphs/embed_torso107",
}

# Алиасы под старые ключи Gemini/ArtDirector
ALIASES = {
    "Chest_Size": "Chest_Scale",
    "Body_Muscle": None,   # пока нет в твоём DIAG; лучше не применять, чем ломать
    "Body_Fat": None,
    "Body_Thin": None,
    "Breast_Shape": None,
}

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(str(msg) + "\n")
            f.flush()
    except Exception:
        pass

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def parse_morph_tree(path):
    morph_to_category = {}
    if not os.path.exists(path):
        return morph_to_category

    cur_cat = None
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip("\n")
            mcat = re.match(r"^\[(.+?)\]\s*$", line.strip())
            if mcat:
                cur_cat = mcat.group(1)
                continue

            mm = re.match(r"^\s*-\s*(.+?)\s*$", line)
            if mm and cur_cat:
                mid = mm.group(1)
                morph_to_category[mid] = cur_cat

    return morph_to_category

def try_call(obj, method_name, arg_variants):
    if not hasattr(obj, method_name):
        return False, f"no method {method_name}"
    fn = getattr(obj, method_name)
    last_err = None
    for args in arg_variants:
        try:
            return True, fn(*args)
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
    return False, last_err or "unknown error"

def get_value(shaping_comp, morph_id, category=None):
    variants = [(morph_id,)]
    if category:
        variants.append((category, morph_id))

    for name in ["GetShapingMorphWeight", "GetShapingMorphValue"]:
        ok, res = try_call(shaping_comp, name, variants)
        if ok:
            try:
                if isinstance(res, (list, tuple)):
                    return float(res[-1])
                return float(res)
            except Exception:
                return None
    return None

def set_value(shaping_comp, morph_id, value, category=None):
    variants = [(morph_id, float(value))]
    if category:
        variants.append((category, morph_id, float(value)))

    for name in ["SetShapingMorphWeight", "SetShapingMorphValue"]:
        ok, _ = try_call(shaping_comp, name, variants)
        if ok:
            return True, f"{name} OK"
    return False, "no compatible setter"

def force_refresh_avatar(avatar):
    try:
        flags = (RLPy.EObjectModifiedType_Attribute | RLPy.EObjectModifiedType_Transform)
        RLPy.RGlobal.ObjectModified(avatar, flags)
        return True, "RGlobal.ObjectModified OK"
    except Exception as e:
        return False, f"ObjectModified failed: {type(e).__name__}: {e}"

def resolve_to_morph_id(key_or_id):
    # если пришёл настоящий morph_id — пропускаем
    if isinstance(key_or_id, str) and (key_or_id.startswith("cc embed morphs/") or re.match(r"^\d{4}-\d{2}-\d{2}-", key_or_id)):
        return key_or_id

    # алиас
    k = key_or_id
    if k in ALIASES:
        k = ALIASES[k]
    if not k:
        return None

    return KEY_TO_ID.get(k)

def main():
    log("=== RUN cc4_apply_once (SHAPING PROD) ===")
    try:
        log("TODO_FILE=" + TODO_FILE)
        log("TREE_FILE=" + TREE_FILE)
        log("exists(todo)=" + str(os.path.exists(TODO_FILE)))
        log("exists(tree)=" + str(os.path.exists(TREE_FILE)))

        if not os.path.exists(TODO_FILE):
            log("[CC4] no todo.json")
            return

        with open(TODO_FILE, "r", encoding="utf-8") as f:
            changes = json.load(f)
        log("changes=" + str(changes))

        avatars = RLPy.RScene.GetAvatars()
        if not avatars:
            log("[FATAL] no avatar in scene")
            return
        avatar = avatars[0]

        if not hasattr(avatar, "GetAvatarShapingComponent"):
            log("[FATAL] no GetAvatarShapingComponent")
            return

        shaping = avatar.GetAvatarShapingComponent()
        if not shaping:
            log("[FATAL] shaping component is None")
            return

        morph_to_cat = parse_morph_tree(TREE_FILE)
        log("tree_morph_count=" + str(len(morph_to_cat)))

        applied = 0

        for key_or_id, delta in (changes or {}).items():
            morph_id = resolve_to_morph_id(key_or_id)
            if not morph_id:
                log(f"[SKIP] key='{key_or_id}' -> no mapping (ignored)")
                continue

            cat = morph_to_cat.get(morph_id)

            cur = get_value(shaping, morph_id, cat)
            if cur is None:
                target = clamp(float(delta) * DELTA_TO_WEIGHT, CLAMP_MIN, CLAMP_MAX)
                ok, info = set_value(shaping, morph_id, target, cat)
                log(f"[SET ABS] key='{key_or_id}' morph='{morph_id}' cat='{cat}' target={target:.4f} -> ok={ok} info={info}")
                if ok:
                    applied += 1
                continue

            dw = float(delta) * DELTA_TO_WEIGHT
            target = clamp(cur + dw, CLAMP_MIN, CLAMP_MAX)
            ok, info = set_value(shaping, morph_id, target, cat)
            log(f"[APPLY] key='{key_or_id}' morph='{morph_id}' cat='{cat}' delta={delta} cur={cur:.4f} target={target:.4f} -> ok={ok} info={info}")
            if ok:
                applied += 1

        okr, infr = force_refresh_avatar(avatar)
        log(f"[REFRESH] ok={okr} info={infr} applied={applied}")

    except Exception as e:
        log("[FATAL] " + repr(e))
        log(traceback.format_exc())

    finally:
        try:
            if os.path.exists(TODO_FILE):
                os.remove(TODO_FILE)
                log("todo.json removed")
        except Exception as e:
            log("remove failed: " + str(e))

        log("=== END ===")

main()
