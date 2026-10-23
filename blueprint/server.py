"""Local web server: upload a model, preview the sheet, drag views around, export the SVG.

    blueprint serve            # http://127.0.0.1:8765

The browser does the interactive part (dragging views is purely client-side). This server
does the heavy lifting once per change and returns per-view geometry in view-local
coordinates, so a view can be moved without recomputing anything. Export reuses the exact
CLI pipeline, so what you download is what the CLI would produce.
"""
from __future__ import annotations

import dataclasses
import json
import re
import tempfile
import threading
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Literal

import numpy as np
import trimesh
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .camera import VIEW_NAMES, get_camera
from .hlr import ViewLines, compute_view
from .loader import load_raw, orient
from .output import build_document, merge_segments, stats_dict, svg_string
from .sheet import PAGES, SheetConfig, compose, draw_view, frame_lines, parse_page, parse_scale, plan_layout, scale_label

WEB_DIR = Path(__file__).parent / "web"
STATIC_DIR = WEB_DIR / "static"
SAMPLES_DIR = WEB_DIR / "samples"

MAX_UPLOAD_BYTES = 300 * 1024 * 1024
ALLOWED_EXT = {".stl", ".obj", ".ply", ".3mf", ".off", ".glb", ".gltf", ".step", ".stp"}
MAX_MODELS = 8

# ------------------------------------------------------------------------------------------------
# model store (in memory, single-user local tool)
# ------------------------------------------------------------------------------------------------
_lock = threading.Lock()
_models: "OrderedDict[str, tuple[str, trimesh.Trimesh]]" = OrderedDict()  # id -> (file name, raw mesh)


def _store(name: str, mesh: trimesh.Trimesh) -> str:
    import uuid

    mid = uuid.uuid4().hex[:12]
    with _lock:
        _models[mid] = (name, mesh)
        while len(_models) > MAX_MODELS:
            _models.popitem(last=False)
    _oriented.cache_clear()
    _view_lines.cache_clear()
    _merged.cache_clear()
    return mid


def _get(mid: str) -> tuple[str, trimesh.Trimesh]:
    with _lock:
        if mid not in _models:
            raise HTTPException(404, "Model not found. Upload it again (the server may have restarted).")
        return _models[mid]


# ------------------------------------------------------------------------------------------------
# request models
# ------------------------------------------------------------------------------------------------
class Orientation(BaseModel):
    up: Literal["z", "y"] = "z"
    steps: list[tuple[Literal["x", "y", "z"], float]] = []
    model_scale: float = Field(1.0, gt=0, le=100000)


class SheetRequest(BaseModel):
    model_id: str
    orientation: Orientation = Orientation()
    views: list[str] = ["front", "top", "right", "iso"]
    angle: float = Field(30.0, ge=1, le=89)
    resolution: int = Field(2000, ge=500, le=6000)
    hidden: bool = True
    hidden_silhouettes: bool = True
    dims: bool = True
    page: str = "a3"
    margin: float = Field(10.0, ge=0, le=80)
    title: str = Field("", max_length=80)
    scale: str = "auto"
    placements: dict[str, tuple[float, float]] | None = None


# ------------------------------------------------------------------------------------------------
# cached computation
# ------------------------------------------------------------------------------------------------
def _okey(o: Orientation) -> tuple:
    return (o.up, tuple((a, float(d)) for a, d in o.steps), float(o.model_scale))


@lru_cache(maxsize=4)
def _oriented(mid: str, okey: tuple) -> trimesh.Trimesh:
    _, raw = _get(mid)
    up, steps, ms = okey
    return orient(raw, up=up, steps=list(steps), model_scale=ms)


@lru_cache(maxsize=64)
def _view_lines(mid: str, okey: tuple, view: str, angle: float, res: int, want_hidden: bool, hs: bool) -> ViewLines:
    return compute_view(
        _oriented(mid, okey), get_camera(view), crease_angle=angle, resolution=res,
        want_hidden=want_hidden, hidden_silhouettes=hs,
    )


@lru_cache(maxsize=64)
def _merged(mid: str, okey: tuple, view: str, angle: float, res: int, want_hidden: bool, hs: bool):
    """Visible/hidden strokes for a view, merged into long polylines in view units."""
    v = _view_lines(mid, okey, view, angle, res, want_hidden, hs)
    return merge_segments(v.visible, 1e-3), merge_segments(v.hidden, 1e-3)


def _prepare(req: SheetRequest):
    name, _ = _get(req.model_id)
    names: list[str] = []
    for n in req.views:
        n = n.lower()
        if n not in VIEW_NAMES:
            raise HTTPException(400, f"Unknown view '{n}'. Choose from: {', '.join(VIEW_NAMES)}.")
        if n not in names:
            names.append(n)
    if not names:
        raise HTTPException(400, "Select at least one view.")
    try:
        cfg = SheetConfig(
            page=parse_page(req.page),
            margin=req.margin,
            title=req.title or Path(name).stem,
            scale=parse_scale(req.scale),
            dims=req.dims,
            hidden=req.hidden,
        )
        ok = _okey(req.orientation)
        mesh = _oriented(req.model_id, ok)
        views = [_view_lines(req.model_id, ok, n, req.angle, req.resolution, req.hidden, req.hidden_silhouettes) for n in names]
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return names, cfg, ok, mesh, views


def _flat(polys, decimals: int = 3) -> list[list[float]]:
    return [np.round(np.asarray(p, float), decimals).ravel().tolist() for p in polys]


def _poly_len(polys) -> float:
    return float(sum(np.linalg.norm(np.diff(np.asarray(p), axis=0), axis=1).sum() for p in polys if len(p) > 1))


# ------------------------------------------------------------------------------------------------
# app
# ------------------------------------------------------------------------------------------------
app = FastAPI(title="blueprint-plotter", version=__version__)


def _model_info(mid: str, name: str, mesh: trimesh.Trimesh) -> dict:
    return {"id": mid, "name": name, "triangles": int(len(mesh.faces)), "extents": [round(float(x), 3) for x in mesh.extents]}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "version": __version__}


@app.get("/api/config")
def config() -> dict:
    return {"pages": {k: list(v) for k, v in PAGES.items()}, "views": list(VIEW_NAMES)}


@app.post("/api/models")
async def upload_model(file: UploadFile = File(...)) -> dict:
    name = Path(file.filename or "model").name
    ext = Path(name).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Use one of: {', '.join(sorted(ALLOWED_EXT))}.")
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / f"model{ext}"
        size = 0
        with open(dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "File is larger than 300 MB.")
                out.write(chunk)
        try:
            mesh = await run_in_threadpool(load_raw, dest, name)
        except ValueError as exc:  # our own message already names the file
            raise HTTPException(400, f"{exc}.") from exc
        except Exception as exc:  # trimesh raises many things for bad files
            hint = " STEP files need `pip install cascadio`." if ext in (".step", ".stp") else ""
            raise HTTPException(400, f"Could not read {name}: {exc}.{hint}") from exc
    mid = _store(name, mesh)
    return _model_info(mid, name, mesh)


@app.get("/api/samples")
def list_samples() -> list[str]:
    return sorted(p.stem for p in SAMPLES_DIR.glob("*.stl")) if SAMPLES_DIR.exists() else []


@app.post("/api/samples/{name}")
def load_sample(name: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_\-]+", name) or not (SAMPLES_DIR / f"{name}.stl").exists():
        raise HTTPException(404, "No such sample.")
    mesh = load_raw(SAMPLES_DIR / f"{name}.stl")
    return _model_info(_store(f"{name}.stl", mesh), f"{name}.stl", mesh)


@app.post("/api/compose")
def compose_preview(req: SheetRequest) -> dict:
    names, cfg, ok, mesh, views = _prepare(req)
    layout = plan_layout(views, cfg)
    s = layout.scale
    dash, gap = cfg.dash

    out_views: dict = {}
    len_vis = len_hid = len_notes = 0.0
    strokes_vis = strokes_hid = 0
    empty = np.zeros((0, 2, 2))
    for n, v in zip(names, views):
        vc = np.array([(v.bounds[0] + v.bounds[2]) / 2, (v.bounds[1] + v.bounds[3]) / 2])
        vis_m, hid_m = _merged(req.model_id, ok, n, req.angle, req.resolution, req.hidden, req.hidden_silhouettes)
        vis = [(p - vc) * s for p in vis_m]
        hid = [(p - vc) * s for p in hid_m] if cfg.hidden else []
        d = draw_view(dataclasses.replace(v, visible=empty, hidden=empty), s, cfg)  # dims + box only
        center = (req.placements or {}).get(n, layout.centers[n])
        out_views[n] = {
            "center": [round(center[0], 3), round(center[1], 3)],
            "size": [round(d.size[0], 3), round(d.size[1], 3)],
            "box": [round(x, 3) for x in d.box],
            "extents": [round(v.width, 3), round(v.height, 3)],
            "visible": _flat(vis),
            "hidden": _flat(hid),
            "notes": _flat(d.notes),
        }
        len_vis += _poly_len(vis)
        len_hid += _poly_len(hid)
        len_notes += _poly_len(d.notes)
        strokes_vis += len(vis)
        strokes_hid += len(hid)

    frame = frame_lines(cfg, s)
    len_notes += _poly_len(frame)
    return {
        "page": list(cfg.page),
        "scale": round(s, 6),
        "scale_label": scale_label(s),
        "fit_scale": round(layout.s_fit, 6),
        "fit_label": scale_label(layout.s_fit),
        "overflow": bool(s > layout.s_fit * 1.0001),
        "extents": [round(float(x), 3) for x in mesh.extents],
        "dash": [dash, gap],
        "frame": _flat(frame),
        "views": out_views,
        "layers": {
            # hidden lines are dashed on export, so ink length is only the dash fraction (approximate)
            "1": {"strokes": strokes_vis, "length_mm": round(len_vis, 1)},
            "2": {"strokes": strokes_hid, "length_mm": round(len_hid * dash / (dash + gap), 1)},
            "3": {"strokes": None, "length_mm": round(len_notes, 1)},
        },
    }


@app.post("/api/export")
def export_svg(req: SheetRequest) -> Response:
    names, cfg, ok, mesh, views = _prepare(req)
    layout = plan_layout(views, cfg)
    sheet = compose(views, cfg, layout=layout, centers=req.placements)
    doc = build_document(sheet, dash=cfg.dash, optimize=True)
    name, _ = _get(req.model_id)
    stem = re.sub(r"[^A-Za-z0-9_\-]+", "_", cfg.title or Path(name).stem).strip("_") or "blueprint"
    stats = stats_dict(doc)
    stats["scale_label"] = scale_label(sheet.scale)
    return Response(
        content=svg_string(doc),
        media_type="image/svg+xml",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.svg"',
            "X-Blueprint-Stats": json.dumps(stats),
        },
    )


# ------------------------------------------------------------------------------------------------
# static front-end
# ------------------------------------------------------------------------------------------------
if (STATIC_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/", response_model=None)
def index():
    page = STATIC_DIR / "index.html"
    if page.exists():
        return FileResponse(page)
    return HTMLResponse(
        "<h1>blueprint-plotter</h1><p>The web UI hasn't been built. From <code>web/</code> run "
        "<code>npm install &amp;&amp; npm run build</code>, or run <code>npm run dev</code> for development. "
        "The API is live at <a href='/docs'>/docs</a>.</p>",
        status_code=200,
    )


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import threading as _t
    import webbrowser

    import uvicorn

    url = f"http://{host}:{port}"
    if open_browser:
        _t.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"blueprint-plotter UI on {url}  (Ctrl+C to stop)")
    uvicorn.run(app, host=host, port=port, log_level="warning")
