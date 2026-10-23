"""Hidden-line removal for triangle meshes.

For each view:
  1. pick "interesting" mesh edges: sharp creases, silhouettes, open boundaries
  2. rasterise a depth buffer of the whole mesh
  3. split the edges into short pieces and test each piece's depth against the buffer
Pieces that pass are *visible*; the rest are *hidden* (drawn dashed by the sheet composer).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import trimesh

from .camera import Camera
from .raster import rasterize_depth


@dataclass
class ViewLines:
    name: str
    visible: np.ndarray  # (n,2,2) segments, view units (mm), x=right y=up
    hidden: np.ndarray   # (m,2,2)
    bounds: tuple[float, float, float, float]  # xmin, ymin, xmax, ymax of the projected mesh

    @property
    def width(self) -> float:
        return self.bounds[2] - self.bounds[0]

    @property
    def height(self) -> float:
        return self.bounds[3] - self.bounds[1]


def candidate_edges(
    mesh: trimesh.Trimesh, view_dir: np.ndarray, crease_angle_deg: float
) -> tuple[np.ndarray, np.ndarray]:
    """Edges worth drawing for this view direction.

    Returns (pairs, smooth_silhouette): vertex-index pairs (k,2), and a bool per pair that is
    True for silhouettes on smooth (non-creased) surfaces. Those need a more forgiving depth
    test because the surface falls away steeply right at the outline.
    """
    chunks = []
    smooth = []

    adj = mesh.face_adjacency
    if len(adj):
        edges = mesh.face_adjacency_edges
        angles = mesh.face_adjacency_angles
        # Front-facing = normal points back at the camera. Faces exactly edge-on (dot == 0,
        # common on CAD exports and symmetric meshes) deterministically count as "not front",
        # so a contour running through them is still found exactly once.
        front = (mesh.face_normals @ view_dir) < -1e-9
        sharp = angles > np.radians(crease_angle_deg)
        silhouette = front[adj[:, 0]] != front[adj[:, 1]]  # one face towards the camera, one away
        keep = sharp | silhouette
        chunks.append(edges[keep])
        smooth.append((silhouette & ~sharp)[keep])

    # open boundaries: edges used by exactly one face
    once = trimesh.grouping.group_rows(mesh.edges_sorted, require_count=1)
    if len(once):
        chunks.append(mesh.edges_sorted[once])
        smooth.append(np.zeros(len(once), dtype=bool))

    if not chunks:
        return np.zeros((0, 2), dtype=np.int64), np.zeros(0, dtype=bool)
    return np.concatenate(chunks), np.concatenate(smooth)


def _max_filter3(z: np.ndarray) -> np.ndarray:
    """3x3 maximum filter (inf propagates, which is what we want at silhouettes)."""
    out = z.copy()
    out[1:, :] = np.maximum(out[1:, :], z[:-1, :])
    out[:-1, :] = np.maximum(out[:-1, :], z[1:, :])
    tmp = out.copy()
    out[:, 1:] = np.maximum(out[:, 1:], tmp[:, :-1])
    out[:, :-1] = np.maximum(out[:, :-1], tmp[:, 1:])
    return out


def compute_view(
    mesh: trimesh.Trimesh,
    cam: Camera,
    crease_angle: float = 30.0,
    resolution: int = 2000,
    want_hidden: bool = True,
    hidden_silhouettes: bool = True,
) -> ViewLines:
    """Project `mesh` through `cam` and classify its feature edges as visible/hidden."""
    P = cam.to_view(mesh.vertices)  # (n,3): x, y, depth
    mn = P[:, :2].min(axis=0)
    mx = P[:, :2].max(axis=0)
    size = mx - mn
    pix = float(max(size.max(), 1e-9) / resolution)

    pad = 2.0 * pix
    ox, oy = mn[0] - pad, mn[1] - pad
    W = int(np.ceil((size[0] + 2 * pad) / pix)) + 2
    H = int(np.ceil((size[1] + 2 * pad) / pix)) + 2

    zbuf = np.full((H, W), np.inf, dtype=np.float64)
    rasterize_depth(np.ascontiguousarray(P[mesh.faces]), zbuf, ox, oy, pix)

    pairs, smooth = candidate_edges(mesh, cam.direction, crease_angle)
    bounds = (float(mn[0]), float(mn[1]), float(mx[0]), float(mx[1]))
    if len(pairs) == 0:
        empty = np.zeros((0, 2, 2))
        return ViewLines(cam.name, empty, empty, bounds)

    a = P[pairs[:, 0]]
    b = P[pairs[:, 1]]

    # Edges whose projected endpoints coincide (top and bottom rim of a through-hole seen
    # end-on, an outline and the edge directly behind it) would be drawn twice. Keep only
    # the nearest of each coincident group.
    q = np.round(np.concatenate([a[:, :2], b[:, :2]], axis=1) / (0.1 * pix)).astype(np.int64)
    flip = (q[:, 0] > q[:, 2]) | ((q[:, 0] == q[:, 2]) & (q[:, 1] > q[:, 3]))
    q[flip] = q[flip][:, [2, 3, 0, 1]]
    nearest_first = np.argsort(a[:, 2] + b[:, 2], kind="stable")
    _, first = np.unique(q[nearest_first], axis=0, return_index=True)
    keep_edges = np.sort(nearest_first[first])
    a, b, smooth = a[keep_edges], b[keep_edges], smooth[keep_edges]

    # edges seen end-on project to a point; a pen would plot that as a dot
    seen = np.linalg.norm(b[:, :2] - a[:, :2], axis=1) > 0.25 * pix
    a, b, smooth = a[seen], b[seen], smooth[seen]
    if len(a) == 0:
        empty = np.zeros((0, 2, 2))
        return ViewLines(cam.name, empty, empty, bounds)

    # --- subdivide long edges so partial occlusion is resolved -----------------------------
    step = 3.0 * pix
    length = np.linalg.norm(b[:, :2] - a[:, :2], axis=1)
    n = np.clip(np.ceil(length / step), 1, 4000).astype(np.int64)
    owner = np.repeat(np.arange(len(a)), n)
    start = np.cumsum(n) - n
    k = np.arange(owner.size) - np.repeat(start, n)
    t0 = (k / n[owner])[:, None]
    t1 = ((k + 1) / n[owner])[:, None]
    p0 = a[owner] + (b[owner] - a[owner]) * t0
    p1 = a[owner] + (b[owner] - a[owner]) * t1

    # --- depth test at piece midpoints --------------------------------------------------------
    mid = 0.5 * (p0 + p1)
    ix = np.clip(((mid[:, 0] - ox) / pix).astype(np.int64), 0, W - 1)
    iy = np.clip(((mid[:, 1] - oy) / pix).astype(np.int64), 0, H - 1)
    depth_range = max(P[:, 2].max() - P[:, 2].min(), 1e-9)
    tol = 0.0015 * depth_range + 2.5 * pix
    ref = zbuf[iy, ix]
    lenient = smooth[owner]
    if lenient.any():
        zmax = _max_filter3(zbuf)
        ref = np.where(lenient, zmax[iy, ix], ref)
    vis = mid[:, 2] <= ref + tol

    segs = np.stack([p0[:, :2], p1[:, :2]], axis=1)
    visible = segs[vis]
    if not want_hidden:
        return ViewLines(cam.name, visible, np.zeros((0, 2, 2)), bounds)

    # A hidden edge directly behind a visible one projects onto the same line; drawing both
    # just overpaints the solid stroke with dashes. Mask visible pieces (dilated a couple of
    # pixels) and drop hidden pieces that land on the mask.
    hid_mask = ~vis
    if not hidden_silhouettes:
        hid_mask &= ~lenient  # hidden outlines of smooth surfaces aren't physical edges
    hid_idx = np.flatnonzero(hid_mask)
    mask = np.zeros((H, W), dtype=bool)
    vix, viy = ix[vis], iy[vis]
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            mask[np.clip(viy + dy, 0, H - 1), np.clip(vix + dx, 0, W - 1)] = True
    keep = ~mask[iy[hid_idx], ix[hid_idx]]
    hidden = segs[hid_idx[keep]]
    return ViewLines(cam.name, visible, hidden, bounds)
