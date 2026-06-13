"""
MapleStory 自動打怪脚本 v5
-------------------------------
v5 改進：

  效能：
  - 每幀只算一次全幀 Canny，切片查詢取代每候選點各算一次 Canny（速度大幅提升）
  - 縮放尺度從 11 個減到 6 個（matchTemplate 呼叫次數減半）
  - 每尺度候選點上限 MAX_CANDIDATES_PER_SCALE，避免大量矩陣運算

  架構：
  - 偵測獨立 thread（_detection_worker），持續更新共享怪物清單
  - 動作 loop 固定 50ms 頻率讀取最新偵測結果並執行攻擊/巡邏
  - 解決「偵測到怪物卻沒攻擊」：動作頻率不再受偵測速度拖慢

  偵測（v4）：
  - BGR 彩色匹配 + Canny 邊緣輔助驗證
  - IoU-based NMS

  戰鬥（v4）：
  - 跳擊、AoE 優先、單體追擊三分支

  導航（v3）：
  - 智慧巡邏、平台記憶、邊緣偵測撞牆、爬繩脫困

操作：
  F8 / =   開關打怪
  D        存目前偵測結果截圖
  P        列印狀態
  ESC      離開程式

設定：下方 CONFIG 區塊
"""

import os
import sys
import time
import threading
import keyboard
import numpy as np
import cv2
import mss

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from maplestory_define import find_maplestory_window

# ============================================================
# CONFIG
# ============================================================

# 移動 / 跳躍鍵
MOVE_LEFT  = "left"
MOVE_RIGHT = "right"
JUMP_KEY   = "alt"
UP_KEY     = "up"       # 爬繩 / 爬梯用

# 揈寶鍵（None = 不揈）
LOOT_KEY      = None
LOOT_INTERVAL = 1.5

# 技能輪轉：[(key, cooldown_sec), ...]
# cooldown > 0 才會在移動中發動；0.0 只在站定後才打（避免動作打斷）
# 若你的技能可以邊走邊打，把 cooldown 改為小正值（如 0.15）
SKILLS = [
    ("ctrl", 0.45),   # 主攻擊冷卻（配合動畫約 0.4-0.5s）
    # ("z",   3.0),
    # ("x",   6.0),
    # ("a",   12.0),
]

# 模板設定
TEMPLATE_DIR    = "monster_templates"
MATCH_THRESHOLD       = 0.48   # 初步顏色匹配門檻
MATCH_THRESHOLD_EDGE  = 0.45   # 邊緣加權後的最終門檻（需 > MATCH_THRESHOLD * 0.82 才有效過濾）
NMS_IOU_THRESH        = 0.45   # IoU NMS 重疊門檻

MAX_MONSTERS = 20         # 同幀偵測超過此數視為全誤判，強制進巡邏

# 子資料夾模式：每種怪只載入這幾幀，平衡覆蓋率與速度
# stand = 靜止幀，move = 行走幀；幀號均勻取樣避免重複
TEMPLATE_FRAMES = [
    "stand_0.png", "stand_10.png", "stand_20.png",  # 靜止三幀（均勻分布，涵蓋 35 幀動畫）
    "move_0.png",  "move_4.png",                    # 行走兩幀
]

USE_MULTISCALE = True
SCALES         = [0.90, 1.0, 1.10]   # 3 尺度（模板數已減半，無需多尺度補償）
MAX_CANDIDATES_PER_SCALE = 20   # 每縮放尺度最多候選數（原30→20，搭配 floor-strip 仍足夠）

ROI_X_START = 0.0
ROI_X_END   = 1.0
ROI_Y_START = 0.15   # 0.08→0.15：排除左上角小地圖，避免小地圖怪物 icon 誤判
ROI_Y_END   = 0.85

CHAR_X_RATIO = 0.50
CHAR_Y_RATIO = 0.65

ATTACK_RANGE_H = 20
ATTACK_RANGE_V = 30
JUMP_COOLDOWN  = 0.9

FACE_SETTLE_SEC     = 0.06
AOE_MIN_TARGETS     = 2
BURST_MODE          = False
JUMP_ATTACK_RANGE_H = 30

LOCK_SEARCH_RADIUS = 150   # px — 鎖定後局部搜尋的半徑（比全幀快 ~15x）
SMOOTH_ALPHA       = 0.35  # EMA 權重：越小越穩定但反應越慢

# 巡邏
PATROL_STEP               = 2.5
PATROL_JUMP_SEC           = 4.5
PATROL_CYCLES_BEFORE_JUMP = 3  # 幾輪無怪後自動展巡跳換層

# 卡牆偵測
STUCK_DIFF_THRESH   = 1.8
STUCK_TIMEOUT       = 2.2
PATROL_EDGE_WINDOW  = 0.8   # 剛換方向後小於此秒內卡住 = 撞牆（秒）
STUCK_RECOVERY_WAIT = 0.35  # 脫困後等落地時間（秒）

ROPE_CLIMB_ENABLED = True   # 卡住時加入上+跳嘗試爬繩
ROPE_CLIMB_SEC     = 1.8    # 按住上鍵爬梯的秒數（依地圖梯子高度調整）

SCAN_INTERVAL = 0.05   # 動作 loop 50ms（偵測 thread 不受此限制）
DEBUG_DIR     = "debug"


# ============================================================
# 模板載入
# ============================================================

def _load_one(path, label):
    """載入單張 RGBA/RGB 圖，回傳 template dict 或 None。"""
    raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        print(f"  ⚠  無法讀取：{path}")
        return None
    if raw.ndim == 3 and raw.shape[2] == 4:
        bgr   = raw[:, :, :3]
        a     = raw[:, :, 3]
        alpha = a if np.any(a < 255) else None
    else:
        bgr   = raw if raw.ndim == 3 else cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
        alpha = None

    gray  = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 100)
    edge_pct = float(np.count_nonzero(edges)) / max(1, bgr.shape[0] * bgr.shape[1])
    edge_tmpl = edges.astype(np.float32) if edge_pct >= 0.08 else None

    flag = "alpha" if alpha is not None else "no-alpha"
    print(f"  ✅ {label}  {bgr.shape[1]}x{bgr.shape[0]}  [{flag}]  edge={edge_pct*100:.0f}%")
    return {
        "name":  label,
        "bgr":   bgr,
        "alpha": alpha,
        "gray":  gray,
        "edges": edge_tmpl,
        "w":     bgr.shape[1],
        "h":     bgr.shape[0],
    }


def load_templates():
    """
    支援兩種目錄結構：
      A) 子資料夾模式：monster_templates/<怪物名>/<幀名>.png
         → 依 TEMPLATE_FRAMES 篩選幀
      B) 舊版扁平模式：monster_templates/*.png
    """
    templates = []
    if not os.path.isdir(TEMPLATE_DIR):
        print(f"  ⚠  找不到資料夾 {TEMPLATE_DIR}/，進入純巡邏模式")
        return templates

    entries = sorted(os.listdir(TEMPLATE_DIR))
    subdirs = [e for e in entries if os.path.isdir(os.path.join(TEMPLATE_DIR, e))]
    files   = [e for e in entries if e.lower().endswith((".png", ".jpg", ".bmp"))]

    if subdirs:
        # ── 子資料夾模式 ─────────────────────────────────────
        for monster in subdirs:
            monster_dir = os.path.join(TEMPLATE_DIR, monster)
            loaded = 0
            for fname in TEMPLATE_FRAMES:
                path = os.path.join(monster_dir, fname)
                if not os.path.isfile(path):
                    continue
                label = f"{monster}/{fname}"
                t = _load_one(path, label)
                if t:
                    templates.append(t)
                    loaded += 1
            if loaded == 0:
                print(f"  ⚠  {monster}/ 內找不到指定幀（TEMPLATE_FRAMES）")
    else:
        # ── 舊版扁平模式（向下相容）──────────────────────────
        for fname in files:
            path = os.path.join(TEMPLATE_DIR, fname)
            t = _load_one(path, fname)
            if t:
                templates.append(t)

    if not templates:
        print(f"  ⚠  {TEMPLATE_DIR}/ 沒有可用模板，進入純巡邏模式")
        return templates

    # 預先計算各尺度縮放版本，避免每幀重複 resize
    scales_to_pre = SCALES if USE_MULTISCALE else [1.0]
    for t in templates:
        t["scaled"] = {}
        for s in scales_to_pre:
            if s == 1.0:
                t["scaled"][s] = {"bgr": t["bgr"], "alpha": t["alpha"], "edges": t["edges"]}
            else:
                oh, ow = t["bgr"].shape[:2]
                nh, nw = max(1, int(oh * s)), max(1, int(ow * s))
                t["scaled"][s] = {
                    "bgr":   cv2.resize(t["bgr"],   (nw, nh), interpolation=cv2.INTER_LINEAR),
                    "alpha": (cv2.resize(t["alpha"], (nw, nh), interpolation=cv2.INTER_NEAREST)
                              if t["alpha"]  is not None else None),
                    "edges": (cv2.resize(t["edges"], (nw, nh), interpolation=cv2.INTER_LINEAR)
                              if t["edges"]  is not None else None),
                }
    print(f"  共載入 {len(templates)} 個模板幀（各預計算 {len(scales_to_pre)} 尺度）")
    return templates


# ============================================================
# 截圖
# ============================================================

def capture_roi(region):
    x, y, w, h = region
    rx = x + int(ROI_X_START * w)
    ry = y + int(ROI_Y_START * h)
    rw = int((ROI_X_END - ROI_X_START) * w)
    rh = int((ROI_Y_END - ROI_Y_START) * h)
    with mss.mss() as sct:
        shot = sct.grab({"left": rx, "top": ry, "width": rw, "height": rh})
    bgr = np.array(shot)[:, :, :3]
    return bgr, (rx, ry, rw, rh)


# ============================================================
# 怪物偵測（BGR彩色 + 邊緣驗證 + IoU NMS）
# ============================================================

def _match_one_scale(frame_bgr, frame_edges, tmpl, scale):
    """
    BGR 彩色模板匹配 + Canny 邊緣輔助驗證。
    frame_edges：由 find_monsters 預先計算的全幀 Canny，避免每候選點各算一次。
    回傳 [(cx, cy, conf, tw, th), ...]，含縮放後模板尺寸供 IoU NMS 使用。
    """
    # 優先使用預計算縮放版本（load_templates 已備好），避免每幀 resize
    if "scaled" in tmpl and scale in tmpl["scaled"]:
        st      = tmpl["scaled"][scale]
        t_bgr   = st["bgr"]
        alpha   = st["alpha"]
        t_edges = st["edges"]
    else:
        t_bgr   = tmpl["bgr"]
        t_edges = tmpl["edges"]
        alpha   = tmpl["alpha"]
        if scale != 1.0:
            oh, ow = t_bgr.shape[:2]
            nh, nw = max(1, int(oh * scale)), max(1, int(ow * scale))
            t_bgr = cv2.resize(t_bgr, (nw, nh), interpolation=cv2.INTER_LINEAR)
            if alpha   is not None: alpha   = cv2.resize(alpha,   (nw, nh), interpolation=cv2.INTER_NEAREST)
            if t_edges is not None: t_edges = cv2.resize(t_edges, (nw, nh), interpolation=cv2.INTER_LINEAR)

    th, tw = t_bgr.shape[:2]
    if frame_bgr.shape[0] < th or frame_bgr.shape[1] < tw:
        return []

    # BGR 彩色匹配：TM_CCOEFF_NORMED 在多通道下自動加總 B/G/R 的歸一化協方差
    if alpha is not None:
        res = cv2.matchTemplate(frame_bgr, t_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha)
    else:
        res = cv2.matchTemplate(frame_bgr, t_bgr, cv2.TM_CCOEFF_NORMED)

    global _diag_best_raw_conf
    _diag_best_raw_conf = max(_diag_best_raw_conf, float(res.max()))

    ys, xs = np.where(res >= MATCH_THRESHOLD)
    if len(xs) == 0:
        return []

    # 限制候選數：取信心值最高的前 N 個，避免大量切片計算
    if len(xs) > MAX_CANDIDATES_PER_SCALE:
        top_idx = np.argpartition(res[ys, xs], -MAX_CANDIDATES_PER_SCALE)[-MAX_CANDIDATES_PER_SCALE:]
        xs, ys = xs[top_idx], ys[top_idx]

    hits = []
    for px, py in zip(xs, ys):
        conf = float(res[py, px])
        # 邊緣輔助驗證：使用預計算的全幀 Canny 切片，取代每點重算 Canny
        if t_edges is not None and frame_edges is not None:
            ey2, ex2 = min(py + th, frame_edges.shape[0]), min(px + tw, frame_edges.shape[1])
            roi_edges = frame_edges[py:ey2, px:ex2]
            if roi_edges.shape[0] != th or roi_edges.shape[1] != tw:
                continue  # 跳過邊界不完整的候選
            t_n = t_edges / (np.linalg.norm(t_edges) + 1e-6)
            r_n = roi_edges / (np.linalg.norm(roi_edges) + 1e-6)
            edge_score = float(np.sum(t_n * r_n))
            conf = conf * 0.82 + max(edge_score, 0.0) * 0.18
            if conf < MATCH_THRESHOLD_EDGE:
                continue
        hits.append((px + tw // 2, py + th // 2, conf, tw, th))
    return hits


def _iou(ax, ay, aw, ah, bx, by, bw, bh):
    ix1, ix2 = max(ax, bx), min(ax + aw, bx + bw)
    iy1, iy2 = max(ay, by), min(ay + ah, by + bh)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def nms(detections):
    """IoU-based NMS，輸入含 (cx,cy,conf,name,tw,th)，回傳 (cx,cy,conf,name,tw,th)"""
    kept = []
    for cx, cy, conf, name, tw, th in sorted(detections, key=lambda d: -d[2]):
        ax, ay = cx - tw // 2, cy - th // 2
        if not any(
            _iou(ax, ay, tw, th, kx - ktw // 2, ky - kth // 2, ktw, kth) > NMS_IOU_THRESH
            for kx, ky, _, _, ktw, kth in kept
        ):
            kept.append((cx, cy, conf, name, tw, th))
    return kept


def find_monsters(frame, templates):
    """回傳 [(cx, cy, conf, name, tw, th), ...]，座標為 frame 像素"""
    if not templates:
        return []
    fh, fw = frame.shape[:2]
    char_cy = int(fh * CHAR_Y_RATIO)
    # 只搜角色所在樓層水平帶，大幅縮小 matchTemplate 面積（↑ 速度 ~3x）
    max_tmpl_h = max(t["h"] for t in templates)
    y0 = max(0, char_cy - ATTACK_RANGE_V - max_tmpl_h)
    y1 = min(fh, char_cy + ATTACK_RANGE_V + max_tmpl_h)
    strip = frame[y0:y1, :]

    strip_gray  = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY)
    frame_edges = cv2.Canny(strip_gray, 30, 100).astype(np.float32)
    all_hits = []
    scales = SCALES if USE_MULTISCALE else [1.0]
    for t in templates:
        for s in scales:
            for cx, cy, conf, tw, th in _match_one_scale(strip, frame_edges, t, s):
                all_hits.append((cx, cy + y0, conf, t["name"], tw, th))
    return nms(all_hits)


def find_monsters_local(frame, templates, center_x, center_y):
    """鎖定後快速局部搜尋：只在 center 周圍 LOCK_SEARCH_RADIUS px 內、scale=1.0 匹配。
    面積約全幀的 1/15，速度快 ~15x。"""
    fh, fw = frame.shape[:2]
    x0 = max(0, center_x - LOCK_SEARCH_RADIUS)
    x1 = min(fw, center_x + LOCK_SEARCH_RADIUS)
    y0 = max(0, center_y - LOCK_SEARCH_RADIUS)
    y1 = min(fh, center_y + LOCK_SEARCH_RADIUS)
    if x1 - x0 < 30 or y1 - y0 < 30:
        return []
    patch      = frame[y0:y1, x0:x1]
    gray       = cv2.cvtColor(patch, cv2.COLOR_BGR2GRAY)
    edges      = cv2.Canny(gray, 30, 100).astype(np.float32)
    hits = []
    for t in templates:
        for cx, cy, conf, tw, th in _match_one_scale(patch, edges, t, 1.0):
            hits.append((cx + x0, cy + y0, conf, t["name"], tw, th))
    return nms(hits)


# ============================================================
# 輸入控制
# ============================================================

_skill_last:  dict[str, float] = {}
_skill_count: dict[str, int]   = {}   # 診斷：各技能按下次數


def press_skills(is_moving: bool = False, burst: bool = False):
    """
    依冷卻時間輪轉觸發各技能。
    is_moving=True 時跳過冷卻為 0 的主攻擊，避免同時持按方向鍵。
    burst=True 則強制發動所有技能（無視冷卻）。
    """
    now = time.time()
    for key, cooldown in SKILLS:
        if is_moving and cooldown == 0.0:
            continue
        last = _skill_last.get(key, 0.0)
        if burst or (now - last >= cooldown):
            keyboard.press(key)
            time.sleep(0.05)
            keyboard.release(key)
            _skill_last[key] = time.time()
            n = _skill_count.get(key, 0) + 1
            _skill_count[key] = n
            print(f"  ⚔️  [{key}] ×{n}  {'移動中' if is_moving else '停止'}")


def start_move(direction):
    if direction == "left":
        keyboard.press(MOVE_LEFT)
        keyboard.release(MOVE_RIGHT)
    elif direction == "right":
        keyboard.press(MOVE_RIGHT)
        keyboard.release(MOVE_LEFT)
    else:
        keyboard.release(MOVE_LEFT)
        keyboard.release(MOVE_RIGHT)


def stop_movement():
    keyboard.release(MOVE_LEFT)
    keyboard.release(MOVE_RIGHT)


def do_jump():
    stop_movement()
    keyboard.press_and_release(JUMP_KEY)
    time.sleep(0.12)


def do_rope_climb():
    """抓繩並持續爬升：按上鍵觸發抓繩，再持續按住 UP 爬完整段梯子"""
    stop_movement()
    keyboard.press(UP_KEY)          # 先按上觸發抓繩/梯
    time.sleep(0.1)
    keyboard.press_and_release(JUMP_KEY)   # 跳躍確保觸發（部分繩索需要）
    time.sleep(ROPE_CLIMB_SEC)      # 持續按住上鍵爬升
    keyboard.release(UP_KEY)


def do_jump_attack():
    """跳躍頂點攻擊：跳躍鍵按下後立刻觸發主攻擊，打上方平台的怪"""
    stop_movement()
    keyboard.press(JUMP_KEY)
    time.sleep(0.03)
    if SKILLS:
        key = SKILLS[0][0]
        keyboard.press_and_release(key)
        _skill_last[key] = time.time()
    keyboard.release(JUMP_KEY)
    time.sleep(0.12)


# ============================================================
# Debug 截圖
# ============================================================

def save_debug_frame(frame, monsters, char_cx, char_cy):
    os.makedirs(DEBUG_DIR, exist_ok=True)
    vis = frame.copy()
    cv2.line(vis, (char_cx, 0), (char_cx, vis.shape[0]), (0, 255, 0), 1)
    cv2.circle(vis, (char_cx, char_cy), 8, (0, 255, 0), -1)
    for cx, cy, conf, name, tw, th in monsters:
        hw, hh = tw // 2, th // 2
        cv2.rectangle(vis, (cx - hw, cy - hh), (cx + hw, cy + hh), (0, 0, 255), 2)
        cv2.putText(vis, f"{name[:12]} {conf:.2f}",
                    (cx - hw, max(12, cy - hh - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)
    path = os.path.join(DEBUG_DIR, f"hunt_debug_{time.strftime('%H%M%S')}.png")
    cv2.imwrite(path, vis)
    print(f"  [D] 已儲存 {path}")


# ============================================================
# 主循環 — 狀態變數
# ============================================================

_diag_best_raw_conf  = 0.0    # best BGR match score seen this window (for diagnostics)
_hunt_region         = None   # current game window region, set when hunt starts
_detection_timestamp = 0.0    # time of last successful detection update

# 目標鎖定
_locked_pos          = None   # (x, y) 鎖定目標的 EMA 平滑後座標
_locked_pos_smooth   = None   # [x, y] 浮點平滑累積值
_locked_miss         = 0      # 連續未見目標的幀數
LOCK_RADIUS          = 220    # px — 在此範圍內視為同一目標（需覆蓋鏡頭捲動量）
LOCK_RELEASE_FRAMES  = 15     # 連續遺失幾幀後解除鎖定（需容忍動畫切換空幀）

_state_lock      = threading.Lock()
running          = False
stop_event       = threading.Event()
_patrol_dir      = "right"
_patrol_timer    = 0.0
_patrol_jump_t   = 0.0
_jump_last_t     = 0.0
_loot_last_t     = 0.0
_prev_frame_gray = None
_no_move_since   = None
_is_moving       = False
_save_debug_req  = False
_last_frame      = None
_last_monsters   = []

# 巡邏智慧狀態
_patrol_no_monster_counts: dict[str, int] = {"left": 0, "right": 0}
_patrol_dir_switch_time: float = 0.0
_patrol_cycle: int = 0

# 偵測執行緒共享狀態
_detect_result_lock  = threading.Lock()
_detected_monsters: list = []
_detected_frame      = None
_detection_frame_id: int = 0

# 即時偵測預覽
_overlay_stop_ev = None
_overlay_thread  = None


def _detection_worker(region, templates, stop_ev):
    """背景偵測執行緒：持續截圖 + find_monsters，更新共享怪物清單。"""
    global _detected_monsters, _detected_frame, _detection_frame_id
    global _last_frame, _last_monsters, _detection_timestamp

    while not stop_ev.is_set():
        t0 = time.time()
        try:
            frame, _ = capture_roi(region)
        except Exception as e:
            print(f"  ⚠  截圖失敗：{e}")
            time.sleep(0.1)
            continue

        # 有鎖定 → 先做局部快速搜尋（~5ms）；沒找到再全面掃（~60ms）
        lp = _locked_pos
        if lp is not None:
            monsters = find_monsters_local(frame, templates, lp[0], lp[1])
            if not monsters:
                monsters = find_monsters(frame, templates)
        else:
            monsters = find_monsters(frame, templates)

        if len(monsters) > MAX_MONSTERS:
            print(f"  ⚠  誤判保護：偵測到 {len(monsters)} 個目標，視為雜訊跳過")
            monsters = []

        with _detect_result_lock:
            _detected_monsters   = monsters
            _detected_frame      = frame
            _detection_frame_id += 1
            _detection_timestamp = time.time()
            _last_frame          = frame
            _last_monsters       = monsters

        if _detection_frame_id % 60 == 0:
            global _diag_best_raw_conf
            print(f"  [偵測] 最近60幀 最佳BGR={_diag_best_raw_conf:.3f} "
                  f"門檻={MATCH_THRESHOLD}  當前怪物={len(monsters)}")
            _diag_best_raw_conf = 0.0

        time.sleep(0.02)   # 限制偵測速率 ~50fps，讓主執行緒獲得 CPU 時間


# ============================================================
# 卡住偵測與脫困
# ============================================================

def _stuck_check(frame_gray):
    """
    偵測角色是否卡住。

    Returns
    -------
    str | False
        False    -> 未卡住
        "edge"   -> 剛換方向後立刻卡住，判定為撞邊牆
        "stuck"  -> 一般卡住（原地卡住超過 STUCK_TIMEOUT 秒）
    """
    global _prev_frame_gray, _no_move_since, _is_moving

    if not _is_moving:
        _no_move_since = None
        _prev_frame_gray = frame_gray
        return False

    if _prev_frame_gray is not None and _prev_frame_gray.shape == frame_gray.shape:
        diff = float(np.mean(
            np.abs(frame_gray.astype(np.int16) - _prev_frame_gray.astype(np.int16))
        ))
        _prev_frame_gray = frame_gray
        if diff < STUCK_DIFF_THRESH:
            if _no_move_since is None:
                _no_move_since = time.time()
            elif time.time() - _no_move_since >= STUCK_TIMEOUT:
                _no_move_since = None
                # 判斷是否在剛換方向後的邊緣視窗內
                since_switch = time.time() - _patrol_dir_switch_time
                if since_switch <= PATROL_EDGE_WINDOW + STUCK_TIMEOUT:
                    return "edge"
                return "stuck"
        else:
            _no_move_since = None
    else:
        _prev_frame_gray = frame_gray

    return False


def _do_stuck_recovery(stuck_type: str):
    """
    精緣脫困序列：
      1. 立即停止移動，清除鍵盤狀態
      2. 跳躍（edge 型 = 跳兩下，力道更大）
      3. 若 ROPE_CLIMB_ENABLED，加一次上鍵+跳躍嘗試抓繩
      4. 等待 STUCK_RECOVERY_WAIT 秒讓角色落地穩定
      5. 反向移動，重置巡邏計時器
    """
    global _patrol_dir, _patrol_timer, _jump_last_t, _patrol_dir_switch_time

    stop_movement()

    jump_count = 2 if stuck_type == "edge" else 1
    now = time.time()
    for _ in range(jump_count):
        if now - _jump_last_t >= JUMP_COOLDOWN:
            do_jump()
            _jump_last_t = time.time()
            now = _jump_last_t
        time.sleep(0.15)

    if ROPE_CLIMB_ENABLED:
        do_rope_climb()
        _jump_last_t = time.time()

    time.sleep(STUCK_RECOVERY_WAIT)

    _patrol_dir = "left" if _patrol_dir == "right" else "right"
    _patrol_timer = time.time()
    _patrol_dir_switch_time = time.time()

    label    = "邊牆" if stuck_type == "edge" else "卡住"
    rope_tag = "+ 爬繩" if ROPE_CLIMB_ENABLED else ""
    print(f"  ⚠  {label}脫困：跳x{jump_count}{rope_tag}  → 改往 {_patrol_dir}")


# ============================================================
# 目標鎖定
# ============================================================

def select_target(same_floor, char_cx):
    """
    從同層怪物選定並持續鎖定一個目標。
    - 已有鎖定 → 在 LOCK_RADIUS 內重新抓取，並用 EMA 平滑座標（減少抖動）
    - 鎖定遺失 → 選最靠近角色的怪，建立新鎖定
    返回帶平滑座標的 monster tuple，或 None。
    """
    global _locked_pos, _locked_pos_smooth, _locked_miss

    if not same_floor:
        _locked_miss += 1
        if _locked_miss >= LOCK_RELEASE_FRAMES:
            _locked_pos        = None
            _locked_pos_smooth = None
            _locked_miss       = 0
        return None

    _locked_miss = 0

    if _locked_pos is not None:
        lx, ly = _locked_pos
        close = [m for m in same_floor
                 if (m[0] - lx) ** 2 + (m[1] - ly) ** 2 <= LOCK_RADIUS ** 2]
        if close:
            raw = min(close, key=lambda m: (m[0] - lx) ** 2 + (m[1] - ly) ** 2)
            # EMA 平滑：減少座標抖動
            if _locked_pos_smooth is None:
                _locked_pos_smooth = [float(raw[0]), float(raw[1])]
            else:
                _locked_pos_smooth[0] += SMOOTH_ALPHA * (raw[0] - _locked_pos_smooth[0])
                _locked_pos_smooth[1] += SMOOTH_ALPHA * (raw[1] - _locked_pos_smooth[1])
            _locked_pos = (int(_locked_pos_smooth[0]), int(_locked_pos_smooth[1]))
            # 回傳帶平滑座標的 tuple（conf/name/tw/th 不變）
            return (_locked_pos[0], _locked_pos[1]) + raw[2:]
        # 鎖定目標消失 → 解除
        _locked_pos        = None
        _locked_pos_smooth = None

    # 新鎖定：選最靠近角色的同層怪
    target = min(same_floor, key=lambda m: abs(m[0] - char_cx))
    _locked_pos        = (target[0], target[1])
    _locked_pos_smooth = [float(target[0]), float(target[1])]
    print(f"  🎯 新鎖定：{target[3].split('/')[-1]}  pos=({target[0]},{target[1]})")
    return target


# ============================================================
# 主循環
# ============================================================

def hunt_loop(region, templates):
    global _patrol_dir, _patrol_timer, _patrol_jump_t
    global _jump_last_t, _loot_last_t, _is_moving
    global _save_debug_req, _last_frame, _last_monsters
    global _patrol_no_monster_counts, _patrol_dir_switch_time, _patrol_cycle
    global _detected_monsters, _detected_frame, _detection_frame_id
    global _hunt_region
    _hunt_region = region

    _patrol_dir    = "right"
    _patrol_timer  = time.time()
    _patrol_jump_t = time.time()
    _jump_last_t   = time.time()
    _loot_last_t   = time.time()
    _patrol_dir_switch_time = time.time()
    _patrol_cycle  = 0
    _patrol_no_monster_counts = {"left": 0, "right": 0}
    _detected_monsters = []
    _detected_frame    = None

    # 從 region 預先計算角色座標（固定值，不依賴截圖）
    _, _, win_w, win_h = region
    roi_w   = int((ROI_X_END - ROI_X_START) * win_w)
    roi_h   = int((ROI_Y_END - ROI_Y_START) * win_h)
    char_cx = int(roi_w * CHAR_X_RATIO)
    char_cy = int(roi_h * CHAR_Y_RATIO)

    # 啟動背景偵測執行緒
    det_stop   = threading.Event()
    det_thread = threading.Thread(
        target=_detection_worker, args=(region, templates, det_stop), daemon=True
    )
    det_thread.start()
    print("🎮 打怪循環啟動（偵測分離執行緒）")

    _last_stuck_fid = -1   # 上次做卡牆偵測的 frame id

    while not stop_event.is_set():
        t0  = time.time()
        now = t0

        # ── 讀取最新偵測結果（非阻塞）─────────────────────────────
        with _detect_result_lock:
            monsters   = list(_detected_monsters)
            cur_frame  = _detected_frame
            cur_fid    = _detection_frame_id
            det_age    = now - _detection_timestamp

        # 偵測結果過舊（角色已移動）→ 捨棄，等新幀
        if det_age > 0.35:
            monsters = []

        # ── Debug 截圖需求 ─────────────────────────────────────────
        if _save_debug_req and cur_frame is not None:
            _save_debug_req = False
            save_debug_frame(cur_frame, monsters, char_cx, char_cy)

        # ── 揈寶 ───────────────────────────────────────────────────
        if LOOT_KEY and now - _loot_last_t >= LOOT_INTERVAL:
            keyboard.press_and_release(LOOT_KEY)
            _loot_last_t = now

        # ── 有怪：攻擊模式（三分支）────────────────────────────────
        same_floor = [m for m in monsters if abs(m[1] - char_cy) <= ATTACK_RANGE_V]
        _jump_viable = any(
            m[1] - char_cy < -ATTACK_RANGE_V and abs(m[0] - char_cx) < JUMP_ATTACK_RANGE_H
            for m in monsters
        )
        # 目標鎖定：從同層怪中選定並持續追蹤同一目標
        target = select_target(same_floor, char_cx)
        # 若無同層目標但有跳擊機會，直接抓最近的跨層怪做跳擊判斷
        jump_target = None
        if target is None and _jump_viable:
            jump_target = min(
                (m for m in monsters
                 if m[1] - char_cy < -ATTACK_RANGE_V and abs(m[0] - char_cx) < JUMP_ATTACK_RANGE_H),
                key=lambda m: abs(m[0] - char_cx), default=None)

        if target is not None or jump_target is not None:
            _patrol_no_monster_counts = {"left": 0, "right": 0}
            _patrol_cycle = 0

            target = target or jump_target
            tx, ty, conf, tname, *_ = target
            dx = tx - char_cx
            dy = ty - char_cy   # 負 = 怪在上方

            # ─ Branch 1: 跳擊 — 怪在正上方且水平接近 ─
            if dy < -ATTACK_RANGE_V and abs(dx) < JUMP_ATTACK_RANGE_H:
                face_dir = "left" if dx < 0 else "right"
                start_move(face_dir)
                time.sleep(FACE_SETTLE_SEC)
                stop_movement()
                _is_moving = False
                if now - _jump_last_t >= JUMP_COOLDOWN:
                    do_jump_attack()
                    _jump_last_t = time.time()
                press_skills(is_moving=False, burst=BURST_MODE)

            # ─ Branch 2: AoE — 同層多隻在攻擊範圍內 ─
            elif len([m for m in same_floor
                      if abs(m[0] - char_cx) <= ATTACK_RANGE_H]) >= AOE_MIN_TARGETS:
                face_dir = "left" if dx < 0 else "right"
                start_move(face_dir)
                time.sleep(FACE_SETTLE_SEC)
                stop_movement()
                _is_moving = False
                press_skills(is_moving=False, burst=BURST_MODE)

            # ─ Branch 3: 單體追擊 ─
            else:
                was_moving = _is_moving
                if abs(dx) > ATTACK_RANGE_H:
                    start_move("left" if dx < 0 else "right")
                    _is_moving = True
                    press_skills(is_moving=True, burst=BURST_MODE)
                else:
                    stop_movement()
                    _is_moving = False
                    # 確保面向怪物方向再攻擊（防止鎖定切換後方向錯誤打空）
                    face_dir = "left" if dx < 0 else "right"
                    start_move(face_dir)
                    time.sleep(FACE_SETTLE_SEC)
                    stop_movement()
                    # 怪在側上方（不同層）→ 普通跳靠近
                    if dy < -ATTACK_RANGE_V and now - _jump_last_t >= JUMP_COOLDOWN:
                        do_jump()
                        _jump_last_t = now
                    press_skills(is_moving=False, burst=BURST_MODE)

            print(f"  🗡  {tname}  conf={conf:.2f}  "
                  f"dx={dx:+d} dy={dy:+d}  "
                  f"同層={len(same_floor)} 全={len(monsters)}")

        # ── 鎖定存活但偵測空幀：只追位不攻擊（避免打死怪的空位）────
        elif _locked_pos is not None:
            lx, ly = _locked_pos
            if abs(ly - char_cy) <= ATTACK_RANGE_V:
                fake_dx = lx - char_cx
                if abs(fake_dx) > ATTACK_RANGE_H:
                    start_move("left" if fake_dx < 0 else "right")
                    _is_moving = True
                else:
                    stop_movement()
                    _is_moving = False
            # 不按技能 — 等下一幀偵測確認怪物是否還在

        # ── 無怪、無鎖定：巡邏模式 ────────────────────────────────
        else:
            if now - _patrol_timer >= PATROL_STEP:
                _patrol_no_monster_counts[_patrol_dir] = (
                    _patrol_no_monster_counts.get(_patrol_dir, 0) + 1
                )
                _patrol_cycle += 1

                left_cnt  = _patrol_no_monster_counts["left"]
                right_cnt = _patrol_no_monster_counts["right"]
                if left_cnt < right_cnt:
                    next_dir = "left"
                elif right_cnt < left_cnt:
                    next_dir = "right"
                else:
                    next_dir = "left" if _patrol_dir == "right" else "right"

                _patrol_dir = next_dir
                _patrol_timer = now
                _patrol_dir_switch_time = now
                print(f"  🔍 巡邏 → {_patrol_dir}  "
                      f"(L:{left_cnt} R:{right_cnt} cycle:{_patrol_cycle})")

                if _patrol_cycle >= PATROL_CYCLES_BEFORE_JUMP:
                    if now - _jump_last_t >= JUMP_COOLDOWN:
                        stop_movement()
                        do_jump()
                        _jump_last_t = time.time()
                        if ROPE_CLIMB_ENABLED:
                            do_rope_climb()
                            _jump_last_t = time.time()
                        _patrol_cycle = 0
                        rope_tag = "+ 爬繩" if ROPE_CLIMB_ENABLED else ""
                        print(f"  ↑ 智慧換層跳（{PATROL_CYCLES_BEFORE_JUMP} 輪無怪）{rope_tag}")

            if now - _patrol_jump_t >= PATROL_JUMP_SEC:
                if now - _jump_last_t >= JUMP_COOLDOWN:
                    do_jump()
                    _jump_last_t = now
                    _patrol_jump_t = now
                    print("  ↑ 巡邏跳")

            start_move(_patrol_dir)
            _is_moving = True
            # 巡邏中不攻擊 — 只有偵測到怪物才出技

        # ── 卡牆偵測（只在新偵測幀才執行，避免重複幀誤觸發）──────────
        if cur_frame is not None and cur_fid != _last_stuck_fid:
            _last_stuck_fid = cur_fid
            stuck = _stuck_check(cv2.cvtColor(cur_frame, cv2.COLOR_BGR2GRAY))
            if stuck:
                _do_stuck_recovery(stuck)

        elapsed = time.time() - t0
        time.sleep(max(0.0, SCAN_INTERVAL - elapsed))  # 動作 loop 50ms

    det_stop.set()
    stop_movement()
    print("⏹  打怪循環結束")


# ============================================================
# 即時偵測預覽：透明覆蓋層（直接疊在遊戲視窗上）
# ============================================================

def _overlay_worker(stop_ev):
    """透明 Tkinter 視窗疊在遊戲 ROI 上，顯示偵測框，點擊可穿透。"""
    import tkinter as tk
    import ctypes

    region = _hunt_region
    if region is None:
        print("  [V] 尚未啟動打怪，無法顯示覆蓋層")
        return

    gx, gy, gw, gh = region
    rx = gx + int(ROI_X_START * gw)
    ry = gy + int(ROI_Y_START * gh)
    rw = int((ROI_X_END  - ROI_X_START) * gw)
    rh = int((ROI_Y_END  - ROI_Y_START) * gh)

    # 洋紅色作透明鍵（MapleStory 畫面不含此色）
    CHROMA_HEX = '#FF00FF'
    CHROMA_REF = 0x00FF00FF   # Win32 COLORREF = 0x00BBGGRR → magenta

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{rw}x{rh}+{rx}+{ry}")
    root.attributes('-topmost', True)
    root.configure(bg=CHROMA_HEX)
    root.update()   # 完整渲染一次，確保 Win32 buffer 填滿洋紅色再設 colorkey

    # 手動設定 WS_EX_LAYERED | WS_EX_TRANSPARENT，再呼叫 SetLayeredWindowAttributes
    GWL_EXSTYLE       = -20
    WS_EX_LAYERED     = 0x80000
    WS_EX_TRANSPARENT = 0x20
    LWA_COLORKEY      = 0x1
    GA_ROOT           = 2

    inner_hwnd = root.winfo_id()
    hwnd = ctypes.windll.user32.GetAncestor(inner_hwnd, GA_ROOT) or inner_hwnd
    ex = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                         ex | WS_EX_LAYERED | WS_EX_TRANSPARENT)
    ctypes.windll.user32.SetLayeredWindowAttributes(
        hwnd, CHROMA_REF, 0, LWA_COLORKEY)

    canvas = tk.Canvas(root, bg=CHROMA_HEX, highlightthickness=0,
                       width=rw, height=rh)
    canvas.place(x=0, y=0, width=rw, height=rh)

    char_px = int(rw * CHAR_X_RATIO)
    char_py = int(rh * CHAR_Y_RATIO)

    def refresh():
        if stop_ev.is_set():
            root.after(0, root.destroy)  # 必須從 Tkinter 自己的 thread 呼叫 destroy
            return

        with _detect_result_lock:
            monsters = list(_detected_monsters)
            is_run   = running
            cur_dir  = _patrol_dir

        canvas.delete('all')

        # 角色十字線 + 攻擊範圍虛線框
        canvas.create_line(char_px, 0, char_px, rh, fill='#00c800', width=1)
        canvas.create_line(0, char_py, rw, char_py, fill='#00c800', width=1)
        canvas.create_oval(char_px-8, char_py-8, char_px+8, char_py+8,
                           outline='#00ff00', width=2)
        canvas.create_rectangle(
            char_px - ATTACK_RANGE_H, char_py - ATTACK_RANGE_V,
            char_px + ATTACK_RANGE_H, char_py + ATTACK_RANGE_V,
            outline='#00cc00', width=1, dash=(4, 2))

        # 怪物偵測框（鎖定目標用黃色粗框）
        lp = _locked_pos
        for mx, my, conf, name, tw, th in monsters:
            hw, hh = tw // 2, th // 2
            is_locked = (lp is not None and
                         (mx - lp[0]) ** 2 + (my - lp[1]) ** 2 <= LOCK_RADIUS ** 2)
            color = '#ffee00' if is_locked else '#ff3030'
            width = 3        if is_locked else 2
            canvas.create_rectangle(mx-hw, my-hh, mx+hw, my+hh,
                                   outline=color, width=width)
            label = f"{'🎯 ' if is_locked else ''}{name.split('/')[-1]} {conf:.2f}"
            canvas.create_text(mx-hw+2, max(2, my-hh-14),
                              text=label, fill='#ffee00' if is_locked else '#00ddff',
                              anchor='nw', font=('Consolas', 8, 'bold'))
            canvas.create_oval(mx-3, my-3, mx+3, my+3,
                              fill=color, outline='')

        # 頂部狀態列
        if not is_run:
            status, sc = 'STOPPED', '#888888'
        elif monsters:
            status, sc = f'ATTACKING  {len(monsters)} targets', '#ff5555'
        else:
            status, sc = f'PATROL → {cur_dir}', '#ffcc00'
        canvas.create_rectangle(0, 0, rw, 20, fill='#111111', outline='')
        canvas.create_text(4, 10, text=status, fill=sc,
                          anchor='w', font=('Consolas', 9, 'bold'))

        root.after(50, refresh)

    refresh()
    root.mainloop()
    print("  [V] 偵測覆蓋層已關閉")


def toggle_overlay():
    global _overlay_thread, _overlay_stop_ev
    if _overlay_thread and _overlay_thread.is_alive():
        _overlay_stop_ev.set()
        print("  [V] 偵測覆蓋層 → 關閉中...")
    else:
        if _hunt_region is None:
            print("  [V] 請先按 F8 啟動打怪再開啟覆蓋層")
            return
        _overlay_stop_ev = threading.Event()
        _overlay_thread  = threading.Thread(
            target=_overlay_worker, args=(_overlay_stop_ev,), daemon=True
        )
        _overlay_thread.start()
        print("  [V] 偵測覆蓋層 → 開啟（直接疊在遊戲上）")


# ============================================================
# 控制函式
# ============================================================

def toggle_hunt():
    global running
    running = not running
    if running:
        stop_event.clear()
        region = find_maplestory_window()
        if not region:
            print("⚠  找不到 MapleStory 視窗，請先開遊戲")
            running = False
            return
        print(f"🟢 打怪啟動  視窗={region}")
        templates = load_templates()
        threading.Thread(target=hunt_loop, args=(region, templates), daemon=True).start()
    else:
        print("🔴 打怪停止")
        stop_event.set()
        stop_movement()
        global _locked_pos, _locked_pos_smooth, _locked_miss
        _locked_pos        = None
        _locked_pos_smooth = None
        _locked_miss       = 0


def request_debug():
    global _save_debug_req
    if not running:
        print("⚠  尚未啟動，請先按 F8")
        return
    _save_debug_req = True
    print("  [D] 下一幀將存 debug 截圖...")


def print_status():
    print(
        f"[狀態] running={running}  dir={_patrol_dir}  "
        f"怪物數={len(_last_monsters)}  "
        f"moving={_is_moving}  "
        f"cycle={_patrol_cycle}  "
        f"no_monster={_patrol_no_monster_counts}"
    )


# ============================================================
# 主程式
# ============================================================

keyboard.add_hotkey("F8", toggle_hunt)
keyboard.add_hotkey("=",  toggle_hunt)
keyboard.add_hotkey("d",  request_debug)
keyboard.add_hotkey("p",  print_status)
keyboard.add_hotkey("v",  toggle_overlay)

print("=" * 60)
print("  MapleStory 自動打怪脚本 v5")
print("=" * 60)
print(f"  攻擊技能：{[s[0] for s in SKILLS]}")
print(f"  跳躍：{JUMP_KEY}  揈寶：{LOOT_KEY or '未設定'}")
print(f"  模板資料夾：{TEMPLATE_DIR}/")
print(f"  爬繩：{'開' if ROPE_CLIMB_ENABLED else '關'}  "
      f"換層門値：{PATROL_CYCLES_BEFORE_JUMP} 輪")
print(f"  F8/=  開關  |  V  偵測預覽  |  D  debug截圖  |  P  狀態  |  ESC  離開")
print("=" * 60)

keyboard.wait("esc")
stop_event.set()
stop_movement()
print("👋 已離開")
