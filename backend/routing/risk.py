from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import shape
from shapely.ops import transform, unary_union

BANDS = ('current', 'h1', 'h3', 'h6')
WEIGHTS = {'current': 0, 'h1': 10, 'h3': 4, 'h6': 1}
# Minutes per weighted kilometre; explicit units, unlike OSM travel_time (seconds).
RISK_LAMBDA = 4.0


def score_graph(graph, fire):
    """Copy graph, block current fire, score each edge's most severe band.

    Use an edge spatial index, and a local metric projection for intersections.
    Only intersection length in the selected band is counted (no cumulative overlap).
    """
    scored = graph.copy()
    first = next(iter(graph.nodes.values()))
    project = Transformer.from_crs('EPSG:4326',
        f"+proj=aeqd +lat_0={first['y']} +lon_0={first['x']} +datum=WGS84 +units=m",
        always_xy=True).transform
    edges = list(graph.edges(keys=True, data=True))
    geometries = [transform(project, e['geometry']) for _, _, _, e in edges]
    index = STRtree(geometries)
    assigned = set()
    for _, _, _, edge in scored.edges(keys=True, data=True):
        edge['exposure_km'] = dict.fromkeys(BANDS, 0.0)
        edge['risk_cost'] = edge['travel_time'] / 60
    for band in BANDS:
        polygon = unary_union([transform(project, shape(f['geometry']))
                               for f in fire['risk_polygons'][band]['features']])
        for raw_index in index.query(polygon, predicate='intersects'):
            i = int(raw_index)
            if i in assigned:
                continue
            assigned.add(i)
            u, v, key, _ = edges[i]
            if band == 'current':
                scored.remove_edge(u, v, key)
                continue
            edge = scored[u][v][key]
            km = min(edge['length'] / 1000, geometries[i].intersection(polygon).length / 1000)
            edge['exposure_km'][band] = km
            edge['risk_cost'] += RISK_LAMBDA * WEIGHTS[band] * km
    return scored
