"""blueprint CLI.

    blueprint part.stl                       # -> part.svg, front/top/right/iso on A3
    blueprint part.step --views front,top --scale 1:2 --title "Bracket"
    blueprint plot part.svg --layer 1 --preview
    blueprint serve                          # web UI at http://127.0.0.1:8765
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .camera import VIEW_NAMES, get_camera
from .hlr import compute_view
from .loader import load_mesh
from .output import build_document, stats, write_svg
from .plot import plot_svg
from .sheet import SheetConfig, compose, parse_page, parse_scale


def _triple(s: str) -> tuple[float, float, float]:
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 3:
        raise argparse.ArgumentTypeError("expected X,Y,Z degrees, e.g. 90,0,0")
    return tuple(parts)  # type: ignore[return-value]


def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="blueprint", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("render", help="model -> blueprint SVG (default command)")
    r.add_argument("model", help="STL/OBJ/PLY/3MF (or STEP with `pip install cascadio`)")
    r.add_argument("-o", "--out", help="output SVG (default: <model>.svg)")
    r.add_argument("--views", default="front,top,right,iso", help=f"comma list from: {', '.join(VIEW_NAMES)}")
    r.add_argument("--title", help="title block text (default: file name)")
    r.add_argument("--page", default="a3", help="a2|a3|a4|letter|tabloid|WxH in mm (default a3)")
    r.add_argument("--margin", type=float, default=10.0, help="page edge to border, mm")
    r.add_argument("--scale", default="auto", help="auto (nearest standard that fits) | fit | 1:2 | 2:1 | 0.5")
    r.add_argument("--angle", type=float, default=30.0, help="crease angle in degrees: edges sharper than this are drawn")
    r.add_argument("--resolution", type=int, default=2000, help="depth-buffer resolution along longest side (visibility accuracy)")
    r.add_argument("--no-hidden", action="store_true", help="omit hidden (dashed) lines")
    r.add_argument("--no-hidden-silhouettes", action="store_true",
                   help="drop hidden outlines of smooth surfaces (cleaner for organic meshes; keep for bores/holes)")
    r.add_argument("--no-dims", action="store_true", help="omit overall dimensions")
    r.add_argument("--no-optimize", action="store_true", help="skip vpype path simplify/sort")
    r.add_argument("--up", choices=["z", "y"], default="z", help="up axis of the source file (default z)")
    r.add_argument("--rotate", type=_triple, default=(0, 0, 0), metavar="X,Y,Z", help="extra rotation in degrees")
    r.add_argument("--model-scale", type=float, default=1.0, help="multiply model units (25.4 if the file is in inches)")

    w = sub.add_parser("serve", help="start the local web UI")
    w.add_argument("--host", default="127.0.0.1", help="bind address (default: localhost only)")
    w.add_argument("--port", type=int, default=8765)
    w.add_argument("--no-browser", action="store_true", help="don't open a browser tab")

    p = sub.add_parser("plot", help="send an SVG to the AxiDraw via axicli")
    p.add_argument("svg")
    p.add_argument("--model", type=int, default=2, help="AxiDraw model (2 = A3, default)")
    p.add_argument("--layer", type=int, help="plot only this layer/pen (1 visible, 2 hidden, 3 notes)")
    p.add_argument("--preview", action="store_true", help="simulate only; print time estimate")
    p.add_argument("--speed-pendown", type=int, help="pen-down speed %% (axicli --speed_pendown)")
    return ap


def _render(args: argparse.Namespace) -> int:
    t0 = time.time()
    model_path = Path(args.model)
    out = Path(args.out) if args.out else model_path.with_suffix(".svg")

    mesh = load_mesh(model_path, up=args.up, rotate=args.rotate, model_scale=args.model_scale)
    ext = mesh.extents
    print(f"loaded {model_path.name}: {len(mesh.faces):,} triangles, "
          f"{ext[0]:.1f} x {ext[1]:.1f} x {ext[2]:.1f} mm (X x Y x Z)")

    names = [v.strip() for v in args.views.split(",") if v.strip()]
    views = []
    for name in names:
        cam = get_camera(name)
        v = compute_view(mesh, cam, crease_angle=args.angle, resolution=args.resolution, want_hidden=not args.no_hidden,
                         hidden_silhouettes=not args.no_hidden_silhouettes)
        print(f"  {name:<6} {len(v.visible):>7,} visible / {len(v.hidden):>7,} hidden pieces")
        views.append(v)

    cfg = SheetConfig(
        page=parse_page(args.page),
        margin=args.margin,
        title=args.title or model_path.stem,
        scale=parse_scale(args.scale),
        dims=not args.no_dims,
        hidden=not args.no_hidden,
    )
    sheet = compose(views, cfg)
    doc = build_document(sheet, dash=cfg.dash, optimize=not args.no_optimize)
    write_svg(doc, out)

    from .sheet import scale_label

    print(f"wrote {out}  (scale {scale_label(sheet.scale)}, {time.time() - t0:.1f}s)")
    print(stats(doc))
    return 0


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `blueprint part.stl ...` is shorthand for `blueprint render part.stl ...`
    if argv and argv[0] not in ("render", "plot", "serve", "-h", "--help"):
        argv.insert(0, "render")
    args = _build_parser().parse_args(argv)
    if args.cmd == "serve":
        try:
            from .server import serve
        except ImportError as exc:
            print(f"error: web extras missing ({exc}). Run: pip install -e \".[web]\"", file=sys.stderr)
            sys.exit(2)
        serve(args.host, args.port, open_browser=not args.no_browser)
        return
    if args.cmd == "render":
        try:
            sys.exit(_render(args))
        except (ValueError, FileNotFoundError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            sys.exit(2)
    sys.exit(plot_svg(args.svg, model=args.model, layer=args.layer, preview=args.preview, speed_pendown=args.speed_pendown))


if __name__ == "__main__":
    main()
