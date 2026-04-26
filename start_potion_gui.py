import re
import time
import threading
import queue
from dataclasses import dataclass
from typing import Optional, Tuple

import cv2
import numpy as np
import pyautogui
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import ImageTk, Image
import mss  # multi-monitor virtual screen capture

import keyboard

# Optional: Windows beep
try:
    import winsound
except Exception:
    winsound = None

# Optional: your helper (if exists)
try:
    from maplestory_define import find_maplestory_window  # noqa
except Exception:
    find_maplestory_window = None


RATIO_PATTERN = re.compile(r"[\[\(]\s*(\d+)\s*/\s*(\d+)\s*[\]\)]")


@dataclass
class MonitorConfig:
    hp_key: str = "pagedown"
    # hp_key: str = "pageup"
    mp_key: str = "pagedown"
    use_super_potion: bool = False
    super_potion_key: str = "end"

    # Thresholds (提示用，不做自動按鍵)
    hp_ratio: float = 0.80
    mp_ratio: float = 0.28

    # Filtering (避免 OCR 垃圾值)
    total_min_hp: float = 50.0
    total_min_mp: float = 40.0

    # Capture pacing
    interval_sec: float = 0.30

    # ROI relative to selected region (x, y, w, h)
    roi_ratio_x: float = 0.0 # 0.266
    roi_ratio_y: float = 0.0 # 0.934
    roi_ratio_w: float = 1.0 # 0.220
    roi_ratio_h: float = 1.0 # 0.029

    # OCR
    languages: Tuple[str, ...] = ("ch_tra", "en")
    use_gpu: bool = True

    # Image preprocess
    resize_fx: float = 3.0
    resize_fy: float = 3.0
    binary_thresh: int = 150

    # UI preview refresh
    preview_interval_ms: int = 150


def compute_roi(base_region: Tuple[int, int, int, int], cfg: MonitorConfig) -> Tuple[int, int, int, int]:
    """ROI is computed relative to the selected base_region"""
    x, y, w, h = base_region
    rx = x + int(cfg.roi_ratio_x * w)
    ry = y + int(cfg.roi_ratio_y * h)
    rw = int(cfg.roi_ratio_w * w)
    rh = int(cfg.roi_ratio_h * h)
    return (rx, ry, rw, rh)


def capture_and_ocr(reader, roi: Tuple[int, int, int, int], cfg: MonitorConfig):
    shot = pyautogui.screenshot(region=roi)
    img = cv2.cvtColor(np.array(shot), cv2.COLOR_RGB2GRAY)
    resized = cv2.resize(img, None, fx=cfg.resize_fx, fy=cfg.resize_fy, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(resized, cfg.binary_thresh, 255, cv2.THRESH_BINARY)
    return reader.readtext(binary)


def parse_hp_mp_from_ocr(result):
    matches = []
    for (box, text, conf) in result:
        m = RATIO_PATTERN.search(text)
        if not m:
            continue
        left_s, total_s = m.groups()
        left = float(left_s)
        total = float(total_s)
        if total <= 0:
            continue
        matches.append((left, total, left / total, text, conf))

    hp = matches[0] if len(matches) >= 1 else None
    mp = matches[1] if len(matches) >= 2 else None
    return hp, mp


class OCRMonitorWorker(threading.Thread):
    def __init__(self, cfg: MonitorConfig, status_q: "queue.Queue[dict]"):
        super().__init__(daemon=True)
        self.cfg = cfg
        self.status_q = status_q
        self.stop_event = threading.Event()
        self.base_region: Optional[Tuple[int, int, int, int]] = None

        self._hp_alert_count = 0
        self._mp_alert_count = 0

    def set_base_region(self, region: Tuple[int, int, int, int]):
        self.base_region = region

    def stop(self):
        self.stop_event.set()

    def run(self):
        try:
            import easyocr
        except Exception as e:
            self.status_q.put({"type": "error", "msg": f"easyocr import 失敗：{e}"})
            return

        try:
            reader = easyocr.Reader(list(self.cfg.languages), gpu=self.cfg.use_gpu)
        except Exception as e:
            self.status_q.put({"type": "error", "msg": f"easyocr Reader 初始化失敗：{e}"})
            return

        if not self.base_region:
            self.status_q.put({"type": "error", "msg": "未設定 base region。"})
            return

        while not self.stop_event.is_set():
            t0 = time.time()
            try:
                roi = compute_roi(self.base_region, self.cfg)
                ocr_result = capture_and_ocr(reader, roi, self.cfg)
                hp, mp = parse_hp_mp_from_ocr(ocr_result)

                hp_alert = False
                mp_alert = False

                if hp is not None:
                    left, total, ratio, text, conf = hp
                    if (ratio < self.cfg.hp_ratio and self.cfg.total_min_hp < total):
                        self._hp_alert_count += 1
                        hp_alert = True
                        keyboard.press_and_release(self.cfg.hp_key)
                        time.sleep(0.2)

                if mp is not None:
                    left, total, ratio, text, conf = mp
                    if (ratio < self.cfg.mp_ratio and self.cfg.total_min_mp < total):
                        self._mp_alert_count += 1
                        mp_alert = True

                        if self.cfg.use_super_potion:
                            keyboard.press_and_release(self.cfg.super_potion_key)
                        else:
                            keyboard.press_and_release(self.cfg.mp_key)
                        time.sleep(0.2)

                self.status_q.put(
                    {
                        "type": "tick",
                        "hp": hp,
                        "mp": mp,
                        "base_region": self.base_region,
                        "roi": roi,
                        "hp_alert": hp_alert,
                        "mp_alert": mp_alert,
                        "hp_alert_count": self._hp_alert_count,
                        "mp_alert_count": self._mp_alert_count,
                    }
                )
            except Exception as e:
                self.status_q.put({"type": "error", "msg": f"OCR 監看過程錯誤：{e}"})

            elapsed = time.time() - t0
            time.sleep(max(0.0, self.cfg.interval_sec - elapsed))

        self.status_q.put({"type": "info", "msg": "已停止 OCR 監看"})


class MonitorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Region Preview (Selected) + OCR ROI")
        self.root.geometry("620x560")
        self.root.attributes("-topmost", True)

        self.cfg = MonitorConfig()
        self.status_q: "queue.Queue[dict]" = queue.Queue()
        self.worker: Optional[OCRMonitorWorker] = None

        # Selected base region (what you manually box)
        self.base_region: Optional[Tuple[int, int, int, int]] = None

        # Preview state
        self.preview_running = False
        self._preview_after_id = None
        self._preview_imgtk = None
        self._preview_scale: Optional[float] = None

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)

        self.topmost_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="置頂", variable=self.topmost_var, command=self._toggle_topmost).pack(side="left")

        self.gpu_var = tk.BooleanVar(value=self.cfg.use_gpu)
        ttk.Checkbutton(top, text="GPU OCR", variable=self.gpu_var).pack(side="left", padx=(12, 0))

        region_frame = ttk.LabelFrame(self.root, text="Selected Region (x, y, w, h)  (支援負座標/多螢幕)")
        region_frame.pack(fill="x", **pad)

        self.x_var = tk.StringVar(value="0")
        self.y_var = tk.StringVar(value="0")
        self.w_var = tk.StringVar(value="0")
        self.h_var = tk.StringVar(value="0")

        for i, (lbl, var) in enumerate([("x", self.x_var), ("y", self.y_var), ("w", self.w_var), ("h", self.h_var)]):
            ttk.Label(region_frame, text=lbl).grid(row=0, column=i * 2, sticky="w", padx=(8, 2), pady=6)
            ttk.Entry(region_frame, textvariable=var, width=10).grid(row=0, column=i * 2 + 1, padx=(0, 8), pady=6)

        btns = ttk.Frame(region_frame)
        btns.grid(row=1, column=0, columnspan=8, sticky="w", padx=8, pady=(0, 8))

        self.auto_btn = ttk.Button(btns, text="自動抓視窗", command=self._auto_find_window)
        self.auto_btn.pack(side="left")

        self.select_btn = ttk.Button(btns, text="手動框選 Region (全螢幕/多螢幕)", command=self._select_region_virtual_screen)
        self.select_btn.pack(side="left", padx=(8, 0))

        ttk.Button(btns, text="套用 region", command=self._apply_region).pack(side="left", padx=(8, 0))

        th_frame = ttk.LabelFrame(self.root, text="Thresholds (只提示用)")
        th_frame.pack(fill="x", **pad)

        self.hp_th_var = tk.DoubleVar(value=self.cfg.hp_ratio)
        self.mp_th_var = tk.DoubleVar(value=self.cfg.mp_ratio)

        ttk.Label(th_frame, text="HP <").grid(row=0, column=0, padx=8, pady=6, sticky="w")
        ttk.Entry(th_frame, textvariable=self.hp_th_var, width=10).grid(row=0, column=1, padx=(0, 18), pady=6)

        ttk.Label(th_frame, text="MP <").grid(row=0, column=2, padx=8, pady=6, sticky="w")
        ttk.Entry(th_frame, textvariable=self.mp_th_var, width=10).grid(row=0, column=3, padx=(0, 18), pady=6)

        ctrl = ttk.Frame(self.root)
        ctrl.pack(fill="x", **pad)

        self.start_btn = ttk.Button(ctrl, text="Start OCR", command=self._start_ocr)
        self.start_btn.pack(side="left")

        self.stop_btn = ttk.Button(ctrl, text="Stop OCR", command=self._stop_ocr, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))

        self.preview_btn = ttk.Button(ctrl, text="Preview Selected Region", command=self._toggle_preview)
        self.preview_btn.pack(side="left", padx=(8, 0))

        self.status_lbl = ttk.Label(self.root, text="狀態：待機", anchor="w")
        self.status_lbl.pack(fill="x", padx=10, pady=(0, 8))

        self.hp_lbl = ttk.Label(self.root, text="HP: -", anchor="w")
        self.hp_lbl.pack(fill="x", padx=10)

        self.mp_lbl = ttk.Label(self.root, text="MP: -", anchor="w")
        self.mp_lbl.pack(fill="x", padx=10)

        preview = ttk.LabelFrame(self.root, text="Preview = 你選取的畫面（base region）")
        preview.pack(fill="both", expand=True, padx=10, pady=10)

        self.preview_lbl = ttk.Label(preview, text="(按 Preview 顯示你框選的畫面)")
        self.preview_lbl.pack(padx=6, pady=6)

        ttk.Button(self.root, text="關閉", command=self._on_close).pack(side="bottom", pady=10)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if not find_maplestory_window:
            self.auto_btn.config(state="disabled")

    def _toggle_topmost(self):
        self.root.attributes("-topmost", bool(self.topmost_var.get()))

    def _auto_find_window(self):
        if not find_maplestory_window:
            messagebox.showwarning("提示", "找不到 find_maplestory_window()，請手動輸入 region 或用框選。")
            return
        try:
            region = find_maplestory_window()
            if not region:
                raise RuntimeError("find_maplestory_window() 回傳空值")
            self._set_base_region(region)
            self.status_lbl.config(text=f"狀態：已取得 region={region}")
        except Exception as e:
            messagebox.showerror("錯誤", f"自動抓視窗失敗：{e}")

    def _set_base_region(self, region: Tuple[int, int, int, int]):
        x, y, w, h = region
        self.x_var.set(str(x))
        self.y_var.set(str(y))
        self.w_var.set(str(w))
        self.h_var.set(str(h))
        self.base_region = region
        self._preview_scale = None  # invalidate cached scale

    def _apply_region(self):
        try:
            x = int(self.x_var.get())
            y = int(self.y_var.get())
            w = int(self.w_var.get())
            h = int(self.h_var.get())
            if w <= 0 or h <= 0:
                raise ValueError("w/h 必須 > 0")
            self.base_region = (x, y, w, h)
            self.status_lbl.config(text=f"狀態：已套用 region={self.base_region}")
        except Exception as e:
            messagebox.showerror("錯誤", f"region 格式錯誤：{e}")

    # --------------------
    # 多螢幕：virtual screen 框選（支援負座標/跨螢幕）
    # --------------------
    def _select_region_virtual_screen(self):
        was_preview = self.preview_running
        if was_preview:
            self._stop_preview()

        self.root.withdraw()
        time.sleep(0.15)

        with mss.mss() as sct:
            mon = sct.monitors[0]  # virtual screen
            v_left = int(mon["left"])
            v_top = int(mon["top"])
            v_w = int(mon["width"])
            v_h = int(mon["height"])

            raw = sct.grab(mon)  # BGRA
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")

        overlay = tk.Toplevel()
        overlay.title("Drag to select region (ESC cancel)")
        overlay.attributes("-topmost", True)
        overlay.configure(cursor="cross")

        # If virtual desktop too large, scale down for usability
        max_show_w = 1400
        scale = 1.0
        show_w, show_h = v_w, v_h
        if v_w > max_show_w:
            scale = max_show_w / float(v_w)
            show_w = int(v_w * scale)
            show_h = int(v_h * scale)
            img_show = img.resize((show_w, show_h))
        else:
            img_show = img

        canvas = tk.Canvas(overlay, width=show_w, height=show_h, highlightthickness=0)
        canvas.pack()

        bg_imgtk = ImageTk.PhotoImage(img_show)
        canvas.create_image(0, 0, anchor="nw", image=bg_imgtk)

        info_text = canvas.create_text(
            10,
            10,
            anchor="nw",
            fill="yellow",
            text=f"VirtualScreen left={v_left}, top={v_top}, w={v_w}, h={v_h}  |  拖曳框選；放開確定；ESC 取消",
        )

        start_x = start_y = 0
        rect_id = None

        def canvas_to_virtual(cx1, cy1, cx2, cy2):
            x1, y1 = min(cx1, cx2), min(cy1, cy2)
            x2, y2 = max(cx1, cx2), max(cy1, cy2)
            return int(x1 / scale) + v_left, int(y1 / scale) + v_top, int((x2 - x1) / scale), int((y2 - y1) / scale)

        def cancel(_event=None):
            overlay.destroy()
            self.root.deiconify()
            if was_preview:
                self._start_preview()

        def on_down(event):
            nonlocal start_x, start_y, rect_id
            start_x, start_y = event.x, event.y
            if rect_id is not None:
                canvas.delete(rect_id)
            rect_id = canvas.create_rectangle(start_x, start_y, start_x, start_y, outline="red", width=2)

        def on_drag(event):
            if rect_id is None:
                return
            canvas.coords(rect_id, start_x, start_y, event.x, event.y)
            vx, vy, vw, vh = canvas_to_virtual(start_x, start_y, event.x, event.y)
            canvas.itemconfig(info_text, text=f"x={vx}, y={vy}, w={vw}, h={vh}  (ESC 取消)")

        def on_up(event):
            vx, vy, vw, vh = canvas_to_virtual(start_x, start_y, event.x, event.y)
            if vw > 10 and vh > 10:
                self._set_base_region((vx, vy, vw, vh))
                self.status_lbl.config(text=f"狀態：已框選 base region={(vx, vy, vw, vh)}")
            cancel()

        overlay.bind("<Escape>", cancel)
        canvas.bind("<ButtonPress-1>", on_down)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_up)

        overlay.update_idletasks()
        overlay.geometry("+80+60")
        overlay.mainloop()

    # --------------------
    # Preview = Selected (base) region
    # --------------------
    def _toggle_preview(self):
        if self.preview_running:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview(self):
        if not self.base_region:
            self._apply_region()
            if not self.base_region:
                return

        self.preview_running = True
        self.preview_btn.config(text="Stop Preview")
        self.status_lbl.config(text="狀態：Preview 中（顯示你選取的畫面 / base region）")
        self._preview_tick()

    def _stop_preview(self):
        self.preview_running = False
        self.preview_btn.config(text="Preview Selected Region")
        if self._preview_after_id is not None:
            try:
                self.root.after_cancel(self._preview_after_id)
            except Exception:
                pass
            self._preview_after_id = None
        self.status_lbl.config(text="狀態：Preview 已停止")

    def _preview_tick(self):
        if not self.preview_running:
            return

        try:
            shot = pyautogui.screenshot(region=self.base_region)

            if self._preview_scale is None:
                w, h = shot.size
                self._preview_scale = min(580 / max(w, 1), 320 / max(h, 1), 1.0)
            s = self._preview_scale
            if s < 1.0:
                w, h = shot.size
                shot = shot.resize((int(w * s), int(h * s)))

            imgtk = ImageTk.PhotoImage(shot)
            self._preview_imgtk = imgtk
            self.preview_lbl.configure(image=imgtk, text="")

        except Exception as e:
            self.preview_lbl.configure(image="", text=f"Preview 失敗：{e}")

        self._preview_after_id = self.root.after(self.cfg.preview_interval_ms, self._preview_tick)

    # --------------------
    # OCR start/stop
    # --------------------
    def _start_ocr(self):
        if self.worker and self.worker.is_alive():
            return

        if not self.base_region:
            self._apply_region()
            if not self.base_region:
                return

        self.cfg.hp_ratio = float(self.hp_th_var.get())
        self.cfg.mp_ratio = float(self.mp_th_var.get())
        self.cfg.use_gpu = bool(self.gpu_var.get())

        self.worker = OCRMonitorWorker(self.cfg, self.status_q)
        self.worker.set_base_region(self.base_region)
        self.worker.start()

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_lbl.config(text="狀態：OCR 監看中...")

        if not self.preview_running:
            self._start_preview()

    def _stop_ocr(self):
        if self.worker:
            self.worker.stop()
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_lbl.config(text="狀態：已送出停止 OCR 指令")

    def _beep(self):
        if winsound:
            try:
                winsound.Beep(1200, 120)
            except Exception:
                pass

    # --------------------
    # Queue polling
    # --------------------
    def _poll_queue(self):
        try:
            while True:
                msg = self.status_q.get_nowait()
                self._handle_msg(msg)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_queue)

    def _handle_msg(self, msg: dict):
        mtype = msg.get("type")
        if mtype == "info":
            self.status_lbl.config(text=f"狀態：{msg.get('msg')}")
            return
        if mtype == "error":
            self.status_lbl.config(text=f"狀態：錯誤 - {msg.get('msg')}")
            return
        if mtype != "tick":
            return

        hp = msg.get("hp")
        mp = msg.get("mp")
        hp_alert = bool(msg.get("hp_alert"))
        mp_alert = bool(msg.get("mp_alert"))
        hp_cnt = msg.get("hp_alert_count", 0)
        mp_cnt = msg.get("mp_alert_count", 0)

        if hp is not None:
            left, total, ratio, text, conf = hp
            self.hp_lbl.config(text=f"HP: {int(left)}/{int(total)} = {ratio:.3f} (conf={conf:.2f}) 警示={hp_cnt}")
        else:
            self.hp_lbl.config(text="HP: (未辨識到)")

        if mp is not None:
            left, total, ratio, text, conf = mp
            self.mp_lbl.config(text=f"MP: {int(left)}/{int(total)} = {ratio:.3f} (conf={conf:.2f}) 警示={mp_cnt}")
        else:
            self.mp_lbl.config(text="MP: (未辨識到)")

        if hp_alert or mp_alert:
            self.status_lbl.config(text="狀態：⚠️ 低於閾值（提示）")
            # self._beep()
        else:
            self.status_lbl.config(text="狀態：OCR 監看中...")

    def _on_close(self):
        try:
            self._stop_preview()
            if self.worker:
                self.worker.stop()
        finally:
            self.root.destroy()


def main():
    root = tk.Tk()
    try:
        style = ttk.Style()
        style.theme_use("clam")
    except Exception:
        pass
    MonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()