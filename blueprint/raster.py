"""Tiny depth-only software rasteriser used for hidden-line tests.

Uses numba when available (fast); falls back to plain Python (works, but slow on big meshes).
"""
from __future__ import annotations

import math

try:
    from numba import njit

    HAVE_NUMBA = True
except Exception:  # pragma: no cover
    HAVE_NUMBA = False

    def njit(*args, **kwargs):  # type: ignore
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return lambda f: f


@njit(cache=True)
def rasterize_depth(tri, zbuf, ox, oy, pix):
    """Fill `zbuf` (H,W) with the nearest depth per pixel.

    tri  -- (n,3,3) float64: per-vertex view-space x, y, depth
    ox,oy -- view-space coordinate of the buffer's (0,0) pixel corner
    pix  -- pixel edge length in view units
    """
    H, W = zbuf.shape
    eps = 1e-4
    for t in range(tri.shape[0]):
        x0 = (tri[t, 0, 0] - ox) / pix
        y0 = (tri[t, 0, 1] - oy) / pix
        x1 = (tri[t, 1, 0] - ox) / pix
        y1 = (tri[t, 1, 1] - oy) / pix
        x2 = (tri[t, 2, 0] - ox) / pix
        y2 = (tri[t, 2, 1] - oy) / pix
        z0 = tri[t, 0, 2]
        z1 = tri[t, 1, 2]
        z2 = tri[t, 2, 2]

        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-12:
            continue  # edge-on triangle: no coverage

        ix0 = max(int(math.floor(min(x0, x1, x2) - 0.5)), 0)
        ix1 = min(int(math.ceil(max(x0, x1, x2) + 0.5)), W - 1)
        iy0 = max(int(math.floor(min(y0, y1, y2) - 0.5)), 0)
        iy1 = min(int(math.ceil(max(y0, y1, y2) + 0.5)), H - 1)

        inv = 1.0 / area
        for iy in range(iy0, iy1 + 1):
            py = iy + 0.5
            for ix in range(ix0, ix1 + 1):
                px = ix + 0.5
                w0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) * inv
                w1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) * inv
                w2 = 1.0 - w0 - w1
                if w0 >= -eps and w1 >= -eps and w2 >= -eps:
                    z = w0 * z0 + w1 * z1 + w2 * z2
                    if z < zbuf[iy, ix]:
                        zbuf[iy, ix] = z
