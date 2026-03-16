import re
import cv2
import time
import keyboard
import easyocr
import pyautogui
import numpy as np
from maplestory_define import find_maplestory_window
import threading
import shutil

clicking = False
stop_event = threading.Event()
original_pos = pyautogui.position()
TARGET_PRICE = 30099999
MINIMUM_PRICE = 500000
LOOP_DELAY = 5
NUMBER_IN_AUCTION = 7

def start_auction(game_region):
    global clicking, stop_event
    reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)
    print("開始搶購!!!!!!!!!!!")

    x, y, w, h = game_region
    # ratio_x, ratio_y, ratio_w, ratio_h = 0.36, 0.25, 0.55, 0.62
    # ratio_x, ratio_y, ratio_w, ratio_h = 0.68, 0.25, 0.11, 0.62
    ratio_x, ratio_y, ratio_w, ratio_h = 0.56, 0.25, 0.11, 0.62
    price_region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))

    while True:
        if not clicking:
            print("wating.....")
            time.sleep(1)
            continue

        refresh_auction(game_region)

        # OCR 辨識
        result = cv_capture(price_region, reader, "auction.png")

        if (len(result) // 2) != NUMBER_IN_AUCTION:
            print("找不到價錢，重新進入拍賣")
            target_x, target_y = game_region[0] + game_region[2] * 0.85, game_region[1] + game_region[3] * 0.95

            start_click()
            # 進入拍賣
            pyautogui.click(target_x, target_y)
            time.sleep(2.0)
            # 多點一次 enter 避免進入失敗
            keyboard.press_and_release('enter')
            resume_click()
            continue

        for ind, (box, text, conf) in enumerate(result):
            match = re.search(r'(\d{1,3}(?:,\d{3})+|\d+)', text)

            if match == None:
                print(f"re.search 結果錯誤 {match}")
                continue
            if (ind % 2 == 0):
                # print(f"OCR：{text}（信心={conf:.2f}）")
                value = int(match.group(1).replace(',', ''))
                index = ind // 2
                print(f"第 {index + 1}/{NUMBER_IN_AUCTION} 項價錢是 {value}")
                # 目標價
                if value <= TARGET_PRICE:
                    item_height = (price_region[3] / 7)
                    item_height_half = item_height / 2
                    target_x, target_y = price_region[0], price_region[1] + item_height * index + item_height_half
                    print(f"第 {index + 1}/{NUMBER_IN_AUCTION} 項價錢是 {value}")
                    shutil.copyfile("auction.png", f"buy_target_{time.time()}.png")

                    if(value <= MINIMUM_PRICE):
                        print(f"低於保護價格 {MINIMUM_PRICE}，先不購買")
                        continue
                    # 雙擊
                    start_click()
                    pyautogui.mouseDown(target_x, target_y)
                    pyautogui.mouseUp()
                    pyautogui.mouseDown(target_x, target_y)
                    pyautogui.mouseUp()
                    time.sleep(0.2)
                    # 點擊 max
                    # pyautogui.mouseDown(game_region[0] + game_region[2] * 0.46, game_region[1] + game_region[3] * 0.47 + item_height * index)
                    # pyautogui.mouseUp()
                    # 購買
                    keyboard.press_and_release('enter')
                    resume_click()
                    break

        print(f"暫停 {LOOP_DELAY} 秒")
        time.sleep(LOOP_DELAY)

def toggle_clicking():
    global clicking
    global stop_event
    clicking = not clicking

    if clicking:
        print("🟢 自動點擊開始")
        stop_event.clear()
    else:
        print("🔴 自動點擊停止")
        stop_event.set()

def refresh_auction(game_region):
    ratio_x, ratio_y = 0.2, 0.05
    x, y, w, h = game_region
    start_click()
    pyautogui.mouseDown(x + int(ratio_x * w), y + int(ratio_y * h))
    pyautogui.mouseUp()
    keyboard.press_and_release('enter')
    resume_click()
    time.sleep(1.0)

def start_click():
    global original_pos
    original_pos = pyautogui.position()

def resume_click():
    global original_pos
    pyautogui.moveTo(original_pos)

def cv_capture(region, reader, result_name):
    screenshot = pyautogui.screenshot(region=region)
    # screenshot = Image.open("image.png")

    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    # gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    resized = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)

    cv2.imwrite(result_name, binary)

    return reader.readtext(binary)

# 綁定熱鍵
keyboard.add_hotkey('F8', toggle_clicking)
keyboard.add_hotkey('=', toggle_clicking)
print("✅ 請使用 F8 開/關自動點擊，ESC 離開")

if __name__ == '__main__':
    game_region = find_maplestory_window()
    threading.Thread(target=start_auction(game_region), daemon=True).start()