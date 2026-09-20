import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import Household
from backend.shelters.fema import SOURCE_URL, access_report, read_catalogue
from backend.shelters.refresh_fema import normalize, refresh
from backend.shelters.shelters import find_shelters
from backend.routing.roads import DATA_DIR, load_graph
from backend.api.fire_service import FireResult

client = TestClient(app)


def feature(**changes):
    attributes = dict(shelter_id=1, shelter_name='Test shelter',
        shelter_status_code='OPEN', evacuation_capacity=100, total_population=10,
        wheelchair_accessible=' ', pet_accommodations_code=None)
    attributes.update(changes)
    return {'attributes': attributes, 'geometry': {'x': -121.58, 'y': 39.76}}


@pytest.fixture
def catalogue(tmp_path, monkeypatch):
    path = tmp_path / 'fema.json'
    monkeypatch.setenv('IGNIS_FEMA_SHELTERS_PATH', str(path))
    monkeypatch.delenv('IGNIS_SHELTER_ENTRANCES_PATH', raising=False)
    def write(record=None, age=0):
        when = datetime.now(timezone.utc) - timedelta(seconds=age)
        shelter = normalize(record or feature(), when)
        path.write_text(json.dumps({'source_url': SOURCE_URL,
            'fetched_at': when.isoformat(), 'shelters': [shelter.model_dump(mode='json')]}))
        return shelter
    write()
    return write


def test_unknowns_preserved_and_required_policies_fail_closed(catalogue):
    shelter = find_shelters()[0]  # Existing demo remains available.
    assert shelter.source == 'demo'
    actual = find_shelters(source='fema')[0]
    assert actual.accepts_pets is None and actual.accessible is None
    assert not find_shelters(Household(accepts_pets=True), source='fema')
    assert not find_shelters(Household(wheelchair_accessible=True), source='fema')
    catalogue(feature(wheelchair_accessible='YES', pet_accommodations_code='ON SITE'))
    assert find_shelters(Household(wheelchair_accessible=True), source='fema')
    assert not find_shelters(Household(accepts_pets=True), source='fema')


@pytest.mark.parametrize('status', ['CLOSED', 'FULL', 'ALERT', 'STANDBY', None, 'bad'])
def test_unavailable_statuses_are_not_candidates(catalogue, status):
    catalogue(feature(shelter_status_code=status))
    assert client.get('/shelters?source=fema').json() == []
    assert len(client.get('/shelters/catalog').json()['shelters']) == 1


@pytest.mark.parametrize('age', [1801, -60])
def test_stale_or_future_snapshot_cannot_supply_routes(catalogue, age):
    catalogue(age=age)
    assert read_catalogue()['stale']
    assert not find_shelters(source='fema')


@pytest.mark.parametrize('capacity,population', [(None, 0), (0, 0), (10, 10), (10, 11)])
def test_unknown_capacity_and_full_capacity_are_not_candidates(catalogue, capacity, population):
    catalogue(feature(evacuation_capacity=capacity, total_population=population))
    assert not find_shelters(source='fema')


def test_missing_cache_is_503_not_demo_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv('IGNIS_FEMA_SHELTERS_PATH', str(tmp_path / 'missing'))
    assert client.get('/shelters?source=fema').status_code == 503
    assert client.get('/shelters/catalog').status_code == 503
    response = client.post('/plan', json={'origin': {'lat': 39.76, 'lon': -121.62}, 'shelter_source': 'fema'})
    assert response.status_code == 503


def test_refresh_paginates_and_preserves_previous_cache_on_error(tmp_path):
    path = tmp_path / 'fema.json'
    calls = []
    def page(request):
        calls.append(request)
        second = request.url.params['resultOffset'] == '1'
        return httpx.Response(200, json={'features': [feature(shelter_id=2 if second else 1)],
            'exceededTransferLimit': not second})
    with httpx.Client(transport=httpx.MockTransport(page)) as http:
        result = refresh(path, http)
    assert len(result['shelters']) == 2 and len(calls) == 2
    assert calls[0].url.params['outSR'] == '4326'
    before = path.read_bytes()
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={'error': {'message': 'unavailable'}}))) as http:
        with pytest.raises(ValueError):
            refresh(path, http)
    assert path.read_bytes() == before


@pytest.fixture
def roads(monkeypatch):
    monkeypatch.setenv('IGNIS_GRAPH_PATH', str(DATA_DIR / 'graph.graphml'))
    load_graph.cache_clear()
    fire = json.loads((DATA_DIR / 'fire.json').read_text())
    monkeypatch.setattr('backend.main.get_fire_result', lambda mode, t: FireResult(fire, 'demo'))
    yield load_graph(), fire
    load_graph.cache_clear()


def test_entrance_review_required_and_used(catalogue, roads, tmp_path, monkeypatch):
    graph, fire = roads
    request = {'origin': {'lat': 39.76, 'lon': -121.62}, 'shelter_source': 'fema'}
    response = client.post('/plan', json=request)
    assert response.status_code == 422 and 'reviewed entrance' in response.text
    shelter = find_shelters(source='fema')[0]
    assert access_report(shelter, graph)['status'] == 'entrance_unverified'
    path = tmp_path / 'entrances.json'
    def entrance(lon, lat):
        path.write_text(json.dumps({'fema_1': {'lon': lon, 'lat': lat,
            'source_url': 'https://example.org/test-entrance-survey',
            'verified_at': datetime.now(timezone.utc).isoformat()}}))
    monkeypatch.setenv('IGNIS_SHELTER_ENTRANCES_PATH', str(path))
    entrance(-121.58, 39.76)
    response = client.post('/plan', json=request)
    assert response.status_code == 200, response.text
    assert response.json()['destination']['entrance']['lon'] == -121.58
    entrance(-121.58, 39.765)  # Approx. 550 m access gap is not accepted.
    assert client.post('/plan', json=request).status_code == 422
    entrance(-121.58, 39.7601)
    # Fire lies between a reviewed entrance and its nearest road node.
    from shapely.geometry import box, mapping
    fire['risk_polygons']['current']['features'] = [{'type': 'Feature',
        'properties': {}, 'geometry': mapping(box(-121.5801, 39.76004, -121.5799, 39.76006))}]
    assert client.post('/plan', json=request).status_code == 422


def test_origin_access_cannot_cross_current_fire(roads):
    _, fire = roads
    from shapely.geometry import box, mapping
    fire['risk_polygons']['current']['features'] = [{'type': 'Feature',
        'properties': {}, 'geometry': mapping(box(-121.6201, 39.76004, -121.6199, 39.76006))}]
    response = client.post('/plan', json={'origin': {'lat': 39.7601, 'lon': -121.62}})
    assert response.status_code == 422
    assert 'Origin access' in response.text
