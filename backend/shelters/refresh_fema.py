"""Download the official Butte County catalogue to an atomic local snapshot."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

import httpx

from ..models import Shelter
from .fema import SOURCE_URL, SNAPSHOT_PATH

FIELDS = ('objectid,shelter_id,shelter_name,address_1,city,state,zip,'
          'shelter_status_code,evacuation_capacity,total_population,'
          'wheelchair_accessible,pet_accommodations_code,pet_accommodations_desc,'
          'facility_type,subfacility_code')


def yes_no(value):
    return {'YES': True, 'NO': False}.get(str(value or '').strip().upper())


def nonnegative(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def normalize(feature, fetched_at):
    a, point = feature['attributes'], feature['geometry']
    status = str(a.get('shelter_status_code') or '').strip().upper()
    if status not in {'OPEN', 'CLOSED', 'FULL', 'ALERT', 'STANDBY'}:
        status = 'UNKNOWN'
    return Shelter(id=f"fema_{a['shelter_id']}", name=a['shelter_name'],
        lat=point['y'], lon=point['x'], source='fema', status=status,
        source_url=SOURCE_URL, fetched_at=fetched_at,
        address=', '.join(str(a.get(k) or '').strip() for k in ('address_1', 'city', 'state', 'zip')),
        accessible=yes_no(a.get('wheelchair_accessible')),
        # NSS pet accommodation codes are not a documented yes/no permission.
        accepts_pets=None,
        pet_policy='; '.join(str(a.get(k) or '').strip() for k in
            ('pet_accommodations_code', 'pet_accommodations_desc') if str(a.get(k) or '').strip()) or None,
        capacity=nonnegative(a.get('evacuation_capacity')),
        reported_population=nonnegative(a.get('total_population')))


def refresh(output=SNAPSHOT_PATH, client=None):
    fetched_at = datetime.now(timezone.utc)
    shelters, seen = [], set()
    def download(http):
        offset = 0
        while True:
            response = http.get(SOURCE_URL + '/query', params={
                'f': 'json', 'where': "state='CA' AND county_parish='BUTTE' AND facility_type='SHELTER' AND subfacility_code='GENPOPSHEL'",
                'outFields': FIELDS, 'outSR': 4326, 'returnGeometry': 'true',
                'orderByFields': 'objectid ASC', 'resultOffset': offset, 'resultRecordCount': 1000})
            response.raise_for_status()
            data = response.json()
            if 'error' in data or not isinstance(data.get('features'), list):
                raise ValueError('FEMA returned an invalid query response')
            for feature in data['features']:
                shelter = normalize(feature, fetched_at)
                if shelter.id in seen:
                    raise ValueError('Duplicate FEMA shelter record; refusing partial cache')
                seen.add(shelter.id)
                shelters.append(shelter.model_dump(mode='json'))
            if not data.get('exceededTransferLimit'):
                break
            if not data['features']:
                raise ValueError('FEMA pagination made no progress')
            offset += len(data['features'])
    if client is None:
        with httpx.Client(timeout=30) as http:
            download(http)
    else:
        download(client)
    payload = {'source_url': SOURCE_URL, 'fetched_at': fetched_at.isoformat(),
               'scope': 'Butte County, CA; general-population shelter facilities', 'shelters': shelters}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output)
    return payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=SNAPSHOT_PATH)
    args = parser.parse_args()
    data = refresh(args.output)
    print(f"Saved {len(data['shelters'])} facilities to {args.output}")


if __name__ == '__main__':
    main()
