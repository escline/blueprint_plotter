"""Turn a composed Sheet into a plotter-ready, layered, path-optimised SVG (via vpype)."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import vpype as vp
import vpype_cli

from .sheet import LAYER_HIDDEN, Sheet, dash_polyline

LAYER_NAMES = {1: "visible", 2: "hidden", 3: "notes"}


def _to_lc(lines: list[np.ndarray], page_h: float, mm: float) -> vp.LineCollection:
    lc = vp.LineCollection()
    for p in lines:
        p = np.asarray(p, float)
        if len(p) >= 2:
            lc.append((p[:, 0] + 1j * (page_h - p[:, 1])) * mm)
    return lc


def _from_lc(lc: vp.LineCollection, page_h: float, mm: float) -> list[np.ndarray]:
    return [np.stack([l.real / mm, page_h - l.imag / mm], axis=1) for l in lc.lines]


def merge_segments(segs: np.ndarray | list[np.ndarray], tol_mm: float = 0.05) -> list[np.ndarray]:
    """Stitch loose segments/polylines (sheet-mm coordinates) into long strokes. Returns (n,2) arrays."""
    lc = vp.LineCollection()
    for p in segs:
        p = np.asarray(p, float)
        if len(p) >= 2:
            lc.append(p[:, 0] + 1j * p[:, 1])
    lc.merge(tolerance=tol_mm)
    return [np.stack([l.real, l.imag], axis=1) for l in lc.lines]


def build_document(
    sheet: Sheet,
    dash: tuple[float, float] = (2.5, 1.2),
    optimize: bool = True,
    merge_tol_mm: float = 0.05,
) -> vp.Document:
    W, H = sheet.page
    mm = vp.convert_length("1mm")
    doc = vp.Document(page_size=(W * mm, H * mm))

    for layer_id, lines in sheet.layers.items():
        if not lines:
            continue
        lc = _to_lc(lines, H, mm)
        lc.merge(tolerance=merge_tol_mm * mm)  # stitch tiny segments into long strokes

        if layer_id == LAYER_HIDDEN and dash[0] > 0:
            dashed: list[np.ndarray] = []
            for poly in _from_lc(lc, H, mm):
                dashed.extend(dash_polyline(poly, dash[0], dash[1]))
            lc = _to_lc(dashed, H, mm)
        doc.add(lc, layer_id=layer_id)

    if optimize:
        # drop collinear points, then order strokes to minimise pen-up travel
        doc = vpype_cli.execute("linesimplify -t 0.02mm linesort", doc)
    return doc


def svg_string(doc: vp.Document) -> str:
    import io

    buf = io.StringIO()
    vp.write_svg(buf, doc, source_string="blueprint-plotter", color_mode="layer", layer_label_format="%d")
    return buf.getvalue()


def stats_dict(doc: vp.Document) -> dict:
    """Per-layer stroke counts and pen-down length in mm."""
    mm = vp.convert_length("1mm")
    layers = {str(lid): {"strokes": len(doc.layers[lid].lines), "length_mm": round(doc.layers[lid].length() / mm, 1)}
              for lid in sorted(doc.layers)}
    return {"layers": layers, "total_mm": round(sum(l["length_mm"] for l in layers.values()), 1)}


def write_svg(doc: vp.Document, path: str | Path) -> None:
    path = Path(path)
    with open(path, "w", encoding="utf-8") as f:
        vp.write_svg(f, doc, source_string="blueprint-plotter", color_mode="layer", layer_label_format="%d")


def stats(doc: vp.Document) -> str:
    mm = vp.convert_length("1mm")
    parts = []
    total = 0.0
    for lid in sorted(doc.layers):
        lc = doc.layers[lid]
        length = lc.length() / mm
        total += length
        parts.append(f"  layer {lid} ({LAYER_NAMES.get(lid, '?')}): {len(lc.lines)} strokes, {length / 1000:.2f} m")
    parts.append(f"  total pen-down: {total / 1000:.2f} m")
    return "\n".join(parts)
