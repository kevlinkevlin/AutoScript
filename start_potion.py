import re
import cv2
import time
import keyboard
import easyocr
import pyautogui
import numpy as np
from maplestory_define import find_maplestory_window

def auto_use_potion(region):
    HP_RATIO = 0.1
    MP_RATIO = 0.8
    pill_timer = time.time()
    skill_timer = time.time()

    reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)
    print("Start detecting hp/mp")
    pill_start = time.time()
    skill_start = time.time()

    x, y, w, h = region
    ratio_x, ratio_y, ratio_w, ratio_h = 0.266, 0.934, 0.22, 0.029
    region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))

    # keypress_loop(keys=['d', 'f', 'g', 'h'])
    keypress_loop(keys=['c'])
    while True:
        # OCR 辨識
        result = cv_capture(region=region, reader=reader, result_name="health.png")

        for ind, (box, text, conf) in enumerate(result):
            # print(f"OCR：{text}（信心={conf:.2f}）")
            match = re.search(r'[\[\(]\s*(\d+)\s*/\s*(\d+)\s*[\]\)]', text)

            if match:
                left, total = match.groups()
                # left, total = match[0], match[1]
                # print(left, total)
                if total == 0:
                    break
                ratio = float(left) / float(total)
                if ind == 0:
                    # print(f"HP: {left}/{total} = {ratio}")
                    if ratio < HP_RATIO and float(total) < 28000.0 and float(total) > 50.0:
                        print("自動補HP")
                        keyboard.press_and_release('end')
                if ind == 1:
                    # print(f"MP: {left}/{total} = {ratio}")
                    if ratio < MP_RATIO and float(total) < 28000.0 and float(total) > 3000.0:
                        print("自動補MP")
                        keyboard.press_and_release('pagedown')
            else:
                print(f"OCR：{text}（信心={conf:.2f}）")
        # print("-----")
        time.sleep(0.3)

        end = time.time()
        # pill_timer = keypress_loop(keys=['d', 'f', 'g', 'h'], last_time=pill_timer,loop_time=540, first=False)
        skill_timer = keypress_loop(keys=['c'], last_time=skill_timer,loop_time=20, first=False)

def cv_capture(region, reader, result_name):
    screenshot = pyautogui.screenshot(region=region)

    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    # gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    resized = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

    _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)

    cv2.imwrite(result_name, binary)

    return reader.readtext(binary)

def keypress_loop(keys, last_time = 0, loop_time = 1, first = True):
    if first:
        for key in keys:
            # print(f"press key {key}")
            keyboard.press(key)
            time.sleep(0.1)
            keyboard.release(key)
            last_time = time.time()
    else:
        if (time.time() - last_time) > loop_time:
            for key in keys:
                # print(f"press key {key}")
                keyboard.press(key)
                time.sleep(0.1)
                keyboard.release(key)
            last_time = time.time()

    return last_time


if __name__ == '__main__':
    region = find_maplestory_window()
    auto_use_potion(region)