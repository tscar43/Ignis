import pytest


@pytest.fixture(autouse=True)
def isolate_evacuation_configuration(monkeypatch):
    monkeypatch.delenv('IGNIS_EVACUATIONS_PATH', raising=False)
