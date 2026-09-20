# `POST /plan` returns 422 for every replay frame

**Status:** open. `mode=demo` was broken too and is now fixed — see
[What was already fixed](#what-was-already-fixed). What remains is replay, and
it is more a design decision than a defect.

**Filed by:** the fire-engine session, for whoever owns `backend/routing/`.
Nothing under `routing/` or `shelters/` was changed to write this; it is a
report, measured against `ab35ccb`.

**Why it matters now:** the evacuation agent being built next calls `/plan`,
and the Camp Fire replay is the scenario the whole pitch is built around.

## Current behaviour

```bash
curl -s -X POST http://localhost:8000/plan -H 'Content-Type: application/json' \
  -d '{"origin":{"lat":39.76,"lon":-121.62,"label":"123 Oak St"}}'
# 200 — routes to a shelter

curl -s -X POST http://localhost:8000/plan -H 'Content-Type: application/json' \
  -d '{"origin":{"lat":39.76,"lon":-121.62,"label":"123 Oak St"},"mode":"replay","t":"T0"}'
# 422 {"detail":"No reachable shelter satisfies household, fire-risk and evacuation restrictions"}
```

Replay fails at every frame. Measured against the 1,279-node Paradise graph:

| payload | edges blocked | reachable | no path | off-network |
|---|---|---|---|---|
| `demo` `T0` | 514 / 2863 | **2** | 0 | 2 |
| `replay` `T0` | 1801 / 2863 | 0 | 2 | 2 |
| `replay` `H1` | 1851 / 2863 | 0 | 2 | 2 |
| `replay` `H6` | 1497 / 2863 | 0 | 2 | 2 |

## Root cause

`routes.calculate_routes` blocks the union of the `current` and `h1` regions,
and `risk.score_graph` enforces the `current` part by deleting edges outright:

```python
if band == 'current':
    scored.remove_edge(u, v, key)
```

On the Camp Fire that union covers **63–65% of the road network**. The two
shelters that are on the network end up in a different component from the
origin, `NetworkXNoPath` is swallowed by the `continue` at `routes.py:165`,
`candidates` comes back empty, and the endpoint raises one sentence.

**This is not wrong about the fire.** Paradise really was cut off on the
morning of 8 November 2018; a model that said otherwise would be lying. The
problem is what the API does with that fact.

## The actual question

An evacuation tool answering "no" with a single unstructured string is the one
behaviour it cannot afford. Three things need deciding, in this order:

### 1. What should "every route is blocked" return?

- **Least-bad route.** Replace `remove_edge` with a large finite penalty so a
  path always exists, and return it with `blocked: true` plus the exposure it
  costs. Preference ordering is unchanged; the UI shouts about it. This is what
  a real evacuation product does — people are on that road either way, and the
  system's job is to pick the least lethal one.
- **Explicit refusal.** Keep the deletion, but return a distinct status (409,
  or 200 with `routes: []`) so the UI can say "no route out is clear of the
  fire — follow official instructions" rather than rendering an error toast.

Either is defensible. The current 422, which reads like a household-constraints
problem, is not.

### 2. Make the reason machine-readable

One `detail` string currently covers household capacity and policies, hazard
blocks, evacuation-zone rules, FEMA record freshness, and snap failures. A
client cannot tell "try a different household" from "the fire has you
surrounded". Collect the per-shelter reason instead of `continue`:

```json
{"detail": "No route to any shelter",
 "reasons": {"shelter_01": "cut off by the current fire region",
             "shelter_03": "1.4 km from the nearest mapped road"}}
```

### 3. Put the last two shelters on the road network

Two of four shelters are further than the 1 km snap limit from any graph node,
in **every** mode including the one that works. That halves the candidate pool
before the fire is even considered. Moving them onto their nearest node is a
fixture edit, not code.

## What was already fixed

Between `7ae57a8` and `ab35ccb` the routing session fixed the worse half of
this, and this file no longer describes it:

- `fdd75bd` routes the demo over the cached 1,279-node OSM graph instead of the
  8-node synthetic one. The old graph was ~2 km across against fire regions
  tens of km wide, so `mode=demo` removed 6 of 16 edges and split the network
  into three components.
- `3cb4bc5` makes default demo routing reachable against the published hazards.
- `9034fd2` brings in the FEMA shelter catalogue with reviewed entrances.

## Regression gap

`backend/routing/demo/fire.json`, the fixture the routing tests route against,
blocks **0 of 2,863** edges — its risk regions touch no road. The suite
exercises the scoring maths and never the case where fire and roads overlap,
which is the only case that matters. One test routing against
`demo_data/risk_demo.json` and one replay frame would close it.

Reproduce the table above:

```bash
./.venv/Scripts/python.exe - <<'EOF'
import networkx as nx
from backend.api.fire_service import get_fire_result
from backend.models import Household
from backend.routing.risk import score_graph
from backend.routing.roads import load_graph, nearest_node
from backend.shelters.shelters import find_shelters

graph = load_graph()
origin, _ = nearest_node(graph, 39.76, -121.62)
shelters = find_shelters(Household())
for mode, t in (("demo", "T0"), ("replay", "T0"), ("replay", "H6")):
    scored = score_graph(graph, get_fire_result(mode, t).payload)
    ok = off = nopath = 0
    for s in shelters:
        try:
            node, _ = nearest_node(graph, s.lat, s.lon)
            ok, nopath = (ok + 1, nopath) if nx.has_path(scored, origin, node) else (ok, nopath + 1)
        except ValueError:
            off += 1
    print(f"{mode}/{t}: blocked {graph.number_of_edges() - scored.number_of_edges()}"
          f"/{graph.number_of_edges()} edges | reachable {ok}, no path {nopath}, off-network {off}")
EOF
```
