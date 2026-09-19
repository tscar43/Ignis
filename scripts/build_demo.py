"""Generate a tiny, explicitly synthetic offline routing fixture. No network calls."""
import json
from pathlib import Path

import networkx as nx
from pyproj import Geod
from shapely.geometry import LineString, box, mapping

ROOT = Path(__file__).resolve().parents[1] / 'backend' / 'routing' / 'demo'


def build():
    ROOT.mkdir(exist_ok=True)
    graph = nx.MultiDiGraph(crs='epsg:4326', source='synthetic demonstration')
    nodes = {'origin': (-121.62, 39.76), 'direct': (-121.60, 39.76),
             'east': (-121.58, 39.76), 'southwest': (-121.62, 39.74),
             'southeast': (-121.58, 39.74), 'north': (-121.58, 39.78),
             'far_east': (-121.56, 39.76), 'far_north': (-121.58, 39.80)}
    for key, (lon, lat) in nodes.items():
        graph.add_node(key, x=lon, y=lat)
    geod = Geod(ellps='WGS84')
    for u, v, minutes, name in [('origin', 'direct', 2, 'Demo Central Road'),
        ('direct', 'east', 2, 'Demo Central Road'), ('origin', 'southwest', 3, 'Demo South Road'),
        ('southwest', 'southeast', 3, 'Demo Bypass'), ('southeast', 'east', 3, 'Demo East Road'),
        ('east', 'north', 3, 'Demo North Road'), ('east', 'far_east', 3, 'Demo Extension'),
        ('north', 'far_north', 3, 'Demo North Road')]:
        length = abs(geod.inv(*nodes[u], *nodes[v])[2])
        for a, b in [(u, v), (v, u)]:
            graph.add_edge(a, b, length=length, travel_time=minutes * 60,
                           name=name, geometry=LineString([nodes[a], nodes[b]]).wkt)
    nx.write_graphml(graph, ROOT / 'graph.graphml')
    shelters = []
    for i, (node, pets, accessible) in enumerate([
        ('east', True, True), ('north', False, True),
        ('far_east', True, False), ('far_north', True, True)], 1):
        lon, lat = nodes[node]
        shelters.append(dict(id=f'shelter_{i:02}', name=f'Demo shelter {i} (fictional)',
            lon=lon, lat=lat, accepts_pets=pets, accessible=accessible, capacity=100 * i))
    (ROOT / 'shelters.json').write_text(json.dumps(shelters, indent=2) + '\n', encoding='utf-8')
    def collection(geom=None):
        return {'type': 'FeatureCollection', 'features': [] if geom is None else [
            {'type': 'Feature', 'properties': {}, 'geometry': mapping(geom)}]}
    fire = dict(generated_at='2026-09-19T12:00:00Z',
        data_as_of=dict(firms='synthetic', weather='synthetic'), fire_points=collection(),
        risk_polygons={
            'current': collection(box(-121.604, 39.767, -121.596, 39.770)),
            'h1': collection(box(-121.607, 39.755, -121.593, 39.773)),
            'h3': collection(box(-121.610, 39.753, -121.590, 39.775)),
            'h6': collection(box(-121.613, 39.750, -121.587, 39.778))},
        summary={'note': 'Synthetic demo only; not real fire predictions or shelter availability.'})
    (ROOT / 'fire.json').write_text(json.dumps(fire, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    build()
