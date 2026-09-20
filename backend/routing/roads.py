from functools import lru_cache
from math import isfinite
from pathlib import Path
import os
from xml.etree.ElementTree import ParseError

import networkx as nx
from pyproj import Geod
from shapely.errors import GEOSException
from shapely import wkt
from shapely.geometry import LineString

DATA_DIR = Path(__file__).resolve().parent / 'demo'
OSM_PATH = Path(__file__).resolve().parent / 'osm' / 'paradise.graphml'
GEOD = Geod(ellps='WGS84')


def _positive(value, what):
    """A length or a duration: a real number, greater than zero.

    `value <= 0` is False for NaN, so a NaN length passed the old check and
    then poisoned every shortest-path sum that touched it -- readiness green,
    routing broken later and nowhere near the cause.
    """
    number = float(value)
    if not isfinite(number) or number <= 0:
        raise ValueError(f'{what} must be a positive finite number, got {value!r}')
    return number


def _coordinate(value, what):
    number = float(value)
    if not isfinite(number):
        raise ValueError(f'{what} must be finite, got {value!r}')
    return number


class RoadUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def load_graph():
    """Read only a local GraphML cache; never fetch roads in a request."""
    path = Path(os.environ.get('IGNIS_GRAPH_PATH', OSM_PATH))
    return read_graph(path)


@lru_cache(maxsize=4)
def read_graph(path):
    try:
        graph = nx.read_graphml(path, force_multigraph=True)
        if not graph.nodes or not graph.edges:
            raise ValueError('Road graph must contain nodes and edges')
        if not graph.is_directed():
            raise ValueError('Road graph must be directed')
        for key, node in graph.nodes(data=True):
            node['x'] = _coordinate(node['x'], f'node {key} x')
            node['y'] = _coordinate(node['y'], f'node {key} y')
            if not (-180 <= node['x'] <= 180 and -90 <= node['y'] <= 90):
                raise ValueError(f'node {key} is not a [lon, lat] position')
        for u, v, _, edge in graph.edges(keys=True, data=True):
            edge['length'] = _positive(edge['length'], f'edge {u}->{v} length')
            edge['travel_time'] = _positive(edge['travel_time'],
                                            f'edge {u}->{v} travel_time')
            edge['geometry'] = wkt.loads(edge['geometry']) if 'geometry' in edge else LineString([
                (graph.nodes[u]['x'], graph.nodes[u]['y']),
                (graph.nodes[v]['x'], graph.nodes[v]['y']),
            ])
            # A road edge has to be a line. A POINT in the geometry column
            # parsed happily and then met every intersects() check as
            # something that cannot cross a fire polygon -- a road that is
            # never blocked, which is the worst possible failure here.
            geometry = edge['geometry']
            if geometry.geom_type != 'LineString':
                raise ValueError(
                    f'edge {u}->{v} geometry must be a LineString, '
                    f'got {geometry.geom_type}')
            if geometry.is_empty or len(geometry.coords) < 2:
                raise ValueError(f'edge {u}->{v} geometry needs two or more points')
            if any(not (isfinite(x) and isfinite(y)) for x, y in geometry.coords):
                raise ValueError(f'edge {u}->{v} geometry has non-finite coordinates')
        return graph
    except (OSError, ValueError, KeyError, TypeError, ParseError, nx.NetworkXException, GEOSException) as exc:
        raise RoadUnavailable('Road cache missing or invalid') from exc



def bounds(graph):
    """(west, south, east, north) of the graph's nodes, in EPSG:4326."""
    xs = [node['x'] for _, node in graph.nodes(data=True)]
    ys = [node['y'] for _, node in graph.nodes(data=True)]
    return min(xs), min(ys), max(xs), max(ys)


def within(graph, bbox) -> bool:
    """Whether every node of `graph` falls inside `bbox` (W, S, E, N).

    The fire model runs over one fixed bbox while `IGNIS_GRAPH_PATH` can point
    anywhere. A graph outside that bbox still routes, and every hazard
    intersection comes back empty -- not because the roads are safe, but
    because the fire polygons are somewhere else entirely. Evacuation coverage
    is checked separately and does not substitute for this.
    """
    west, south, east, north = bbox
    gw, gs, ge, gn = bounds(graph)
    return west <= gw and gs >= south and ge <= east and gn <= north


def nearest_node(graph, lat, lon, max_distance_m=1000):
    distances = [(abs(GEOD.inv(lon, lat, node['x'], node['y'])[2]), key)
                 for key, node in graph.nodes(data=True)]
    distance, node = min(distances)
    if distance > max_distance_m:
        raise ValueError('Location is outside the cached road network (maximum snap distance 1 km)')
    return node, distance
