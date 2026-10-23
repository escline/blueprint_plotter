"""Thin wrapper that shells out to Bantam Tools' `nextdraw` CLI, or the older `axicli`.

Both take the same flags. `nextdraw` defaults to a NextDraw model, so `--model` is always passed.
AxiDraw model numbers: 1 = V2/V3 A4, 2 = V3/SE A3 (this project's default), 3 = XLX, 5 = A1, 6 = A2.
Pen-lift codes: 1 = model default (standard servo), 3 = narrow-band brushless servo (this project's default).
With the wrong pen-lift code the pen never lowers, and the plot runs "in the air".

Verified on an AxiDraw SE/A3 with brushless pen lift (NextDraw 1.7.5, firmware 3.0.3).
"""
from __future__ import annotations

import shutil
import subprocess
import sys

PLOTTER_CLIS = ("nextdraw", "axicli")


def find_plotter_cli() -> str | None:
    for name in PLOTTER_CLIS:
        exe = shutil.which(name)
        if exe:
            return exe
    return None


def plot_svg(
    svg: str,
    model: int = 2,
    penlift: int = 3,
    layer: int | None = None,
    preview: bool = False,
    speed_pendown: int | None = None,
    extra: list[str] | None = None,
) -> int:
    exe = find_plotter_cli()
    if exe is None:
        print("Neither nextdraw nor axicli found. Install the NextDraw CLI (see README), then retry.", file=sys.stderr)
        return 127

    cmd = [exe, svg, "--model", str(model), "--penlift", str(penlift)]
    if layer is not None:
        cmd += ["--mode", "layers", "--layer", str(layer)]
    if preview:
        cmd += ["--preview", "--report_time"]
    if speed_pendown is not None:
        cmd += ["--speed_pendown", str(speed_pendown)]
    cmd += extra or []

    print("running:", " ".join(cmd), flush=True)
    return subprocess.call(cmd)
