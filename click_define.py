import time
import pyautogui
import threading
from find_boss import find_maplestory_window, detect_boss, detect_confirm

change_channel_path = [
    [0.88, 0.97, 0.3, "點目錄"],
    [0.88, 0.88, 1, "點頻道"],
    [0.6823, 0.1815, 3, "點隨機切頻道"],
    [0.4667, 0.5444, 20, "確認"],
    [0.6771, 0.5093, 2.5, "登入"],
    [0.6719, 0.3435, 1, "選擇角色"]
    ]

night_market_boss_path = [
    [0.3417, 0.6722, 0.3, "點阿勇伯"],
    [0.6906, 0.6463, 0.3, "點是"]
]

clicking = False
stop_event = threading.Event()
start = time.time()

def toggle_clicking():
    global clicking
    global stop_event
    global start
    clicking = not clicking

    if clicking:
        print("🟢 點擊開始")
        print(f"閒置 {time.time() - start} 秒")
        stop_event.clear()
    else:
        print("🔴 點擊停止")
        print(f"經過 {time.time() - start} 秒")
        stop_event.set()

    start = time.time()

def click_loop():
    global clicking, stop_event

    region = find_maplestory_window()
    while True:
        if not clicking:
            print("wating.....")
            time.sleep(1)
            continue

        offset_x, offset_y = region[0], region[1]
        screen_width, screen_height = region[2], region[3]
        for relative_x, relative_y, interval, move in night_market_boss_path:
            print(move)
            actual_x = int(screen_width * relative_x)
            actual_y = int(screen_height * relative_y)
            original_pos = pyautogui.position()
            pyautogui.click(offset_x + actual_x, offset_y + actual_y)
            pyautogui.moveTo(original_pos)

            if move in ["選擇角色"]:
                if detect_boss(region, detect_time=7):
                    print("Boss is found!!!!")
                    toggle_clicking()
            elif move in ["確認"]:
                stop_event.wait(timeout=interval)
                if detect_confirm(region, detect_time=10):
                    print("Confirm button is found!")
                    stop_event.wait(timeout=3)
            else:
                stop_event.wait(timeout=interval)

            if stop_event.is_set():
                break

def check_pos():
    global clicking, stop_event

    while True:
        if not clicking:
            time.sleep(1)
            continue
        x, y = pyautogui.position()
        screen_width, screen_height = pyautogui.size()
        print(f"實際座標: ({x}, {y})")
        print(f"比例位置: ({x/screen_width:.4f}, {y/screen_height:.4f})")
        stop_event.wait(timeout=1)