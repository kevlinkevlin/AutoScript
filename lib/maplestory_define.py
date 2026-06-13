import ctypes
import pygetwindow as gw

def _get_dpi_scale():
    """回傳 Windows 顯示縮放比例（100% → 1.0，125% → 1.25）"""
    try:
        # SetProcessDpiAwareness(2) = Per-Monitor DPI Aware
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass
    try:
        hdc = ctypes.windll.user32.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
        ctypes.windll.user32.ReleaseDC(0, hdc)
        return dpi / 96.0
    except Exception:
        return 1.0

_DPI_SCALE = _get_dpi_scale()

def find_window(title_keyword):
    for w in gw.getWindowsWithTitle(title_keyword):
        if w.isActive or w.visible:
            # SetProcessDpiAwareness(2) 已讓 pygetwindow 回傳實體像素，不需再乘 DPI 縮放
            left   = int(w.left)
            top    = int(w.top)
            width  = int(w.width)
            height = int(w.height)
            print(f"✅ 找到遊戲視窗：{w.title}")
            print(f"位置：({left}, {top})，尺寸：{width}x{height}  (DPI scale={_DPI_SCALE:.2f})")
            return (left, top, width, height)
    print("⚠️ 沒找到遊戲視窗")
    return None

def find_maplestory_window(title_keyword="MapleStory Worlds-Artale"):
    return find_window(title_keyword)

def find_TFT_window(title_keyword="League of Legends"):
    return find_window(title_keyword)
