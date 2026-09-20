"""One-off script: download and cache the demo road graph.

Run once (needs internet): .venv/Scripts/python scripts/cache_graph.py
After that, the app only reads demo_data/graph.graphml — never Overpass.
"""

from pathlib import Path

import osmnx as ox

CENTER = (39.76, -121.62)  # demo area (Auburn CA vicinity, per brief examples)
DIST_M = 3000
OUT = Path(__file__).resolve().parent.parent / "demo_data" / "graph.graphml"


def main() -> None:
    print(f"Downloading drive graph around {CENTER} (dist {DIST_M} m)...")
    g = ox.graph_from_point(CENTER, dist=DIST_M, network_type="drive")
    ox.add_edge_speeds(g)
    ox.add_edge_travel_times(g)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ox.save_graphml(g, OUT)
    print(f"Saved {OUT} — {len(g.nodes)} nodes, {len(g.edges)} edges")
    print(f"File size: {OUT.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
