import numpy as np
import pytest
import trimesh

from blueprint.camera import get_camera
from blueprint.hlr import compute_view
from blueprint.output import build_document
from blueprint.sheet import SheetConfig, compose, parse_scale


def _box(extents=(40, 20, 10)):
    return trimesh.creation.box(extents=extents)


def test_box_front_view_is_a_rectangle():
    v = compute_view(_box(), get_camera("front"), resolution=800)
    assert v.width == pytest.approx(40) and v.height == pytest.approx(10)
    xs = v.visible[..., 0]
    ys = v.visible[..., 1]
    assert xs.min() == pytest.approx(-20, abs=0.1) and xs.max() == pytest.approx(20, abs=0.1)
    assert ys.min() == pytest.approx(-5, abs=0.1) and ys.max() == pytest.approx(5, abs=0.1)


def test_hidden_edges_behind_box_are_not_duplicated():
    # in the front view the back edges sit exactly behind the front ones -> nothing extra to draw
    v = compute_view(_box(), get_camera("front"), resolution=800)
    assert len(v.hidden) == 0


def test_iso_box_has_three_hidden_edges():
    v = compute_view(_box(), get_camera("iso"), resolution=1200)
    assert len(v.hidden) > 0
    total_hidden = np.linalg.norm(v.hidden[:, 1] - v.hidden[:, 0], axis=1).sum()
    # hidden corner edges: 40 + 20 + 10 mm projected under iso foreshortening (roughly 0.5-0.82 each)
    assert 25 < total_hidden < 70


def test_edge_on_faces_do_not_break_silhouettes():
    # 64-gon prism: facets exactly parallel to the view direction (dot == 0)
    cyl = trimesh.creation.cylinder(radius=10, height=30, sections=64)
    v = compute_view(cyl, get_camera("front"), resolution=800)
    left = v.visible[(v.visible[..., 0] < -9.9).all(axis=1)]
    right = v.visible[(v.visible[..., 0] > 9.9).all(axis=1)]
    assert len(left) and len(right), "both silhouette sides must be found"


def test_compose_and_document():
    mesh = _box()
    views = [compute_view(mesh, get_camera(n), resolution=600) for n in ("front", "top", "right", "iso")]
    sheet = compose(views, SheetConfig(title="t"))
    assert sheet.scale > 0
    doc = build_document(sheet)
    assert set(doc.layers) == {1, 2, 3}


def test_parse_scale():
    assert parse_scale("1:2") == 0.5 and parse_scale("2:1") == 2.0 and parse_scale("auto") == "auto"
