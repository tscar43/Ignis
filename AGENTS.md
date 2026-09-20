# Ignis — repo rules for agents

Three people are building this in parallel. This file exists so an agent
working in one area does not silently rewrite another area's work. Read it
before editing anything.

If you are working inside `backend/fire/` or `backend/weather/`, stop here and
read [backend/fire/AGENTS.md](backend/fire/AGENTS.md) instead — it has the
modelling rules this file does not repeat.

## Who owns what

| area | owner | agents from other areas |
|---|---|---|
| `backend/fire/`, `backend/weather/` | Justin (`jngo1129`) | **do not edit** |
| `demo_data/` | Justin — these are generated outputs | **do not edit**, do not hand-edit the JSON |
| `contracts/` | shared, currently empty | needs all three to agree |
| backend API / app entry point | backend agent (this session) | see backend/api/AGENTS.md |
| frontend / map | Daniel, per `frontend/README.md` | ask first — Justin added the national view tab (`NationalMap.jsx`) and the Palisades validation tab (`PalisadesView.jsx`); both are additive, App.jsx gained a third `view` arm and nothing else moved |
| `.gitignore`, `.vscode/`, `.mcp.json`, root `README.md` | shared | add to them, don't rewrite them |

Unclaimed areas are genuinely unclaimed: claim one by adding a row, and add
your own `AGENTS.md` next to your code the way `backend/fire/` does.

"Do not edit" is about **silent** edits, not permission. Ask in chat and it is
almost certainly fine. The reason for the rule is that the fire engine's files
are tested and contract-checked, and an agent that reformats or regenerates
them tends to break a guarantee it could not see.

## What already exists, so you don't rebuild it

The fire engine is done and merged: satellite detections, wind, fuel and
terrain in, 1h/3h/6h risk polygons out. It runs live or in replay against real
data. Full orientation in [backend/fire/README.md](backend/fire/README.md).

For consuming it, the one file to read is
[demo_data/README.md](demo_data/README.md) — the contract in prose, with key
names, units and CRS.

- `demo_data/risk_demo.json` — hand-drawn, deterministic, safe to build against.
- `demo_data/risk_replay.json` — four real frames of the 2018 Camp Fire.
- `demo_data/fuel_overlay.png` + `.json` — map overlay, EPSG:4326, with bounds
  in Leaflet order and a colour legend.
- `backend/fire/contract.py` — the machine-checkable version. Import
  `validate()` rather than writing your own checks.

For a live payload, call the engine rather than reading a file:

```python
from backend.fire.spread import risk_payload
risk_payload()
```

Three HTTP endpoints now exist. Two are live, in the API layer with a TTL
cache in front: `GET /fire` for the fixed engine area, and `GET /fires` for
every fire currently burning in the contiguous US. The third, `GET /palisades`,
reads a static fixture and never touches the network -- it is the model-vs-truth
replay of the January 2025 Palisades Fire, shape in `demo_data/README.md`,
regenerated with `python -m backend.fire.palisades --json`. The national sweep is
`backend/fire/national.py` — one FIRMS query, clustered into incidents, one
`risk_payload()` per incident in a process pool, joined to NIFC WFIGS for
official names, acreage, containment and -- where an agency has mapped one --
the perimeter the model seeds from. Its payload shape is in
[demo_data/README.md](demo_data/README.md); the frontend's second tab draws it.

## Rules that hold everywhere

- **Never `git add -A`.** Sessions run concurrently against this tree and the
  git index is shared. Stage explicit paths and read
  `git diff --cached --name-only` before committing. This has already filed one
  person's work under another's commit message twice (`a7acf52`, `40bcb40`).
- `git fetch origin` and check divergence before every push.
- Never commit `.env`, `.tif`, or anything over 10 MB.
- **Do not read `demo_data/risk_replay.json` into context.** It is 1.4 MB
  across 53,000 lines and will exhaust your context window in a single call.
  You need its shape, which is in `demo_data/README.md`, not its contents. For
  real JSON read `demo_data/risk_demo.json` (36 KB, same contract), or slice
  one frame:
  `./.venv/Scripts/python.exe -c "import json; print(json.load(open('demo_data/risk_replay.json'))[0]['summary'])"`
  The same goes for `backend/fire/cache/` and any `demo_data/*.png`.
- Payload geometry is **`[lon, lat]`**, EPSG:4326, and bands are **cumulative**
  (`h6 ⊇ h3 ⊇ h1 ⊇ current`). No JSON schema expresses either; `contract.py`
  does. If you need a key that is not in the contract, ask — do not add it to
  the JSON by hand.
- Python here is the venv interpreter, called by path:
  `./.venv/Scripts/python.exe`. A bare `python` is the system 3.14 with none of
  the geospatial wheels.
