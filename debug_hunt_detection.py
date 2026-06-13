"""
Debug script: 對 hunt_debug PNG 跑模板匹配，輸出標注結果圖
用法: python debug_hunt_detection.py [hunt_debug圖路徑]
"""

import os
import sys
import glob
import numpy as np
import cv2

# ── 參數（與 start_hunt.py 保持一致，可在此調整測試）──
TEMPLATE_DIR         = "monster_templates"
MATCH_THRESHOLD      = 0.55
MATCH_THRESHOLD_EDGE = 0.50
NMS_IOU_THRESH       = 0.45
SCALES               = [0.50, 0.60, 0.70, 0.80, 0.90, 1.0, 1.10, 1.20, 1.35, 1.50]

# 指定要測試的幀 — 載入子資料夾裡 *所有* png
USE_ALL_FRAMES = False  # True = 全幀；False = 只用下面的子集（與 start_hunt.py 一致）
TEMPLATE_FRAMES = [
    "stand_0.png", "stand_17.png", "stand_26.png",
    "move_0.png",  "move_4.png",
]


# ── 載入模板 ─────────────────────────────────────────────

def _load_one(path, label):
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
    print(f"  OK {label}  {bgr.shape[1]}x{bgr.shape[0]}  [{flag}]  edge={edge_pct*100:.0f}%")
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
    templates = []
    if not os.path.isdir(TEMPLATE_DIR):
        print(f"  ⚠  找不到 {TEMPLATE_DIR}/")
        return templates

    entries = sorted(os.listdir(TEMPLATE_DIR))
    subdirs = [e for e in entries if os.path.isdir(os.path.join(TEMPLATE_DIR, e))]
    files   = [e for e in entries if e.lower().endswith((".png", ".jpg", ".bmp"))]

    if subdirs:
        for monster in subdirs:
            monster_dir = os.path.join(TEMPLATE_DIR, monster)
            if USE_ALL_FRAMES:
                frame_files = sorted(
                    f for f in os.listdir(monster_dir)
                    if f.lower().endswith((".png", ".jpg", ".bmp"))
                )
            else:
                frame_files = TEMPLATE_FRAMES

            loaded = 0
            for fname in frame_files:
                path = os.path.join(monster_dir, fname)
                if not os.path.isfile(path):
                    continue
                t = _load_one(path, f"{monster}/{fname}")
                if t:
                    templates.append(t)
                    loaded += 1
            print(f"  [{monster}] 載入 {loaded} 幀")
    else:
        for fname in files:
            t = _load_one(os.path.join(TEMPLATE_DIR, fname), fname)
            if t:
                templates.append(t)

    print(f"  共載入 {len(templates)} 個模板幀\n")
    return templates


# ── 匹配 ─────────────────────────────────────────────────

def _match_one_scale(frame_bgr, tmpl, scale):
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

    if alpha is not None:
        res = cv2.matchTemplate(frame_bgr, t_bgr, cv2.TM_CCOEFF_NORMED, mask=alpha)
    else:
        res = cv2.matchTemplate(frame_bgr, t_bgr, cv2.TM_CCOEFF_NORMED)

    # 報告此模板此縮放的最佳分數（用於調參）
    best = float(res.max())
    if best > 0.25:
        loc = np.unravel_index(res.argmax(), res.shape)
        print(f"    scale={scale:.2f}  {tmpl['name']}  best={best:.3f}  @({loc[1]},{loc[0]})")

    ys, xs = np.where(res >= MATCH_THRESHOLD)
    if len(xs) == 0:
        return []

    hits = []
    for px, py in zip(xs, ys):
        conf = float(res[py, px])
        if t_edges is not None:
            roi_gray  = cv2.cvtColor(frame_bgr[py:py+th, px:px+tw], cv2.COLOR_BGR2GRAY)
            roi_edges = cv2.Canny(roi_gray, 30, 100).astype(np.float32)
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
    kept = []
    for cx, cy, conf, name, tw, th in sorted(detections, key=lambda d: -d[2]):
        ax, ay = cx - tw // 2, cy - th // 2
        if not any(
            _iou(ax, ay, tw, th, kx - ktw // 2, ky - kth // 2, ktw, kth) > NMS_IOU_THRESH
            for kx, ky, _, _, ktw, kth in kept
        ):
            kept.append((cx, cy, conf, name, tw, th))
    return [(cx, cy, conf, name) for cx, cy, conf, name, *_ in kept]


def find_monsters(frame, templates):
    all_hits = []
    for t in templates:
        for s in SCALES:
            for cx, cy, conf, tw, th in _match_one_scale(frame, t, s):
                all_hits.append((cx, cy, conf, t["name"], tw, th))
    return nms(all_hits)


# ── 主程式 ───────────────────────────────────────────────

def main():
    debug_path = sys.argv[1] if len(sys.argv) > 1 else None
    if not debug_path:
        # 自動找最新的 hunt_debug_*.png
        pattern = os.path.join("debug", "hunt_debug_*.png")
        candidates = sorted(glob.glob(pattern))
        if not candidates:
            # fallback: 直接用 debug 裡任意 png
            candidates = sorted(glob.glob(os.path.join("debug", "*.png")))
        if not candidates:
            print("找不到 debug 圖，請傳入路徑：python debug_hunt_detection.py <圖路徑>")
            sys.exit(1)
        debug_path = candidates[-1]

    print(f"\n=== 測試圖：{debug_path} ===\n")
    frame = cv2.imread(debug_path)
    if frame is None:
        print(f"無法讀取：{debug_path}")
        sys.exit(1)
    print(f"圖片尺寸：{frame.shape[1]}x{frame.shape[0]}\n")

    print("── 載入模板 ──")
    templates = load_templates()
    if not templates:
        print("無模板可用，退出")
        sys.exit(1)

    print("\n── 開始偵測（輸出 best > 0.25 的候選）──")
    monsters = find_monsters(frame, templates)

    print(f"\n── NMS 後偵測結果：{len(monsters)} 個怪物 ──")
    for i, (cx, cy, conf, name) in enumerate(monsters):
        print(f"  [{i+1}] {name}  conf={conf:.3f}  center=({cx},{cy})")

    # 繪製標注圖
    vis = frame.copy()
    # 顏色對應
    color_map = {}
    palette = [(0,0,255),(255,128,0),(0,200,255),(200,0,255),(0,255,128)]
    for cx, cy, conf, name in monsters:
        monster_type = name.split("/")[0]
        if monster_type not in color_map:
            color_map[monster_type] = palette[len(color_map) % len(palette)]
        color = color_map[monster_type]
        # 估算框大小（若有比例就用，這裡用固定值）
        half = 30
        cv2.rectangle(vis, (cx - half, cy - half), (cx + half, cy + half), color, 2)
        cv2.putText(vis, f"{name[:18]} {conf:.2f}",
                    (cx - half, cy - half - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, color, 1)
        cv2.circle(vis, (cx, cy), 3, color, -1)

    out_path = debug_path.replace(".png", "_detected.png")
    cv2.imwrite(out_path, vis)
    print(f"\n[done] saved: {out_path}")

    if not monsters:
        print("\n[warn] no monsters detected. possible reasons:")
        print("   1. template color mismatch (e.g. gray in screenshot vs brown/pink template)")
        print("   2. MATCH_THRESHOLD too high (current:", MATCH_THRESHOLD, ")")
        print("   3. SCALES range does not cover actual monster size")
        print("   -> lower MATCH_THRESHOLD or add matching monster templates")


if __name__ == "__main__":
    main()
