import pyautogui
import keyboard
import threading
import time
from maplestory_define import find_TFT_window

relative_pos = [
    [0.4078, 0.9486, 1, "尋找對戰"],
    [0.4977, 0.7681, 10, "接受"],
    [0.5043, 0.5413, 5, "離開遊戲"],
    [0.4047, 0.9514, 1, "再來一場"]
]
clicking = False
stop_event = threading.Event()

def check_pos():
    target_region = find_TFT_window("League of Legends (TM) Client")
    region_x, region_y, region_width, region_height = target_region

    while True:
        x, y = pyautogui.position()
        screen_width, screen_height = pyautogui.size()
        print(f"實際座標: ({x}, {y})")
        print(f"比例位置: ({x/screen_width:.4f}, {y/screen_height:.4f})")
        print(f"目標畫面比例位置: ({(x - region_x)/region_width:.4f}, {(y - region_y)/region_height:.4f})")
        stop_event.wait(timeout=2)

def click_loop():
    global clicking, stop_event

    target_region = find_TFT_window()
    region_x, region_y, region_width, region_height = target_region

    while True:
        if not clicking:
            print("waiting...")
            time.sleep(1)
            continue

        for relative_x, relative_y, interval, move in relative_pos:
            print(move)
            actual_x = region_x + int(region_width * relative_x)
            actual_y = region_y + int(region_height * relative_y)
            original_pos = pyautogui.position()

            pyautogui.mouseDown(actual_x, actual_y)
            pyautogui.sleep(0.1)
            pyautogui.mouseUp(actual_x, actual_y)
            pyautogui.moveTo(original_pos)

            if move in ["接受"]:
                stop_event.wait(timeout=interval)
                game_region = find_TFT_window("League of Legends (TM) Client")
                if game_region is None:
                    break
                region_x, region_y, region_width, region_height = game_region
            elif move in ["離開遊戲"]:
                stop_event.wait(timeout=interval)
                region_x, region_y, region_width, region_height = target_region
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
