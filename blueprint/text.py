"""Single-stroke lettering (Hershey 'futural') - outline fonts plot badly, stroke fonts plot great."""
from __future__ import annotations

import numpy as np
from HersheyFonts import HersheyFonts

_font: HersheyFonts | None = None
_CAP = 0.75  # cap height as a fraction of the font's nominal size
_BASE = 0.25  # baseline offset as a fraction of nominal size


def _get_font() -> HersheyFonts:
    global _font
    if _font is None:
        _font = HersheyFonts()
        _font.load_default_font("futural")
    return _font


def text_segments(
    text: str,
    x: float,
    y: float,
    height: float,
    anchor: str = "left",
    angle: float = 0.0,
) -> np.ndarray:
    """Return line segments (k,2,2) for `text` with cap-height `height` (mm).

    (x, y) is the baseline anchor point; angle is degrees CCW.
    """
    font = _get_font()
    size = height / _CAP
    font.normalize_rendering(size)
    raw = [((x1, y1), (x2, y2)) for (x1, y1), (x2, y2) in font.lines_for_text(text)]
    if not raw:
        return np.zeros((0, 2, 2))
    arr = np.asarray(raw, float)
    arr[..., 1] -= _BASE * size
    lo, hi = arr[..., 0].min(), arr[..., 0].max()
    arr[..., 0] -= {"left": lo, "center": (lo + hi) / 2, "right": hi}[anchor]
    if angle:
        th = np.radians(angle)
        c, s = np.cos(th), np.sin(th)
        rot = np.array([[c, -s], [s, c]])
        arr = arr @ rot.T
    arr[..., 0] += x
    arr[..., 1] += y
    return arr


def text_width(text: str, height: float) -> float:
    seg = text_segments(text, 0, 0, height)
    return float(seg[..., 0].max() - seg[..., 0].min()) if len(seg) else 0.0
