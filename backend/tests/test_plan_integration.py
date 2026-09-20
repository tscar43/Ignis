"""Exercise the shipped roads and fire payloads together, without fire mocks."""
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

from backend.main import app

client = TestClient(app)
ORIGIN = {'lat': 39.76, 'lon': -121.62}


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
        assert coords[0] == [ORIGIN['lon'], ORIGIN['lat']]
        assert coords[-1] == [shelter['lon'], shelter['lat']]
        assert not current.intersects(LineString(coords))
        assert route['exposure_breakdown_km']['current'] == 0
        assert route['distance_km'] > 0
        assert route['travel_time_min'] > 0
        assert 'Demo Outer Bypass' in route['named_roads']


def test_published_replay_does_not_invent_a_route():
    response = client.post('/plan', json={
        'origin': ORIGIN, 'mode': 'replay', 't': 'T0'})
    assert response.status_code == 422
    assert 'No reachable shelter' in response.json()['detail']
