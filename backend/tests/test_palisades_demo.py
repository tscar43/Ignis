from fastapi.testclient import TestClient
from shapely.geometry import shape
from shapely.ops import unary_union

from backend.main import app
from backend.models import PlanRequest
from backend.routing.routes import calculate_routes
import pytest

client = TestClient(app)


def test_historical_toggle_changes_route_without_disabling_fire_checks():
    info = client.get('/demo/palisades')
    assert info.status_code == 200, info.text
    info = info.json()
    assert info['historical'] is True
    assert info['banner']['as_of'] == '2025-01-08T11:00:00Z'
    assert len(info['evacuations']['features']) == 5
    orders = unary_union([shape(f['geometry']) for f in info['evacuations']['features']
                          if f['properties']['level'] == 'order'])
    restrictions = unary_union([shape(f['geometry']) for f in info['evacuations']['features']])
    hazard = unary_union([shape(f['geometry']) for band in ('current', 'h1')
                         for f in info['fire']['risk_polygons'][band]['features']])
    off = client.post('/demo/palisades/plan', json={'apply_evacuation_orders': False})
    on = client.post('/demo/palisades/plan', json={'apply_evacuation_orders': True})
    assert off.status_code == on.status_code == 200, (off.text, on.text)
    off, on = off.json(), on.json()
    assert off['comparison_only'] is True and on['comparison_only'] is False
    assert off['routes'][0]['type'] == 'comparison'
    assert on['routes'][0]['type'] == 'recommended'
    assert off['banner']['visible'] and on['banner']['visible']
    assert 'ignored' in off['banner']['title']
    assert 'enforced' in on['banner']['title']
    assert off['routes'][0]['travel_time_min'] < on['routes'][0]['travel_time_min']
    assert orders.intersects(shape(off['routes'][0]['geometry']))
    assert off['routes'][0]['geometry'] != on['routes'][0]['geometry']
    for result in (off, on):
        for route in result['routes']:
            assert not hazard.intersects(shape(route['geometry']))
    for route in on['routes']:
        assert not restrictions.intersects(shape(route['geometry']))
    assert on['evacuation']['status'] == 'historical'
    assert on['data_as_of'] == info['fire']['data_as_of']


def test_demo_toggle_is_not_accepted_on_live_plan():
    response = client.post('/plan', json={'origin': {'lat': 34.05, 'lon': -118.48},
        'mode': 'live', 'apply_evacuation_orders': False})
    assert response.status_code == 422
    with pytest.raises(ValueError, match='cannot be disabled'):
        calculate_routes(PlanRequest(origin={'lat': 34.05, 'lon': -118.48}, mode='live'),
                         {}, apply_orders=False)


def test_demo_rejects_invalid_or_out_of_area_origins():
    for origin in ({'lat': 91, 'lon': 0}, {'lat': 0, 'lon': 0}):
        response = client.post('/demo/palisades/plan', json={'origin': origin})
        assert response.status_code == 422
