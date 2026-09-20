from datetime import datetime, timezone
from itertools import islice

import networkx as nx
from shapely.geometry import LineString, Point, shape
from shapely.ops import unary_union

from ..api.evacuations import EvacuationsUnavailable, origin_orders, read_evacuations
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
    breakdown['smoke'] = 0.0
    for u, v, key in edges:
        edge = graph[u][v][key]
        breakdown['smoke'] += edge.get('smoke_km', 0.0)
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
    # `exposure` stays a fire number, so a smoke-avoiding route is not scored
    # as more dangerous than the one it replaced. Smoke is reported separately.
    exposure = sum(WEIGHTS[b] * breakdown[b] for b in BANDS) / (10 * distance) if distance else 0
    return Route(type=kind, geometry=RouteGeometry(coordinates=coords),
                 travel_time_min=round(seconds / 60, 3), distance_km=round(distance, 3),
                 exposure=min(1, max(0, exposure)),
                 exposure_breakdown_km=ExposureBreakdown(**breakdown), named_roads=names)


def order_allows(line, zones, origin):
    """Avoid entering order/warning zones; permit a contiguous exit from origin's zone."""
    for zone in zones:
        intersection = line.intersection(zone)
        if intersection.is_empty:
            continue
        if not zone.covers(origin) or not zone.covers(Point(line.coords[0])):
            return False
        # A multi-part intersection would allow leaving then re-entering the zone.
        if intersection.geom_type not in ('LineString', 'Point'):
            return False
    return True


def oriented_line(graph, u, edge):
    coords = list(edge['geometry'].coords)
    node = Point(graph.nodes[u]['x'], graph.nodes[u]['y'])
    if node.distance(Point(coords[-1])) < node.distance(Point(coords[0])):
        coords.reverse()
    return LineString(coords)


def alternative_edges(graph, start, end, primary):
    """At most one distinct alternative: <=50% detour and <=80% shared length.

    ponytail: inspect only 20 shortest simple paths; use a corridor-aware routing
    engine if this bounded search misses useful alternatives on larger networks.
    """
    simple = nx.DiGraph()
    simple.add_nodes_from(graph.nodes)
    for u, v, key, edge in graph.edges(keys=True, data=True):
        if not simple.has_edge(u, v) or edge['travel_time'] < simple[u][v]['weight']:
            simple.add_edge(u, v, weight=edge['travel_time'], key=key)
    primary_time = sum(graph[u][v][k]['travel_time'] for u, v, k in primary)
    primary_length = sum(graph[u][v][k]['length'] for u, v, k in primary)
    if not primary_length:
        return None
    primary_set = set(primary)
    for nodes in islice(nx.shortest_simple_paths(simple, start, end, weight='weight'), 20):
        edges = [(u, v, simple[u][v]['key']) for u, v in zip(nodes, nodes[1:])]
        seconds = sum(graph[u][v][k]['travel_time'] for u, v, k in edges)
        if seconds > primary_time * 1.5:
            break
        length = sum(graph[u][v][k]['length'] for u, v, k in edges)
        shared = sum(graph[u][v][k]['length'] for u, v, k in edges if (u, v, k) in primary_set)
        if length and shared / min(length, primary_length) <= 0.8:
            return edges
    return None


def calculate_routes(request, fire, graph=None, *, evacuation_data=None, shelters=None, apply_orders=True):
    if request.mode == 'live' and not apply_orders:
        raise ValueError('Evacuation restrictions cannot be disabled for live routing')
    if not request.household.has_vehicle:
        raise ValueError('This demo supports driving routes only; vehicle assistance is not modeled')
    evacuation = origin_orders(evacuation_data if evacuation_data is not None else read_evacuations(request.mode),
                               request.origin.lon, request.origin.lat)
    if request.mode == 'live' and evacuation['status'] != 'fresh':
        raise EvacuationsUnavailable('Live routing requires a fresh evacuation snapshot for the area')
    snapshot = evacuation['snapshot']
    coverage = shape(snapshot['coverage']) if snapshot else None
    zones = [shape(f['geometry']) for f in snapshot['features']
             if f['properties']['level'] in ('order', 'warning')] if snapshot and apply_orders else []
    graph = graph if graph is not None else load_graph()
    avoid_smoke = request.household.respiratory_sensitive
    origin, snap_distance = nearest_node(graph, request.origin.lat, request.origin.lon)
    current = unary_union([shape(f['geometry']) for f in fire['risk_polygons']['current']['features']])
    blocked = unary_union([current] + [shape(f['geometry']) for f in fire['risk_polygons']['h1']['features']])
    origin_point = Point(request.origin.lon, request.origin.lat)
    if current.intersects(origin_point):
        raise ValueError('Origin is inside the modeled current fire region')
    if blocked.intersects(origin_point):
        raise ValueError('Origin is inside the modeled 1-hour risk region; no route meets the routing policy')
    origin_node = graph.nodes[origin]
    origin_connector = LineString([(request.origin.lon, request.origin.lat),
                                   (origin_node['x'], origin_node['y'])])
    if blocked.intersects(origin_connector):
        raise ValueError('Origin access to the road network intersects current fire or the 1-hour risk region')
    if not order_allows(origin_connector, zones, origin_point):
        raise ValueError('Origin access enters an evacuation order or warning zone')
    if coverage is not None and not coverage.covers(origin_connector):
        raise ValueError('Origin access is outside evacuation data coverage')
    scored = score_graph(graph, fire, avoid_smoke=avoid_smoke)
    for u, v, key, edge in list(scored.edges(keys=True, data=True)):
        line = oriented_line(scored, u, edge)
        if (blocked.intersects(line) or not order_allows(line, zones, origin_point)
                or (coverage is not None and not coverage.covers(line))):
            scored.remove_edge(u, v, key)
    candidates = []
    if shelters is None:
        shelters = (find_shelters(request.household) if request.shelter_source == 'demo'
                    else find_shelters(request.household, source=request.shelter_source))
    for shelter in shelters:
        facility = Point(shelter.lon, shelter.lat)
        if blocked.intersects(facility) or any(z.intersects(facility) for z in zones):
            continue
        if coverage is not None and not coverage.covers(facility):
            continue
        try:
            if shelter.source == 'fema' and shelter.entrance is None:
                continue
            target = shelter.entrance or shelter
            destination, destination_snap = nearest_node(
                graph, target.lat, target.lon, max_distance_m=50 if shelter.source == 'fema' else 1000)
            node = graph.nodes[destination]
            connector = LineString([(node['x'], node['y']), (target.lon, target.lat)])
            target_point = Point(target.lon, target.lat)
            if (blocked.intersects(connector) or blocked.intersects(target_point)
                    or any(z.intersects(connector) or z.intersects(target_point) for z in zones)
                    or (coverage is not None and not coverage.covers(connector))):
                continue
            # risk_cost, not travel_time: it is travel minutes plus the
            # weighted hazard penalty risk.py computes. Routing on raw
            # travel_time meant WEIGHTS and RISK_LAMBDA were calculated for
            # every edge and then never consulted, so the h1/h3/h6 bands only
            # ever mattered where they blocked an edge outright.
            edges = route_edges(scored, origin, destination, 'risk_cost')
            if not edges:
                continue  # A node snap alone is not a driving route to a shelter.
            seconds = sum(scored[u][v][k]['travel_time'] for u, v, k in edges)
            candidates.append((seconds, shelter.id, shelter, destination, destination_snap, edges))
        except (ValueError, nx.NetworkXNoPath):
            continue
    if not candidates:
        if request.shelter_source == 'fema':
            raise ValueError('No eligible FEMA shelter: requires a fresh OPEN record, household capacity/policies, a reviewed entrance within 50 m of the road network, and a route meeting hazard and evacuation restrictions')
        raise ValueError('No reachable shelter satisfies household, fire-risk and evacuation restrictions')
    _, _, shelter, destination, destination_snap, primary_edges = min(candidates, key=lambda c: (c[0], c[1]))
    primary = describe_route(scored, primary_edges, 'recommended' if apply_orders else 'comparison', origin)
    routes = [primary]
    warnings = []
    if evacuation['status'] in ('fresh', 'historical') and apply_orders:
        edges = alternative_edges(scored, origin, destination, primary_edges)
        if edges:
            alternative = describe_route(scored, edges, 'alternative', origin)
            if alternative.geometry != primary.geometry:
                routes.append(alternative)
    elif not apply_orders:
        warnings.append('DEMO COMPARISON ONLY: historical evacuation restrictions are ignored; this route is not an evacuation recommendation.')
    else:
        warnings.append('Evacuation information is unknown or stale; alternatives are withheld. This is a modeled demonstration route only.')
    if len(routes) == 1:
        warnings.append('No distinct alternative meeting the routing policy is available.')
    for route in routes:
        if route.exposure_breakdown_km.h3 or route.exposure_breakdown_km.h6:
            warnings.append(f'{route.type.capitalize()} route crosses a modeled 3-hour or 6-hour risk region.')
    if evacuation['origin_orders']:
        warnings.append('Origin has evacuation information: read evacuation.origin_orders for the issuing authority and instructions.')
    warnings.append('Routes exclude current fire and 1-hour risk. These checks do not certify safety.')
    if avoid_smoke:
        warnings.append('Smoke preference applied: routes prefer to stay out of the modeled '
                        'downwind plume. This is the burning footprint swept along the forecast '
                        'wind, not measured air quality, and it never overrides an evacuation '
                        'order. Anyone with a respiratory condition should follow medical advice '
                        'and official instructions over this route.')
        if all(r.exposure_breakdown_km.smoke for r in routes):
            warnings.append('Every available route still passes through the modeled plume; '
                            'the preference could only reduce it, not avoid it.')
    if apply_orders:
        warnings.append('Routes avoid entering supplied evacuation order/warning zones; an origin inside a zone may exit without re-entry.')
    if graph.graph.get('source') == 'synthetic demonstration':
        warnings.append('Roads are synthetic demonstration data.')
    else:
        warnings.append('Routes use a cached road network with estimated travel times; traffic and turn restrictions are not modeled.')
    if shelter.source == 'demo':
        warnings.append('Shelter capacity and availability are not verified; bundled shelters are fictional demonstration locations.')
    else:
        warnings.append('FEMA status and nominal capacity are source reports, not guaranteed available beds; confirm with the operator.')
        warnings.append('The route ends at a road node near a reviewed entrance; the access connector is not a modeled driving route.')
    warnings.append('Official evacuation orders and road closures override these modeled routes. Road closure data is not integrated.')
    if max(snap_distance, destination_snap) > 1:
        warnings.append(f'Routes begin/end at road nodes: origin snap {snap_distance:.0f} m, shelter snap {destination_snap:.0f} m. Access segments are not modeled.')
    return PlanResponse(generated_at=datetime.now(timezone.utc).isoformat(),
        data_as_of=fire['data_as_of'], origin=request.origin, destination=shelter,
        routes=routes, warnings=warnings, evacuation=evacuation)
