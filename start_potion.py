import re
import cv2
import time
import keyboard
import easyocr
import pyautogui
import numpy as np
from maplestory_define import find_maplestory_window

def auto_use_potion(region):
    HP_RATIO, MP_RATIO = 0.3, 0.4
    HP_KEY, MP_KEY = "pagedown", "pagedown"

    reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)
    print("Start detecting hp/mp")

    x, y, w, h = region
    ratio_x, ratio_y, ratio_w, ratio_h = 0.266, 0.934, 0.22, 0.029
    capture_region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))
    HP_count, MP_count = 0, 0

    while True:
        result = cv_capture(region=capture_region, reader=reader)

        for ind, (box, text, conf) in enumerate(result):
            match = re.search(r'[\[\(]\s*(\d+)\s*/\s*(\d+)\s*[\]\)]', text)

            if match:
                left, total = match.groups()
                if float(total) == 0:
                    break
                ratio = float(left) / float(total)
                if ind == 0:
                    if ratio < HP_RATIO and 50.0 < float(total) < 28000.0:
                        HP_count += 1
                        print(f"自動補HP, 已消耗 {HP_count} 個")
                        keyboard.press_and_release(HP_KEY)
                elif ind == 1:
                    if ratio < MP_RATIO and 40.0 < float(total) < 28000.0:
                        MP_count += 1
                        print(f"自動補MP, 已消耗 {MP_count} 個")
                        keyboard.press_and_release(MP_KEY)
            else:
                print(f"OCR：{text}（信心={conf:.2f}）")

        time.sleep(0.3)


def cv_capture(region, reader):
    screenshot = pyautogui.screenshot(region=region)
    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    resized = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)
    return reader.readtext(binary)


if __name__ == '__main__':
    region = find_maplestory_window()
    auto_use_potion(region)
