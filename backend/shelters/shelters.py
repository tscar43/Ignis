import json
import os
from pathlib import Path

from ..models import Household, Shelter
from ..routing.roads import DATA_DIR
from .fema import is_fresh, read_catalogue


def find_shelters(household: Household | None = None, source="demo"):
    household = household or Household()
    if source == 'fema':
        shelters = read_catalogue()['shelters']
    elif source == 'demo':
        path = Path(os.environ.get('IGNIS_SHELTERS_PATH', DATA_DIR / 'shelters.json'))
        shelters = [Shelter.model_validate(item) for item in
                    json.loads(path.read_text(encoding='utf-8'))]
    else:
        raise ValueError('Unknown shelter source')
    return [s for s in shelters
            if (s.source == 'demo' or (s.status == 'OPEN' and is_fresh(s.fetched_at)))
            and s.capacity is not None and s.capacity >= household.occupants
            and (s.reported_population is None or s.capacity - s.reported_population >= household.occupants)
            and (not household.accepts_pets or s.accepts_pets is True)
            and (not household.wheelchair_accessible or s.accessible is True)]
