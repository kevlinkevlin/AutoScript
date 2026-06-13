import os
import re
import io
import cv2
import sys
import time
import queue
import shutil
import base64
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'lib'))

import keyboard
import pytesseract
import pyautogui
import numpy as np

from maplestory_define import find_maplestory_window

TESS_CONFIG = '--psm 6 --oem 3 -c tessedit_char_whitelist=0123456789,'
for _p in [r'C:\Program Files\Tesseract-OCR\tesseract.exe',
           r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe']:
    if os.path.exists(_p):
        pytesseract.pytesseract.tesseract_cmd = _p
        break

SINGLE_MODE, TOTAL_MODE = "Single", "Total"
CLICK_SEARCH, CLICK_TOP_LEFT = "ClickSearch", "ClickTopLeft"
LOG_FILE = "logs/ocr_log.txt"
os.makedirs("logs", exist_ok=True)


@dataclass
class AuctionConfig:
    target_price: int = 80_000_000
    minimum_price: int = 500
    loop_delay: float = 20.0
    number_in_auction: int = 7
    min_confidence: float = 0.75
    mode: str = TOTAL_MODE
    refresh_method: str = CLICK_SEARCH
    ocr_engine: str = "easyocr"  # "easyocr" | "tesseract" | "claude"


class AuctionWorker(threading.Thread):
    _easyocr_reader = None  # class-level cache，避免每次 start 重新載模型

    def __init__(self, cfg: AuctionConfig, game_region, status_q: "queue.Queue"):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.game_region = game_region
        self.status_q = status_q
        self.stop_event = threading.Event()
        self._original_pos = pyautogui.position()

    def stop(self):
        self.stop_event.set()

    def _log(self, msg: str):
        self.status_q.put({"type": "log", "msg": msg})

    def run(self):
        os.makedirs("ocr_debug_image", exist_ok=True)
        os.makedirs("image", exist_ok=True)

        self._log("開始搶購！")
        x, y, w, h = self.game_region

        if self.cfg.mode == SINGLE_MODE:
            ratio_x, ratio_y, ratio_w, ratio_h = 0.68, 0.25, 0.11, 0.62
        else:
            ratio_x, ratio_y, ratio_w, ratio_h = 0.56, 0.25, 0.11, 0.62

        price_region = (
            x + int(ratio_x * w),
            y + int(ratio_y * h),
            int(ratio_w * w),
            int(ratio_h * h),
        )

        while not self.stop_event.is_set():
            if self.cfg.refresh_method == CLICK_TOP_LEFT:
                self._refresh_auction()
            else:
                self._refresh_auction_click_search()

            pyautogui.moveTo(
                self.game_region[0] + int(self.game_region[2] * 0.5),
                self.game_region[1] + int(self.game_region[3] * 0.05),
            )
            time.sleep(1.0)

            if self.stop_event.is_set():
                break

            result = self._cv_capture(price_region, save_debug_image=True)
            check_time = time.time()
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"\n--- {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            price_results = self._filter_price_results(result)

            if len(price_results) != self.cfg.number_in_auction:
                self._log(f"OCR 結果不完整（{len(price_results)}/{self.cfg.number_in_auction}），重新 OCR")
                shutil.copyfile(
                    "auction.png",
                    f"./ocr_debug_image/{time.strftime('%Y-%m-%d_%H-%M-%S')}.png",
                )

            while (
                time.time() - check_time < 10.0
                and len(price_results) != self.cfg.number_in_auction
                and not self.stop_event.is_set()
            ):
                result = self._cv_capture(price_region)
                price_results = self._filter_price_results(result)

            if self.stop_event.is_set():
                break

            if len(price_results) < self.cfg.number_in_auction:
                self._log("找不到價錢，重新進入拍賣")
                target_x = self.game_region[0] + self.game_region[2] * 0.85
                target_y = self.game_region[1] + self.game_region[3] * 0.95
                self._start_click()
                pyautogui.click(target_x, target_y)
                time.sleep(2.0)
                keyboard.press_and_release('enter')
                self._resume_click()
                continue

            bought = False
            for index, (box, text, conf) in enumerate(price_results):
                value = self._reconstruct_price(text)
                if value is None:
                    self._log(f"無法解析價格: {text!r}")
                    continue
                target_x = price_region[0]
                center_y_in_ocr = (box[0][1] + box[2][1]) / 2
                target_y = price_region[1] + center_y_in_ocr / 4 - 8

                if value <= self.cfg.target_price:
                    if value < self.cfg.minimum_price:
                        self._log(f"低於保護價格 {self.cfg.minimum_price}，先不購買")
                        continue

                    shutil.copyfile(
                        "auction.png",
                        f"./image/{time.strftime('%Y-%m-%d_%H-%M-%S')}_buy_target_{value}.png",
                    )

                    self._start_click()
                    pyautogui.mouseDown(target_x, target_y)
                    pyautogui.mouseUp()
                    pyautogui.mouseDown(target_x, target_y)
                    pyautogui.mouseUp()
                    time.sleep(0.2)

                    if self.cfg.mode == SINGLE_MODE:
                        pyautogui.click(
                            self.game_region[0] + self.game_region[2] * 0.46,
                            self.game_region[1] + self.game_region[3] * 0.47,
                        )

                    keyboard.press_and_release('enter')
                    self._resume_click()
                    self.status_q.put({"type": "buy", "value": value})
                    bought = True
                    break

            if not bought:
                self.status_q.put({"type": "tick"})

            self._log(f"暫停 {self.cfg.loop_delay} 秒")
            deadline = time.time() + self.cfg.loop_delay
            while time.time() < deadline and not self.stop_event.is_set():
                time.sleep(0.1)

        self._log("搶購執行緒已結束")
        self.status_q.put({"type": "stopped"})

    def _refresh_auction(self):
        x, y, w, h = self.game_region
        self._start_click()
        pyautogui.click(x + int(0.2 * w), y + int(0.05 * h))
        keyboard.press_and_release('enter')
        self._resume_click()

    def _refresh_auction_click_search(self):
        x, y, w, h = self.game_region
        self._start_click()
        pyautogui.click(x + int(0.25 * w), y + int(0.8 * h))
        self._resume_click()

    def _start_click(self):
        self._original_pos = pyautogui.position()

    def _resume_click(self):
        pyautogui.moveTo(self._original_pos)

    def _cv_capture(self, region, save_debug_image=False):
        if self.cfg.ocr_engine == "easyocr":
            return self._cv_capture_easyocr(region, save_debug_image)
        if self.cfg.ocr_engine == "claude":
            return self._cv_capture_claude(region, save_debug_image)
        return self._cv_capture_tesseract(region, save_debug_image)

    def _cv_capture_easyocr(self, region, save_debug_image=False):
        """EasyOCR — 讀取繁體中文，可直接辨識億/萬符號，不需 whitelist"""
        import easyocr

        if AuctionWorker._easyocr_reader is None:
            self._log("初始化 EasyOCR（首次約需 10 秒）...")
            AuctionWorker._easyocr_reader = easyocr.Reader(
                ['ch_tra', 'en'], gpu=True, verbose=False
            )
            self._log("EasyOCR 初始化完成")

        screenshot = pyautogui.screenshot(region=region)
        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        padded = cv2.copyMakeBorder(img, 8, 8, 50, 10, cv2.BORDER_CONSTANT, value=255)
        resized = cv2.resize(padded, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(resized)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        if np.mean(binary) < 128:
            binary = cv2.bitwise_not(binary)

        # Fill tiny gaps in small characters (commas tend to break after Otsu)
        kernel = np.ones((2, 2), np.uint8)
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        if save_debug_image:
            cv2.imwrite("auction.png", binary)

        return AuctionWorker._easyocr_reader.readtext(
            binary,
            paragraph=False,
            min_size=10,
            contrast_ths=0.3,
            adjust_contrast=0.8,
        )

    def _cv_capture_claude(self, region, save_debug_image=False):
        """Claude Vision API — 與 Claude 直接看圖相同的辨識引擎，準確率最高"""
        try:
            import anthropic
        except ImportError:
            self._log("[Claude OCR] anthropic 套件未安裝，切換回 Tesseract。請執行: pip install anthropic")
            return self._cv_capture_tesseract(region, save_debug_image)

        screenshot = pyautogui.screenshot(region=region)

        if save_debug_image:
            img_bgr = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
            upscaled = cv2.resize(img_bgr, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            cv2.imwrite("auction.png", upscaled)

        buf = io.BytesIO()
        screenshot.save(buf, format='PNG')
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        try:
            client = anthropic.Anthropic()  # 讀取環境變數 ANTHROPIC_API_KEY
            msg = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=256,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": "image/png", "data": img_b64}
                        },
                        {
                            "type": "text",
                            "text": (
                                "這是 MapleStory 楓之谷拍賣屋的價格欄截圖。\n"
                                "請從上到下列出所有拍賣項目的主要梅索價格，每行一個純數字（不含逗號、億、萬等文字）。\n"
                                "只輸出數字，例如：\n777777777\n499999999\n538888888"
                            )
                        }
                    ]
                }]
            )
            raw_text = msg.content[0].text.strip()
        except Exception as e:
            self._log(f"[Claude OCR 失敗] {e}，切換回 Tesseract")
            return self._cv_capture_tesseract(region, save_debug_image=False)

        prices = []
        for line in raw_text.split('\n'):
            clean = re.sub(r'[^\d]', '', line)
            if len(clean) >= 4:
                prices.append(int(clean))

        if not prices:
            self._log(f"[Claude OCR] 無法解析回傳: {raw_text!r}，切換回 Tesseract")
            return self._cv_capture_tesseract(region, save_debug_image=False)

        self._log(f"[Claude OCR] {[f'{p:,}' for p in prices]}")

        # 根據 item index 計算點擊 Y 座標（等分）
        # run() 計算：target_y = region[1] + center_y_in_ocr/4 - 8
        # 目標：target_y = region[1] + (i+0.5)*region[3]/n
        # 故：center_y_in_ocr = 4*(i+0.5)*region[3]/n + 32
        n = len(prices)
        results = []
        for i, price in enumerate(prices):
            cy = int(4 * (i + 0.5) * region[3] / n + 32)
            box = [[0, cy - 12], [100, cy - 12], [100, cy + 12], [0, cy + 12]]
            results.append((box, f"{price:,}", 0.99))
        return results

    def _cv_capture_tesseract(self, region, save_debug_image=False):
        screenshot = pyautogui.screenshot(region=region)
        img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
        padded = cv2.copyMakeBorder(img, 8, 8, 50, 10, cv2.BORDER_CONSTANT, value=255)
        resized = cv2.resize(padded, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(resized)
        _, binary = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        if np.mean(binary) < 128:
            binary = cv2.bitwise_not(binary)

        if save_debug_image:
            cv2.imwrite("auction.png", binary)

        data = pytesseract.image_to_data(
            binary, config=TESS_CONFIG, output_type=pytesseract.Output.DICT
        )

        # 以 Tesseract 的 (block_num, par_num, line_num) 將同一行的 word 合并
        # 避免 row_text 截圖起點 x-50 不穩定、多 token 被合并成錯誤大數的問題
        line_map = {}
        for i in range(len(data['text'])):
            if data['level'][i] != 5:
                continue
            raw = data['text'][i].strip()
            conf_raw = int(data['conf'][i])
            if not raw or conf_raw < 0:
                continue
            lkey = (data['block_num'][i], data['par_num'][i], data['line_num'][i])
            if lkey not in line_map:
                line_map[lkey] = []
            line_map[lkey].append({
                'text': raw, 'conf': conf_raw,
                'x': data['left'][i], 'y': data['top'][i],
                'w': data['width'][i], 'h': data['height'][i],
            })

        results = []
        for words in line_map.values():
            words.sort(key=lambda w: w['x'])
            line_text = ' '.join(w['text'] for w in words)
            valid_confs = [w['conf'] for w in words if w['conf'] > 0]
            avg_conf = sum(valid_confs) / len(valid_confs) if valid_confs else 50
            min_x = min(w['x'] for w in words)
            min_y = min(w['y'] for w in words)
            max_x = max(w['x'] + w['w'] for w in words)
            max_y = max(w['y'] + w['h'] for w in words)
            box = [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]]
            results.append((box, line_text, avg_conf / 100.0))

        return results

    @staticmethod
    def _parse_wan_tokens(wan_items, price_hint=None):
        """
        從萬/億行重建完整價格（finditer 版，支援 10億+）。

        LINE-LEVEL 後同一行所有數字已合并在單一 text 中，用 finditer 取出：
          "7 7,777 7,777"  → [7, 7777, 7777] → 7×1e8 + 7777×1e4 + 7777 = 777,777,777
          "11 9,999 9,999" → [11,9999,9999]  → 1,199,999,999
          "14"             → [14]            → 14×1e8 = 1,400,000,000 (用 price_hint 判斷)
          "1,242"          → [1242]          → 1242×1e4 = 12,420,000
        """
        nums = []
        for _, text, _ in sorted(wan_items, key=lambda r: r[0][0][0]):
            for m in re.finditer(r'(\d{1,3}(?:,\d{3})+|\d+)', text):
                nums.append(int(m.group(1).replace(',', '')))
        if not nums:
            return None

        # 3 token：N億 M萬 P
        if len(nums) >= 3 and nums[1] < 10000 and nums[2] < 10000:
            return nums[0] * 100_000_000 + nums[1] * 10_000 + nums[2]

        # 2 token
        if len(nums) >= 2 and nums[1] < 10000:
            n0, n1 = nums[0], nums[1]
            if n0 < 100:
                # N億 M萬 → N*1e8 + M*1e4  (N < 100 確認為億單位)
                return n0 * 100_000_000 + n1 * 10_000
            else:
                # N萬 P → N*1e4 + P
                return n0 * 10_000 + n1

        # 1 token
        if len(nums) >= 1:
            n0 = nums[0]
            if n0 >= 100:
                return n0 * 10_000  # N萬（N≥100，如 1,242萬）
            # N < 100：可能是 N億 或 N萬，用 price_hint 決定
            if price_hint and price_hint > 0:
                val_yi = n0 * 100_000_000
                val_wan = n0 * 10_000
                return val_yi if abs(val_yi - price_hint) <= abs(val_wan - price_hint) else val_wan
            # 無 hint：1-9 視為億，10-99 視為萬
            return n0 * (100_000_000 if n0 <= 9 else 10_000)

        return None

    @staticmethod
    def _normalize_ocr_text(text):
        """Fix recurring OCR misreads before price parsing."""
        text = re.sub(r'_', '', text)                               # "1_,300,006" → "1,300,006"
        text = re.sub(r'(?<=\d) (?=\d{3}(?!\d))', ',', text)       # "9 999 999"  → "9,999,999"
        return text

    @staticmethod
    def _reconstruct_price(text):
        """
        從 LINE-LEVEL OCR 文字還原完整價格整數。
        處理 Tesseract 將千位分隔數字切成多個 word 的情況：
          "777,777 777"  → 777,777,777
          "777,777,777"  → 777,777,777
          "1,199,999,999" → 1,199,999,999
        """
        m = re.search(r'\d{1,3}(?:,\d{3})+', text)
        if m:
            val = int(m.group(0).replace(',', ''))
            # 檢查緊接後方是否有被切斷的 3 位尾段
            rest = text[m.end():]
            tail = re.match(r'\s*(\d{3})(?!\d)', rest)
            if tail:
                val = val * 1000 + int(tail.group(1))
            return val
        m = re.search(r'\d+', text)
        return int(m.group(0)) if m else None

    def _filter_price_results(self, result):
        """
        Y-clustering 取 price 行，並用萬/億行交叉校驗。
        LINE-LEVEL 後每行已完整合并，_reconstruct_price 處理殘餘斷字。
        """
        if not result:
            return []

        INTRA_GAP = 200  # 4x 放大圖中，同 slot 內 price→萬行約 100~160px

        def _is_valid(text, conf):
            if conf < self.cfg.min_confidence:
                return False
            if re.search(r'[一-鿿㐀-䶿豈-﫿（）【】]', text):
                return False
            if re.match(r'^\s*,', text) or re.search(r',\s*$', text):
                return False
            val = AuctionWorker._reconstruct_price(text)
            if val is None or val < self.cfg.minimum_price:
                return False
            return True

        sorted_result = sorted(result, key=lambda r: (r[0][0][1] + r[0][2][1]) / 2)

        slots, cur = [], [sorted_result[0]]
        slot_first_cy = (sorted_result[0][0][0][1] + sorted_result[0][0][2][1]) / 2
        for item in sorted_result[1:]:
            cy = (item[0][0][1] + item[0][2][1]) / 2
            if cy - slot_first_cy < INTRA_GAP:
                cur.append(item)
            else:
                slots.append(cur)
                cur = [item]
                slot_first_cy = cy
        slots.append(cur)

        price_results = []
        for slot in slots:
            price_item = min(slot, key=lambda r: r[0][0][1])
            price_y = price_item[0][0][1]
            wan_items = [r for r in slot if r[0][0][1] > price_y + 50]

            box, text, conf = price_item
            text = AuctionWorker._normalize_ocr_text(text)

            if not _is_valid(text, conf):
                if conf < self.cfg.min_confidence:
                    self._log(f"OCR 信心度過低，排除: {text!r} ({conf:.4f})")
                with open(LOG_FILE, 'a', encoding='utf-8') as f:
                    f.write(f"{text}\t{conf:.4f}\n")
                continue

            price_val = self._reconstruct_price(text)
            if price_val is None:
                continue

            # 萬/億行交叉校驗
            wan_val = self._parse_wan_tokens(wan_items, price_hint=price_val)
            log_extra = f"\twan_val={wan_val}"
            used_source = f"price_val={price_val}"

            if wan_val and wan_val >= self.cfg.minimum_price:
                ratio = wan_val / price_val if price_val > 0 else float('inf')
                diff_pct = abs(price_val - wan_val) / wan_val
                if ratio > 10.0 or ratio < 0.1:
                    # 量級差距過大：兩者皆可疑，記錄但信任 price 行
                    self._log(f"[萬行校正跳過] wan={wan_val:,} price={price_val:,} ratio={ratio:.2f}")
                elif diff_pct > 0.05:
                    # 差異 > 5%：萬行結構化格式更可靠，以萬行修正
                    self._log(f"[萬行校正] {price_val:,} → {wan_val:,} (diff={diff_pct:.1%})")
                    price_val = wan_val
                    text = f"{wan_val:,}"
                    used_source = f"wan_val={wan_val}"
                log_extra += f"\tprice_val={price_val}\tused={used_source}"

            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"{text}\t{conf:.4f}{log_extra}\n")

            price_results.append((box, text, conf))

        price_results.sort(key=lambda r: r[0][0][1])
        return price_results


class AuctionApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("拍賣屋搶購 GUI")
        self.root.geometry("560x700")
        self.root.attributes("-topmost", True)
        self.root.resizable(True, True)

        self.cfg = AuctionConfig()
        self.status_q: "queue.Queue[dict]" = queue.Queue()
        self.worker = None
        self.base_region = None
        self.buy_count = 0

        self._drag_x = 0
        self._drag_y = 0

        self._build_ui()
        self._poll_queue()
        self._setup_hotkeys()
        self._create_float_window()

    def _setup_hotkeys(self):
        keyboard.add_hotkey('F8', lambda: self.root.after(0, self._hotkey_toggle))
        keyboard.add_hotkey('=', lambda: self.root.after(0, self._hotkey_toggle))

    def _hotkey_toggle(self):
        if self.worker and self.worker.is_alive():
            self._stop_auction()
        else:
            self._start_auction()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 5}

        # ── 可捲動容器 ────────────────────────────────────
        canvas = tk.Canvas(self.root, highlightthickness=0)
        vsb = ttk.Scrollbar(self.root, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        inner = ttk.Frame(canvas)
        win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win_id, width=e.width))
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        # ── 頂部選項 ──────────────────────────────────────
        top = ttk.Frame(inner)
        top.pack(fill="x", **pad)

        self.topmost_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="置頂", variable=self.topmost_var,
                        command=self._toggle_topmost).pack(side="left")
        ttk.Button(top, text="懸浮視窗", command=self._show_float).pack(side="left", padx=(10, 0))

        # ── Region ────────────────────────────────────────
        region_frame = ttk.LabelFrame(inner, text="遊戲視窗 Region (x, y, w, h)")
        region_frame.pack(fill="x", **pad)

        self.x_var = tk.StringVar(value="0")
        self.y_var = tk.StringVar(value="0")
        self.w_var = tk.StringVar(value="0")
        self.h_var = tk.StringVar(value="0")

        for i, (lbl, var) in enumerate([
            ("x", self.x_var), ("y", self.y_var), ("w", self.w_var), ("h", self.h_var)
        ]):
            ttk.Label(region_frame, text=lbl).grid(row=0, column=i * 2, sticky="w", padx=(8, 2), pady=6)
            ttk.Entry(region_frame, textvariable=var, width=10).grid(
                row=0, column=i * 2 + 1, padx=(0, 8), pady=6)

        region_btns = ttk.Frame(region_frame)
        region_btns.grid(row=1, column=0, columnspan=8, sticky="w", padx=8, pady=(0, 8))
        ttk.Button(region_btns, text="自動抓視窗", command=self._auto_find_window).pack(side="left")
        ttk.Button(region_btns, text="套用 Region", command=self._apply_region).pack(side="left", padx=(8, 0))

        # ── 搶購設定 ──────────────────────────────────────
        cfg_frame = ttk.LabelFrame(inner, text="搶購設定")
        cfg_frame.pack(fill="x", **pad)

        self.target_price_var = tk.StringVar(value="5200000")
        self.min_price_var = tk.StringVar(value="500")
        self.loop_delay_var = tk.StringVar(value="40")
        self.num_in_auction_var = tk.StringVar(value="7")
        self.min_conf_var = tk.StringVar(value="0.5")

        left_fields = [
            ("目標價格", self.target_price_var),
            ("最低保護價", self.min_price_var),
            ("搜尋間隔 (秒)", self.loop_delay_var),
            ("拍賣物數量", self.num_in_auction_var),
            ("最低信心度", self.min_conf_var),
        ]

        for row, (lbl, var) in enumerate(left_fields):
            ttk.Label(cfg_frame, text=lbl).grid(row=row, column=0, sticky="w", padx=(8, 4), pady=4)
            ttk.Entry(cfg_frame, textvariable=var, width=16).grid(
                row=row, column=1, sticky="w", padx=(0, 16), pady=4)

        # 價格模式
        self.mode_var = tk.StringVar(value=TOTAL_MODE)
        mode_frame = ttk.LabelFrame(cfg_frame, text="價格模式")
        mode_frame.grid(row=0, column=2, rowspan=2, sticky="nw", padx=(4, 8), pady=4)
        ttk.Radiobutton(mode_frame, text="總價", variable=self.mode_var, value=TOTAL_MODE).pack(anchor="w", padx=6, pady=2)
        ttk.Radiobutton(mode_frame, text="單價", variable=self.mode_var, value=SINGLE_MODE).pack(anchor="w", padx=6, pady=2)

        # 刷新方式
        self.refresh_var = tk.StringVar(value=CLICK_SEARCH)
        refresh_frame = ttk.LabelFrame(cfg_frame, text="刷新方式")
        refresh_frame.grid(row=2, column=2, rowspan=2, sticky="nw", padx=(4, 8), pady=4)
        ttk.Radiobutton(refresh_frame, text="點左上角", variable=self.refresh_var, value=CLICK_TOP_LEFT).pack(anchor="w", padx=6, pady=2)
        ttk.Radiobutton(refresh_frame, text="點搜尋", variable=self.refresh_var, value=CLICK_SEARCH).pack(anchor="w", padx=6, pady=2)

        # OCR 引擎
        self.ocr_engine_var = tk.StringVar(value="easyocr")
        ocr_frame = ttk.LabelFrame(cfg_frame, text="OCR 引擎")
        ocr_frame.grid(row=4, column=2, rowspan=3, sticky="nw", padx=(4, 8), pady=4)
        ttk.Radiobutton(ocr_frame, text="EasyOCR", variable=self.ocr_engine_var, value="easyocr").pack(anchor="w", padx=6, pady=2)
        ttk.Radiobutton(ocr_frame, text="Tesseract", variable=self.ocr_engine_var, value="tesseract").pack(anchor="w", padx=6, pady=2)
        ttk.Radiobutton(ocr_frame, text="Claude API", variable=self.ocr_engine_var, value="claude").pack(anchor="w", padx=6, pady=2)

        # ── 控制 ──────────────────────────────────────────
        ctrl_frame = ttk.LabelFrame(inner, text="控制")
        ctrl_frame.pack(fill="x", **pad)

        btn_row = ttk.Frame(ctrl_frame)
        btn_row.pack(fill="x", padx=8, pady=(8, 4))

        self.start_btn = ttk.Button(btn_row, text="開始搶購", command=self._start_auction, width=12)
        self.start_btn.pack(side="left")

        self.stop_btn = ttk.Button(btn_row, text="停止搶購", command=self._stop_auction,
                                   state="disabled", width=12)
        self.stop_btn.pack(side="left", padx=(8, 0))

        ttk.Label(ctrl_frame, text="快捷鍵：F8 / = 切換開關", foreground="gray").pack(
            anchor="w", padx=8, pady=(0, 2))

        self.status_lbl = ttk.Label(ctrl_frame, text="狀態：待機", anchor="w")
        self.status_lbl.pack(fill="x", padx=8, pady=2)

        self.buy_lbl = ttk.Label(ctrl_frame, text="購買次數：0", anchor="w")
        self.buy_lbl.pack(fill="x", padx=8, pady=(0, 8))

        # ── Log ───────────────────────────────────────────
        log_frame = ttk.LabelFrame(inner, text="Log")
        log_frame.pack(fill="x", **pad)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, height=10, state="disabled", font=("Consolas", 9), wrap="word")
        self.log_text.pack(fill="x", padx=4, pady=4)

        # ── 底部按鈕 ──────────────────────────────────────
        bottom = ttk.Frame(inner)
        bottom.pack(fill="x", padx=10, pady=6)
        ttk.Button(bottom, text="清除 Log", command=self._clear_log).pack(side="right")
        ttk.Button(bottom, text="關閉", command=self._on_close).pack(side="right", padx=(0, 8))

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 懸浮視窗 ────────────────────────────────────────

    def _create_float_window(self):
        self._float = tk.Toplevel(self.root)
        self._float.overrideredirect(True)
        self._float.attributes("-topmost", True)
        self._float.attributes("-alpha", 0.88)
        self._float.configure(bg="#1e1e1e")

        frame = tk.Frame(self._float, bg="#1e1e1e")
        frame.pack(fill="both", expand=True)

        self._float_lbl = tk.Label(
            frame, text="  ●  待機",
            font=("Microsoft JhengHei UI", 12, "bold"),
            bg="#1e1e1e", fg="#888888",
            padx=10, pady=8,
        )
        self._float_lbl.pack(side="left", fill="both", expand=True)

        close_btn = tk.Label(frame, text="✕", bg="#1e1e1e", fg="#555555",
                             font=("Arial", 9), padx=8, pady=8, cursor="hand2")
        close_btn.pack(side="right")
        close_btn.bind("<Button-1>", lambda e: self._float.withdraw())
        close_btn.bind("<Enter>", lambda e: close_btn.config(fg="#ffffff"))
        close_btn.bind("<Leave>", lambda e: close_btn.config(fg="#555555"))

        for w in (frame, self._float_lbl):
            w.bind("<ButtonPress-1>", self._float_drag_start)
            w.bind("<B1-Motion>", self._float_drag_move)

        self._float.geometry("+200+200")

    def _float_drag_start(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def _float_drag_move(self, event):
        x = self._float.winfo_x() + event.x - self._drag_x
        y = self._float.winfo_y() + event.y - self._drag_y
        self._float.geometry(f"+{x}+{y}")

    def _update_float(self, text: str, fg: str):
        self._float_lbl.config(text=text, fg=fg)
        self._float.deiconify()

    def _show_float(self):
        self._float.deiconify()
        self._float.lift()

    # ── Region ──────────────────────────────────────────

    def _toggle_topmost(self):
        self.root.attributes("-topmost", bool(self.topmost_var.get()))

    def _auto_find_window(self):
        try:
            region = find_maplestory_window()
            if not region:
                raise RuntimeError("find_maplestory_window() 回傳空值")
            x, y, w, h = region
            self.x_var.set(str(x))
            self.y_var.set(str(y))
            self.w_var.set(str(w))
            self.h_var.set(str(h))
            self.base_region = region
            self.status_lbl.config(text=f"狀態：已取得 region={region}")
        except Exception as e:
            messagebox.showerror("錯誤", f"自動抓視窗失敗：{e}")

    def _apply_region(self) -> bool:
        try:
            x = int(self.x_var.get())
            y = int(self.y_var.get())
            w = int(self.w_var.get())
            h = int(self.h_var.get())
            if w <= 0 or h <= 0:
                raise ValueError("w/h 必須 > 0")
            self.base_region = (x, y, w, h)
            self.status_lbl.config(text=f"狀態：已套用 region={self.base_region}")
            return True
        except Exception as e:
            messagebox.showerror("錯誤", f"region 格式錯誤：{e}")
            return False

    def _apply_config(self) -> bool:
        try:
            self.cfg.target_price = int(self.target_price_var.get())
            self.cfg.minimum_price = int(self.min_price_var.get())
            self.cfg.loop_delay = float(self.loop_delay_var.get())
            self.cfg.number_in_auction = int(self.num_in_auction_var.get())
            self.cfg.min_confidence = float(self.min_conf_var.get())
            self.cfg.mode = self.mode_var.get()
            self.cfg.refresh_method = self.refresh_var.get()
            self.cfg.ocr_engine = self.ocr_engine_var.get()
            return True
        except Exception as e:
            messagebox.showerror("設定錯誤", f"設定格式不正確：{e}")
            return False

    # ── 控制 ────────────────────────────────────────────

    def _start_auction(self):
        if self.worker and self.worker.is_alive():
            return

        if not self.base_region and not self._apply_region():
            messagebox.showwarning("提示", "請先設定遊戲視窗 Region")
            return

        if not self._apply_config():
            return

        self.worker = AuctionWorker(self.cfg, self.base_region, self.status_q)
        self.worker.start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_lbl.config(text="狀態：搶購中...", foreground="green")
        self._append_log("=== 開始搶購 ===")
        self._update_float("  ●  搶購中", "#00dd55")

    def _stop_auction(self):
        if self.worker:
            self.worker.stop()
        self.stop_btn.config(state="disabled")
        self.status_lbl.config(text="狀態：停止中...", foreground="darkorange")
        self._update_float("  ●  停止中...", "#ff8800")

    # ── Log ─────────────────────────────────────────────

    def _append_log(self, msg: str):
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    # ── Queue ────────────────────────────────────────────

    def _poll_queue(self):
        try:
            while True:
                self._handle_msg(self.status_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _handle_msg(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "log":
            self._append_log(msg.get("msg", ""))
        elif mtype == "error":
            self._append_log(f"[ERROR] {msg.get('msg', '')}")
            self.status_lbl.config(text=f"狀態：錯誤 - {msg.get('msg', '')}", foreground="red")
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self._update_float("  ●  錯誤", "#ff4444")
        elif mtype == "buy":
            value = msg.get("value", 0)
            self.buy_count += 1
            self.buy_lbl.config(text=f"購買次數：{self.buy_count}  （最後成交：{value:,}）")
            self._append_log(f"[購買] 成功！價格：{value:,}")
            self._update_float(f"  ●  購買成功！", "#00ffaa")
            self.root.after(2500, lambda: self._update_float("  ●  搶購中", "#00dd55"))
        elif mtype == "stopped":
            self.start_btn.config(state="normal")
            self.stop_btn.config(state="disabled")
            self.status_lbl.config(text="狀態：已停止", foreground="black")
            self._append_log("=== 搶購已停止 ===")
            self._update_float("  ●  已停止", "#ff4444")

    def _on_close(self):
        try:
            if self.worker:
                self.worker.stop()
            keyboard.unhook_all_hotkeys()
            self._float.destroy()
        finally:
            self.root.destroy()


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("clam")
    except Exception:
        pass
    AuctionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
