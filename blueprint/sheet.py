"""Compose projected views onto a drawing sheet: layout, scale, dimensions, border, title block.

Everything here works in millimetres with the origin at the sheet's bottom-left (y up).
Output is a `Sheet` holding polylines/segments per logical layer (= pen):

    layer 1  visible outlines      (thick/dark pen)
    layer 2  hidden lines, dashed  (thin pen)
    layer 3  dimensions, text, border, title block
"""
from __future__ import annotations

import datetime as _dt
import sys
from dataclasses import dataclass, field

import numpy as np

from .hlr import ViewLines
from .text import text_segments, text_width

PAGES = {"a2": (594.0, 420.0), "a3": (420.0, 297.0), "a4": (297.0, 210.0), "letter": (279.4, 215.9), "tabloid": (431.8, 279.4)}

# third-angle-style grid: (column, row), row 0 is the top of the sheet
GRID = {
    "top": (1, 0),
    "left": (0, 1),
    "front": (1, 1),
    "right": (2, 1),
    "back": (3, 1),
    "bottom": (1, 2),
    "iso": (2, 0),
}

# ISO/ASME-ish drawing scales as model->paper ratios
NICE_SCALES = [1 / 1000, 1 / 500, 1 / 200, 1 / 100, 1 / 50, 1 / 25, 1 / 20, 1 / 10, 1 / 5, 1 / 4, 1 / 2.5, 1 / 2,
               1, 2, 2.5, 4, 5, 10, 20, 50]

LAYER_VISIBLE, LAYER_HIDDEN, LAYER_NOTES = 1, 2, 3


def parse_page(spec: str) -> tuple[float, float]:
    spec = spec.lower().strip()
    if spec in PAGES:
        return PAGES[spec]
    try:
        w, h = spec.lower().replace("mm", "").split("x")
        return float(w), float(h)
    except Exception:
        raise ValueError(f"bad page '{spec}': use one of {', '.join(PAGES)} or WIDTHxHEIGHT in mm") from None


def parse_scale(spec: str) -> str | float:
    """'auto' | 'fit' | '1:2' | '2:1' | '0.5'  ->  'auto' | 'fit' | float (paper/model)."""
    spec = spec.strip().lower()
    if spec in ("auto", "fit"):
        return spec
    if ":" in spec:
        p, m = spec.split(":")
        return float(p) / float(m)
    return float(spec)


def fmt_num(v: float, places: int = 1) -> str:
    s = f"{v:.{places}f}".rstrip("0").rstrip(".")
    return s or "0"


def scale_label(s: float) -> str:
    return f"{fmt_num(s, 2)}:1" if s >= 1 else f"1:{fmt_num(1 / s, 2)}"


@dataclass
class SheetConfig:
    page: tuple[float, float] = PAGES["a3"]
    margin: float = 10.0          # page edge -> border (pen can't reach the very edge, and paper slips)
    inner: float = 6.0            # border -> drawing area
    gap: float = 12.0             # space between views
    title: str = ""
    scale: str | float = "auto"
    dims: bool = True
    hidden: bool = True
    dash: tuple[float, float] = (2.5, 1.2)  # dash, gap in mm
    title_block: tuple[float, float] = (130.0, 24.0)
    dim_text_height: float = 3.0
    dim_pad: float = 16.0
    date: str = field(default_factory=lambda: _dt.date.today().isoformat())


@dataclass
class Sheet:
    page: tuple[float, float]
    scale: float
    layers: dict[int, list[np.ndarray]]  # layer id -> list of polylines (n,2) in sheet mm, y up
    placed: dict[str, tuple[float, float, float, float]]  # view name -> sheet bbox


# ------------------------------------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------------------------------------
def _segs_to_lines(segs: np.ndarray) -> list[np.ndarray]:
    return [s for s in segs]  # each (2,2)


def dash_polyline(pts: np.ndarray, dash: float, gap: float) -> list[np.ndarray]:
    """Cut a polyline (n,2) into dashes."""
    if len(pts) < 2:
        return []
    d = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    cum = np.concatenate([[0.0], np.cumsum(d)])
    total = cum[-1]
    if total <= dash * 1.2:
        return [pts]
    out = []
    period = dash + gap
    # centre the pattern so both ends start/end with a dash
    n = max(int(round((total + gap) / period)), 1)
    period = (total + gap) / n
    dash_len = period - gap
    for i in range(n):
        s0, s1 = i * period, i * period + dash_len
        inner = cum[(cum > s0) & (cum < s1)]
        ss = np.concatenate([[s0], inner, [s1]])
        out.append(np.stack([np.interp(ss, cum, pts[:, 0]), np.interp(ss, cum, pts[:, 1])], axis=1))
    return out


def _arrow(tip: np.ndarray, toward: np.ndarray, size: float = 2.5, half: float = 0.8) -> list[np.ndarray]:
    u = toward - tip
    u = u / (np.linalg.norm(u) + 1e-12)
    nrm = np.array([-u[1], u[0]])
    base = tip + u * size
    return [np.stack([tip, base + nrm * half]), np.stack([tip, base - nrm * half])]


def _line(a, b) -> np.ndarray:
    return np.array([a, b], float)


def choose_scale(spec: str | float, s_fit: float) -> float:
    if spec == "fit":
        return s_fit
    if spec == "auto":
        ok = [s for s in NICE_SCALES if s <= s_fit * 1.0001]
        return ok[-1] if ok else s_fit
    s = float(spec)
    if s > s_fit * 1.0001:
        print(f"warning: scale {scale_label(s)} is larger than the sheet fits ({scale_label(s_fit)}); "
              "views will overflow", file=sys.stderr)
    return s


# ------------------------------------------------------------------------------------------------
# composition
#
#   plan_layout -> where each view goes and at what scale (the "auto layout")
#   draw_view   -> one view's geometry relative to its own centre (movable as a unit)
#   frame_lines -> border + title block
#   compose     -> assemble everything, optionally with caller-supplied view centres
# ------------------------------------------------------------------------------------------------
@dataclass
class Layout:
    scale: float
    s_fit: float                                  # largest scale at which the auto layout fits
    centers: dict[str, tuple[float, float]]       # view name -> centre on the sheet (mm, y up)


@dataclass
class ViewDrawing:
    name: str
    size: tuple[float, float]                     # scaled view width/height on the sheet (mm)
    visible: np.ndarray                           # (k,2,2) segments, relative to the view centre
    hidden: np.ndarray
    notes: list[np.ndarray]                       # dimension lines/text, relative to the view centre
    box: tuple[float, float, float, float]        # local extent of everything above (for hit-testing)


def plan_layout(views: list[ViewLines], cfg: SheetConfig) -> Layout:
    W, H = cfg.page
    tb_w, tb_h = cfg.title_block

    # ---- grid occupancy -----------------------------------------------------------------------
    cells = {}
    for v in views:
        if v.name not in GRID:
            raise ValueError(f"no grid slot for view '{v.name}'")
        cells[v.name] = GRID[v.name]
    cols = sorted({c for c, _ in cells.values()})
    rows = sorted({r for _, r in cells.values()})
    ci = {c: i for i, c in enumerate(cols)}
    ri = {r: i for i, r in enumerate(rows)}
    colw = np.zeros(len(cols))
    rowh = np.zeros(len(rows))
    for v in views:
        c, r = cells[v.name]
        colw[ci[c]] = max(colw[ci[c]], v.width)
        rowh[ri[r]] = max(rowh[ri[r]], v.height)

    pad = cfg.dim_pad if cfg.dims else 0.0
    area_x0 = cfg.margin + cfg.inner
    area_x1 = W - cfg.margin - cfg.inner
    area_y0 = cfg.margin + cfg.inner + tb_h + 2.0   # keep clear of the title block
    area_y1 = H - cfg.margin - cfg.inner
    avail_w = area_x1 - area_x0
    avail_h = area_y1 - area_y0

    fixed_w = len(cols) * pad + (len(cols) - 1) * cfg.gap
    fixed_h = len(rows) * pad + (len(rows) - 1) * cfg.gap
    s_fit = min((avail_w - fixed_w) / colw.sum(), (avail_h - fixed_h) / rowh.sum())
    if s_fit <= 0:
        raise ValueError("sheet too small for the requested views")
    s = choose_scale(cfg.scale, s_fit)

    cell_w = s * colw + pad
    cell_h = s * rowh + pad
    total_w = cell_w.sum() + (len(cols) - 1) * cfg.gap
    total_h = cell_h.sum() + (len(rows) - 1) * cfg.gap
    x_start = area_x0 + (avail_w - total_w) / 2
    y_top = area_y1 - (avail_h - total_h) / 2

    col_x = x_start + np.concatenate([[0], np.cumsum(cell_w + cfg.gap)[:-1]])
    row_top = y_top - np.concatenate([[0], np.cumsum(cell_h + cfg.gap)[:-1]])

    centers = {}
    for v in views:
        c, r = cells[v.name]
        i, j = ci[c], ri[r]
        centers[v.name] = (float(col_x[i] + s * colw[i] / 2), float(row_top[j] - s * rowh[j] / 2))
    return Layout(float(s), float(s_fit), centers)


def draw_view(v: ViewLines, s: float, cfg: SheetConfig) -> ViewDrawing:
    """Scale a view and express it relative to its own centre, with its dimensions attached."""
    vc = np.array([(v.bounds[0] + v.bounds[2]) / 2, (v.bounds[1] + v.bounds[3]) / 2])
    visible = (v.visible - vc) * s if len(v.visible) else np.zeros((0, 2, 2))
    hidden = (v.hidden - vc) * s if (cfg.hidden and len(v.hidden)) else np.zeros((0, 2, 2))
    w, h = s * v.width, s * v.height
    bbox = (-w / 2, -h / 2, w / 2, h / 2)
    notes: list[np.ndarray] = []
    if cfg.dims and v.name != "iso":
        notes = _dimensions(bbox, v.width, v.height, cfg.dim_text_height)

    pts = [np.array([[bbox[0], bbox[1]], [bbox[2], bbox[3]]])]
    pts += [n for n in notes if len(n)]
    allp = np.concatenate(pts)
    box = (float(allp[:, 0].min()), float(allp[:, 1].min()), float(allp[:, 0].max()), float(allp[:, 1].max()))
    return ViewDrawing(v.name, (float(w), float(h)), visible, hidden, notes, box)


def frame_lines(cfg: SheetConfig, s: float) -> list[np.ndarray]:
    return _border_and_title(cfg, s)


def compose(
    views: list[ViewLines],
    cfg: SheetConfig,
    layout: Layout | None = None,
    centers: dict[str, tuple[float, float]] | None = None,
) -> Sheet:
    """Place views on the sheet. `centers` overrides the auto layout for the views it names."""
    layout = layout or plan_layout(views, cfg)
    s = layout.scale
    layers: dict[int, list[np.ndarray]] = {LAYER_VISIBLE: [], LAYER_HIDDEN: [], LAYER_NOTES: []}
    placed: dict[str, tuple[float, float, float, float]] = {}

    for v in views:
        cx, cy = (centers or {}).get(v.name, layout.centers[v.name])
        d = draw_view(v, s, cfg)
        off = np.array([cx, cy])
        layers[LAYER_VISIBLE].extend(_segs_to_lines(d.visible + off))
        layers[LAYER_HIDDEN].extend(_segs_to_lines(d.hidden + off))
        layers[LAYER_NOTES].extend(n + off for n in d.notes)
        placed[v.name] = (cx - d.size[0] / 2, cy - d.size[1] / 2, cx + d.size[0] / 2, cy + d.size[1] / 2)

    layers[LAYER_NOTES].extend(frame_lines(cfg, s))
    return Sheet(cfg.page, s, layers, placed)


# ------------------------------------------------------------------------------------------------
# annotation
# ------------------------------------------------------------------------------------------------
ARROW = 2.5


def _dim_axis(axis: str, t0: float, t1: float, u: float, ext_from: float, ext_to: float, label: str, th: float) -> list[np.ndarray]:
    """One dimension between t0 and t1 (along `axis`, 'h' or 'v') with its line at offset u.

    Falls back to drafting practice for narrow spans: arrows move outside the extension lines
    (pointing in), and the text moves beside them, instead of colliding in the middle.
    """
    def P(t: float, uu: float) -> np.ndarray:
        return np.array([t, uu]) if axis == "h" else np.array([uu, t])

    tw = text_width(label, th)
    span = t1 - t0
    arrows_fit = span >= 2 * ARROW + 1.0
    text_fits = span >= tw + 2 * ARROW + 2.0

    out = [_line(P(t0, ext_from), P(t0, ext_to)), _line(P(t1, ext_from), P(t1, ext_to))]
    if arrows_fit:
        out.append(_line(P(t0, u), P(t1, u)))
        out += _arrow(P(t0, u), P(t1, u)) + _arrow(P(t1, u), P(t0, u))
        tc = (t0 + t1) / 2 if text_fits else t1 + 3.0 + tw / 2
    else:
        lead = ARROW + 2.0
        out.append(_line(P(t0, u), P(t1, u)))
        out.append(_line(P(t0 - lead, u), P(t0, u)))
        out.append(_line(P(t1, u), P(t1 + lead, u)))
        out += _arrow(P(t0, u), P(t0 - ARROW, u)) + _arrow(P(t1, u), P(t1 + ARROW, u))
        tc = t1 + lead + 2.0 + tw / 2

    if axis == "h":
        out += list(text_segments(label, tc, u + 1.5, th, anchor="center"))
    else:
        out += list(text_segments(label, u + 1.5 + th, tc, th, anchor="center", angle=90))
    return out


def _dimensions(bbox, model_w: float, model_h: float, th: float) -> list[np.ndarray]:
    x0, y0, x1, y1 = bbox
    yl = y0 - 8.0   # horizontal dimension line, below the view
    xl = x1 + 8.0   # vertical dimension line, right of the view
    return (
        _dim_axis("h", x0, x1, yl, y0 - 1.5, yl - 1.5, fmt_num(model_w), th)
        + _dim_axis("v", y0, y1, xl, x1 + 1.5, xl + 1.5, fmt_num(model_h), th)
    )


def _rect(x0, y0, x1, y1) -> np.ndarray:
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]], float)


def _border_and_title(cfg: SheetConfig, s: float) -> list[np.ndarray]:
    W, H = cfg.page
    m = cfg.margin
    tb_w, tb_h = cfg.title_block
    out: list[np.ndarray] = [_rect(m, m, W - m, H - m)]

    x1, y0 = W - m, m
    x0, y1 = x1 - tb_w, y0 + tb_h
    out.append(_rect(x0, y0, x1, y1))

    # three cells: title | scale | date
    c1 = x0 + tb_w * 0.54
    c2 = x0 + tb_w * 0.77
    out.append(_line((c1, y0), (c1, y1)))
    out.append(_line((c2, y0), (c2, y1)))

    def cell(label: str, value: str, left: float, right: float) -> None:
        out.extend(text_segments(label, left + 1.5, y1 - 4.0, 2.0))
        h = 5.0
        avail = right - left - 5.0
        w = text_width(value, h)
        if w > avail > 0:
            h *= avail / w
        out.extend(text_segments(value, left + 1.5, y0 + 4.5, h))

    cell("TITLE", (cfg.title or "UNTITLED").upper(), x0, c1)
    cell("SCALE", scale_label(s), c1, c2)
    cell("DATE", cfg.date, c2, x1)
    out.extend(text_segments("DIMENSIONS IN MM - THIRD ANGLE", x0 + 1.5, y1 + 2.0, 2.0))
    return out
