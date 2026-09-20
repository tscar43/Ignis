import json
from datetime import datetime, timedelta, timezone

import networkx as nx
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, box, mapping, shape

from backend.api.fire_service import (MAX_OBSERVATION_AGE_S, FireResult,
                                      observation_age_seconds)
from backend.main import app
from backend.models import Shelter
from backend.routing.risk import score_graph
from backend.routing.routes import order_allows

client = TestClient(app)
REQUEST = {'origin': {'lat': 0, 'lon': 0}, 'mode': 'demo'}


@pytest.fixture
def scenario(monkeypatch, tmp_path):
    graph = nx.MultiDiGraph(source='synthetic demonstration')
    for node, coords in {'s': (0, 0), 'a': (.02, 0), 'b': (.02, .01), 't': (.04, 0)}.items():
        graph.add_node(node, x=coords[0], y=coords[1])
    for u, v, seconds in [('s', 'a', 100), ('a', 't', 100), ('s', 'b', 120), ('b', 't', 120)]:
        graph.add_edge(u, v, travel_time=seconds, length=2500,
                       geometry=LineString([(graph.nodes[n]['x'], graph.nodes[n]['y']) for n in (u, v)]))
    # Observed just now, so the live gate's observation-age check passes. A
    # fixed timestamp would have quietly started failing the day after it was
    # written, which is the trap the gate itself exists to catch.
    observed = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    fire = {'risk_polygons': {b: {'type': 'FeatureCollection', 'features': []}
                             for b in ('current', 'h1', 'h3', 'h6')},
            'data_as_of': {'firms': observed, 'weather': observed}}
    monkeypatch.setattr('backend.main.get_fire_result', lambda mode, t: FireResult(
        fire, mode, observation_age_seconds=observation_age_seconds(fire)))
    monkeypatch.setattr('backend.routing.routes.load_graph', lambda: graph)
    monkeypatch.setattr('backend.routing.routes.find_shelters', lambda _: [
        Shelter(id='test', name='Fictional test shelter', lat=0, lon=.04, capacity=100)])
    now = datetime.now(timezone.utc)
    snapshot = {'type': 'FeatureCollection', 'mode': 'demo', 'fetched_at': now.isoformat(),
                'authority': 'Fictional test authority', 'source_url': 'https://example.org/test',
                'coverage': mapping(box(-.1, -.1, .1, .1)), 'features': []}
    path = tmp_path / 'orders.json'
    monkeypatch.setenv('IGNIS_EVACUATIONS_PATH', str(path))
    def write():
        path.write_text(json.dumps(snapshot))
    write()
    return graph, fire, snapshot, write, now


def add_zone(snapshot, now, polygon, level='order'):
    snapshot['features'].append({'type': 'Feature', 'geometry': mapping(polygon),
        'properties': {'id': 'test-1', 'zone': 'TEST', 'level': level,
            'authority': 'Fictional test authority', 'source_url': 'https://example.org/test',
            'instructions': 'Synthetic test only', 'updated_at': now.isoformat(),
            'valid_until': (now + timedelta(minutes=20)).isoformat()}})


def test_quickest_primary_and_distinct_eligible_alternative(scenario):
    response = client.post('/plan', json=REQUEST)
    assert response.status_code == 200, response.text
    primary, alternative = response.json()['routes']
    assert [primary['type'], alternative['type']] == ['recommended', 'alternative']
    assert primary['travel_time_min'] == pytest.approx(200 / 60, abs=.001)
    assert alternative['travel_time_min'] == 4
    assert primary['geometry'] != alternative['geometry']
    assert response.json()['evacuation']['status'] == 'fresh'


@pytest.mark.parametrize('band', ['current', 'h1'])
def test_hazardous_alternative_is_omitted(scenario, band):
    _, fire, _, _, _ = scenario
    polygon = box(.018, .009, .022, .011)
    fire['risk_polygons'][band]['features'] = [{'geometry': mapping(polygon)}]
    response = client.post('/plan', json=REQUEST)
    assert response.status_code == 200, response.text
    assert len(response.json()['routes']) == 1
    assert not polygon.intersects(shape(response.json()['routes'][0]['geometry']))


def test_excessive_detour_is_not_offered(scenario):
    graph, *_ = scenario
    graph['s']['b'][0]['travel_time'] = 500
    assert len(client.post('/plan', json=REQUEST).json()['routes']) == 1


@pytest.mark.parametrize('level', ['order', 'warning'])
def test_order_changes_route_and_is_exposed_for_map(scenario, level):
    _, _, snapshot, write, now = scenario
    add_zone(snapshot, now, box(.015, -.001, .025, .001), level)
    write()
    response = client.post('/plan', json=REQUEST)
    assert response.status_code == 200, response.text
    assert len(response.json()['routes']) == 1
    assert response.json()['routes'][0]['travel_time_min'] == 4
    data = client.get('/evacuations?mode=demo&lat=0&lon=0.02').json()
    assert data['origin_covered'] and data['origin_orders'][0]['level'] == level
    assert data['origin_orders'][0]['instructions'] == 'Synthetic test only'


def test_origin_can_exit_order_zone_without_reentry(scenario):
    _, _, snapshot, write, now = scenario
    zone = box(-.001, -.001, .005, .005)
    add_zone(snapshot, now, zone)
    write()
    response = client.post('/plan', json=REQUEST)
    assert response.status_code == 200, response.text
    assert response.json()['evacuation']['origin_orders'][0]['level'] == 'order'
    from shapely.geometry import Point
    assert not order_allows(LineString([(0, 0), (.01, 0), (.002, .002)]), [zone], Point(0, 0))
    assert not order_allows(LineString([(.01, 0), (0, 0)]), [zone], Point(0, 0))


def test_destination_in_order_zone_is_rejected(scenario):
    _, _, snapshot, write, now = scenario
    add_zone(snapshot, now, box(.035, -.005, .045, .005))
    write()
    assert client.post('/plan', json=REQUEST).status_code == 422


@pytest.mark.parametrize('change', ['missing', 'stale', 'expired', 'future', 'wrong_mode'])
def test_unknown_or_stale_orders_withhold_alternatives(scenario, monkeypatch, change):
    _, _, snapshot, write, now = scenario
    if change == 'missing':
        monkeypatch.delenv('IGNIS_EVACUATIONS_PATH')
    elif change == 'stale':
        snapshot['fetched_at'] = (now - timedelta(hours=1)).isoformat()
    elif change == 'future':
        snapshot['fetched_at'] = (now + timedelta(hours=1)).isoformat()
    elif change == 'expired':
        add_zone(snapshot, now - timedelta(hours=1), box(.07, .07, .08, .08))
    else:
        snapshot['mode'] = 'live'
    write()
    response = client.post('/plan', json=REQUEST)
    assert response.status_code == 200, response.text
    assert len(response.json()['routes']) == 1
    assert response.json()['evacuation']['status'] in ('unknown', 'stale')


def test_live_plan_requires_current_orders_and_fire(scenario, monkeypatch):
    _, fire, snapshot, write, _ = scenario
    request = {**REQUEST, 'mode': 'live'}
    assert client.post('/plan', json=request).status_code == 503
    snapshot['mode'] = 'live'
    write()
    assert client.post('/plan', json=request).status_code == 200
    monkeypatch.setattr('backend.main.get_fire_result', lambda mode, t: FireResult(
        fire, mode, True, 600, observation_age_seconds=0))
    assert client.post('/plan', json=request).status_code == 503


def test_live_plan_refuses_a_fresh_fetch_of_stale_observations(scenario, monkeypatch):
    """A recent fetch is not a recent observation.

    The cache only ever measured time since a successful fetch, so a loader
    returning a valid but frozen payload reported stale=False forever and live
    routing ran on detections from yesterday. Nothing about the fetch can tell
    you that; only `data_as_of` can.
    """
    _, fire, snapshot, write, _ = scenario
    snapshot['mode'] = 'live'
    write()
    request = {**REQUEST, 'mode': 'live'}

    old_fire = {**fire, 'data_as_of': {
        **fire['data_as_of'],
        'firms': (datetime.now(timezone.utc)
                  - timedelta(seconds=MAX_OBSERVATION_AGE_S + 3600)
                  ).strftime('%Y-%m-%dT%H:%M:%SZ')}}
    monkeypatch.setattr('backend.main.get_fire_result', lambda mode, t: FireResult(
        old_fire, mode, False, 0,
        observation_age_seconds=observation_age_seconds(old_fire)))
    response = client.post('/plan', json=request)
    assert response.status_code == 503
    assert 'observations' in response.json()['detail']


def test_live_plan_refuses_an_unreadable_observation_time(scenario, monkeypatch):
    _, fire, snapshot, write, _ = scenario
    snapshot['mode'] = 'live'
    write()
    monkeypatch.setattr('backend.main.get_fire_result', lambda mode, t: FireResult(
        fire, mode, False, 0, observation_age_seconds=None))
    assert client.post('/plan', json={**REQUEST, 'mode': 'live'}).status_code == 503


def test_outside_order_coverage_is_not_used(scenario):
    _, _, snapshot, write, _ = scenario
    snapshot['coverage'] = mapping(box(-.01, -.01, .05, .005))
    write()
    response = client.post('/plan', json=REQUEST)
    assert response.status_code == 200, response.text
    assert len(response.json()['routes']) == 1
    snapshot['coverage'] = mapping(box(-.01, -.01, .01, .01))
    write()
    assert client.post('/plan', json=REQUEST).status_code == 422


def test_malformed_order_input_fails_closed(scenario):
    _, _, snapshot, write, _ = scenario
    snapshot['coverage']['coordinates'] = []
    write()
    assert client.get('/evacuations').status_code == 503
    assert client.post('/plan', json=REQUEST).status_code == 503


def test_origin_snap_across_one_hour_risk_is_rejected(scenario):
    _, fire, _, _, _ = scenario
    fire['risk_polygons']['h1']['features'] = [{'geometry': mapping(box(-.001, .0004, .001, .0006))}]
    response = client.post('/plan', json={**REQUEST, 'origin': {'lon': 0, 'lat': .001}})
    assert response.status_code == 422 and 'Origin access' in response.text


def test_mixed_band_lengths_are_not_lost_or_double_counted():
    graph = nx.MultiDiGraph()
    graph.add_node('a', x=0, y=0)
    graph.add_node('b', x=.03, y=0)
    graph.add_edge('a', 'b', length=3340, travel_time=60, geometry=LineString([(0, 0), (.03, 0)]))
    fire = {'risk_polygons': {b: {'features': [{'geometry': mapping(poly)}] if poly else []}
            for b, poly in [('current', None), ('h1', box(0, -.01, .01, .01)),
                            ('h3', box(0, -.01, .02, .01)), ('h6', box(0, -.01, .03, .01))]}}
    exposure = score_graph(graph, fire)['a']['b'][0]['exposure_km']
    assert exposure['h1'] == pytest.approx(1.113, abs=.002)
    assert exposure['h3'] == pytest.approx(1.113, abs=.002)
    assert exposure['h6'] == pytest.approx(1.113, abs=.002)
    assert sum(exposure.values()) <= 3.34
    assert 'exposure_km' not in graph['a']['b'][0]
