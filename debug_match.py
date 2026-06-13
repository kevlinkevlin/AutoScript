"""
模板匹配診斷：印出每個模板在最新 debug 截圖上的最高分，
幫助判斷 threshold 該設多少。
"""
import cv2
import numpy as np
import os
import glob

TEMPLATE_DIR = "monster_templates"
DEBUG_DIR    = "debug"
SCALES       = [0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3, 1.4]

# 找最新的 debug 截圖
shots = sorted(glob.glob(os.path.join(DEBUG_DIR, "hunt_debug_*.png")))
if not shots:
    print("找不到 debug 截圖，請先按 D 存一張")
    exit()

frame_path = shots[-1]
print(f"使用截圖：{frame_path}\n")
frame = cv2.imread(frame_path)
if frame is None:
    print("無法讀取截圖")
    exit()

# ROI（與 start_hunt.py 一致）
ROI_Y_START, ROI_Y_END = 0.08, 0.85
fh, fw = frame.shape[:2]
frame = frame[int(fh*ROI_Y_START):int(fh*ROI_Y_END), :]

# 收集所有模板（支援子資料夾 + 舊版扁平）
TEMPLATE_FRAMES = [
    "stand_0.png", "stand_8.png", "stand_17.png", "stand_26.png",
    "move_0.png",  "move_4.png",
]

template_paths = []
entries = sorted(os.listdir(TEMPLATE_DIR))
subdirs = [e for e in entries if os.path.isdir(os.path.join(TEMPLATE_DIR, e))]
if subdirs:
    for monster in subdirs:
        for fname in TEMPLATE_FRAMES:
            p = os.path.join(TEMPLATE_DIR, monster, fname)
            if os.path.isfile(p):
                template_paths.append((f"{monster}/{fname}", p))
else:
    for fname in entries:
        if fname.lower().endswith((".png", ".jpg", ".bmp")):
            template_paths.append((fname, os.path.join(TEMPLATE_DIR, fname)))

for label, path in template_paths:
    raw = cv2.imread(path, cv2.IMREAD_UNCHANGED)
    if raw is None:
        continue

    has_alpha = raw.ndim == 3 and raw.shape[2] == 4
    if has_alpha:
        t_bgr = raw[:, :, :3]
        alpha = raw[:, :, 3]
        if not np.any(alpha < 255):
            alpha = None
    else:
        t_bgr = raw if raw.ndim == 3 else cv2.cvtColor(raw, cv2.COLOR_GRAY2BGR)
        alpha = None

    best_score = 0.0
    best_scale = 1.0
    best_loc   = (0, 0)

    for s in SCALES:
        oh, ow = t_bgr.shape[:2]
        nh, nw = max(1, int(oh*s)), max(1, int(ow*s))
        t  = cv2.resize(t_bgr, (nw, nh))
        a  = cv2.resize(alpha, (nw, nh), interpolation=cv2.INTER_NEAREST) if alpha is not None else None

        if frame.shape[0] < nh or frame.shape[1] < nw:
            continue

        if a is not None:
            res = cv2.matchTemplate(frame, t, cv2.TM_CCOEFF_NORMED, mask=a)
        else:
            res = cv2.matchTemplate(frame, t, cv2.TM_CCOEFF_NORMED)

        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        if max_val > best_score:
            best_score = max_val
            best_scale = s
            best_loc   = max_loc

    alpha_tag = "有透明" if has_alpha and alpha is not None else "【無透明背景】"
    print(f"  {label:<35} 最高分={best_score:.3f}  scale={best_scale:.1f}  loc={best_loc}  {alpha_tag}")

print(f"\n目前 MATCH_THRESHOLD = 0.50  MATCH_THRESHOLD_EDGE = 0.42")
print("建議：分數 >= 0.45 → threshold OK；分數 0.35–0.44 → 考慮再降 threshold；分數 < 0.35 → 模板需重截或加透明背景")
