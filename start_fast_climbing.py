import pygame
import keyboard
import threading
import time

# 初始化 pygame 的 joystick 模組
pygame.init()
pygame.joystick.init()

def press_left_right():
    keyboard.press_and_release('left')
    time.sleep(0.03)
    # keyboard.press_and_release('right')
    # time.sleep(0.03)

# def toggle():
#     global running, thread
#     running = not running
#     if running:
#         print("開始循環按左右鍵。")
#         thread = threading.Thread(target=press_left_right)
#         thread.start()
#     else:
#         print("停止循環。")

# 偵測是否有手把
if pygame.joystick.get_count() == 0:
    print("沒有偵測到手把")
    exit()

# 取得第一個手把
joystick = pygame.joystick.Joystick(0)
joystick.init()
print(f"偵測到手把：{joystick.get_name()}")

# 主迴圈
try:
    while True:
        pygame.event.pump()
        for event in pygame.event.get():
            if event.type == pygame.JOYBUTTONDOWN:
                print(f"按下按鈕 {event.button}")
            elif event.type == pygame.JOYBUTTONUP:
                print(f"放開按鈕 {event.button}")
            elif event.type == pygame.JOYAXISMOTION:
                print(f"搖桿移動 軸: {event.axis} 值: {event.value:.2f}")
        
        # rt_value = joystick.get_axis(4)
        rt_value = joystick.get_button(0)

        # 檢查是否壓下
        if rt_value > 0.1:  # 沒壓時大多是 0，壓越多接近 1
            print(f"RT 觸發值: {rt_value:.2f}")
            press_left_right()
        time.sleep(0.01)
except KeyboardInterrupt:
    print("結束程式")
finally:
    pygame.quit()