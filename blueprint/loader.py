"""Load and normalise meshes (STL/OBJ/PLY/3MF, and STEP if `cascadio` is installed)."""
from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import trimesh


def _rot(axis: str, degrees: float) -> np.ndarray:
    return trimesh.transformations.rotation_matrix(np.radians(degrees), {"x": [1, 0, 0], "y": [0, 1, 0], "z": [0, 0, 1]}[axis])


RotationSteps = Sequence[tuple[str, float]]  # e.g. [("x", 90), ("z", -90)] applied in order about world axes


def load_raw(path: str | Path, name: str | None = None) -> trimesh.Trimesh:
    """Load a model file and return a cleaned, consistently-wound mesh in its native orientation/units.

    `name` is the name to show in error messages (the server loads from a temp file).
    """
    path = Path(path)
    name = name or path.name
    if not path.exists():
        raise FileNotFoundError(path)

    loaded = trimesh.load(str(path), force="mesh", process=True)
    if isinstance(loaded, trimesh.Scene):  # defensive: force="mesh" normally concatenates already
        loaded = loaded.to_geometry() if hasattr(loaded, "to_geometry") else loaded.dump(concatenate=True)
    mesh: trimesh.Trimesh = loaded
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise ValueError(f"{name} did not contain a triangle mesh")

    mesh.update_faces(mesh.nondegenerate_faces())
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    if not mesh.is_winding_consistent:
        try:
            trimesh.repair.fix_winding(mesh)
            trimesh.repair.fix_normals(mesh)
        except Exception as exc:  # pragma: no cover - best effort
            print(f"warning: could not repair winding ({exc}); silhouettes may be noisy", file=sys.stderr)
    return mesh


def orient(
    raw: trimesh.Trimesh,
    up: str = "z",
    steps: RotationSteps = (),
    model_scale: float = 1.0,
) -> trimesh.Trimesh:
    """Return a copy of `raw` in millimetres, Z-up, centred on the origin.

    up           -- which axis the *file* treats as up ("z" or "y"); Y-up files are rotated to Z-up
    steps        -- extra rotations [(axis, degrees), ...] applied in order after `up`
    model_scale  -- multiply coordinates (e.g. 25.4 if the file is in inches)
    """
    mesh = raw.copy()
    up = up.lower()
    if up == "y":
        mesh.apply_transform(_rot("x", 90))
    elif up != "z":
        raise ValueError("up must be 'z' or 'y'")
    for axis, deg in steps:
        axis = axis.lower()
        if axis not in "xyz" or len(axis) != 1:
            raise ValueError(f"bad rotation axis '{axis}'")
        if deg:
            mesh.apply_transform(_rot(axis, float(deg)))
    if model_scale != 1.0:
        mesh.apply_scale(model_scale)
    mesh.apply_translation(-mesh.bounds.mean(axis=0))  # centre on origin
    return mesh


def load_mesh(
    path: str | Path,
    up: str = "z",
    rotate: tuple[float, float, float] = (0.0, 0.0, 0.0),
    model_scale: float = 1.0,
) -> trimesh.Trimesh:
    """Load + orient in one go (CLI path). `rotate` is (rx, ry, rz) degrees, applied x then y then z."""
    return orient(load_raw(path), up=up, steps=list(zip("xyz", rotate)), model_scale=model_scale)
