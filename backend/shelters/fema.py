"""Read a locally refreshed FEMA NSS catalogue; HTTP requests never fetch it."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from pydantic import ValidationError

from ..models import Shelter, ShelterEntrance

SOURCE_URL = 'https://gis.fema.gov/arcgis/rest/services/NSS/FEMA_NSS/FeatureServer/5'
SNAPSHOT_PATH = Path(__file__).parent / 'data' / 'fema_butte.json'
MAX_AGE_SECONDS = 30 * 60


class ShelterUnavailable(RuntimeError):
    pass


def is_fresh(fetched_at, now=None):
    now = now or datetime.now(timezone.utc)
    return fetched_at is not None and 0 <= (now - fetched_at).total_seconds() <= MAX_AGE_SECONDS


def read_catalogue():
    path = Path(os.environ.get('IGNIS_FEMA_SHELTERS_PATH', SNAPSHOT_PATH))
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data['source_url'] != SOURCE_URL:
            raise ValueError('Unexpected source')
        shelters = [Shelter.model_validate(item) for item in data['shelters']]
        fetched_at = datetime.fromisoformat(data['fetched_at'])
        if fetched_at.tzinfo is None:
            raise ValueError('Missing timezone')
        if any(s.source != 'fema' or s.fetched_at != fetched_at or s.source_url != SOURCE_URL
               for s in shelters):
            raise ValueError('Inconsistent provenance')
        if len({s.id for s in shelters}) != len(shelters):
            raise ValueError('Duplicate shelter ids')
        entrance_path = os.environ.get('IGNIS_SHELTER_ENTRANCES_PATH')
        if entrance_path:
            entrances = json.loads(Path(entrance_path).read_text(encoding='utf-8'))
            if not isinstance(entrances, dict) or set(entrances) - {s.id for s in shelters}:
                raise ValueError('Entrance overrides must reference known FEMA shelter ids')
            for shelter in shelters:
                if shelter.id in entrances:
                    entrance = ShelterEntrance.model_validate(entrances[shelter.id])
                    if entrance.verified_at > datetime.now(timezone.utc):
                        raise ValueError('Entrance verification is in the future')
                    shelter.entrance = entrance
    except (OSError, ValueError, KeyError, TypeError, ValidationError) as exc:
        raise ShelterUnavailable('FEMA shelter cache unavailable; run python -m backend.shelters.refresh_fema') from exc
    return {'source_url': SOURCE_URL, 'fetched_at': fetched_at,
            'stale': not is_fresh(fetched_at), 'shelters': shelters}


def access_report(shelter, graph):
    # A short straight-line snap is not evidence of a drivable entrance.
    from ..routing.roads import nearest_node

    target = shelter.entrance or shelter
    try:
        node, distance = nearest_node(graph, target.lat, target.lon)
    except ValueError:
        return {'status': 'outside_road_cache', 'road_node': None, 'snap_distance_m': None}
    status = 'entrance_unverified' if shelter.entrance is None else (
        'snap_too_far' if distance > 50 else 'reviewed_entrance')
    return {'status': status, 'road_node': str(node), 'snap_distance_m': round(distance, 1)}
