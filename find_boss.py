import cv2
import time
import easyocr
import pyautogui
import numpy as np
from difflib import SequenceMatcher
from maplestory_define import find_maplestory_window

# 初始化 EasyOCR（繁體中文 + 英文）
reader = easyocr.Reader(['ch_tra', 'en'], gpu=True)

# 相似度比對
def similar(a, b):
    return SequenceMatcher(None, a, b).ratio()

def detect_boss(region, detect_time=5):
    print("Start detecting Boss")
    start = time.time()

    # expected = "踩著滑雪板的歡樂雪毛怪人出現了。"
    # keywords = ["雪毛怪", "滑雪板", "歡樂", "出現"]
    # expected = "隨著周圍突然安靜，仙人人偶出現了。"
    # keywords = ["周圍", "安靜", "仙人", "人偶", "出現"]
    expected = "伴隨著冤魂的哭聲，書生幽靈出現了。"
    keywords = ["伴隨", "冤魂", "哭聲", "書生幽靈", "出現"]

    x, y, w, h = region
    ratio_x, ratio_y, ratio_w, ratio_h = 0.35, 0.23, 0.28, 0.05
    region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))

    while True:
        screenshot = pyautogui.screenshot(region=region)

        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        resized = cv2.resize(gray, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

        _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)

        cv2.imwrite("boss_text.png", binary)

        # OCR 辨識
        result = reader.readtext(binary)

        for _, text, conf in result:
            print(f"OCR：{text}（信心={conf:.2f}）")

            matched = sum(kw in text for kw in keywords)

            sim = similar(text, expected)

            if matched > 0 or sim > 0.7:
                print("偵測到雪毛怪出現事件！")
                return True

        end = time.time()
        time_pass = end - start
        # print(f"時間經過 {time_pass} s")
        if time_pass > detect_time:
            return False

def detect_confirm(region, detect_time=5):
    print("Start detecting confirm")
    start = time.time()

    expected = "登入"
    keywords = ["登入", "登", "入"]
    x, y, w, h = region
    ratio_x, ratio_y, ratio_w, ratio_h = 0.64, 0.47, 0.08, 0.08
    region = (x + int(ratio_x * w), y + int(ratio_y * h), int(ratio_w * w), int(ratio_h * h))

    while True:
        screenshot = pyautogui.screenshot(region=region)

        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

        # gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

        resized = cv2.resize(img, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)

        _, binary = cv2.threshold(resized, 150, 255, cv2.THRESH_BINARY)

        cv2.imwrite("confirm_btn.png", binary)

        # OCR 辨識
        result = reader.readtext(binary)

        for _, text, conf in result:
            print(f"OCR：{text}（信心={conf:.2f}）")

            matched = sum(kw in text for kw in keywords)

            sim = similar(text, expected)

            if matched > 0 or sim > 0.7:
                print("偵測到登入按鈕!")
                return True

        end = time.time()
        time_pass = end - start
        # print(f"時間經過 {time_pass} s")
        if time_pass > detect_time:
            print("未偵測到登入按鈕!")
            return False




if __name__ == '__main__':
    region = find_maplestory_window()
    # detect_confirm(region, 10)
    detect_hp(region)
