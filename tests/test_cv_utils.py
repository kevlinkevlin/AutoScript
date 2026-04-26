import numpy as np
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_preprocess_returns_binary():
    from cv_utils import preprocess
    img = np.full((80, 100, 3), 200, dtype=np.uint8)
    result = preprocess(img, resize_scale=2, thresh=150)
    assert result.dtype == np.uint8
    assert set(result.flatten().tolist()).issubset({0, 255})


def test_preprocess_scales_size():
    from cv_utils import preprocess
    img = np.zeros((40, 60, 3), dtype=np.uint8)
    result = preprocess(img, resize_scale=3, thresh=150)
    assert result.shape == (120, 180)


def test_capture_and_ocr_calls_reader(monkeypatch):
    from unittest.mock import MagicMock, patch
    import numpy as np

    fake_frame = np.zeros((30, 100, 3), dtype=np.uint8)

    with patch("cv_utils.screenshot_mss", return_value=fake_frame):
        import cv_utils
        mock_reader = MagicMock()
        mock_reader.readtext.return_value = [("box", "123/456", 0.9)]
        result = cv_utils.capture_and_ocr(mock_reader, (0, 0, 100, 30))
        mock_reader.readtext.assert_called_once()
        assert result == [("box", "123/456", 0.9)]
