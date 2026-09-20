"""Exercise the shipped roads and fire payloads together, without fire mocks."""
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

from backend.main import app
from backend.routing.roads import load_graph, nearest_node

client = TestClient(app)
ORIGIN = {'lat': 39.76, 'lon': -121.62}


@pytest.fixture(autouse=True)
def default_road_cache(monkeypatch):
    monkeypatch.delenv('IGNIS_GRAPH_PATH', raising=False)
    monkeypatch.delenv('IGNIS_SHELTERS_PATH', raising=False)
    load_graph.cache_clear()
    yield
    load_graph.cache_clear()


@pytest.mark.parametrize('household', [
    {}, {'accepts_pets': True, 'wheelchair_accessible': True},
    {'occupants': 100, 'accepts_pets': True, 'wheelchair_accessible': True},
])
def test_published_demo_has_reachable_eligible_shelter(household):
    response = client.post('/plan', json={
        'origin': ORIGIN, 'mode': 'demo', 'household': household})
    assert response.status_code == 200, response.text
    assert response.headers['x-fire-source'] == 'demo'
    plan = response.json()
    fire = client.get('/fire').json()
    graph = load_graph()
    assert graph.graph['created_with'].startswith('OSMnx ')
    assert len(graph) > 100
    assert all('osmid' in e for _, _, e in graph.edges(data=True))
    road_geometry = unary_union([e['geometry'] for _, _, e in graph.edges(data=True)])
    current = unary_union([shape(f['geometry'])
                           for f in fire['risk_polygons']['current']['features']])
    shelter = plan['destination']
    assert shelter['capacity'] >= household.get('occupants', 1)
    assert not household.get('accepts_pets') or shelter['accepts_pets']
    assert not household.get('wheelchair_accessible') or shelter['accessible']
    assert not current.intersects(Point(shelter['lon'], shelter['lat']))
    assert plan['data_as_of'] == fire['data_as_of']
    assert [r['type'] for r in plan['routes']] == ['recommended', 'fastest']
    for route in plan['routes']:
        coords = route['geometry']['coordinates']
        origin_node, _ = nearest_node(graph, ORIGIN['lat'], ORIGIN['lon'])
        destination_node, _ = nearest_node(graph, shelter['lat'], shelter['lon'])
        assert coords[0] == [graph.nodes[origin_node]['x'], graph.nodes[origin_node]['y']]
        assert coords[-1] == [graph.nodes[destination_node]['x'], graph.nodes[destination_node]['y']]
        assert road_geometry.buffer(1e-9).covers(LineString(coords))
        assert not current.intersects(LineString(coords))
        assert route['exposure_breakdown_km']['current'] == 0
        assert route['distance_km'] > 0
        assert route['travel_time_min'] > 0
        assert route['named_roads']
        assert all(not name.startswith('Demo ') for name in route['named_roads'])
    assert any('fictional' in warning for warning in plan['warnings'])
    assert any('snap' in warning for warning in plan['warnings'])


def test_published_replay_does_not_invent_a_route():
    response = client.post('/plan', json={
        'origin': ORIGIN, 'mode': 'replay', 't': 'T0'})
    assert response.status_code == 422
    assert 'No reachable shelter' in response.json()['detail']
