import pygame
import keyboard
import time

pygame.init()
pygame.joystick.init()

def press_left():
    keyboard.press('left')
    time.sleep(0.01)
    keyboard.release('left')
    time.sleep(0.01)

if pygame.joystick.get_count() == 0:
    print("沒有偵測到手把")
    exit()

joystick = pygame.joystick.Joystick(0)
joystick.init()
print(f"偵測到手把：{joystick.get_name()}")

timer = time.time()

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

        jump_trigger = joystick.get_button(0)
        enter_trigger = joystick.get_button(1)

        if jump_trigger:
            if (time.time() - timer) > 0.3:
                press_left()
        else:
            timer = time.time()

        if enter_trigger:
            keyboard.press_and_release("enter")

        time.sleep(0.01)
except KeyboardInterrupt:
    print("結束程式")
finally:
    pygame.quit()
