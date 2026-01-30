import re
import cv2
import time
import keyboard
import easyocr
import pyautogui
import numpy as np
from maplestory_define import find_maplestory_window

def detect_hp(region):
    HP_RATIO = 0.01
    MP_RATIO = 0.8

    reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)
    print("Start detecting hp/mp")
    pill_start = time.time()
    skill_start = time.time()

    x, y, w, h = region
    ratio_x, ratio_y, ratio_w, ratio_h = 0.266, 0.932, 0.23, 0.03
    region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))

    keyboard.press('c')
    time.sleep(0.1)
    keyboard.release('c')
    keyboard.press_and_release('d')
    time.sleep(0.25)
    keyboard.press_and_release('f')
    time.sleep(0.25)
    # keyboard.press_and_release('g')
    # time.sleep(0.25)
    # keyboard.press_and_release('h')
    # time.sleep(0.25)

    while True:
        screenshot = pyautogui.screenshot(region=region)

        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

        # gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        resized = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

        _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)

        cv2.imwrite("health.png", binary)

        # OCR 辨識
        result = reader.readtext(binary)
        match_hp, match_mp = None, None
        for ind, (box, text, conf) in enumerate(result):
            # print(f"OCR：{ind} {text}（信心={conf:.2f}）")
            # match_hp = re.search(r"^1.*\[(\d+)/(\d+)\]", text)
            # match_mp = re.search(r"^7.*\[(\d+)/(\d+)\]", text)
            match = re.search(r'(\d+)\s*/\s*(\d+)', text)

            if match:
                left, total = match.groups()
                if float(total) == 0.0:
                    print("float(total) == 0.0 跳出迴圈")
                    break
                ratio = float(left) / float(total)

                if ind == 0:
                    print(f"HP: {left}/{total} = {ratio}")
                    if ratio < HP_RATIO and float(total) < 28000.0 and float(total) > 4000.0:
                        print("自動補HP")
                        keyboard.press_and_release('end')
                elif ind == 1:
                    print(f"MP: {left}/{total} = {ratio}")
                    if ratio < MP_RATIO and float(total) < 28000.0 and float(total) > 10000.0:
                        print("自動補MP")
                        keyboard.press_and_release('pagedown')

            # if not match_hp and not match_mp:
            if not match:
                print(f"OCR：{text}（信心={conf:.2f}）")
        # print("-----")
        time.sleep(0.25)

        end = time.time()
        time_pass = end - pill_start
        if time_pass > 540:
            print("使用藥丸")
            keyboard.press_and_release('d')
            time.sleep(0.25)
            keyboard.press_and_release('f')
            time.sleep(0.25)
            # keyboard.press_and_release('g')
            # time.sleep(0.25)
            # keyboard.press_and_release('h')
            # time.sleep(0.25)
            pill_start = end

        time_pass = end - skill_start
        if time_pass > 20:
            print("召喚冰魔")
            keyboard.press('c')
            time.sleep(0.1)
            keyboard.release('c')
            skill_start = end

if __name__ == '__main__':
    region = find_maplestory_window()
    detect_hp(region)