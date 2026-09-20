"""The downwind smoke preference. No network.

The property that matters is not "picks the cleaner road" -- it is that the
preference can only ever choose among routes the fire blocking and the
evacuation orders already permit. A health preference that could unlock a
forbidden road would be worse than not having one.
"""

import pathlib

import networkx as nx
import pytest
from pyproj import Transformer
from shapely.geometry import LineString, box, mapping

from backend.routing.risk import SMOKE_WEIGHT, plume, score_graph


def _fire(wind_toward_deg, burning):
    """A payload with one burning square and an otherwise empty band set."""
    features = [{'type': 'Feature', 'properties': {},
                 'geometry': mapping(burning)}]
    empty = {'type': 'FeatureCollection', 'features': []}
    return {
        'risk_polygons': {'current': {'type': 'FeatureCollection',
                                      'features': features},
                          'h1': empty, 'h3': empty, 'h6': empty},
        'summary': {'wind_toward_deg': wind_toward_deg},
    }


def _graph():
    """Origin at (0,0); two ways east, one running north, one running south."""
    graph = nx.MultiDiGraph()
    for name, (x, y) in {'o': (0, 0), 'n': (0, 0.02), 's': (0, -0.02),
                         'e': (0.04, 0)}.items():
        graph.add_node(name, x=x, y=y)
    for u, v in (('o', 'n'), ('n', 'e'), ('o', 's'), ('s', 'e')):
        graph.add_edge(u, v, travel_time=100, length=2500,
                       geometry=LineString([(graph.nodes[u]['x'], graph.nodes[u]['y']),
                                            (graph.nodes[v]['x'], graph.nodes[v]['y'])]))
    return graph


# A real equidistant projection, not a flat scale factor: shapely's transform
# collapses a naive two-argument lambda, which reads as a plume bug rather
# than a test bug and cost an hour once.
PROJECT = Transformer.from_crs(
    'EPSG:4326', '+proj=aeqd +lat_0=0 +lon_0=0 +datum=WGS84 +units=m',
    always_xy=True).transform

BURNING = box(-0.002, -0.002, 0.002, 0.002)  # ~444 m square on the origin
EDGE_M = 0.002 * 111000


def test_plume_runs_downwind_not_upwind():
    north = plume(_fire(0, BURNING), PROJECT).bounds
    south = plume(_fire(180, BURNING), PROJECT).bounds
    east = plume(_fire(90, BURNING), PROJECT).bounds

    assert north[3] > EDGE_M                             # extends north
    assert north[1] == pytest.approx(-EDGE_M, abs=5)     # but not south
    assert south[1] < -EDGE_M                            # extends south
    assert south[3] == pytest.approx(EDGE_M, abs=5)      # but not north
    assert east[2] > EDGE_M                              # bearing is a compass one
    assert east[3] == pytest.approx(EDGE_M, abs=5)       # 90 is east, not north


def test_the_plume_is_one_connected_shape_not_a_dotted_line():
    """The step has to be smaller than the footprint.

    Stepping 1 km with a 444 m footprint produced nine detached blobs with
    clean air between them, so a road threading a gap scored no smoke at all.
    """
    for source in (BURNING, box(-0.02, -0.02, 0.02, 0.02)):
        swept = plume(_fire(0, source), PROJECT)
        assert swept.geom_type == 'Polygon'


def test_the_preference_costs_the_smoky_side_and_leaves_the_other_alone():
    graph = _graph()
    # Burning WEST of the road network, off every edge, with the wind pushing
    # its smoke east across the northern way out. The southern way is far
    # enough south that the plume never reaches it.
    fire = _fire(90, box(-0.010, 0.008, -0.006, 0.012))

    plain = score_graph(graph, fire)
    avoided = score_graph(graph, fire, avoid_smoke=True)

    assert plain['o']['n'][0]['smoke_km'] == 0.0
    assert avoided['o']['n'][0]['smoke_km'] > 0
    assert avoided['o']['n'][0]['risk_cost'] > plain['o']['n'][0]['risk_cost']

    # The clean side is untouched, so this reorders rather than inflating both.
    assert avoided['o']['s'][0]['smoke_km'] == 0.0
    assert avoided['o']['s'][0]['risk_cost'] == plain['o']['s'][0]['risk_cost']


def test_the_preference_never_unblocks_an_edge_the_fire_removed():
    """The safety property. Smoke cost is added, never subtracted.

    A respiratory preference that could reopen a road inside the fire would be
    strictly worse than having no preference at all.
    """
    graph = _graph()
    fire = _fire(0, box(-0.002, 0.004, 0.002, 0.024))  # sits on the northern way

    plain = score_graph(graph, fire)
    avoided = score_graph(graph, fire, avoid_smoke=True)

    assert set(avoided.edges(keys=True)) == set(plain.edges(keys=True))
    for u, v, key in plain.edges(keys=True):
        assert avoided[u][v][key]['risk_cost'] >= plain[u][v][key]['risk_cost']


def test_smoke_is_weighted_below_every_fire_band():
    from backend.routing.risk import WEIGHTS

    assert SMOKE_WEIGHT < WEIGHTS['h1']
    assert 0 < SMOKE_WEIGHT


def test_an_empty_fire_produces_no_plume_and_no_cost():
    graph = _graph()
    empty = {'type': 'FeatureCollection', 'features': []}
    fire = {'risk_polygons': dict.fromkeys(('current', 'h1', 'h3', 'h6'), empty),
            'summary': {'wind_toward_deg': 0}}
    scored = score_graph(graph, fire, avoid_smoke=True)
    assert all(e['smoke_km'] == 0.0 for _, _, e in scored.edges(data=True))


def test_the_primary_route_is_weighted_by_risk_cost_not_raw_travel_time():
    """The wiring this feature needed, and that the fire bands needed too.

    `risk.py` computes `risk_cost` as travel minutes plus the weighted hazard
    penalty, but `routes.py` routed on `travel_time`, so WEIGHTS and
    RISK_LAMBDA were calculated for every edge and never consulted -- the
    h1/h3/h6 bands only mattered where they blocked an edge outright. A smoke
    cost added to `risk_cost` would have been just as inert.
    """
    source = (pathlib.Path(__file__).resolve().parents[1]
              / 'routing' / 'routes.py').read_text(encoding='utf-8')
    assert "route_edges(scored, origin, destination, 'risk_cost')" in source
    assert "route_edges(scored, origin, destination, 'travel_time')" not in source


def test_smoke_cost_reaches_risk_cost_in_the_units_risk_cost_uses():
    """risk_cost is in minutes, so the smoke term has to be too."""
    graph = _graph()
    fire = _fire(90, box(-0.010, 0.008, -0.006, 0.012))
    plain = score_graph(graph, fire)
    avoided = score_graph(graph, fire, avoid_smoke=True)
    edge_plain = plain['o']['n'][0]
    edge_avoid = avoided['o']['n'][0]
    from backend.routing.risk import RISK_LAMBDA
    expected = RISK_LAMBDA * SMOKE_WEIGHT * edge_avoid['smoke_km']
    assert edge_avoid['risk_cost'] - edge_plain['risk_cost'] == pytest.approx(expected)
