"""Prepare a local drive network; never called from an HTTP request."""
import argparse
from pathlib import Path

from .roads import OSM_PATH


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lat', type=float, default=39.76)
    parser.add_argument('--lon', type=float, default=-121.62)
    parser.add_argument('--radius-m', type=int, default=3000)
    parser.add_argument('--output', type=Path, default=OSM_PATH)
    args = parser.parse_args()
    if not (-90 <= args.lat <= 90 and -180 <= args.lon <= 180 and args.radius_m > 0):
        parser.error('Provide valid latitude/longitude and a positive radius.')
    import osmnx as ox

    graph = ox.graph_from_point((args.lat, args.lon), dist=args.radius_m, network_type='drive')
    graph = ox.routing.add_edge_speeds(graph)
    graph = ox.routing.add_edge_travel_times(graph)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    ox.io.save_graphml(graph, filepath=args.output)
    print(f'Saved {args.output}: {len(graph)} nodes, {graph.number_of_edges()} edges')


if __name__ == '__main__':
    main()
