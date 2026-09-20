import os
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from backend.main import app
from backend.api import palisades_demo
from backend.routing.roads import load_graph, read_graph

client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_asset_caches():
    load_graph.cache_clear()
    read_graph.cache_clear()
    palisades_demo.assets.cache_clear()
    yield
    load_graph.cache_clear()
    read_graph.cache_clear()
    palisades_demo.assets.cache_clear()


def test_ready_checks_bundled_demos():
    response = client.get('/ready')
    assert response.status_code == 200, response.text
    assert response.json() == {'status': 'ready', 'scope': 'offline_demos'}


@pytest.mark.parametrize('content', [None, '<not-valid-graphml>'])
def test_unavailable_graph_is_503_not_bad_request(tmp_path, monkeypatch, content):
    path = tmp_path / 'bad.graphml'
    if content is not None:
        path.write_text(content)
    monkeypatch.setenv('IGNIS_GRAPH_PATH', str(path))
    assert client.get('/health').status_code == 200
    assert client.get('/ready').status_code == 503
    response = client.post('/plan', json={'origin': {'lat': 39.76, 'lon': -121.62}})
    assert response.status_code == 503
    assert response.json()['detail'] == 'Road cache missing or invalid'


@pytest.mark.parametrize('content', [None, '{}'])
def test_palisades_missing_or_malformed_assets_are_503(tmp_path, monkeypatch, content):
    (tmp_path / 'demo').mkdir()
    if content is not None:
        (tmp_path / 'demo/palisades_evacuation_raw.geojson').write_text(content)
    monkeypatch.setattr(palisades_demo, 'ROUTING', tmp_path)
    assert client.get('/demo/palisades').status_code == 503
    assert client.post('/demo/palisades/plan', json={}).status_code == 503
    assert client.get('/ready').status_code == 503


def test_deployed_frontend_origin_can_be_configured():
    env = {**os.environ, 'IGNIS_CORS_ORIGINS': ' https://frontend.example ,http://localhost:5173 '}
    script = """
from fastapi.testclient import TestClient
from backend.main import app
client = TestClient(app)
for origin, expected in [('https://frontend.example', 200), ('https://unlisted.example', 400)]:
    response = client.options('/demo/palisades/plan', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'POST'})
    assert response.status_code == expected, response.text
    if expected == 200:
        assert response.headers['access-control-allow-origin'] == origin
"""
    subprocess.run([sys.executable, '-c', script], env=env, check=True,
                   capture_output=True, text=True, timeout=30)
