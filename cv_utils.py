import cv2
import numpy as np

_sct = None


def screenshot_mss(region):
    global _sct
    import mss
    if _sct is None:
        _sct = mss.mss()
    x, y, w, h = region
    mon = {"left": x, "top": y, "width": w, "height": h}
    raw = _sct.grab(mon)
    return np.array(raw)[:, :, :3]  # BGR, drop alpha


def preprocess(img_bgr, resize_scale=3, thresh=150):
    gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(
        gray, None, fx=resize_scale, fy=resize_scale, interpolation=cv2.INTER_CUBIC
    )
    _, binary = cv2.threshold(resized, thresh, 255, cv2.THRESH_BINARY)
    return binary


def capture_and_ocr(reader, region, resize_scale=3, thresh=150):
    img = screenshot_mss(region)
    binary = preprocess(img, resize_scale, thresh)
    return reader.readtext(binary)
