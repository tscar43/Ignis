"""Regression tests for the 2026-09-20 backend and fire-model audit.

One test per finding that had no test standing over it. They live together
rather than scattered through the suite because what they have in common is
the failure mode, not the module: every one of these used to look like a
working system from the outside -- a 200 with empty hazards, a 500 where a 503
belonged, a graph that validated and then produced NaN routes.

The fire-engine findings are covered next to their own modules, in
backend/fire/tests/.
"""

import json

from fastapi.testclient import TestClient
import networkx as nx
import pytest

from backend.main import app
from backend.api import palisades_demo
from backend.api.fire_service import (FireResult, MAX_OBSERVATION_AGE_S,
                                      observation_age_seconds)
from backend.routing.roads import RoadUnavailable, load_graph, read_graph, within

client = TestClient(app)

PARADISE = {'origin': {'lat': 39.76, 'lon': -121.62}}


@pytest.fixture(autouse=True)
def clear_asset_caches():
    load_graph.cache_clear()
    read_graph.cache_clear()
    palisades_demo.assets.cache_clear()
    yield
    load_graph.cache_clear()
    read_graph.cache_clear()
    palisades_demo.assets.cache_clear()


def _graphml(path, *, length='2500', travel_time='100', geometry=None):
    graph = nx.MultiDiGraph()
    graph.add_node('a', x=-121.62, y=39.76)
    graph.add_node('b', x=-121.60, y=39.77)
    edge = {'length': length, 'travel_time': travel_time}
    if geometry is not None:
        edge['geometry'] = geometry
    graph.add_edge('a', 'b', **edge)
    nx.write_graphml(graph, path)
    return path


# --------------------------------------------------------------- D2: 503s
@pytest.mark.parametrize('route', ['/fire', '/scenario/T0'])
def test_missing_fire_fixture_is_503_not_500(route, tmp_path, monkeypatch):
    """An empty fire-data directory used to reach the client as a 500.

    Worse, a fixture that parsed but failed the contract came back 422, which
    tells the caller its request was wrong when the file on the server is.
    """
    from backend.api import fire_service

    monkeypatch.setattr(fire_service, 'DATA_DIR', tmp_path)
    fire_service._demo.cache_clear()
    fire_service._replay.cache_clear()
    try:
        response = client.get(route)
        assert response.status_code == 503, response.text
        assert 'missing or invalid' in response.json()['detail']
    finally:
        fire_service._demo.cache_clear()
        fire_service._replay.cache_clear()


def test_invalid_fire_fixture_is_503_not_422(tmp_path, monkeypatch):
    from backend.api import fire_service

    (tmp_path / 'risk_demo.json').write_text(json.dumps({'nonsense': True}))
    monkeypatch.setattr(fire_service, 'DATA_DIR', tmp_path)
    fire_service._demo.cache_clear()
    try:
        assert client.get('/fire').status_code == 503
    finally:
        fire_service._demo.cache_clear()


def test_missing_shelter_catalogue_is_503_on_both_routes(tmp_path, monkeypatch):
    monkeypatch.setenv('IGNIS_SHELTERS_PATH', str(tmp_path / 'gone.json'))
    assert client.get('/shelters').status_code == 503
    assert client.post('/plan', json=PARADISE).status_code == 503


def test_ready_validates_the_replay_it_serves(tmp_path, monkeypatch):
    """/ready reported ready while every /scenario/* offset returned 503.

    It loaded the demo frame and never touched the Camp replay, so the one
    endpoint whose job is to say the demo data is present could not see the
    half of it the presentation actually steps through.
    """
    from backend.api import fire_service

    assert client.get('/ready').status_code == 200

    # A directory holding the demo frame but no replay: previously ready.
    (tmp_path / 'risk_demo.json').write_text(
        (fire_service.DATA_DIR / 'risk_demo.json').read_text(encoding='utf-8'),
        encoding='utf-8')
    monkeypatch.setattr(fire_service, 'DATA_DIR', tmp_path)
    fire_service._demo.cache_clear()
    fire_service._replay.cache_clear()
    try:
        assert client.get('/ready').status_code == 503
    finally:
        fire_service._demo.cache_clear()
        fire_service._replay.cache_clear()


# ------------------------------------------------- road graph validation
def test_nan_length_is_rejected(tmp_path):
    """`value <= 0` is False for NaN, so this graph used to validate.

    It then poisoned every shortest-path sum that touched the edge, far from
    here and long after readiness had gone green.
    """
    path = _graphml(tmp_path / 'nan.graphml', length='NaN')
    with pytest.raises(RoadUnavailable):
        read_graph(path)


def test_nan_travel_time_is_rejected(tmp_path):
    path = _graphml(tmp_path / 'nant.graphml', travel_time='nan')
    with pytest.raises(RoadUnavailable):
        read_graph(path)


def test_point_geometry_is_rejected(tmp_path):
    """A POINT parsed fine and then never intersected a fire polygon.

    That is the worst shape this failure can take: a road the hazard filter
    can never block, presented as a safe route.
    """
    path = _graphml(tmp_path / 'point.graphml', geometry='POINT (-121.62 39.76)')
    with pytest.raises(RoadUnavailable):
        read_graph(path)


def test_non_finite_node_coordinate_is_rejected(tmp_path):
    graph = nx.MultiDiGraph()
    graph.add_node('a', x=float('nan'), y=39.76)
    graph.add_node('b', x=-121.60, y=39.77)
    graph.add_edge('a', 'b', length='2500', travel_time='100')
    path = tmp_path / 'nannode.graphml'
    nx.write_graphml(graph, path)
    with pytest.raises(RoadUnavailable):
        read_graph(path)


def test_a_well_formed_graph_still_loads(tmp_path):
    assert read_graph(_graphml(tmp_path / 'ok.graphml')).number_of_edges() == 1


# ------------------------------------------- fire-model coverage of roads
def test_within_rejects_a_graph_outside_the_modelled_bbox(tmp_path):
    from backend.fire.firms import DEMO_BBOX

    inside = read_graph(_graphml(tmp_path / 'inside.graphml'))
    assert within(inside, DEMO_BBOX)

    graph = nx.MultiDiGraph()  # Los Angeles, not Butte County
    graph.add_node('a', x=-118.60, y=34.05)
    graph.add_node('b', x=-118.58, y=34.06)
    graph.add_edge('a', 'b', length='2500', travel_time='100')
    path = tmp_path / 'elsewhere.graphml'
    nx.write_graphml(graph, path)
    assert not within(read_graph(path), DEMO_BBOX)


def test_live_plan_refuses_a_graph_the_fire_model_does_not_cover(tmp_path, monkeypatch):
    """Hazard intersections outside the modelled bbox are empty, not safe.

    The graph routes, every fire polygon is hundreds of kilometres away, and
    the plan comes back clean. Evacuation coverage is checked separately and
    does not stand in for this.
    """
    graph = nx.MultiDiGraph()
    graph.add_node('a', x=-118.60, y=34.05)
    graph.add_node('b', x=-118.58, y=34.06)
    graph.add_edge('a', 'b', length='2500', travel_time='100')
    path = tmp_path / 'la.graphml'
    nx.write_graphml(graph, path)
    monkeypatch.setenv('IGNIS_GRAPH_PATH', str(path))

    response = client.post('/plan', json={'origin': {'lat': 34.05, 'lon': -118.60},
                                          'mode': 'live'})
    assert response.status_code == 503
    assert 'fire model covers' in response.json()['detail']


# ------------------------------------- M8: fetch age is not observation age
def test_observation_age_reads_the_payload_not_the_clock():
    fresh = {'data_as_of': {'firms': '2026-09-20T00:00:00Z'}}
    from datetime import datetime, timezone

    now = datetime(2026, 9, 20, 3, 0, tzinfo=timezone.utc)
    assert observation_age_seconds(fresh, now) == 3 * 3600
    assert observation_age_seconds({'data_as_of': {'firms': 'not a time'}}) is None
    assert observation_age_seconds({}) is None


def test_a_recently_fetched_payload_can_still_be_stale_data():
    """The gap this closes: stale=False said nothing about the observations."""
    old = {'data_as_of': {'firms': '2020-01-01T00:00:00Z'}}
    result = FireResult(old, 'live', stale=False, age_seconds=0,
                        observation_age_seconds=observation_age_seconds(old))
    assert result.stale is False
    assert result.observations_fresh is False

    result = FireResult(old, 'live', observation_age_seconds=MAX_OBSERVATION_AGE_S - 1)
    assert result.observations_fresh is True
