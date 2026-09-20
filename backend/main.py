import os
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.chat import reply as chat_reply
from .api.evacuations import EvacuationsUnavailable, read_evacuations, origin_orders
from .api.palisades_demo import (DemoUnavailable, PalisadesDemoRequest, PalisadesPlanResponse,
                                 ROUTING, demo_info, plan_demo)
from .api.fire_service import (FireUnavailable, get_fire_result,
                               get_national_result, get_palisades_replay)
from .models import (ChatRequest, GeocodeRequest, Household, Origin,
                     PlanRequest, PlanResponse, ReplayTime, Shelter)
from .routing.routes import calculate_routes
from .shelters.shelters import find_shelters
from .shelters.fema import ShelterUnavailable, access_report, read_catalogue
from .routing.roads import RoadUnavailable, load_graph, read_graph, within
from .fire.firms import DEMO_BBOX

app = FastAPI(title='Ignis API', version='0.3.0')
app.add_middleware(CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get(
        'IGNIS_CORS_ORIGINS', 'http://localhost:5173,http://localhost:3000').split(',')
        if origin.strip()],
    allow_methods=['GET', 'POST'], allow_headers=['*'],
    expose_headers=['X-Fire-Source', 'X-Fire-Stale', 'X-Fire-Cache-Age'])


@app.exception_handler(RoadUnavailable)
@app.exception_handler(DemoUnavailable)
async def unavailable_dataset(request, exc):
    return JSONResponse(status_code=503, content={'detail': str(exc)})


@app.get('/ready')
def ready():
    """Validate bundled demo inputs without calling live upstream services.

    Every offline surface the demo actually presents is loaded here, including
    the Camp replay behind `/scenario/*`. Checking only the demo frame left
    readiness able to report ready while every replay offset returned 503.

    FireUnavailable and the dataset errors are all RuntimeError subclasses and
    were not caught, so a missing fixture escaped as a 500 from the one
    endpoint whose job is to say the data is missing.
    """
    try:
        get_fire_result('demo', 'T0')
        for offset in ('T0', 'H1', 'H3', 'H6'):
            get_fire_result('replay', offset)
        load_graph()
        find_shelters()
        demo_info()
        read_graph(ROUTING / 'osm/palisades.graphml')
    except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
        raise HTTPException(503, f'Demo data missing or invalid: {exc}') from exc
    return {'status': 'ready', 'scope': 'offline_demos'}


@app.get('/health')
def health():
    return {'status': 'ok', 'service': 'wildfire-evacuation-intelligence'}


def fire_headers(response, result, source=None):
    response.headers['X-Fire-Source'] = source or result.source
    response.headers['X-Fire-Stale'] = str(result.stale).lower()
    response.headers['X-Fire-Cache-Age'] = str(result.age_seconds)
    # Cache age is when we last fetched; observation age is how old the data
    # is. They are different numbers and only the second one says whether the
    # fire picture is current.
    if result.observation_age_seconds is not None:
        response.headers['X-Fire-Observation-Age'] = str(result.observation_age_seconds)
    response.headers['Cache-Control'] = 'no-store'


def fire_for_time(mode, t, response):
    try:
        result = get_fire_result(mode, t)
    except FireUnavailable as exc:
        raise HTTPException(503, str(exc), headers={'Retry-After': '30'}) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    fire_headers(response, result)
    return result.payload, result


@app.get('/fire', response_model=None)
def fire(response: Response, mode: Literal['demo', 'replay', 'live'] = 'demo',
         t: ReplayTime = 'T0'):
    """Fixed engine area; mode explicitly selects demo, historical replay, or live."""
    return fire_for_time(mode, t, response)[0]


@app.get('/fires', response_model=None)
def fires(response: Response):
    """Every wildfire currently burning in CONUS, each with its own risk bands.

    `/fire` is one engine area; this is the national sweep. Cached longer --
    see fire_service.national_cache -- and the cache headers say how old it is.
    """
    try:
        result = get_national_result()
    except FireUnavailable as exc:
        raise HTTPException(503, str(exc), headers={'Retry-After': '30'}) from exc
    fire_headers(response, result, source='live-national')
    return result.payload


@app.get('/palisades', response_model=None)
def palisades():
    """Stepped model-vs-truth replay of the January 2025 Palisades Fire.

    A static fixture, not a live run: the tab is presented in front of people
    and must not wait on a FIRMS round trip. Regenerate it with
    `python -m backend.fire.palisades --json`.
    """
    return get_palisades_replay()


@app.get('/shelters', response_model=list[Shelter])
def shelters(accepts_pets: bool = False, wheelchair_accessible: bool = False,
             occupants: int = Query(default=1, ge=1, le=100),
             source: Literal['demo', 'fema'] = 'demo'):
    try:
        return find_shelters(Household(accepts_pets=accepts_pets,
            wheelchair_accessible=wheelchair_accessible, occupants=occupants), source=source)
    except ShelterUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get('/shelters/catalog')
def shelter_catalog():
    try:
        data = read_catalogue()
    except ShelterUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    graph = load_graph()
    data['access'] = {s.id: access_report(s, graph) for s in data['shelters']}
    return data


@app.post('/geocode', response_model=Origin)
def geocode(request: GeocodeRequest):
    address = ' '.join(request.address.lower().replace('.', '').split())
    if address not in ('123 oak st', '123 oak street'):
        raise HTTPException(404, 'Unknown demo address. Use 123 Oak St or submit coordinates to /plan.')
    return Origin(lat=39.76, lon=-121.62, label=request.address)


@app.post('/plan', response_model=PlanResponse)
def plan(request: PlanRequest, response: Response):
    # Before anything is fetched: the live engine models one fixed bbox, and a
    # road graph outside it routes perfectly well while reporting no hazards at
    # all -- the fire polygons are simply elsewhere. An empty intersection that
    # reads as safety. Checked first because it is a configuration error, and
    # modelling a fire to then discard the answer helps nobody.
    if request.mode == 'live' and not within(load_graph(), DEMO_BBOX):
        raise HTTPException(503, 'Live routing requires a road graph inside the '
                                 'area the fire model covers; IGNIS_GRAPH_PATH '
                                 'points outside it')
    payload, result = fire_for_time(request.mode, request.t, response)
    # Two separate gates after that, because they fail for different reasons. A
    # stale cache means the refresh loop is behind; stale observations mean the
    # satellites are, and no amount of refetching fixes that. Checking only the
    # first let a valid-but-frozen payload route as though it were current.
    if request.mode == 'live':
        if result.stale:
            raise HTTPException(503, 'Live routing requires a fresh fire fetch')
        if not result.observations_fresh:
            age = result.observation_age_seconds
            raise HTTPException(503, 'Live routing requires fresh fire observations; '
                                     + (f'newest detection is {age // 60} min old'
                                        if age is not None
                                        else 'observation time is unreadable'))
    try:
        return calculate_routes(request, payload)
    except (ShelterUnavailable, EvacuationsUnavailable) as exc:
        raise HTTPException(503, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@app.get('/scenario/{t}', response_model=None)
def scenario(t: ReplayTime, response: Response):
    """Return an existing fire replay frame unchanged (does not include routes)."""
    return fire_for_time('replay', t, response)[0]


@app.post('/chat')
def chat(request: ChatRequest, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    # `plan` itself is handed over, not a copy of its body: the assistant then
    # routes through the same staleness, bbox and evacuation gates the map does.
    return chat_reply(request, plan)


@app.get('/evacuations')
def evacuations(response: Response, mode: Literal['demo', 'replay', 'live'] = 'live',
                lat: float | None = Query(default=None, ge=-90, le=90),
                lon: float | None = Query(default=None, ge=-180, le=180)):
    if (lat is None) != (lon is None):
        raise HTTPException(422, 'Provide both lat and lon, or neither')
    response.headers['Cache-Control'] = 'no-store'
    try:
        data = read_evacuations(mode)
        return origin_orders(data, lon, lat) if lat is not None else data
    except EvacuationsUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get('/demo/palisades')
def palisades_info(response: Response):
    response.headers['Cache-Control'] = 'no-store'
    try:
        return demo_info()
    except (OSError, ValueError) as exc:
        raise HTTPException(503, 'Palisades demo assets unavailable') from exc


@app.post('/demo/palisades/plan', response_model=PalisadesPlanResponse)
def palisades_plan(request: PalisadesDemoRequest, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Fire-Source'] = 'palisades-historical'
    try:
        return plan_demo(request)
    except OSError as exc:
        raise HTTPException(503, 'Palisades demo assets unavailable') from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
