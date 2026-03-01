import tkinter as tk
import time

class FloatingCountdown:
    def __init__(self, seconds=10.0):
        self.root = tk.Tk()
        self.root.overrideredirect(True)          # 無邊框
        self.root.attributes("-topmost", True)    # 永遠最上層
        self.root.attributes("-alpha", 0.95)

        self.total = float(seconds)
        self.remaining = self.total
        self.running = True

        self.root.geometry("220x100+1200+100")

        # ===== 標題列區 =====
        self.top_frame = tk.Frame(self.root, bg="#222")
        self.top_frame.pack(fill="x")

        self.close_btn = tk.Button(
            self.top_frame,
            text="✕",
            command=self.exit_app,
            bg="#aa0000",
            fg="white",
            bd=0,
            width=3,
            activebackground="#ff0000"
        )
        self.close_btn.pack(side="right")

        # ===== 倒數顯示 =====
        self.label = tk.Label(self.root, font=("Consolas", 32))
        self.label.pack(expand=True)

        # ===== 鍵盤事件 =====
        self.root.bind("<Key-r>", self.reset)
        self.root.bind("<Key-R>", self.reset)
        self.root.bind("<Escape>", self.exit_app)
        self.root.focus_force()

        # ===== 拖曳視窗 =====
        self.top_frame.bind("<Button-1>", self.start_move)
        self.top_frame.bind("<B1-Motion>", self.do_move)

        self.last_time = time.perf_counter()

        self.update_timer()
        self.force_topmost()
        self.root.mainloop()

    def update_timer(self):
        if self.running:
            now = time.perf_counter()
            elapsed = now - self.last_time
            self.last_time = now

            self.remaining -= elapsed
            if self.remaining <= 0:
                self.remaining = self.total

            self.label.config(text=f"{self.remaining:04.1f}")

        self.root.after(50, self.update_timer)

    def reset(self, event=None):
        self.remaining = self.total
        self.last_time = time.perf_counter()

    def force_topmost(self):
        self.root.attributes("-topmost", True)
        self.root.lift()
        self.root.after(500, self.force_topmost)

    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + event.x - self.x
        y = self.root.winfo_y() + event.y - self.y
        self.root.geometry(f"+{x}+{y}")

    def exit_app(self, event=None):
        self.root.destroy()


if __name__ == "__main__":
    FloatingCountdown(10.0)