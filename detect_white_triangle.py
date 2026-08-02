"""
偵測畫面中「白色實心三角形」的位置
用法: python detect_white_triangle.py [圖片路徑]
      不帶參數時預設讀取 test2.png
"""

import sys
import cv2
import numpy as np

# ── 參數 ─────────────────────────────────────────────
WHITE_S_MAX   = 60     # HSV 飽和度上限（越低越接近純白/灰白）
WHITE_V_MIN   = 200    # HSV 明度下限（越高越亮）
MIN_AREA      = 200    # 過濾雜訊用的最小輪廓面積（像素）
APPROX_EPS    = 0.04   # 多邊形近似精度（相對周長比例）


def find_white_triangles(bgr):
    """回傳所有偵測到的白色三角形： [(cx, cy, area, pts), ...]，依面積由大到小排序"""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 0, WHITE_V_MIN), (180, WHITE_S_MAX, 255))

    # 補洞、去雜訊
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    triangles = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < MIN_AREA:
            continue

        peri = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, APPROX_EPS * peri, True)
        if len(approx) != 3:
            continue

        # 三角形要夠「實心」：實際面積 / 外接三角形面積 不能太小
        tri_area = cv2.contourArea(approx)
        if tri_area <= 0 or area / tri_area < 0.85:
            continue

        M = cv2.moments(c)
        if M["m00"] == 0:
            continue
        cx = int(M["m10"] / M["m00"])
        cy = int(M["m01"] / M["m00"])

        triangles.append((cx, cy, area, approx.reshape(-1, 2)))

    triangles.sort(key=lambda t: -t[2])
    return triangles, mask


def main():
    img_path = sys.argv[1] if len(sys.argv) > 1 else "test2.png"

    bgr = cv2.imread(img_path)
    if bgr is None:
        print(f"無法讀取：{img_path}")
        sys.exit(1)

    print(f"圖片：{img_path}  尺寸={bgr.shape[1]}x{bgr.shape[0]}")

    triangles, mask = find_white_triangles(bgr)

    if not triangles:
        print("未偵測到白色三角形（可調整 WHITE_S_MAX / WHITE_V_MIN / MIN_AREA 再試）")
        cv2.imwrite("detect_white_triangle_mask.png", mask)
        sys.exit(0)

    print(f"\n偵測到 {len(triangles)} 個白色三角形：")
    vis = bgr.copy()
    for i, (cx, cy, area, pts) in enumerate(triangles):
        tag = "★" if i == 0 else " "
        print(f"  {tag} [{i+1}] center=({cx}, {cy})  area={area:.0f}")
        color = (0, 0, 255) if i == 0 else (0, 200, 255)
        cv2.polylines(vis, [pts.astype(np.int32)], True, color, 2)
        cv2.circle(vis, (cx, cy), 4, color, -1)
        cv2.putText(vis, f"#{i+1}", (cx + 8, cy - 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    out_path = "detect_white_triangle_result.png"
    cv2.imwrite(out_path, vis)
    cv2.imwrite("detect_white_triangle_mask.png", mask)
    print(f"\n最主要三角形中心座標：{triangles[0][:2]}")
    print(f"[done] 標注圖已存：{out_path}")


if __name__ == "__main__":
    main()
