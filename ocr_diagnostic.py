#!/usr/bin/env python3
"""
ocr_diagnostic.py
掃描 ocr_debug_image/ 中所有圖片（即 auction.png 的歷史存檔），
對每張執行 EasyOCR，找出低信心度結果，分析原因並提出改善建議。
同時輸出標注圖與低信心裁切圖供視覺確認。
"""

import os
import re
import cv2
import numpy as np
import easyocr
from pathlib import Path
from datetime import datetime

# ── 設定（對齊 start_auction.py） ──────────────────────────────────────
IMAGE_DIR        = "ocr_debug_image"
ANNOTATED_DIR    = "ocr_diagnostic_annotated"
CROPS_DIR        = "ocr_diagnostic_crops"
REPORT_FILE      = "ocr_diagnostic_report.txt"
MIN_CONFIDENCE   = 0.75
NUMBER_IN_AUCTION = 7
ALLOWLIST        = '0123456789,'
# ───────────────────────────────────────────────────────────────────────


# ── 工具函式 ────────────────────────────────────────────────────────────

def pixel_stats(img: np.ndarray):
    white = float(np.sum(img > 200)) / img.size
    std   = float(np.std(img))
    return white, std


def crop_box(img: np.ndarray, box, padding: int = 6):
    pts = np.array(box, dtype=np.int32)
    x1, y1 = pts[:, 0].min() - padding, pts[:, 1].min() - padding
    x2, y2 = pts[:, 0].max() + padding, pts[:, 1].max() + padding
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(img.shape[1], x2), min(img.shape[0], y2)
    if x2 <= x1 or y2 <= y1:
        return None
    return img[y1:y2, x1:x2]


def find_overlapping(results, target_box):
    """在另一組 OCR 結果中找與 target_box IoU 最高的項目"""
    tb = np.array(target_box)
    tx1, ty1 = tb[:, 0].min(), tb[:, 1].min()
    tx2, ty2 = tb[:, 0].max(), tb[:, 1].max()
    best, best_ov = None, 0
    for box, text, conf in results:
        b = np.array(box)
        ox = max(0, min(tx2, b[:, 0].max()) - max(tx1, b[:, 0].min()))
        oy = max(0, min(ty2, b[:, 1].max()) - max(ty1, b[:, 1].min()))
        ov = ox * oy
        if ov > best_ov:
            best_ov, best = ov, (box, text, conf)
    return best


def detect_ui_overlay(results_full) -> list[str]:
    """
    在全字元 OCR 結果中找非數字的中文/英文文字，
    判斷是否有系統對話框或 tooltip 遮擋拍賣列表。
    回傳疑似遮擋文字的清單。
    """
    overlay_texts = []
    for _, text, conf in results_full:
        # 含中文字且信心夠高 → 疑似 UI 元素而非價格
        if conf > 0.5 and re.search(r'[一-鿿＀-￯]', text):
            overlay_texts.append(f"{text!r} (conf={conf:.3f})")
    return overlay_texts


def validate_price(text: str):
    """
    驗證 OCR 結果是否為合理價格。
    回傳 (is_valid, value_or_None, reason_str)
    """
    if re.match(r'^\s*,', text):
        return False, None, "開頭逗號（前置數字截斷）"
    if re.search(r',\s*$', text):
        return False, None, "末尾逗號（後置數字截斷）"

    m = re.search(r'(\d{1,3}(?:,\d{3})+|\d+)', text)
    if not m:
        return False, None, "無法解析數字"

    if m.start() > 0 and text[m.start() - 1] == ',':
        return False, None, "數字前緊鄰逗號（前段截斷）"

    val = int(m.group(1).replace(',', ''))
    if val < 500:
        return False, val, f"數值 {val:,} 過小（疑截斷誤讀）"
    if ',' not in m.group(1) and val >= 10000:
        return False, val, f"數值 {val:,} 無逗號（疑漏讀千位符）"

    return True, val, "OK"


def diagnose_low_conf(img: np.ndarray, box, text: str, conf: float,
                      full_text: str | None = None):
    """分析低信心度原因，回傳 (causes, suggestions) 字串清單"""
    crop = crop_box(img, box)
    causes, suggestions = [], []

    if crop is None:
        return ["無法裁切區域（bbox 超出圖片）"], ["檢查 cv_capture 的 padding 設定"]

    h, w = crop.shape[:2]
    white, std = pixel_stats(crop)

    # ── 原因 1：幾乎無文字像素 ──
    if white < 0.04:
        causes.append(f"文字區白像素率過低 ({white:.1%})，截到空白或純黑背景")
        suggestions.append("調整 ratio_y / ratio_h 確保截取範圍完全落在價格欄")

    # ── 原因 2：背景噪訊高（遊戲地圖穿透） ──
    if std > 90:
        causes.append(f"像素標準差高 (σ={std:.0f})，背景噪訊疑似遊戲地圖穿透")
        suggestions.append("確認拍賣視窗完整顯示後才截圖，可在 cv_capture 前加視窗存在確認")

    # ── 原因 3：文字高度過小 ──
    if h < 28:
        causes.append(f"行高僅 {h}px（含 4× 放大後仍過小），數字細節不足")
        suggestions.append("嘗試 5× 放大（fx=5, fy=5）或增大 ratio_h")

    # ── 原因 4：首末逗號（截斷） ──
    if text.startswith(',') or text.endswith(','):
        causes.append("OCR 結果首/末含逗號，前置或後置數字被截斷")
        suggestions.append("增加左側 padding（目前 30px → 嘗試 50~60px）")

    # ── 原因 5：大數字缺逗號 ──
    raw = text.replace(',', '')
    if re.match(r'^\d{6,}$', raw):
        causes.append(f"讀到 {len(raw)} 位數字但無逗號分隔，OCR 漏讀千位符")
        suggestions.append("嘗試 paragraph=False 或調整 allowlist 加入空格來分段辨識")

    # ── 原因 6：連續重複數字 ──
    if re.search(r'(\d)\1{3,}', raw):
        causes.append("連續重複數字（如 1111、9999），EasyOCR 對此類型信心較低")
        suggestions.append("多次 OCR 取最高信心值，或以 filter_price_results 後再 cross-validate")

    # ── 原因 7：full-OCR 對照差異大 ──
    if full_text and full_text.strip() != text.strip():
        causes.append(f"無 allowlist OCR 讀到 {full_text!r}（與數字 OCR {text!r} 不同）")
        suggestions.append("檢查實際圖片：可能有中文/符號混入數字區域")

    if not causes:
        causes.append("字型渲染邊緣模糊或數字組合罕見，EasyOCR 先天信心偏低")
        suggestions.append("嘗試膨脹 kernel (2×2) 補粗筆劃後重新二值化")

    return causes, suggestions


def annotate_image(img: np.ndarray, results, filepath: str):
    colored = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for box, text, conf in results:
        pts   = np.array(box, dtype=np.int32)
        color = (0, 200, 0) if conf >= MIN_CONFIDENCE else (0, 60, 220)
        cv2.polylines(colored, [pts], True, color, 2)
        x, y  = pts[0]
        label = f"{text[:22]}  {conf:.3f}"
        cv2.putText(colored, label, (max(x, 2), max(y - 5, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, color, 1, cv2.LINE_AA)
    cv2.imwrite(filepath, colored)


# ── 主程式 ──────────────────────────────────────────────────────────────

def main():
    os.makedirs(ANNOTATED_DIR, exist_ok=True)
    os.makedirs(CROPS_DIR,     exist_ok=True)

    print("初始化 EasyOCR（GPU）…")
    reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)

    images = sorted(Path(IMAGE_DIR).glob("*.png"))
    print(f"共 {len(images)} 張圖片，開始診斷…\n")

    lines = [
        "=" * 92,
        f"  OCR 診斷報告   {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"  來源: {IMAGE_DIR}/   張數: {len(images)}   MIN_CONFIDENCE={MIN_CONFIDENCE}",
        "=" * 92, "",
    ]

    total_rows    = 0
    low_conf_rows = 0
    bad_images    = 0
    all_issues    = []
    seen_crops    = set()   # (text, conf_3dp) → 已存過，不重複產圖

    for img_path in images:
        img = cv2.imread(str(img_path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            lines.append(f"[SKIP] 無法讀取: {img_path.name}")
            continue

        h, w          = img.shape
        white, std    = pixel_stats(img)

        lines.append(f"┌─ {img_path.name}  ({w}×{h})  白像素:{white:.1%}  σ:{std:.1f}")

        # ── 無效截圖：遊戲背景穿透 ──
        if white <= 0.02 or std > 115:
            reason = "白像素過少" if white <= 0.02 else "背景雜訊過高"
            lines.append(f"│  ⛔ 無效截圖（{reason}）—— 拍賣視窗可能未完整顯示")
            lines.append("│  改善：加長 time.sleep(1.0)，或在截圖前確認視窗前景")
            lines.append("└" + "─" * 80)
            bad_images += 1
            continue

        # ── 數字 OCR（生產設定） ──
        results_num  = reader.readtext(img, allowlist=ALLOWLIST)
        # ── 全字元 OCR（對照用，找出被 allowlist 過濾掉的字） ──
        results_full = reader.readtext(img)

        # ── 偵測 UI 遮擋（對話框 / tooltip） ──
        overlays = detect_ui_overlay(results_full)
        if overlays:
            lines.append(f"│  🚨 偵測到 UI 遮擋！以下文字出現在價格區：")
            for ov in overlays:
                lines.append(f"│     {ov}")
            lines.append(f"│  改善：截圖前先關閉系統對話框，或偵測到中文文字時自動重試")
            bad_images += 1

        # ── 儲存標注圖 ──
        ann_path = os.path.join(ANNOTATED_DIR, img_path.name)
        annotate_image(img, results_num, ann_path)

        price_rows = []

        for idx, (box, text, conf) in enumerate(results_num):
            if re.search(r'[一-鿿＀-￯]', text):
                continue
            total_rows += 1
            is_price_row = (idx % 2 == 0)  # 偶數=價格行，奇數=萬行
            tag  = "價格" if is_price_row else "萬行"
            icon = "✅" if conf >= MIN_CONFIDENCE else "❌"

            lines.append(f"│  [{idx:2d}] {icon} {tag}  conf={conf:.4f}  {text!r}")

            # ── 低信心度分析 ──
            if conf < MIN_CONFIDENCE:
                low_conf_rows += 1

                full_match = find_overlapping(results_full, box)
                full_text  = full_match[1] if full_match else None
                if full_text and full_text.strip() != text.strip():
                    lines.append(f"│       full-OCR 對照: {full_text!r}  conf={full_match[2]:.4f}")

                causes, suggs = diagnose_low_conf(img, box, text, conf, full_text)
                for c in causes:
                    lines.append(f"│       ⚑ 原因: {c}")
                for s in suggs:
                    lines.append(f"│       ➤ 改善: {s}")

                crop_name  = f"{img_path.stem}_r{idx}_conf{conf:.3f}.png"
                crop       = crop_box(img, box)
                has_chinese = bool(full_text and re.search(r'[一-鿿＀-￯]', full_text))
                crop_key   = (text.strip(), f"{conf:.3f}")
                if crop is not None and not has_chinese:
                    if crop_key in seen_crops:
                        lines.append(f"│       ⏭ 裁切圖略過（相同數字+信心度已存過）")
                    else:
                        seen_crops.add(crop_key)
                        cv2.imwrite(os.path.join(CROPS_DIR, crop_name), crop)
                        lines.append(f"│       📁 裁切圖: {CROPS_DIR}/{crop_name}")

                all_issues.append(dict(image=img_path.name, idx=idx, text=text,
                                       conf=conf, causes=causes, suggs=suggs))

            # ── 即使信心夠，也驗證格式合理性 ──
            if is_price_row:
                valid, val, reason = validate_price(text)
                if not valid:
                    lines.append(f"│       ⚠️  格式驗證失敗: {reason}")
                    if conf >= MIN_CONFIDENCE:   # 高信心但格式有問題
                        all_issues.append(dict(image=img_path.name, idx=idx, text=text,
                                               conf=conf, causes=[reason],
                                               suggs=["人工目視確認此行"]))
                price_rows.append((box, text, conf, valid, val))

        # ── 每張圖的完整性摘要 ──
        ok_prices = [r for r in price_rows if r[3]]
        lines.append(f"│  → 有效價格: {len(ok_prices)}/{NUMBER_IN_AUCTION}"
                     + ("  ✅" if len(ok_prices) == NUMBER_IN_AUCTION else "  ⚠️  不足！"))

        if ok_prices:
            vals = ", ".join(f"{r[4]:,}" for r in ok_prices)
            lines.append(f"│     解析值: {vals}")

        if len(ok_prices) < NUMBER_IN_AUCTION:
            bad_images += 1

        lines.append("└" + "─" * 80)

    # ── 總結 ────────────────────────────────────────────────────────────
    cause_cnt = {}
    sugg_cnt  = {}
    for item in all_issues:
        for c in item["causes"]:
            cause_cnt[c] = cause_cnt.get(c, 0) + 1
        for s in item["suggs"]:
            sugg_cnt[s]  = sugg_cnt.get(s, 0) + 1

    lines += [
        "",
        "=" * 92,
        "  總結統計",
        "=" * 92,
        f"  圖片總數          : {len(images)}",
        f"  無效/不完整截圖   : {bad_images}",
        f"  OCR 結果總行數    : {total_rows}",
        f"  低信心度行數      : {low_conf_rows}  ({low_conf_rows / max(total_rows, 1) * 100:.1f}%)",
        "",
        "  常見低信心原因（依次數）:",
    ]
    for cause, n in sorted(cause_cnt.items(), key=lambda x: -x[1]):
        lines.append(f"    [{n:3d}次]  {cause}")

    lines += ["", "  改善建議（依次數）:"]
    for sug, n in sorted(sugg_cnt.items(), key=lambda x: -x[1]):
        lines.append(f"    [{n:3d}次]  {sug}")

    lines += [
        "",
        "  輸出檔案:",
        f"    報告  : {REPORT_FILE}",
        f"    標注圖: {ANNOTATED_DIR}/",
        f"    裁切圖: {CROPS_DIR}/",
    ]

    report = "\n".join(lines)
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report)

    print(report)
    print(f"\n✅ 報告 → {REPORT_FILE}")
    print(f"✅ 標注圖 → {ANNOTATED_DIR}/  ({len(images)} 張)")
    print(f"✅ 低信心裁切 → {CROPS_DIR}/  ({len(all_issues)} 個)")


if __name__ == '__main__':
    main()
