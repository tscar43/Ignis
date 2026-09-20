import math

from pyproj import Transformer
from shapely import STRtree
from shapely.affinity import translate
from shapely.geometry import shape
from shapely.ops import transform, unary_union

BANDS = ('current', 'h1', 'h3', 'h6')
WEIGHTS = {'current': 0, 'h1': 10, 'h3': 4, 'h6': 1}
# Minutes per weighted kilometre; explicit units, unlike OSM travel_time (seconds).
RISK_LAMBDA = 4.0

# Smoke sits below every fire band: it is a health preference, not a lethality.
# It only ever reorders routes that fire and evacuation rules already allow.
SMOKE_WEIGHT = 3
# How far downwind to sweep the burning footprint.
# ponytail: a translated footprint is not a dispersion model -- no plume rise,
# no terrain channelling, no decay with distance. Swap in NOAA HMS smoke
# polygons if this ever needs to be more than a preference ordering.
PLUME_KM = 8.0
MAX_PLUME_COPIES = 64  # keeps the union cheap on a large footprint


def plume(fire, project):
    """The burning footprint swept downwind, in the caller's metric CRS.

    Smoke goes where the wind pushes it, and the payload already carries the
    bearing and the footprint -- so this needs no new data source. Sweeping
    rather than translating keeps the ground between the fire and the far edge
    of the plume, which is the part people actually drive through.
    """
    source = unary_union([transform(project, shape(f['geometry']))
                          for band in ('current', 'h1')
                          for f in fire['risk_polygons'][band]['features']])
    if source.is_empty:
        return source
    bearing = math.radians(fire['summary']['wind_toward_deg'])
    east, north = math.sin(bearing), math.cos(bearing)
    # The step has to be smaller than the footprint or the copies land apart
    # and the "plume" is a dotted line with clean air between the dots -- a
    # road threading one of those gaps would score zero smoke.
    west_, south_, east_, north_ = source.bounds
    step = max(50.0, min(east_ - west_, north_ - south_) / 2)
    steps = min(MAX_PLUME_COPIES, max(1, round(PLUME_KM * 1000 / step)))
    swept = unary_union([translate(source, east * step * i, north * step * i)
                         for i in range(steps + 1)])
    assert swept.geom_type == 'Polygon' or not source.geom_type == 'Polygon', (
        'a single footprint must sweep into one connected plume')
    return swept


def score_graph(graph, fire, avoid_smoke=False):
    """Copy graph, block current fire, score each segment's most severe band.

    Use an edge spatial index, and a local metric projection for intersections.
    Subtract higher-risk regions so cumulative bands never double-count distance.

    `avoid_smoke` adds the downwind plume as an extra cost. It is a preference,
    not a permission: it can only reorder routes that survive the fire blocking
    here and the evacuation-order filter in `routes.py`.
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
        edge['smoke_km'] = 0.0
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

    if avoid_smoke:
        # Same index, same projection, one more polygon. Deliberately not
        # differenced against `covered`: the bands measure where fire will be
        # and this measures what you breathe getting past it, so the two
        # overlap on purpose.
        downwind = plume(fire, project)
        for raw_index in index.query(downwind, predicate='intersects'):
            i = int(raw_index)
            u, v, key, _ = edges[i]
            if not scored.has_edge(u, v, key):
                continue
            edge = scored[u][v][key]
            km = min(edge['length'] / 1000,
                     geometries[i].intersection(downwind).length / 1000)
            edge['smoke_km'] = km
            edge['risk_cost'] += RISK_LAMBDA * SMOKE_WEIGHT * km
    return scored
