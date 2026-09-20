import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Event

import pytest
from fastapi.testclient import TestClient

from backend.api import fire_service
from backend.api.fire_service import DATA_DIR, LiveFireCache
from backend.main import app

client = TestClient(app)


@pytest.fixture
def payload():
    return json.loads((DATA_DIR / 'risk_demo.json').read_text(encoding='utf-8'))


def test_ttl_and_mutation_isolation(payload):
    now = [0]
    calls = []
    def load():
        calls.append(1)
        return payload
    cache = LiveFireCache(load, clock=lambda: now[0])
    first = cache.get()
    first.payload['summary']['extra'] = 'must not leak'
    now[0] = 299
    assert 'extra' not in cache.get().payload['summary']
    assert len(calls) == 1
    now[0] = 300
    assert cache.get().stale is False
    assert len(calls) == 2


def test_refresh_failure_stale_retry_and_recovery(payload):
    now = [0]
    calls = []
    def load():
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError('upstream failure')
        return payload
    cache = LiveFireCache(load, clock=lambda: now[0])
    cache.get()
    now[0] = 301
    result = cache.get()
    assert result.stale and result.age_seconds == 301
    assert result.payload == payload
    now[0] = 320
    assert cache.get().stale and len(calls) == 2
    now[0] = 332
    assert not cache.get().stale and len(calls) == 3


def test_first_failure_is_503_and_retries_are_throttled(monkeypatch):
    calls = []
    def fail():
        calls.append(1)
        raise RuntimeError('private upstream details')
    monkeypatch.setattr(fire_service, 'live_cache', LiveFireCache(fail, clock=lambda: 0))
    for _ in range(2):
        response = client.get('/fire?mode=live')
        assert response.status_code == 503
        assert response.headers['retry-after'] == '30'
        assert 'private' not in response.text
    assert len(calls) == 1


def test_invalid_refresh_keeps_valid_payload(payload):
    now = [0]
    values = iter([payload, {}])
    cache = LiveFireCache(lambda: next(values), clock=lambda: now[0])
    cache.get()
    now[0] = 301
    assert cache.get().payload == payload
    assert cache.get().stale


def test_single_refresh_serves_old_payload_without_waiting(payload):
    entered, release = Event(), Event()
    now = [0]
    calls = []
    def load():
        calls.append(1)
        if len(calls) > 1:
            entered.set()
            assert release.wait(5)
        return payload
    cache = LiveFireCache(load, clock=lambda: now[0])
    cache.get()
    now[0] = 301
    with ThreadPoolExecutor(max_workers=2) as pool:
        refresh = pool.submit(cache.get)
        try:
            assert entered.wait(5)
            assert pool.submit(cache.get).result(timeout=2).stale
        finally:
            release.set()
        assert not refresh.result(timeout=5).stale
    assert len(calls) == 2


def test_concurrent_first_load_runs_once(payload):
    entered, release = Event(), Event()
    calls = []
    def load():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return payload
    cache = LiveFireCache(load)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(cache.get)
        assert entered.wait(5)
        second = pool.submit(cache.get)
        release.set()
        assert first.result(timeout=5).payload == second.result(timeout=5).payload
    assert len(calls) == 1


def test_demo_served_unchanged(payload):
    response = client.get('/fire')
    assert response.status_code == 200
    assert response.json() == payload
    assert response.headers['x-fire-source'] == 'demo'


@pytest.mark.parametrize('time,offset', [('T0', 0), ('H1', 1), ('H3', 3), ('H6', 6)])
def test_replay_exact_frame(time, offset):
    frames = json.loads((DATA_DIR / 'risk_replay.json').read_text(encoding='utf-8'))
    expected = next(frame for frame in frames if frame['replay']['offset_h'] == offset)
    response = client.get(f'/fire?mode=replay&t={time}')
    assert response.status_code == 200, response.text
    assert response.json() == expected
    assert client.get(f'/scenario/{time}').json() == expected


def test_additive_fields_survive_and_stale_headers_are_exposed(payload, monkeypatch):
    payload = deepcopy(payload)
    payload['magi'] = {'future_extension': 'preserve'}
    now = [0]
    def load():
        if now[0]:
            raise RuntimeError('upstream failure')
        return payload
    cache = LiveFireCache(load, clock=lambda: now[0])
    monkeypatch.setattr(fire_service, 'live_cache', cache)
    assert client.get('/fire?mode=live').json() == payload
    now[0] = 301
    response = client.get('/fire?mode=live', headers={'Origin': 'http://localhost:5173'})
    assert response.json() == payload
    assert response.headers['x-fire-stale'] == 'true'
    assert 'X-Fire-Stale' in response.headers['access-control-expose-headers']
    assert response.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('url', ['/fire?mode=live&t=H1', '/fire?t=H1',
    '/fire?mode=invalid', '/fire?mode=replay&t=H2', '/scenario/H2'])
def test_invalid_mode_time_combinations(url):
    assert client.get(url).status_code == 422


def test_published_demo_cannot_invent_route_through_blocked_network():
    response = client.post('/plan', json={'origin': {'lat': 39.76, 'lon': -121.62}})
    assert response.status_code == 422
    assert 'No reachable shelter' in response.json()['detail']


def test_palisades_fixture_is_served_whole_and_is_not_a_fire_payload():
    """The comparison carries model scores, not risk bands, so it must not be
    validated against the /fire contract -- and must not be trimmed to it."""
    body = client.get('/palisades').json()
    assert body['fire'].startswith('Palisades Fire')
    assert len(body['windows']) == 4
    window = body['windows'][0]
    assert {'seed', 'observed', 'predictions', 'models'} <= set(window)
    assert all('iou' in stats for stats in window['models'].values())
    assert 'risk_polygons' not in body
