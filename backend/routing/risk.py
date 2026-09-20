from pyproj import Transformer
from shapely import STRtree
from shapely.geometry import shape
from shapely.ops import transform, unary_union

BANDS = ('current', 'h1', 'h3', 'h6')
WEIGHTS = {'current': 0, 'h1': 10, 'h3': 4, 'h6': 1}
# Minutes per weighted kilometre; explicit units, unlike OSM travel_time (seconds).
RISK_LAMBDA = 4.0


def score_graph(graph, fire):
    """Copy graph, block current fire, score each segment's most severe band.

    Use an edge spatial index, and a local metric projection for intersections.
    Subtract higher-risk regions so cumulative bands never double-count distance.
    """
    scored = graph.copy()
    first = next(iter(graph.nodes.values()))
    project = Transformer.from_crs('EPSG:4326',
        f"+proj=aeqd +lat_0={first['y']} +lon_0={first['x']} +datum=WGS84 +units=m",
        always_xy=True).transform
    edges = list(graph.edges(keys=True, data=True))
    geometries = [transform(project, e['geometry']) for _, _, _, e in edges]
    index = STRtree(geometries)
    covered = unary_union([])
    for _, _, _, edge in scored.edges(keys=True, data=True):
        edge['exposure_km'] = dict.fromkeys(BANDS, 0.0)
        edge['risk_cost'] = edge['travel_time'] / 60
    for band in BANDS:
        polygon = unary_union([transform(project, shape(f['geometry']))
                               for f in fire['risk_polygons'][band]['features']])
        for raw_index in index.query(polygon, predicate='intersects'):
            i = int(raw_index)
            u, v, key, _ = edges[i]
            if not scored.has_edge(u, v, key):
                continue
            if band == 'current':
                scored.remove_edge(u, v, key)
                continue
            edge = scored[u][v][key]
            length = geometries[i].intersection(polygon).difference(covered).length
            remaining = max(0, edge['length'] / 1000 - sum(edge['exposure_km'].values()))
            km = min(remaining, length / 1000)
            edge['exposure_km'][band] = km
            edge['risk_cost'] += RISK_LAMBDA * WEIGHTS[band] * km
        covered = covered.union(polygon)
    return scored
