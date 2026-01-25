import ctypes
import time

# 定義常數
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# 定義 INPUT 結構
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long),
                ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong),
                ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong))]

class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT)]
    _fields_ = [("type", ctypes.c_ulong),
                ("ii", _INPUT)]

# 輔助函數：把座標轉換為絕對座標（0~65535）
def to_absolute(x, y):
    screen_width = ctypes.windll.user32.GetSystemMetrics(0)
    screen_height = ctypes.windll.user32.GetSystemMetrics(1)
    abs_x = int(x * 65535 / screen_width)
    abs_y = int(y * 65535 / screen_height)
    return abs_x, abs_y

# 輔助函數：模擬滑鼠點擊（不移動游標）
def click_at(x, y):
    abs_x, abs_y = to_absolute(x, y)

    # LEFTDOWN
    mi_down = MOUSEINPUT(dx=abs_x, dy=abs_y, mouseData=0,
                         dwFlags=MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN,
                         time=0, dwExtraInfo=None)
    input_down = INPUT(type=0, ii=INPUT._INPUT(mi=mi_down))

    # LEFTUP
    mi_up = MOUSEINPUT(dx=abs_x, dy=abs_y, mouseData=0,
                       dwFlags=MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTUP,
                       time=0, dwExtraInfo=None)
    input_up = INPUT(type=0, ii=INPUT._INPUT(mi=mi_up))

    ctypes.windll.user32.SendInput(1, ctypes.byref(input_down), ctypes.sizeof(INPUT))
    ctypes.windll.user32.SendInput(1, ctypes.byref(input_up), ctypes.sizeof(INPUT))


time.sleep(1)  # 有一秒可以移開滑鼠
click_at(100, 200)