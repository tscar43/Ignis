"""Source-attributed local evacuation input; no public write endpoint or live fetch."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Literal

from math import isfinite
from pydantic import AwareDatetime, Field, HttpUrl, model_validator
from shapely.errors import GEOSException
from shapely import get_coordinates
from shapely.geometry import shape, Point

from backend.models import Model

MAX_AGE_SECONDS = 1800


class EvacuationsUnavailable(RuntimeError):
    pass


class ZoneGeometry(Model):
    type: Literal['Polygon', 'MultiPolygon']
    coordinates: list

    @model_validator(mode='after')
    def valid_geometry(self):
        try:
            polygon = shape(self.model_dump())
            coords = get_coordinates(polygon)
            valid = (not polygon.is_empty and polygon.is_valid and not polygon.has_z
                     and all(isfinite(x) and isfinite(y) and abs(x) <= 180 and abs(y) <= 90
                             for x, y in coords))
        except (TypeError, ValueError, IndexError, GEOSException) as exc:
            raise ValueError('Invalid EPSG:4326 polygon') from exc
        if not valid:
            raise ValueError('Expected valid, nonempty 2D EPSG:4326 polygon')
        return self


class OrderProperties(Model):
    id: str = Field(min_length=1)
    zone: str = Field(min_length=1)
    level: Literal['order', 'warning', 'lifted']
    authority: str = Field(min_length=1)
    source_url: HttpUrl
    updated_at: AwareDatetime
    valid_until: AwareDatetime
    instructions: str = Field(min_length=1)

    @model_validator(mode='after')
    def valid_dates(self):
        if self.valid_until <= self.updated_at:
            raise ValueError('valid_until must follow updated_at')
        return self


class OrderFeature(Model):
    type: Literal['Feature'] = 'Feature'
    geometry: ZoneGeometry
    properties: OrderProperties


class OrderSnapshot(Model):
    type: Literal['FeatureCollection'] = 'FeatureCollection'
    mode: Literal['demo', 'replay', 'live']
    fetched_at: AwareDatetime
    source_url: HttpUrl
    authority: str = Field(min_length=1)
    coverage: ZoneGeometry
    features: list[OrderFeature]

    @model_validator(mode='after')
    def consistent_records(self):
        if len({f.properties.id for f in self.features}) != len(self.features):
            raise ValueError('Duplicate evacuation record ids')
        coverage = shape(self.coverage.model_dump())
        for feature in self.features:
            if feature.properties.updated_at > self.fetched_at:
                raise ValueError('Record update is later than snapshot fetch')
            if not coverage.covers(shape(feature.geometry.model_dump())):
                raise ValueError('Evacuation zone is outside declared coverage')
        return self


def read_evacuations(mode='live', now=None):
    now = now or datetime.now(timezone.utc)
    path = os.environ.get('IGNIS_EVACUATIONS_PATH')
    if not path:
        return {'status': 'unknown', 'reason': 'No evacuation snapshot configured',
                'snapshot': None}
    try:
        snapshot = OrderSnapshot.model_validate(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError) as exc:
        raise EvacuationsUnavailable('Evacuation snapshot missing or invalid') from exc
    if snapshot.mode != mode:
        return {'status': 'unknown', 'reason': 'Evacuation snapshot does not match the fire mode',
                'snapshot': None}
    age = (now - snapshot.fetched_at).total_seconds()
    stale = not 0 <= age <= MAX_AGE_SECONDS or any(
        f.properties.valid_until <= now for f in snapshot.features)
    return {'status': 'stale' if stale else 'fresh',
            'reason': 'Evacuation snapshot expired or future-dated' if stale else '',
            'snapshot': snapshot.model_dump(mode='json')}


def origin_orders(data, lon, lat):
    snapshot = data['snapshot']
    point = Point(lon, lat)
    if snapshot is None:
        return {**data, 'origin_covered': False, 'origin_orders': []}
    return {**data, 'origin_covered': shape(snapshot['coverage']).covers(point),
            'origin_orders': [f['properties'] for f in snapshot['features']
                              if shape(f['geometry']).covers(point)]}
