import tkinter as tk
import time
import keyboard

class DualCountdown:
    def __init__(self, timer1=60.0, timer2=10.0):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)
        self.root.geometry("+100+100")

        self.t1_total = float(timer1)
        self.t2_total = float(timer2)

        self.t1_rem = self.t1_total
        self.t2_rem = self.t2_total

        self.t1_active = tk.BooleanVar(value=True)
        self.t2_active = tk.BooleanVar(value=True)

        self.last_time = time.perf_counter()

        # ===== 標題列 =====
        self.top_frame = tk.Frame(self.root, bg="#222")
        self.top_frame.pack(fill="x")

        self.close_btn = tk.Button(
            self.top_frame,
            text="✕",
            command=self.exit_app,
            bg="#aa0000",
            fg="white",
            bd=0,
            width=3
        )
        self.close_btn.pack(side="right")

        # ===== 顯示區 =====
        self.display_frame = tk.Frame(self.root, bg="#111", padx=10, pady=10)
        self.display_frame.pack(expand=True, fill="both")

        # ===== Timer1 =====
        self.frame1 = tk.Frame(self.display_frame, bg="#111")
        self.frame1.pack()

        self.check1 = tk.Checkbutton(
            self.frame1,
            text="Timer1",
            variable=self.t1_active,
            bg="#111",
            fg="#00ffcc",
            selectcolor="#111",
            font=("Consolas", 8)
        )
        self.check1.pack(side="left")

        self.label1 = tk.Label(
            self.frame1,
            font=("Consolas", 8),
            bg="#111",
            fg="#00ffcc"
        )
        self.label1.pack(side="left", padx=10)

        # ===== Timer2 =====
        self.frame2 = tk.Frame(self.display_frame, bg="#111")
        self.frame2.pack()

        self.check2 = tk.Checkbutton(
            self.frame2,
            text="Timer2",
            variable=self.t2_active,
            bg="#111",
            fg="#ffcc00",
            selectcolor="#111",
            font=("Consolas", 8)
        )
        self.check2.pack(side="left")

        self.label2 = tk.Label(
            self.frame2,
            font=("Consolas", 8),
            bg="#111",
            fg="#ffcc00"
        )
        self.label2.pack(side="left", padx=10)

        # ===== 提示 =====
        self.hint = tk.Label(
            self.display_frame,
            text="R: 重置 Timer1/T: 重置 Timer2",
            font=("Consolas", 8),
            bg="#111",
            fg="#888888"
        )
        self.hint.pack(pady=4)

        # ===== 拖曳 =====
        self.top_frame.bind("<Button-1>", self.start_move)
        self.top_frame.bind("<B1-Motion>", self.do_move)

        # ===== 全域鍵 =====
        keyboard.add_hotkey("r", lambda: self.root.after(0, self.reset_t1))
        keyboard.add_hotkey("t", lambda: self.root.after(0, self.reset_t2))
        keyboard.add_hotkey("esc", lambda: self.root.after(0, self.exit_app))

        self.update()
        self.root.mainloop()

    def update(self):
        now = time.perf_counter()
        elapsed = now - self.last_time
        self.last_time = now

        if self.t1_active.get():
            self.t1_rem -= elapsed
            if self.t1_rem <= 0:
                self.t1_rem = self.t1_total

        if self.t2_active.get():
            self.t2_rem -= elapsed
            if self.t2_rem <= 0:
                self.t2_rem = self.t2_total

        self.label1.config(text=f"{self.t1_rem:5.1f}")
        self.label2.config(text=f"{self.t2_rem:5.1f}")

        self.root.after(50, self.update)

    def reset_t1(self):
        self.t1_rem = self.t1_total

    def reset_t2(self):
        self.t2_rem = self.t2_total

    def start_move(self, event):
        self._drag_x = event.x
        self._drag_y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def exit_app(self):
        keyboard.unhook_all()
        self.root.destroy()


if __name__ == "__main__":
    DualCountdown(60.0, 10.0)