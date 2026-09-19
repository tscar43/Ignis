from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_geocode_demo_address():
    resp = client.post("/geocode", json={"address": "123 Oak St, Auburn, CA"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["lat"] == 39.76
    assert body["lon"] == -121.62
    assert body["source"] == "demo"


def test_geocode_echoes_fallback_coords():
    resp = client.post(
        "/geocode", json={"address": "777 Nowhere Ln", "lat": 39.78, "lon": -121.65}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["lat"] == 39.78
    assert body["lon"] == -121.65
    assert body["source"] == "echo"


def test_geocode_unknown_without_coords_is_404():
    resp = client.post("/geocode", json={"address": "777 Nowhere Ln"})
    assert resp.status_code == 404


def test_plan_is_501():
    resp = client.post(
        "/plan", json={"origin": {"lat": 39.76, "lon": -121.62, "label": "123 Oak St"}}
    )
    assert resp.status_code == 501
    assert "not implemented" in resp.json()["detail"].lower()


def test_scenario_is_501():
    resp = client.get("/scenario/H1")
    assert resp.status_code == 501
    assert "not implemented" in resp.json()["detail"].lower()


def test_chat_is_501():
    resp = client.post("/chat", json={"messages": [{"role": "user", "content": "hi"}]})
    assert resp.status_code == 501
    assert "not implemented" in resp.json()["detail"].lower()
