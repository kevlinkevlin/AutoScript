import pygetwindow as gw

def find_maplestory_window(title_keyword="MapleStory Worlds-Artale"):
    for w in gw.getWindowsWithTitle(title_keyword):
        if w.isActive or w.visible:
            print(f"✅ 找到遊戲視窗：{w.title}")
            print(f"位置：({w.left}, {w.top})，尺寸：{w.width}x{w.height}")
            return (w.left, w.top, w.width, w.height)
    print("⚠️ 沒找到遊戲視窗")
    return None

def find_TFT_window(title_keyword="League of Legends"):
    for w in gw.getWindowsWithTitle(title_keyword):
        if w.isActive or w.visible:
            print(f"✅ 找到遊戲視窗：{w.title}")
            print(f"位置：({w.left}, {w.top})，尺寸：{w.width}x{w.height}")
            return (w.left, w.top, w.width, w.height)
    print("⚠️ 沒找到遊戲視窗")
    return None