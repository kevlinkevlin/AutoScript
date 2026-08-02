"""
持續追蹤畫面中「目標白色圖形」的位置。

註：先前版本追蹤圖形中央的粉紅色圖示，後來確認那其實是「滑鼠游標」，
不是遊戲畫面固定的標記，所以那個方法是誤判，已移除。

目前是最簡單的第一版：直接找畫面中「偏白」的區域（高明度、低飽和度），
不限定形狀（因為目標不一定是三角形，也可能旋轉），偵測到的位置用
紅色十字標示出來，方便你在即時畫面上肉眼確認判斷準不準。

已知限制（先用這版測試、再依實際狀況調整）：
  - 背景會持續變動、圖形會旋轉 → 目前每一幀都是獨立偵測，不依賴形狀比對
  - 顏色會隨時間淡化融入背景 → 目前的絕對亮度門檻在淡化後可能會失效，
    到時候可能要改成「相對背景的局部對比」或「時間序列變化」來判斷

重要：偵測完全不看滑鼠游標（那個粉紅圖示只是游標，不是目標）。
但因為「滑鼠會自動移到偵測到的位置」，游標本身也帶有一圈白色，
如果不排除，下一幀就可能抓到「自己剛剛移過去的游標」而不是真正
目標，造成一直原地打轉、跟丟了也不知道。所以每次偵測前，會先用
系統回報的實際滑鼠座標，把游標所在的一小圈範圍從白色遮罩中挖掉
（cv2.circle 畫黑洞），確保鎖定的永遠是畫面上的白色圖形本身，
不是游標的殘影。

用法：
  python track_triangle.py                    # 預設：自動偵測大理石紋理範圍後即時追蹤
  python track_triangle.py --pick              # 手動框選範圍（跳過自動偵測）
  python track_triangle.py --region x,y,w,h   # 指定螢幕區域追蹤
  python track_triangle.py --auto              # 只抓 MapleStory 視窗本身，不裁切大理石紋理範圍
  python track_triangle.py test2.png           # 單張圖片測試（偵測完存檔就結束）
"""

import sys
import os
import time
import argparse

# 修正 Windows 多螢幕、不同縮放比例下 mss/GDI 截圖錯位或只抓到一半的問題：
# 讓這個 process 宣告自己是 per-monitor DPI aware，Windows 就不會用主螢幕的
# 縮放比例去套用到其他螢幕，座標/尺寸才會跟實際物理像素對得上。
# 必須在建立任何視窗、截圖之前盡早呼叫。
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import cv2
import numpy as np
import pyautogui

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))
from cv_utils import screenshot_mss  # noqa

try:
    from maplestory_define import find_maplestory_window  # noqa
except Exception:
    find_maplestory_window = None


# ── 參數：白色區域的 HSV 門檻 ──
WHITE_S_MAX = 60      # 飽和度上限（越低越接近純白/灰白）
WHITE_V_MIN = 190     # 明度下限（越高越亮）

MIN_AREA_RATIO = 0.0008  # 最小面積（相對畫面面積的比例），過濾雜訊
MAX_AREA_RATIO = 0.08    # 最大面積（相對畫面面積的比例），避免抓到過大的區塊

TRACK_MAX_JUMP    = 150    # 追蹤時允許與上一幀中心的最大距離（像素）
LOST_GRACE_FRAMES = 15     # 連續幾幀找不到才視為跟丟，重新在整張畫面搜尋
CAPTURE_INTERVAL  = 0.08   # 擷取間隔（秒）

CENTER_LOCK_MAX_RATIO = 0.4  # 初次鎖定時，候選離畫面中心最遠可接受的距離（相對 min(w,h) 的比例）

CURSOR_EXCLUDE_RADIUS = 26  # 排除游標所在小範圍的半徑（像素），避免抓到游標自己

# ── 大理石紋理背景的 HSV 範圍，用來自動偵測追蹤範圍（不用手動框選）──
MARBLE_H_RANGE = (8, 28)
MARBLE_S_MIN = 60
MARBLE_V_MIN = 40


MARBLE_MIN_AREA_RATIO = 0.05  # 大理石範圍至少要佔畫面面積的比例，太小視為雜訊
MARBLE_MIN_EXTENT = 0.85      # 輪廓面積 / 外接矩形面積，越接近 1 越像一個實心矩形面板


def detect_marble_region(bgr):
    """在整張畫面中找出大理石紋理背景所在的邊界框

    回傳 (x, y, w, h)，座標是相對這張 bgr 畫面本身（不是螢幕絕對座標）。
    找不到就回傳 None。

    大理石面板本身顏色很純、範圍完整，原始遮罩幾乎不需要修補就已經是一塊
    很乾淨的矩形。這裡刻意只做「輕微」的open去雜訊、不做大範圍的close，
    是因為之前用很大的 close 核心，會把面板跟旁邊角色、UI 等其他偏棕色的
    雜訊「橋接」成同一塊輪廓，導致外接矩形被拉大、跨到面板以外的地方。
    改成看每個候選輪廓的「實心程度」(面積 / 外接矩形面積)，只挑真正接近
    實心矩形的那一塊，就不會被橋接的雜訊誤導。
    """
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (MARBLE_H_RANGE[0], MARBLE_S_MIN, MARBLE_V_MIN), (MARBLE_H_RANGE[1], 255, 255))

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    frame_area = bgr.shape[0] * bgr.shape[1]
    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < MARBLE_MIN_AREA_RATIO * frame_area:
            continue
        x, y, w, h = cv2.boundingRect(c)
        extent = area / float(w * h)
        if extent < MARBLE_MIN_EXTENT:
            continue
        candidates.append((area, (x, y, w, h)))

    if not candidates:
        return None

    candidates.sort(key=lambda t: -t[0])
    return candidates[0][1]


def auto_detect_region():
    """不用手動框選：自動找 MapleStory 視窗（找不到就用整個虛擬螢幕），
    再從裡面抓出大理石紋理背景的範圍，當作追蹤用的預設區域。
    """
    import mss

    base_region = None
    if find_maplestory_window:
        try:
            base_region = find_maplestory_window()
        except Exception:
            base_region = None

    if base_region is None:
        with mss.mss() as sct:
            mon = sct.monitors[0]
            base_region = (int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"]))
        print("找不到 MapleStory 視窗，改成在整個虛擬螢幕範圍內找大理石紋理")
    else:
        print(f"已抓到 MapleStory 視窗：{base_region}")

    frame = screenshot_mss(base_region)
    bbox = detect_marble_region(frame)
    if bbox is None:
        print("找不到大理石紋理，改用整個視窗/螢幕範圍")
        return base_region

    x, y, w, h = bbox
    region = (base_region[0] + x, base_region[1] + y, w, h)
    print(f"已自動偵測到大理石紋理範圍：{region}")
    return region


def _exclude_cursor(mask, region):
    """把目前滑鼠游標所在位置從遮罩中挖掉，避免偵測到游標本身而不是真正的目標"""
    try:
        mx, my = pyautogui.position()
    except Exception:
        return mask

    rx, ry, _rw, _rh = region
    lx, ly = mx - rx, my - ry
    if 0 <= lx < mask.shape[1] and 0 <= ly < mask.shape[0]:
        cv2.circle(mask, (lx, ly), CURSOR_EXCLUDE_RADIUS, 0, -1)
    return mask


def find_candidates(bgr, region=None):
    """回傳所有偵測到的白色區域： [(cx, cy, area, contour), ...]，面積由大到小排序

    region 是這張 bgr 畫面對應的螢幕範圍 (x, y, w, h)；有給的話，
    會把目前滑鼠游標所在的位置從候選中排除（見檔案開頭說明）。
    """
    frame_h, frame_w = bgr.shape[:2]
    frame_area = frame_h * frame_w
    min_area = MIN_AREA_RATIO * frame_area
    max_area = MAX_AREA_RATIO * frame_area

    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, WHITE_V_MIN), (180, WHITE_S_MAX, 255))

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    if region is not None:
        mask = _exclude_cursor(mask, region)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < min_area or area > max_area:
            continue
        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])
        candidates.append((cx, cy, area, c))

    candidates.sort(key=lambda t: -t[2])
    return candidates


def draw_crosshair(vis, cx, cy, color=(0, 0, 255), size=16, thickness=2):
    cv2.line(vis, (cx - size, cy), (cx + size, cy), color, thickness)
    cv2.line(vis, (cx, cy - size), (cx, cy + size), color, thickness)
    cv2.circle(vis, (cx, cy), 3, color, -1)


def pick_target(candidates, prev_center, frame_shape=None):
    """挑選目標：每一幀都優先選「離畫面中心最近」的候選，不是只有剛鎖定
    那一刻才看中心。

    原本的版本是「有上一幀位置就只看離上一幀最近的」，結果只要有一幀不小心
    鎖到倒數數字（它位置通常不太動），之後每一幀都會覺得「上一幀的位置附近
    還有東西」→ 繼續鎖著數字，永遠不會發現旁邊才是真正的目標，數字倒數期間
    整個追蹤就卡死在數字上。實測比對過（test4~test6）真正目標離畫面中心的
    距離，一路都遠比倒數數字/其他白色文字近很多，所以改成每一幀都重新用
    「離中心最近」判斷，就不會被鎖死在數字上。

    只有當畫面中心附近完全沒有候選（例如目標真的移動出中心範圍很遠）時，
    才退而求其次改用「離上一幀位置最近」延續追蹤，避免瞬間跟丟。
    """
    if not candidates:
        return None

    if frame_shape is not None:
        fh, fw = frame_shape[:2]
        fcx, fcy = fw / 2.0, fh / 2.0
        max_dist = CENTER_LOCK_MAX_RATIO * min(fw, fh)
        near_center = [c for c in candidates if np.hypot(c[0] - fcx, c[1] - fcy) <= max_dist]
        if near_center:
            near_center.sort(key=lambda t: np.hypot(t[0] - fcx, t[1] - fcy))
            return near_center[0]

    if prev_center is not None:
        px, py = prev_center
        in_range = [c for c in candidates if np.hypot(c[0] - px, c[1] - py) <= TRACK_MAX_JUMP]
        if in_range:
            in_range.sort(key=lambda t: np.hypot(t[0] - px, t[1] - py))
            return in_range[0]
        return None

    return candidates[0]


def _parse_region(s):
    x, y, w, h = (int(v) for v in s.split(","))
    return (x, y, w, h)


def pick_region_interactive():
    """截取整個虛擬螢幕（含多螢幕），縮放後跳出視窗讓使用者拖曳框選範圍

    之前直接把原始解析度的截圖丟給 cv2.selectROI，視窗沒有縮放、
    也只抓 monitors[1]（單一主螢幕），導致：
      1. 解析度較高（尤其開了 Windows 縮放）時，視窗會比螢幕還大，
         只看得到/框得到左上角一小塊，看起來「可以框選的範圍很小」
      2. 如果目標在副螢幕上，monitors[1] 根本抓不到那個畫面
    這裡改成抓 monitors[0]（涵蓋所有螢幕），並依實際可視大小縮小
    顯示，選取完再把座標換算回真實螢幕座標。
    """
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[0]  # virtual screen：涵蓋所有螢幕
        v_left, v_top = int(mon["left"]), int(mon["top"])
        full = np.array(sct.grab(mon))[:, :, :3]

    h, w = full.shape[:2]
    max_show_w, max_show_h = 1400, 850
    scale = min(max_show_w / w, max_show_h / h, 1.0)
    show = cv2.resize(full, (int(w * scale), int(h * scale))) if scale < 1.0 else full

    win = "拖曳框選追蹤範圍  (框好按 Enter/Space 確認，Esc 取消)"
    print("請在跳出的視窗中用滑鼠拖曳框選要追蹤的範圍，框好後按 Enter 或空白鍵確認（Esc 取消）")
    x, y, sw, sh = cv2.selectROI(win, show, showCrosshair=True, fromCenter=False)
    cv2.destroyWindow(win)

    if sw == 0 or sh == 0:
        print("未選取範圍，取消")
        return None

    x, y, sw, sh = (int(x / scale), int(y / scale), int(sw / scale), int(sh / scale))
    return (v_left + x, v_top + y, sw, sh)


def run_image_test(path):
    bgr = cv2.imread(path)
    if bgr is None:
        print(f"無法讀取：{path}")
        sys.exit(1)

    candidates = find_candidates(bgr)
    target = pick_target(candidates, None, bgr.shape)

    vis = bgr.copy()
    for cx, cy, area, c in candidates:
        cv2.drawContours(vis, [c], -1, (0, 200, 255), 1)

    if target:
        cx, cy, area, c = target
        draw_crosshair(vis, cx, cy)
        cv2.putText(vis, f"({cx},{cy})", (cx + 12, cy - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        print(f"判斷位置：({cx}, {cy})  area={area:.0f}")
    else:
        print("未偵測到目標")

    out_path = "track_triangle_result.png"
    cv2.imwrite(out_path, vis)
    print(f"[done] 已存：{out_path}")


def run_live(region, show):
    print(f"追蹤區域：{region}")
    prev_center = None
    lost_frames = 0

    try:
        while True:
            frame = screenshot_mss(region)
            candidates = find_candidates(frame, region)
            target = pick_target(candidates, prev_center, frame.shape)

            if target:
                cx, cy, area, c = target
                prev_center = (cx, cy)
                lost_frames = 0
                sx, sy = region[0] + cx, region[1] + cy
                print(f"[{time.strftime('%H:%M:%S')}] 判斷位置  區域內=({cx},{cy})  螢幕座標=({sx},{sy})  area={area:.0f}")
            else:
                lost_frames += 1
                if lost_frames >= LOST_GRACE_FRAMES:
                    if prev_center is not None:
                        print(f"[{time.strftime('%H:%M:%S')}] 跟丟目標，重新搜尋整個畫面")
                    prev_center = None

            if show:
                vis = frame.copy()
                for ccx, ccy, area, c in candidates:
                    cv2.drawContours(vis, [c], -1, (0, 200, 255), 1)
                if target:
                    cx, cy, area, c = target
                    draw_crosshair(vis, cx, cy)
                cv2.imshow("track_triangle (q 離開)", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            time.sleep(CAPTURE_INTERVAL)
    except KeyboardInterrupt:
        pass
    finally:
        if show:
            cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description="持續追蹤畫面中的白色圖形位置（十字標示判斷結果）")
    parser.add_argument("image", nargs="?", help="單張圖片測試模式的圖片路徑")
    parser.add_argument("--region", type=_parse_region, help="x,y,w,h  指定螢幕擷取區域")
    parser.add_argument("--pick", action="store_true", help="手動框選範圍（跳過自動偵測大理石紋理）")
    parser.add_argument("--auto", action="store_true", help="只抓 MapleStory 視窗本身，不裁切大理石紋理範圍")
    parser.add_argument("--no-show", action="store_true", help="即時模式不開預覽視窗")
    args = parser.parse_args()

    if args.image:
        run_image_test(args.image)
        return

    region = args.region

    if region is None and args.auto:
        if find_maplestory_window:
            region = find_maplestory_window()
        if region is None:
            with __import__("mss").mss() as sct:
                mon = sct.monitors[0]
                region = (int(mon["left"]), int(mon["top"]), int(mon["width"]), int(mon["height"]))
            print("找不到 MapleStory 視窗，改用整個虛擬螢幕")

    if region is None and args.pick:
        region = pick_region_interactive()
        if region is None:
            return

    if region is None:
        region = auto_detect_region()

    run_live(region, show=not args.no_show)


if __name__ == "__main__":
    main()
