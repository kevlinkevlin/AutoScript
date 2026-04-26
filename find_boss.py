import cv2
import time
import easyocr
import pyautogui
import numpy as np
from difflib import SequenceMatcher
from maplestory_define import find_maplestory_window

reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)

def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def _capture_and_ocr(window_region, ratio_bounds):
    x, y, w, h = window_region
    rx, ry, rw, rh = ratio_bounds
    capture_region = (x + int(rx * w), y + int(ry * h), int(rw * w), int(rh * h))

    screenshot = pyautogui.screenshot(region=capture_region)
    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
    resized = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)
    return reader.readtext(binary)

def detect_boss(region, detect_time=5):
    print("Start detecting Boss")
    start = time.time()
    expected = "伴隨著冤魂的哭聲，書生幽靈出現了。"
    keywords = ["伴隨", "冤魂", "哭聲", "書生幽靈", "出現"]
    ratio_bounds = (0.35, 0.23, 0.28, 0.05)

    while time.time() - start < detect_time:
        for _, text, conf in _capture_and_ocr(region, ratio_bounds):
            print(f"OCR：{text}（信心={conf:.2f}）")
            if sum(kw in text for kw in keywords) > 0 or similar(text, expected) > 0.7:
                print("偵測到書生幽靈出現事件！")
                return True
    return False

def detect_confirm(region, detect_time=5):
    print("Start detecting confirm")
    start = time.time()
    expected = "登入"
    keywords = ["登入", "登", "入"]
    ratio_bounds = (0.64, 0.47, 0.08, 0.08)

    while time.time() - start < detect_time:
        for _, text, conf in _capture_and_ocr(region, ratio_bounds):
            print(f"OCR：{text}（信心={conf:.2f}）")
            if sum(kw in text for kw in keywords) > 0 or similar(text, expected) > 0.7:
                print("偵測到登入按鈕!")
                return True
    print("未偵測到登入按鈕!")
    return False


if __name__ == '__main__':
    region = find_maplestory_window()
    detect_confirm(region, 10)
