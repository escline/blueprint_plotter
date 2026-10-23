"""Thin wrapper that shells out to AxiDraw's `axicli`.

NOTE: not exercised against real hardware in development - run with --preview first.
AxiDraw model numbers: 1 = V3/SE A4, 2 = V3/SE A3 (this project's default), 3 = XLX, 5 = A1, 6 = A2.
"""
from __future__ import annotations

import shutil
import subprocess
import sys


def plot_svg(
    svg: str,
    model: int = 2,
    layer: int | None = None,
    preview: bool = False,
    speed_pendown: int | None = None,
    extra: list[str] | None = None,
) -> int:
    exe = shutil.which("axicli")
    if exe is None:
        print("axicli not found. Install the AxiDraw CLI/API (see README), then retry.", file=sys.stderr)
        return 127

    cmd = [exe, svg, "--model", str(model)]
    if layer is not None:
        cmd += ["--mode", "layers", "--layer", str(layer)]
    if preview:
        cmd += ["--preview"]
    if speed_pendown is not None:
        cmd += ["--speed_pendown", str(speed_pendown)]
    cmd += extra or []

    print("running:", " ".join(cmd))
    return subprocess.call(cmd)
