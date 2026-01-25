import pyautogui
import keyboard
import threading
import time
import find_boss
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
    global clicking, stop_event

    while True:
        x, y = pyautogui.position()
        screen_width, screen_height = pyautogui.size()
        print(f"實際座標: ({x}, {y})")
        print(f"比例位置: ({x/screen_width:.4f}, {y/screen_height:.4f})")
        stop_event.wait(timeout=1)

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
        for relative_x, relative_y, interval, move in relative_pos:
            print(move)
            actual_x = int(screen_width * relative_x)
            actual_y = int(screen_height * relative_y)
            original_pos = pyautogui.position()
            pyautogui.click(offset_x + actual_x, offset_y + actual_y)
            pyautogui.moveTo(original_pos)

            if move in ["選擇角色"]:
                if find_boss.detect_boss(region, detect_time=7):
                    print("Boss is found!!!!")
                    toggle_clicking()
            elif move in ["確認"]:
                stop_event.wait(timeout=interval)
                if find_boss.detect_confirm(region, detect_time=10):
                    print("Confirm button is found!")
                    stop_event.wait(timeout=3)
            else:
                stop_event.wait(timeout=interval)

            if stop_event.is_set():
                break
        # break
    # toggle_clicking()

def toggle_clicking():
    global clicking
    global stop_event
    global start
    clicking = not clicking

    if clicking:
        print("🟢 自動點擊開始")
        print(f"打王打了{time.time() - start}秒")
        stop_event.clear()
    else:
        print("🔴 自動點擊停止")
        print(f"找王找了{time.time() - start}秒")
        stop_event.set()

    start = time.time()

# 綁定熱鍵
keyboard.add_hotkey('F8', toggle_clicking)
keyboard.add_hotkey('=', toggle_clicking)
print("✅ 請使用 F8 開/關自動點擊，ESC 離開")

start = time.time()
threading.Thread(target=click_loop, daemon=True).start()
# threading.Thread(target=check_pos, daemon=True).start()

# 偵測 ESC 離開
keyboard.wait('esc')
