import platform
import tkinter as tk
from pynput import keyboard as pynput_kb

# Internal unit: tenths of a second (1 tick = 100 ms = 0.1 s)
_STEP = 100   # tenths per +/- press  (10 s)
_INIT = 100   # tenths at startup     (10 s)
_MIN = 100    # minimum total         (10 s)

_FONT = "Menlo" if platform.system() == "Darwin" else "Consolas"


class CountdownTimer:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.total = _INIT
        self.remaining = _INIT
        self._blink = True

        self._build_ui()
        self._listener = self._bind_hotkeys()
        self._tick()

    def _build_ui(self):
        self.root.title("Countdown")
        self.root.attributes("-topmost", True)
        self.root.resizable(False, False)
        self.root.configure(bg="#111111")

        self._lbl_total = tk.Label(
            self.root,
            text=self._fmt_total(),
            font=(_FONT, 11),
            fg="#555555",
            bg="#111111",
        )
        self._lbl_total.pack(pady=(12, 0))

        self._lbl_time = tk.Label(
            self.root,
            text=self._fmt(self.remaining),
            font=(_FONT, 84, "bold"),
            fg="#ffffff",
            bg="#111111",
            width=5,
            anchor="center",
        )
        self._lbl_time.pack(padx=24)

        tk.Label(
            self.root,
            text="R reset  +/- ±10s",
            font=(_FONT, 9),
            fg="#3a3a3a",
            bg="#111111",
        ).pack(pady=(0, 12))

    def _bind_hotkeys(self) -> pynput_kb.Listener:
        def on_press(key):
            try:
                ch = key.char
            except AttributeError:
                return
            if ch == 'r':
                self.root.after(0, self._reset)
            elif ch in ('+', '='):
                self.root.after(0, self._add)
            elif ch == '-':
                self.root.after(0, self._sub)

        listener = pynput_kb.Listener(on_press=on_press)
        listener.start()
        return listener

    @staticmethod
    def _fmt(tenths: int) -> str:
        return f"{tenths // 10}.{tenths % 10}"

    def _fmt_total(self) -> str:
        return f"total: {self.total // 10}s"

    def _color(self) -> str:
        if self.remaining == 0:
            return "#ff4444"
        if self.remaining <= 30:
            return "#ffaa00"
        return "#ffffff"

    def _reset(self):
        self.remaining = self.total
        self._refresh()

    def _add(self):
        self.total += _STEP
        self.remaining = self.total
        self._refresh()

    def _sub(self):
        self.total = max(_MIN, self.total - _STEP)
        self.remaining = self.total
        self._refresh()

    def _refresh(self):
        self._lbl_total.config(text=self._fmt_total())
        self._lbl_time.config(text=self._fmt(self.remaining), fg=self._color())

    def _tick(self):
        if self.remaining > 0:
            self.remaining -= 1
            self._lbl_time.config(text=self._fmt(self.remaining), fg=self._color())
        else:
            self._blink = not self._blink
            self._lbl_time.config(fg="#ff4444" if self._blink else "#111111")
        self.root.after(100, self._tick)


def main():
    root = tk.Tk()
    timer = CountdownTimer(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (timer._listener.stop(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
