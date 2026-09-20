# Paradise OpenStreetMap road cache

`paradise.graphml` is the default road network for `/plan`. It contains 1,279
nodes and 2,863 directed edges, downloaded with OSMnx 2.1.1 on
2026-09-19 at 15:00:20 (timestamp stored by the original cache).
The query center was latitude 39.76, longitude -121.62 with a 3,000 m radius.
This is Paradise, California, not Auburn. It is not a nationwide road network.

The file is copied unchanged from the earlier `demo_data/graph.graphml` cache
into the backend-owned routing directory. Lengths are metres; travel times are
seconds estimated by OSMnx from road speeds. One-way connections and road
geometry are preserved. Closures, traffic and turn restrictions are not modeled.
Shelters remain fictional; this cache does not establish shelter availability.

Data: © OpenStreetMap contributors, licensed under ODbL:
https://www.openstreetmap.org/copyright
Generator documentation: https://osmnx.readthedocs.io/en/stable/user-reference.html

To rebuild (network required only at build time):

```powershell
./.venv/Scripts/python.exe -m pip install -r backend/routing/requirements.txt
./.venv/Scripts/python.exe -m backend.routing.cache_osm
```

For another prepared area, use `--lat`, `--lon`, `--radius-m`, and `--output`,
then set `IGNIS_GRAPH_PATH` to the resulting file. Supply matching destinations
with `IGNIS_SHELTERS_PATH`. `/plan` never downloads roads during a request.
Restart the API after replacing a cache file.
