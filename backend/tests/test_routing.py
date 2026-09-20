import json
from pathlib import Path

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box, mapping

from backend.api.fire_service import FireResult
from backend.main import app
from backend.models import Household
from backend.routing.risk import score_graph
from backend.routing.roads import load_graph
from backend.routing.routes import route_edges
from backend.shelters.shelters import find_shelters

client = TestClient(app)
REQUEST = {'origin': {'lat': 39.76, 'lon': -121.62}}


def get_fire_data():
    return json.loads((Path(__file__).parents[1] / 'routing/demo/fire.json').read_text())


@pytest.fixture(autouse=True)
def synthetic_routing_fire(monkeypatch):
    monkeypatch.setenv('IGNIS_GRAPH_PATH', str(Path(__file__).parents[1] / 'routing/demo/graph.graphml'))
    load_graph.cache_clear()
    monkeypatch.setattr('backend.main.get_fire_result', lambda mode, t: FireResult(get_fire_data(), 'demo'))
    yield
    load_graph.cache_clear()



def test_plan_prefers_lower_exposure_and_preserves_metrics():
    response = client.post('/plan', json=REQUEST)
    assert response.status_code == 200, response.text
    result = response.json()
    recommended, fastest = result['routes']
    assert recommended['travel_time_min'] == 9
    assert fastest['travel_time_min'] == 4
    assert recommended['exposure'] == 0 < fastest['exposure']
    assert fastest['exposure_breakdown_km']['h1'] > 1
    assert fastest['exposure_breakdown_km']['h3'] == 0
    assert fastest['exposure_breakdown_km']['h6'] == 0
    assert recommended['geometry']['coordinates'][0] == [-121.62, 39.76]
    assert recommended['geometry']['coordinates'][-1] == [-121.58, 39.76]
    assert 'Demo Bypass' in recommended['named_roads']
    assert any('1-hour' in w for w in result['warnings'])


def test_current_fire_blocks_fastest_too_and_does_not_mutate_cache():
    graph = load_graph()
    fire = get_fire_data()
    fire['risk_polygons']['current'] = {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': mapping(box(-121.606, 39.755, -121.594, 39.765)), 'properties': {}}]}
    scored = score_graph(graph, fire)
    assert not scored.has_edge('origin', 'direct')
    assert graph.has_edge('origin', 'direct')
    assert len(route_edges(scored, 'origin', 'east', 'travel_time')) == 3


def test_parallel_edges_use_same_objective_as_path_search():
    graph = nx.MultiDiGraph()
    graph.add_edge('a', 'b', key='quick', travel_time=1, risk_cost=10)
    graph.add_edge('a', 'b', key='low_risk', travel_time=5, risk_cost=2)
    assert route_edges(graph, 'a', 'b', 'risk_cost') == [('a', 'b', 'low_risk')]
    assert route_edges(graph, 'a', 'b', 'travel_time') == [('a', 'b', 'quick')]


def test_household_constraints():
    shelters = find_shelters(Household(accepts_pets=True, wheelchair_accessible=True))
    assert {s.id for s in shelters} == {'shelter_01', 'shelter_04'}
    assert client.post('/plan', json={**REQUEST, 'household': {
        'has_vehicle': False}}).status_code == 422


@pytest.mark.parametrize('payload', [
    {'origin': {'lat': 91, 'lon': 0}}, {'origin': {'lat': 0, 'lon': 0}},
    {**REQUEST, 'household': {'occupants': 0}}, {**REQUEST, 't': '../../etc'},
])
def test_invalid_requests(payload):
    assert client.post('/plan', json=payload).status_code == 422


def test_no_reachable_shelter(monkeypatch):
    monkeypatch.setattr('backend.routing.routes.find_shelters', lambda _: [])
    response = client.post('/plan', json=REQUEST)
    assert response.status_code == 422
    assert 'No reachable shelter' in response.json()['detail']


def test_cors_and_geocoding():
    response = client.options('/plan', headers={'Origin': 'http://localhost:5173',
        'Access-Control-Request-Method': 'POST'})
    assert response.headers['access-control-allow-origin'] == 'http://localhost:5173'
    assert client.post('/geocode', json={'address': '123 Oak St.'}).status_code == 200
    assert client.post('/geocode', json={'address': 'unknown'}).status_code == 404


def test_identical_routes_disclosed(monkeypatch):
    fire = get_fire_data()
    for band in ('current', 'h1', 'h3', 'h6'):
        fire['risk_polygons'][band] = {'type': 'FeatureCollection', 'features': []}
    monkeypatch.setattr('backend.main.get_fire_result', lambda mode, t: FireResult(fire, 'demo'))
    result = client.post('/plan', json=REQUEST).json()
    assert result['routes'][0]['geometry'] == result['routes'][1]['geometry']
    assert any('also the recommended' in w for w in result['warnings'])
