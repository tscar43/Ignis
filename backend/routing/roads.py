from functools import lru_cache
from pathlib import Path
import os

import networkx as nx
from pyproj import Geod
from shapely import wkt
from shapely.geometry import LineString

DATA_DIR = Path(__file__).resolve().parent / 'demo'
OSM_PATH = Path(__file__).resolve().parent / 'osm' / 'paradise.graphml'
GEOD = Geod(ellps='WGS84')


@lru_cache(maxsize=1)
def load_graph():
    """Read only a local GraphML cache; never fetch roads in a request."""
    path = Path(os.environ.get('IGNIS_GRAPH_PATH', OSM_PATH))
    return read_graph(path)


@lru_cache(maxsize=4)
def read_graph(path):
    graph = nx.read_graphml(path, force_multigraph=True)
    if not graph.is_directed():
        raise ValueError('Road graph must be directed')
    for _, node in graph.nodes(data=True):
        node['x'], node['y'] = float(node['x']), float(node['y'])
    for u, v, _, edge in graph.edges(keys=True, data=True):
        edge['length'] = float(edge['length'])
        edge['travel_time'] = float(edge['travel_time'])
        edge['geometry'] = wkt.loads(edge['geometry']) if 'geometry' in edge else LineString([
            (graph.nodes[u]['x'], graph.nodes[u]['y']),
            (graph.nodes[v]['x'], graph.nodes[v]['y']),
        ])
        if edge['length'] <= 0 or edge['travel_time'] <= 0:
            raise ValueError('Road lengths and travel times must be positive')
    return graph


def nearest_node(graph, lat, lon, max_distance_m=1000):
    distances = [(abs(GEOD.inv(lon, lat, node['x'], node['y'])[2]), key)
                 for key, node in graph.nodes(data=True)]
    distance, node = min(distances)
    if distance > max_distance_m:
        raise ValueError('Location is outside the cached road network (maximum snap distance 1 km)')
    return node, distance
