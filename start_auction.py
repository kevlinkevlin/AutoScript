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
stop_event = threading.Event()
original_pos = pyautogui.position()
SINGLE_MODE, TOTAL_MODE = "Single", "Total"
CLICK_SEARCH, CLICK_TOP_LEFT = "ClickSearch", "ClickTopLeft"

TARGET_PRICE = 4800000
MINIMUM_PRICE = 1
LOOP_DELAY = 45
NUMBER_IN_AUCTION = 7
MODE = TOTAL_MODE        # SINGLE_MODE: 單價， TOTAL_MODE: 總價
REFRESH_METHOD = CLICK_SEARCH  # CLICK_SEARCH: 點搜尋刷新， CLICK_TOP_LEFT: 點左上角刷新


def start_auction(game_region):
    global clicking, stop_event
    reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)
    print("開始搶購!!!!!!!!!!!")

    x, y, w, h = game_region

    if MODE == SINGLE_MODE:
        ratio_x, ratio_y, ratio_w, ratio_h = 0.68, 0.25, 0.11, 0.62
    else:
        ratio_x, ratio_y, ratio_w, ratio_h = 0.56, 0.25, 0.11, 0.62

    price_region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))

    while True:
        if not clicking:
            print("waiting...")
            time.sleep(1)
            continue

        pyautogui.moveTo(game_region[0] + 10, game_region[1] + 10)

        if REFRESH_METHOD == CLICK_TOP_LEFT:
            refresh_auction(game_region)
        elif REFRESH_METHOD == CLICK_SEARCH:
            refresh_auction_click_search(game_region)

        time.sleep(0.5)

        result = cv_capture(price_region, reader)

        if (len(result) // 2) != NUMBER_IN_AUCTION:
            print("找不到價錢，重新進入拍賣")
            target_x = game_region[0] + game_region[2] * 0.85
            target_y = game_region[1] + game_region[3] * 0.95
            start_click()
            pyautogui.click(target_x, target_y)
            time.sleep(2.0)
            keyboard.press_and_release('enter')
            resume_click()
            continue

        for ind, (box, text, conf) in enumerate(result):
            match = re.search(r'(\d{1,3}(?:,\d{3})+|\d+)', text)

            if match is None:
                print(f"re.search 結果錯誤 {match}")
                continue
            if ind % 2 == 0:
                value = int(match.group(1).replace(',', ''))
                index = ind // 2
                item_height = price_region[3] / 7
                target_x = price_region[0]
                target_y = price_region[1] + item_height * index + item_height / 2
                print(f"第 {index + 1}/{NUMBER_IN_AUCTION} 項價錢是 {value}")

                if value <= TARGET_PRICE:
                    shutil.copyfile("auction.png", f"./image/buy_target_{value}_{time.strftime('%Y-%m-%d_%H-%M-%S')}.png")

                    if value <= MINIMUM_PRICE:
                        print(f"低於保護價格 {MINIMUM_PRICE}，先不購買")
                        continue

                    start_click()
                    # pyautogui.doubleClick(target_x, target_y)
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


def toggle_clicking():
    global clicking, stop_event
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
    pyautogui.click(x + int(0.25 * w), y + int(0.68 * h))
    resume_click()


def start_click():
    global original_pos
    original_pos = pyautogui.position()


def resume_click():
    pyautogui.moveTo(original_pos)


def cv_capture(region, reader):
    screenshot = pyautogui.screenshot(region=region)
    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    resized = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)

    # cv2.imwrite("auction.png",binary)

    return reader.readtext(binary)


keyboard.add_hotkey('F8', toggle_clicking)
keyboard.add_hotkey('=', toggle_clicking)
print("✅ 請使用 F8 開/關自動點擊，ESC 離開")

if __name__ == '__main__':
    game_region = find_maplestory_window()
    threading.Thread(target=start_auction, args=(game_region,), daemon=True).start()
    keyboard.wait('esc')
