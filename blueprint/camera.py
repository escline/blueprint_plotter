"""Orthographic cameras for the standard drafting views (model is Z-up, front faces -Y)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Camera:
    name: str
    direction: np.ndarray  # unit vector the camera looks along (towards the model)
    right: np.ndarray
    up: np.ndarray

    @classmethod
    def look(cls, name: str, direction, up_hint) -> "Camera":
        d = np.asarray(direction, float)
        d /= np.linalg.norm(d)
        right = np.cross(d, np.asarray(up_hint, float))
        right /= np.linalg.norm(right)
        up = np.cross(right, d)
        return cls(name, d, right, up)

    def to_view(self, points: np.ndarray) -> np.ndarray:
        """Model coords (n,3) -> view coords (n,3): x=right, y=up, z=depth (bigger = farther)."""
        basis = np.stack([self.right, self.up, self.direction])  # (3,3) rows
        return np.asarray(points, float) @ basis.T


# name -> (view direction, up hint)
_DEFS = {
    "front": ((0, 1, 0), (0, 0, 1)),     # viewer at -Y
    "back": ((0, -1, 0), (0, 0, 1)),
    "right": ((-1, 0, 0), (0, 0, 1)),    # viewer at +X (sits to the right of front in 3rd-angle)
    "left": ((1, 0, 0), (0, 0, 1)),
    "top": ((0, 0, -1), (0, 1, 0)),      # viewer above
    "bottom": ((0, 0, 1), (0, -1, 0)),
    "iso": ((-1, 1, -1), (0, 0, 1)),     # viewer at front-right-top
}

VIEW_NAMES = tuple(_DEFS)


def get_camera(name: str) -> Camera:
    try:
        d, up = _DEFS[name.lower()]
    except KeyError:
        raise ValueError(f"unknown view '{name}'. choose from: {', '.join(VIEW_NAMES)}") from None
    return Camera.look(name.lower(), d, up)
