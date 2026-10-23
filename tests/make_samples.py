"""Generate a few sample STL files for testing (no external assets needed)."""
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Point, Polygon

out = Path(__file__).resolve().parent.parent / "samples"
out.mkdir(exist_ok=True)

# 1. flat plate with a big hole, two small holes and a notch  (80 x 50 x 8)
plate = Polygon([(0, 0), (80, 0), (80, 50), (30, 50), (30, 38), (0, 38)])
plate = plate.difference(Point(40, 20).buffer(10, 48)).difference(Point(10, 10).buffer(3, 32)).difference(Point(70, 40).buffer(3, 32))
m = trimesh.creation.extrude_polygon(plate, 8)
m.export(out / "plate.stl")

# 2. stepped cylinder with a blind pocket on top: tests hidden lines
base = trimesh.creation.cylinder(radius=30, height=12, sections=96)
mid = trimesh.creation.cylinder(radius=18, height=20, sections=96)
mid.apply_translation([0, 0, 16])
top = trimesh.creation.cylinder(radius=8, height=14, sections=96)
top.apply_translation([0, 0, 33])
step = trimesh.boolean.union([base, mid, top], engine="manifold")
step.export(out / "stepped_cylinder.stl")

# 3. torus: smooth surface -> silhouettes only
trimesh.creation.torus(major_radius=30, minor_radius=10, major_sections=72, minor_sections=36).export(out / "torus.stl")
print("wrote", sorted(p.name for p in out.glob("*.stl")))
