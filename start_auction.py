import re
import cv2
import time

import keyboard
import easyocr
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

TARGET_PRICE = 4500000
MINIMUM_PRICE = 500
LOOP_DELAY = 45
NUMBER_IN_AUCTION = 7
MIN_CONFIDENCE = 0.8
MODE, REFRESH_METHOD = TOTAL_MODE, CLICK_SEARCH # SINGLE_MODE: 單價， TOTAL_MODE: 總價
                                                # CLICK_SEARCH: 點搜尋刷新， CLICK_TOP_LEFT: 點左上角刷新
# MODE, REFRESH_METHOD = SINGLE_MODE, CLICK_TOP_LEFT

def start_auction(game_region):
    reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)
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

        pyautogui.moveTo(game_region[0] + game_region[2] // 3, game_region[1] + game_region[3] * 0.3)

        if REFRESH_METHOD == CLICK_TOP_LEFT:
            refresh_auction(game_region)
        elif REFRESH_METHOD == CLICK_SEARCH:
            refresh_auction_click_search(game_region)

        time.sleep(0.6)

        result = cv_capture(price_region, reader, save_debug_image=True)
        check_time = time.time()
        price_results = filter_price_results(result)

        while time.time() - check_time < 10.0 and len(price_results) != NUMBER_IN_AUCTION:
            print("OCR 結果不完整，重新 OCR")
            result = cv_capture(price_region, reader)
            price_results = filter_price_results(result)

        if len(price_results) != NUMBER_IN_AUCTION:
            print("找不到價錢，重新進入拍賣")
            target_x = game_region[0] + game_region[2] * 0.85
            target_y = game_region[1] + game_region[3] * 0.95
            start_click()
            pyautogui.click(target_x, target_y)
            time.sleep(2.0)
            keyboard.press_and_release('enter')
            resume_click()
            continue

        item_height = price_region[3] / NUMBER_IN_AUCTION

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
            target_y = price_region[1] + item_height * index + item_height / 2
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


def filter_price_results(result):
    """過濾掉萬行與低信心度，只保留純價格行，並依 Y 座標由上到下排序"""
    price_results = []
    for box, text, conf in result:
        # print(text, conf)
        if conf < MIN_CONFIDENCE:
            continue
        if '萬' in text or '(' in text or ')' in text:
            continue
        if re.search(r'[一-鿿㐀-䶿豈-﫿]', text):
            print(f"[跳過] 含中文字，排除: {text!r}")
            continue
        # 防呆：開頭出現逗號代表 OCR 截斷了前置數字（例如 ,444,444 → 實為 1,444,444）
        if re.match(r'^\s*,', text):
            print(f"[防呆] 截斷結果（開頭逗號），排除: {text!r}")
            continue
        # print(text, conf)
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


def cv_capture(region, reader, save_debug_image=False):
    screenshot = pyautogui.screenshot(region=region)
    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)

    # 左右加 padding，避免首位數字被截掉（,444,444 問題的根源）
    padded = cv2.copyMakeBorder(img, 8, 8, 30, 10, cv2.BORDER_CONSTANT, value=255)

    # 4x 放大，比 3x 更利於小字辨識
    resized = cv2.resize(padded, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)

    # 銳化，強化數字邊緣
    kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
    sharpened = cv2.filter2D(resized, -1, kernel)

    # Otsu 自適應門檻，比固定 150 更能應對亮度變化
    _, binary = cv2.threshold(sharpened, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 膨脹補粗細筆劃（如 "1"），避免二值化後斷裂導致信心偏低
    kernel_dilate = np.ones((2, 2), np.uint8)
    binary = cv2.dilate(binary, kernel_dilate, iterations=1)

    if save_debug_image:
        cv2.imwrite("auction.png", binary)

    # allowlist 限定只辨識數字與逗號，大幅降低誤讀率
    return reader.readtext(binary, allowlist='0123456789,')


keyboard.add_hotkey('F8', toggle_clicking)
keyboard.add_hotkey('=', toggle_clicking)
print("✅ 請使用 F8 開/關自動點擊，ESC 離開")

if __name__ == '__main__':
    game_region = find_maplestory_window()
    threading.Thread(target=start_auction, args=(game_region,), daemon=True).start()
    keyboard.wait('esc')
