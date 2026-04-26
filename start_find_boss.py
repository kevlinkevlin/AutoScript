import pyautogui
import keyboard
import threading
import time
from find_boss import detect_boss, detect_confirm
from maplestory_define import find_maplestory_window

relative_pos = [
    [0.88, 0.97, 0.3, "點目錄"],
    [0.88, 0.88, 1, "點頻道"],
    [0.6823, 0.1815, 3, "點隨機切頻道"],
    [0.4667, 0.5444, 20, "確認"],
    [0.6771, 0.5093, 2.5, "登入"],
    [0.6, 0.43, 1, "選擇角色"]
]
clicking = False
stop_event = threading.Event()

def check_pos():
    while True:
        x, y = pyautogui.position()
        screen_width, screen_height = pyautogui.size()
        print(f"實際座標: ({x}, {y})")
        print(f"比例位置: ({x/screen_width:.4f}, {y/screen_height:.4f})")
        stop_event.wait(timeout=1)

def click_loop():
    global clicking, stop_event

    while True:
        if not clicking:
            print("waiting...")
            time.sleep(1)
            continue

        region = find_maplestory_window()
        if region is None:
            print("⚠️ 找不到遊戲視窗，等待重試...")
            time.sleep(2)
            continue

        offset_x, offset_y = region[0], region[1]
        screen_width, screen_height = region[2], region[3]
        for relative_x, relative_y, interval, move in relative_pos:
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

def toggle_clicking():
    global clicking, stop_event, start
    clicking = not clicking

    if clicking:
        print("🟢 自動點擊開始")
        print(f"閒置了 {time.time() - start:.1f} 秒")
        stop_event.clear()
    else:
        print("🔴 自動點擊停止")
        print(f"執行了 {time.time() - start:.1f} 秒")
        stop_event.set()

    start = time.time()

keyboard.add_hotkey('F8', toggle_clicking)
keyboard.add_hotkey('=', toggle_clicking)
print("✅ 請使用 F8 開/關自動點擊，ESC 離開")

start = time.time()
threading.Thread(target=click_loop, daemon=True).start()

keyboard.wait('esc')
