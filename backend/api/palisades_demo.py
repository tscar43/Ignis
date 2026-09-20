"""Offline historical Palisades comparison; never used by the live endpoint."""
from copy import deepcopy
from functools import lru_cache
import json
from pathlib import Path
from typing import Literal

from pydantic import Field
from shapely.geometry import box, mapping

from .evacuations import ZoneGeometry
from .fire_service import checked
from ..models import Model, Origin, PlanRequest, PlanResponse, Shelter
from ..routing.roads import read_graph
from ..routing.routes import calculate_routes

ROUTING = Path(__file__).resolve().parents[1] / 'routing'
SCENARIO = 'palisades-2025-01-08'
ORIGIN = {'lat': 34.0560908, 'lon': -118.4805176, 'label': 'Palisades-area demo start'}
DESTINATION = {'lat': 34.0852906, 'lon': -118.4725349,
               'label': 'Demo comparison destination (not a shelter)'}


class PalisadesDemoRequest(Model):
    origin: Origin = Field(default_factory=lambda: Origin(**ORIGIN))
    destination: Origin = Field(default_factory=lambda: Origin(**DESTINATION))
    apply_evacuation_orders: bool = True


class DemoBanner(Model):
    visible: bool = True
    severity: Literal['warning'] = 'warning'
    title: str
    message: str
    source_url: str
    as_of: str


class PalisadesPlanResponse(PlanResponse):
    scenario: Literal['palisades-2025-01-08'] = SCENARIO
    historical: bool = True
    apply_evacuation_orders: bool
    comparison_only: bool
    banner: DemoBanner


@lru_cache(maxsize=1)
def assets():
    raw = json.loads((ROUTING / 'demo/palisades_evacuation_raw.geojson').read_text(encoding='utf-8'))
    metadata = raw['metadata']
    features = []
    for feature in raw['features']:
        geometry = ZoneGeometry.model_validate(feature['geometry']).model_dump()
        props = feature['properties']
        features.append({'type': 'Feature', 'geometry': geometry, 'properties': {
            'id': str(props['OBJECTID']),
            'zone': props['ZONE_NAME'] or f"Archived area {props['OBJECTID']}",
            'level': {'Evacuation Order': 'order', 'Evacuation Warning': 'warning'}[props['STATUS']],
            'authority': metadata['authority'], 'source_url': metadata['source_url'],
            'archived_at': metadata['archived_at'], 'instructions': props['NOTES'],
        }})
    snapshot = {'type': 'FeatureCollection', 'mode': 'demo',
                'source_url': metadata['source_url'], 'authority': metadata['authority'],
                'archived_at': metadata['archived_at'],
                'coverage': mapping(box(*metadata['query_bbox'])), 'features': features}
    fire = checked(json.loads((ROUTING / 'demo/palisades_fire.json').read_text(encoding='utf-8')))
    return snapshot, fire


def banner(enabled):
    snapshot, _ = assets()
    return DemoBanner(
        title=('Historical evacuation restrictions enforced' if enabled else
               'Comparison only: evacuation restrictions ignored'),
        message=('Palisades Fire, January 8, 2025 at 3:00 a.m. Pacific. '
                 'Archived order and warning areas, not current evacuation advice. '
                 'Current-fire and 1-hour model exclusions remain enabled in both views. '
                 'The destination is a demonstration point, not a verified shelter.'),
        source_url=snapshot['source_url'], as_of=snapshot['archived_at'])


def demo_info():
    snapshot, fire = assets()
    return {'scenario': SCENARIO, 'historical': True, 'banner': banner(True),
            'defaults': PalisadesDemoRequest(),
            'evacuations': deepcopy(snapshot), 'fire': deepcopy(fire)}


def plan_demo(request):
    snapshot, fire = assets()
    destination = Shelter(**request.destination.model_dump(), id='palisades-demo-destination',
                          name='Demo comparison destination (not a shelter)', capacity=100)
    plan = calculate_routes(PlanRequest(origin=request.origin), fire,
        graph=read_graph(ROUTING / 'osm/palisades.graphml'),
        evacuation_data={'status': 'historical', 'reason': 'Fixed archive, not current orders',
                         'snapshot': snapshot}, shelters=[destination],
        apply_orders=request.apply_evacuation_orders)
    plan.warnings.insert(0, 'Historical demonstration with current cached roads; not a reconstruction of 2025 traffic, closures or shelter availability.')
    return PalisadesPlanResponse(**plan.model_dump(),
        apply_evacuation_orders=request.apply_evacuation_orders,
        comparison_only=not request.apply_evacuation_orders,
        banner=banner(request.apply_evacuation_orders))
