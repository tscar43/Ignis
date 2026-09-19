from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)


def test_shelters_returns_4_to_6():
    resp = client.get("/shelters")
    assert resp.status_code == 200
    shelters = resp.json()
    assert 4 <= len(shelters) <= 6


def test_shelter_fields_and_ranges():
    for s in client.get("/shelters").json():
        assert set(s) == {
            "id",
            "name",
            "lat",
            "lon",
            "accepts_pets",
            "accessible",
            "capacity",
        }
        assert 38.0 <= s["lat"] <= 41.0
        assert -123.0 <= s["lon"] <= -120.0
        assert s["capacity"] > 0
        assert isinstance(s["accepts_pets"], bool)
        assert isinstance(s["accessible"], bool)


def test_shelter_ids_unique():
    shelters = client.get("/shelters").json()
    ids = [s["id"] for s in shelters]
    assert len(ids) == len(set(ids))
