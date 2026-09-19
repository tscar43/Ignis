import json

from fastapi.testclient import TestClient

from backend.main import DEMO_DATA_DIR, app

client = TestClient(app)


def test_fire_serves_demo_scenario():
    resp = client.get("/fire", params={"lat": 39.76, "lon": -121.62, "t": "T0"})
    assert resp.status_code == 200
    with (DEMO_DATA_DIR / "fire.json").open(encoding="utf-8") as f:
        assert resp.json() == json.load(f)


def test_fire_has_all_cumulative_bands():
    body = client.get("/fire", params={"lat": 39.76, "lon": -121.62}).json()
    for band in ("current", "h1", "h3", "h6"):
        fc = body["risk_polygons"][band]
        assert fc["type"] == "FeatureCollection"
    assert body["fire_points"]["type"] == "FeatureCollection"
    assert body["data_as_of"]["firms"]
    assert body["data_as_of"]["weather"]


def test_fire_requires_coordinates():
    assert client.get("/fire").status_code == 422
