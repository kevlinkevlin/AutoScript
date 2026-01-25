import re
import cv2
import time
import keyboard
import easyocr
import pyautogui
import numpy as np
from maplestory_define import find_maplestory_window

def detect_hp(region):
    HP_RATIO = 0.5
    MP_RATIO = 0.05

    reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)
    print("Start detecting hp/mp")
    start = time.time()

    x, y, w, h = region
    ratio_x, ratio_y, ratio_w, ratio_h = 0.266, 0.935, 0.21, 0.028
    region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))

    keyboard.press_and_release('d')
    time.sleep(0.25)
    keyboard.press_and_release('f')
    time.sleep(0.25)
    keyboard.press_and_release('g')
    time.sleep(0.25)
    keyboard.press_and_release('h')
    time.sleep(0.25)

    while True:
        screenshot = pyautogui.screenshot(region=region)

        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

        # gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        resized = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

        _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)

        cv2.imwrite("health.png", binary)

        # OCR 辨識
        result = reader.readtext(binary)
        for _, text, conf in result:
            # print(f"OCR：{text}（信心={conf:.2f}）")
            match_hp = re.search(r"^1.*\[(\d+)/(\d+)\]", text)
            match_mp = re.search(r"^7.*\[(\d+)/(\d+)\]", text)

            if match_hp:
                left, total = match_hp.groups()
                ratio = float(left) / float(total)
                # print(f"HP: {left}/{total} = {ratio}")
                if ratio < HP_RATIO and float(total) < 28000.0 and float(total) > 4000.0:
                    print("自動補HP")

                    keyboard.press_and_release('end')

            if match_mp:
                left, total = match_mp.groups()
                ratio = float(left) / float(total)
                # print()
                if ratio < MP_RATIO and float(total) < 28000.0 and float(total) > 500.0:
                    print("自動補MP")
                    keyboard.press_and_release('pagedown')
            if not match_hp and not match_mp:
                print(f"OCR：{text}（信心={conf:.2f}）")
        # print("-----")
        time.sleep(0.5)

        end = time.time()
        time_pass = end - start
        if time_pass > 540:
            print("使用藥丸")
            keyboard.press_and_release('d')
            time.sleep(0.25)
            keyboard.press_and_release('f')
            time.sleep(0.25)
            keyboard.press_and_release('g')
            time.sleep(0.25)
            keyboard.press_and_release('h')
            time.sleep(0.25)
            start = end

if __name__ == '__main__':
    region = find_maplestory_window()
    detect_hp(region)