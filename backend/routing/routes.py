from datetime import datetime, timezone

import networkx as nx
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from ..models import PlanResponse, Route, RouteGeometry, ExposureBreakdown
from ..shelters.shelters import find_shelters
from .risk import BANDS, WEIGHTS, score_graph
from .roads import load_graph, nearest_node


def route_edges(graph, start, end, weight):
    nodes = nx.shortest_path(graph, start, end, weight=weight)
    return [(u, v, min(graph[u][v], key=lambda k: graph[u][v][k][weight]))
            for u, v in zip(nodes, nodes[1:])]


def describe_route(graph, edges, kind, start):
    coords, names = [], []
    seconds = metres = 0.0
    breakdown = dict.fromkeys(BANDS, 0.0)
    for u, v, key in edges:
        edge = graph[u][v][key]
        line = list(edge['geometry'].coords)
        node = graph.nodes[u]
        if Point(line[-1]).distance(Point(node['x'], node['y'])) < Point(line[0]).distance(Point(node['x'], node['y'])):
            line.reverse()
        coords.extend(line if not coords else line[1:])
        seconds += edge['travel_time']
        metres += edge['length']
        for band in BANDS:
            breakdown[band] += edge['exposure_km'][band]
        name = edge.get('name')
        if name and name not in names:
            names.append(str(name))
    if not coords:
        node = graph.nodes[start]
        coords = [(node['x'], node['y'])] * 2
    distance = metres / 1000
    exposure = sum(WEIGHTS[b] * breakdown[b] for b in BANDS) / (10 * distance) if distance else 0
    return Route(type=kind, geometry=RouteGeometry(coordinates=coords),
                 travel_time_min=round(seconds / 60, 3), distance_km=round(distance, 3),
                 exposure=min(1, max(0, exposure)),
                 exposure_breakdown_km=ExposureBreakdown(**breakdown), named_roads=names)


def compare_routes(recommended, fastest):
    warnings = []
    if recommended.geometry == fastest.geometry:
        warnings.append('The fastest route is also the recommended route under the configured exposure cost.')
    for route in (recommended, fastest):
        if route.exposure_breakdown_km.h1 > 0:
            warnings.append(f'{route.type.capitalize()} route crosses the modeled 1-hour risk region.')
    return warnings


def calculate_routes(request, fire, graph=None):
    if not request.household.has_vehicle:
        raise ValueError('This demo supports driving routes only; vehicle assistance is not modeled')
    graph = graph if graph is not None else load_graph()
    origin, snap_distance = nearest_node(graph, request.origin.lat, request.origin.lon)
    current = unary_union([shape(f['geometry']) for f in fire['risk_polygons']['current']['features']])
    if current.intersects(Point(request.origin.lon, request.origin.lat)):
        raise ValueError('Origin is inside the modeled current fire region')
    scored = score_graph(graph, fire)
    candidates = []
    for shelter in find_shelters(request.household):
        if current.intersects(Point(shelter.lon, shelter.lat)):
            continue
        try:
            destination, destination_snap = nearest_node(graph, shelter.lat, shelter.lon)
            recommended = route_edges(scored, origin, destination, 'risk_cost')
            cost = sum(scored[u][v][k]['risk_cost'] for u, v, k in recommended)
            candidates.append((cost, shelter.id, shelter, destination, destination_snap, recommended))
        except (ValueError, nx.NetworkXNoPath):
            continue
    if not candidates:
        raise ValueError('No reachable shelter satisfies the household constraints and current-fire blocks')
    _, _, shelter, destination, destination_snap, recommended_edges = min(candidates, key=lambda c: (c[0], c[1]))
    fastest_edges = route_edges(scored, origin, destination, 'travel_time')
    recommended = describe_route(scored, recommended_edges, 'recommended', origin)
    fastest = describe_route(scored, fastest_edges, 'fastest', origin)
    warnings = compare_routes(recommended, fastest)
    warnings.append('Synthetic demonstration data; roads, fire, shelter availability and times are not operational guidance.')
    warnings.append('Official evacuation orders and road closures override these modeled routes.')
    if max(snap_distance, destination_snap) > 1:
        warnings.append(f'Routes begin/end at road nodes: origin snap {snap_distance:.0f} m, shelter snap {destination_snap:.0f} m. Access segments are not modeled.')
    return PlanResponse(generated_at=datetime.now(timezone.utc).isoformat(),
        data_as_of=fire['data_as_of'], origin=request.origin, destination=shelter,
        routes=[recommended, fastest], warnings=warnings)
