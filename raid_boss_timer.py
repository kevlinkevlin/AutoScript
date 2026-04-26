import tkinter as tk
import time

class FloatingCountdown:
    def __init__(self, seconds=10.0):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.95)

        self.total = float(seconds)
        self.remaining = self.total

        self.root.geometry("220x100+1200+100")

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

        self.label = tk.Label(self.root, font=("Consolas", 32))
        self.label.pack(expand=True)

        self.root.bind("<Key-r>", self.reset)
        self.root.bind("<Key-R>", self.reset)
        self.root.bind("<Escape>", self.exit_app)
        self.root.focus_force()

        self.top_frame.bind("<Button-1>", self.start_move)
        self.top_frame.bind("<B1-Motion>", self.do_move)

        self.last_time = time.perf_counter()

        self.update_timer()
        self.force_topmost()
        self.root.mainloop()

    def update_timer(self):
        now = time.perf_counter()
        self.remaining -= now - self.last_time
        self.last_time = now

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
        self._drag_x = event.x
        self._drag_y = event.y

    def do_move(self, event):
        x = self.root.winfo_x() + event.x - self._drag_x
        y = self.root.winfo_y() + event.y - self._drag_y
        self.root.geometry(f"+{x}+{y}")

    def exit_app(self, event=None):
        self.root.destroy()


if __name__ == "__main__":
    FloatingCountdown(10.0)
