import re
import cv2
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))

import keyboard
import pytesseract
import pyautogui
import numpy as np
import shutil
import threading
from maplestory_define import find_maplestory_window

clicking = False
clicking_lock = threading.Lock()
stop_event = threading.Event()
original_pos = pyautogui.position()
SINGLE_MODE, TOTAL_MODE = "Single", "Total"
CLICK_SEARCH, CLICK_TOP_LEFT = "ClickSearch", "ClickTopLeft"
LOG_FILE = "logs/ocr_log.txt"
os.makedirs("logs", exist_ok=True)

TESS_CONFIG = '--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789,'
TESS_ROW_CONFIG = '--psm 7 --oem 3 -c tessedit_char_whitelist=0123456789,'
for _p in [r'C:\Program Files\Tesseract-OCR\tesseract.exe',
           r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe']:
    if os.path.exists(_p):
        pytesseract.pytesseract.tesseract_cmd = _p
        break

TARGET_PRICE = 4500000
MINIMUM_PRICE = 500
LOOP_DELAY = 40
NUMBER_IN_AUCTION = 7
MIN_CONFIDENCE = 0.8  # 0.75→0.70：10,000,000 等整數價格穩定讀在 0.73~0.74，原門檻錯誤排除
MODE, REFRESH_METHOD = TOTAL_MODE, CLICK_TOP_LEFT # SINGLE_MODE: 單價， TOTAL_MODE: 總價
                                                # CLICK_SEARCH: 點搜尋刷新， CLICK_TOP_LEFT: 點左上角刷新
# MODE, REFRESH_METHOD = SINGLE_MODE, CLICK_TOP_LEFT

def start_auction(game_region):
    print("開始搶購!!!!!!!!!!!")

    x, y, w, h = game_region

    if MODE == SINGLE_MODE:
        ratio_x, ratio_y, ratio_w, ratio_h = 0.68, 0.25, 0.11, 0.62
    else:
        ratio_x, ratio_y, ratio_w, ratio_h = 0.56, 0.25, 0.11, 0.62

    price_region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))

    while True:
        with clicking_lock:
            is_clicking = clicking
        if not is_clicking:
            time.sleep(1)
            continue

        if REFRESH_METHOD == CLICK_TOP_LEFT:
            refresh_auction(game_region)
        elif REFRESH_METHOD == CLICK_SEARCH:
            refresh_auction_click_search(game_region)

        # 移到頂部 UI 區（搜尋欄附近），避免 hover 在物品列上觸發 tooltip 遮擋截圖
        pyautogui.moveTo(game_region[0] + int(game_region[2] * 0.5), game_region[1] + int(game_region[3] * 0.05))
        time.sleep(1.0)

        result = cv_capture(price_region, save_debug_image=True)
        check_time = time.time()
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        price_results = filter_price_results(result)

        if len(price_results) != NUMBER_IN_AUCTION:
            print("OCR 結果不完整，重新 OCR--------------")
            shutil.copyfile(
                    "auction.png", f"./ocr_debug_image/{time.strftime('%Y-%m-%d_%H-%M-%S')}.png")

        while time.time() - check_time < 10.0 and len(price_results) != NUMBER_IN_AUCTION:
            result = cv_capture(price_region)
            price_results = filter_price_results(result)

        if len(price_results) < NUMBER_IN_AUCTION:
            print("找不到價錢，重新進入拍賣")
            target_x = game_region[0] + game_region[2] * 0.85
            target_y = game_region[1] + game_region[3] * 0.95
            start_click()
            pyautogui.click(target_x, target_y)
            time.sleep(2.0)
            keyboard.press_and_release('enter')
            resume_click()
            continue

        for index, (box, text, conf) in enumerate(price_results):
            match = re.search(r'(\d{1,3}(?:,\d{3})+|\d+)', text)
            if match is None:
                print(f"re.search 結果錯誤: {text!r}")
                continue

            # 防呆：match 前方緊鄰逗號，代表 OCR 漏掉開頭數字（截斷）
            if match.start() > 0 and text[match.start() - 1] == ',':
                print(f"[防呆] 數字前出現逗號，OCR 截斷，跳過: {text!r}")
                continue

            value = int(match.group(1).replace(',', ''))
            target_x = price_region[0]
            # 用 bbox 中心反推螢幕 Y（補償 cv_capture 中的 padding 8px 和 4x 放大）
            center_y_in_ocr = (box[0][1] + box[2][1]) / 2
            target_y = price_region[1] + center_y_in_ocr / 4 - 8
            # print(f"第 {index + 1}/{NUMBER_IN_AUCTION} 項價錢是 {value}")

            if value <= TARGET_PRICE:
                if value < MINIMUM_PRICE:
                    print(f"低於保護價格 {MINIMUM_PRICE}，先不購買")
                    continue

                shutil.copyfile(
                    "auction.png", f"./image/{time.strftime('%Y-%m-%d_%H-%M-%S')}_buy_target_{value}.png")

                start_click()
                pyautogui.mouseDown(target_x, target_y)
                pyautogui.mouseUp()
                pyautogui.mouseDown(target_x, target_y)
                pyautogui.mouseUp()
                time.sleep(0.2)

                if MODE == SINGLE_MODE:
                    pyautogui.click(game_region[0] + game_region[2] * 0.46, game_region[1] + game_region[3] * 0.47)

                keyboard.press_and_release('enter')
                resume_click()
                break

        print(f"暫停 {LOOP_DELAY} 秒")
        time.sleep(LOOP_DELAY)


def _parse_wan_tokens(wan_items):
    """
    從萬/億行的數字 token 重建完整價格。
    Tesseract digit-whitelist 後中文字被丟棄，只剩數字 token：
      (799萬 9,999) → ["799", "9,999"] → 7,999,999
      (830萬)       → ["830"]          → 8,300,000
      (1億 2,345萬) → ["1", "2,345"]   → 123,450,000
      (PSM 7 整行) → ["7987777"]       → 7,987,777
    """
    nums = []
    for _, text, _ in sorted(wan_items, key=lambda r: r[0][0][0]):
        m = re.search(r'(\d{1,3}(?:,\d{3})+|\d+)', text)
        if m:
            nums.append(int(m.group(1).replace(',', '')))
    if not nums:
        return None
    # PSM 7 行掃描可能把「798萬 7,777」整合成 7987777，或帶尾部 artifact
    # 第一個 token >= 10萬 代表已是完整數字，後面的 token 是重複掃描產生的 artifact
    if nums[0] >= 100_000:
        return nums[0]
    if len(nums) >= 3 and nums[0] <= 9 and nums[1] < 10000 and nums[2] < 10000:
        return nums[0] * 100_000_000 + nums[1] * 10_000 + nums[2]
    if len(nums) >= 2 and nums[1] < 10000:
        return nums[0] * 10_000 + nums[1]
    return nums[0] * 10_000


def filter_price_results(result):
    """
    從 OCR 結果取出純價格行，依 Y 座標由上到下排序。
    每個 slot = 一個拍賣項目（price 行 + 萬/億行）。
    萬/億行的數字 token 會與 price 行交叉校驗，修正 "7"→"1" 等誤判。
    """
    if not result:
        return []

    INTRA_GAP = 200  # 4x 放大圖中，同 slot 內 price→萬行約 100~160px

    def _is_valid(text, conf):
        if conf < MIN_CONFIDENCE:
            return False
        if '萬' in text or '(' in text or ')' in text:
            return False
        if re.search(r'[一-鿿㐀-䶿豈-﫿]', text):
            return False
        if re.match(r'^\s*,', text) or re.search(r',\s*$', text):
            return False
        m = re.search(r'(\d{1,3}(?:,\d{3})+|\d+)', text)
        if not m:
            return False
        if m.start() > 0 and text[m.start() - 1] == ',':
            return False
        val = int(m.group(1).replace(',', ''))
        if val < MINIMUM_PRICE:
            return False
        if ',' not in m.group(1) and val >= 10000:
            return False
        return True

    sorted_result = sorted(result, key=lambda r: (r[0][0][1] + r[0][2][1]) / 2)

    # 用每個 slot 第一個 item 的 y 做基準，避免 prev_cy 累進導致萬行跟下一個 price 行合并
    slots, cur = [], [sorted_result[0]]
    slot_first_cy = (sorted_result[0][0][0][1] + sorted_result[0][0][2][1]) / 2
    for item in sorted_result[1:]:
        cy = (item[0][0][1] + item[0][2][1]) / 2
        if cy - slot_first_cy < INTRA_GAP:
            cur.append(item)
        else:
            slots.append(cur)
            cur = [item]
            slot_first_cy = cy
    slots.append(cur)

    price_results = []
    for slot in slots:
        price_item = min(slot, key=lambda r: r[0][0][1])
        price_y = price_item[0][0][1]
        wan_items = [r for r in slot if r[0][0][1] > price_y + 50]

        box, text, conf = price_item

        wan_val = _parse_wan_tokens(wan_items)

        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            if wan_val is None:
                wan_debug = ', '.join(f"{t!r}({c:.2f})" for _, t, c in wan_items) if wan_items else "empty"
                f.write(f"{text}\t{conf:.4f}\twan_val=None\twan_items=[{wan_debug}]\n")
                print(f"[萬行None] {text!r} (conf={conf:.4f}) wan_items=[{wan_debug}]")
            else:
                f.write(f"{text}\t{conf:.4f}\twan_val={wan_val}\n")

        if not _is_valid(text, conf):
            if conf < MIN_CONFIDENCE:
                print(f"OCR 信心度過低，排除: {text!r} (conf={conf:.4f})")
            continue

        # 萬/億行校正：交叉驗證 price 行，修正字型導致的誤判（如 7→1）
        # 若 wan_val 與 price_val 差超過 10 倍，代表「萬」字被誤讀為數字（如 38），跳過校正
        if wan_val and wan_val >= MINIMUM_PRICE:
            m = re.search(r'(\d{1,3}(?:,\d{3})+|\d+)', text)
            if m:
                price_val = int(m.group(1).replace(',', ''))
                ratio = wan_val / price_val if price_val > 0 else float('inf')
                if ratio > 10 or ratio < 0.1:
                    print(f"[萬行校正跳過] wan_val={wan_val:,} 與 price_val={price_val:,} 量級差異過大，信任 price 行")
                elif abs(price_val - wan_val) / wan_val > 0.05:
                    print(f"[萬行校正] {price_val:,} → {wan_val:,}")
                    text = f"{wan_val:,}"

        price_results.append((box, text, conf))

    price_results.sort(key=lambda r: r[0][0][1])
    return price_results


def toggle_clicking():
    global clicking
    with clicking_lock:
        clicking = not clicking

    if clicking:
        print("🟢 自動點擊開始")
        stop_event.clear()
    else:
        print("🔴 自動點擊停止")
        stop_event.set()


def refresh_auction(game_region):
    x, y, w, h = game_region
    start_click()
    pyautogui.click(x + int(0.2 * w), y + int(0.05 * h))
    keyboard.press_and_release('enter')
    resume_click()


def refresh_auction_click_search(game_region):
    x, y, w, h = game_region
    start_click()
    pyautogui.click(x + int(0.25 * w), y + int(0.8 * h))
    resume_click()


def start_click():
    global original_pos
    original_pos = pyautogui.position()


def resume_click():
    pyautogui.moveTo(original_pos)


def cv_capture(region, save_debug_image=False):
    screenshot = pyautogui.screenshot(region=region)
    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)

    # 左側 50px 白色 padding，避免最左位數字被截斷
    padded = cv2.copyMakeBorder(img, 8, 8, 50, 10, cv2.BORDER_CONSTANT, value=255)

    # 4x 放大
    resized = cv2.resize(padded, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

    # CLAHE 局部對比增強（比全局 Otsu 更能保留小逗號）
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(resized)

    # Otsu 二值化
    _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 確保黑字白底（背景亮度 > 128 代表正確；否則翻轉）
    if np.mean(binary) < 128:
        binary = cv2.bitwise_not(binary)

    # 白化遊戲 UI 左側黑色邊框：從白色 padding 右邊開始往右掃，遇到整欄偏黑就填白
    _left_pad = 50 * 4  # 50px padding × 4x = 200px
    _ci = _left_pad
    while _ci < min(_left_pad + 400, binary.shape[1]) and np.mean(binary[:, _ci]) < 128:
        binary[:, _ci] = 255
        _ci += 1

    # 白化遊戲 UI 右側黑色邊框：從右 padding 左邊往左掃
    _right_pad = 10 * 4  # 10px padding × 4x = 40px
    _ci = binary.shape[1] - _right_pad - 1
    while _ci >= 0 and np.mean(binary[:, _ci]) < 128:
        binary[:, _ci] = 255
        _ci -= 1

    if save_debug_image:
        cv2.imwrite("auction.png", binary)

    data = pytesseract.image_to_data(
        binary, config=TESS_CONFIG, output_type=pytesseract.Output.DICT
    )
    results = []
    img_h = binary.shape[0]
    for i in range(len(data['text'])):
        if data['level'][i] != 5:  # 只取 word 層
            continue
        text = data['text'][i].strip()
        conf_raw = int(data['conf'][i])
        if not text or conf_raw < 0:
            continue
        conf = conf_raw / 100.0
        x, y, w, h = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
        # 全行重新 OCR（PSM 7 單行模式）：邊框已白化，從 x 往左 50px 取完整數字
        if conf_raw > 0:
            row = binary[max(0, y - 10):min(img_h, y + h + 10), max(0, x - 50):]
            row_text = pytesseract.image_to_string(row, config=TESS_ROW_CONFIG).strip()
            if row_text:
                text = row_text
        box = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
        results.append((box, text, conf))
    return results


keyboard.add_hotkey('F8', toggle_clicking)
keyboard.add_hotkey('=', toggle_clicking)
print("✅ 請使用 F8 開/關自動點擊，ESC 離開")

if __name__ == '__main__':
    game_region = find_maplestory_window()
    threading.Thread(target=start_auction, args=(game_region,), daemon=True).start()
    keyboard.wait('esc')
