import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from blueprint.server import app  # noqa: E402

client = TestClient(app)


@pytest.fixture(scope="module")
def model():
    r = client.post("/api/samples/plate")
    assert r.status_code == 200
    return r.json()


def _req(model, **kw):
    body = {"model_id": model["id"], "resolution": 800}
    body.update(kw)
    return body


def test_sample_info(model):
    assert model["name"] == "plate.stl"
    assert model["extents"] == pytest.approx([80, 50, 8], abs=0.01)


def test_compose_returns_local_view_geometry(model):
    r = client.post("/api/compose", json=_req(model))
    assert r.status_code == 200
    d = r.json()
    assert d["page"] == [420, 297]
    assert set(d["views"]) == {"front", "top", "right", "iso"}
    top = d["views"]["top"]
    assert top["extents"] == pytest.approx([80, 50], abs=0.01)
    # geometry is relative to the view centre, so it must straddle the origin
    xs = [x for poly in top["visible"] for x in poly[0::2]]
    assert min(xs) < 0 < max(xs)
    assert d["layers"]["1"]["length_mm"] > 0 and d["frame"]


def test_placements_override_centres(model):
    r = client.post("/api/compose", json=_req(model, placements={"top": [111.0, 222.0]}))
    v = r.json()["views"]
    assert v["top"]["center"] == [111.0, 222.0]
    assert v["front"]["center"] != [111.0, 222.0]


def test_scale_overflow_flag(model):
    r = client.post("/api/compose", json=_req(model, scale="50:1"))
    assert r.json()["overflow"] is True
    r = client.post("/api/compose", json=_req(model, scale="1:2"))
    assert r.json()["overflow"] is False and r.json()["scale_label"] == "1:2"


def test_rotation_steps_change_the_views(model):
    base = client.post("/api/compose", json=_req(model, views=["front"])).json()["views"]["front"]["extents"]
    rot = client.post("/api/compose", json=_req(model, views=["front"], orientation={"steps": [["x", 90]]})).json()
    assert base == pytest.approx([80, 8], abs=0.01)
    assert rot["views"]["front"]["extents"] == pytest.approx([80, 50], abs=0.01)  # plate stood on its edge


def test_export_is_layered_svg_and_honours_placements(model):
    r = client.post("/api/export", json=_req(model, title="Test plate"))
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    assert 'inkscape:label="1"' in r.text and 'inkscape:label="3"' in r.text
    stats = json.loads(r.headers["x-blueprint-stats"])
    assert stats["total_mm"] > 0 and stats["layers"]["1"]["strokes"] > 0
    moved = client.post("/api/export", json=_req(model, placements={"iso": [60.0, 60.0]}))
    assert moved.status_code == 200 and moved.text != r.text


@pytest.mark.parametrize(
    "patch,code",
    [({"views": ["sideways"]}, 400), ({"views": []}, 400), ({"page": "a9"}, 400), ({"scale": "huge"}, 400), ({"model_id": "nope"}, 404)],
)
def test_bad_requests(model, patch, code):
    r = client.post("/api/compose", json=_req(model, **patch))
    assert r.status_code == code, r.text


def test_upload_rejects_bad_type_and_garbage():
    assert client.post("/api/models", files={"file": ("x.exe", b"MZ")}).status_code == 400
    assert client.post("/api/models", files={"file": ("x.stl", b"not a mesh")}).status_code == 400
