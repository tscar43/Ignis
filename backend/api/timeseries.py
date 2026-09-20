"""Fire history in TigerData (TimescaleDB).

Two hypertables and one continuous aggregate. The satellite detections are
the genuine time series here -- 350 per Camp Fire frame, each with its own
acquisition time and radiative power -- and the modelled band areas are the
derived series drawn against them.

Everything here is optional. With no `TIGERDATA_URL` configured the endpoints
return 503 and the rest of the application is unaffected; nothing in the
routing or fire path reads from the database.

ponytail: no connection pool, no migrations, no ORM. One short-lived
connection per request against a demo-sized table. Add a pool if this ever
serves more than one browser.
"""

import psycopg

from ..fire.firms import env_value

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS timescaledb;

CREATE TABLE IF NOT EXISTS fire_detections (
    observed_at timestamptz NOT NULL,
    fire_id     text        NOT NULL,
    lat         double precision NOT NULL,
    lon         double precision NOT NULL,
    frp         double precision,
    confidence  text,
    sensor      text
);
SELECT create_hypertable('fire_detections', 'observed_at',
                         if_not_exists => TRUE);

CREATE TABLE IF NOT EXISTS risk_area (
    observed_at     timestamptz NOT NULL,
    fire_id         text        NOT NULL,
    band            text        NOT NULL,
    area_km2        double precision NOT NULL,
    wind_speed_kmh  double precision,
    wind_toward_deg double precision
);
SELECT create_hypertable('risk_area', 'observed_at', if_not_exists => TRUE);

CREATE UNIQUE INDEX IF NOT EXISTS risk_area_frame
    ON risk_area (fire_id, band, observed_at);

-- One satellite detection is one row. Consecutive replay frames re-seed from
-- the same VIIRS pass, so without this the 21:30 pass is counted twice and
-- the intensity aggregate reports a burst that never happened.
CREATE UNIQUE INDEX IF NOT EXISTS fire_detections_unique
    ON fire_detections (fire_id, observed_at, lat, lon);
"""

# Separate because a continuous aggregate cannot be created inside a
# transaction block with the tables it reads.
AGGREGATE = """
CREATE MATERIALIZED VIEW IF NOT EXISTS detection_intensity
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '30 minutes', observed_at) AS bucket,
       fire_id,
       count(*)   AS detections,
       sum(frp)   AS total_frp,
       max(frp)   AS peak_frp
FROM fire_detections
GROUP BY bucket, fire_id
WITH NO DATA;
"""


class DatabaseUnavailable(Exception):
    """No TigerData connection is configured, or it cannot be reached."""


def connect():
    url = env_value('TIGERDATA_URL')
    if not url or url == 'your_connection_string_here':
        raise DatabaseUnavailable(
            'Fire history is unavailable: no TIGERDATA_URL is configured. '
            'Paste the connection string from the TigerData console into .env.')
    try:
        return psycopg.connect(url, connect_timeout=8)
    except psycopg.Error as exc:
        raise DatabaseUnavailable(f'Cannot reach TigerData: {exc}') from exc


def ensure_schema():
    """Idempotent. Safe to run on every startup or by hand."""
    with connect() as db:
        db.autocommit = True
        with db.cursor() as cur:
            cur.execute(SCHEMA)
            cur.execute(AGGREGATE)
            # Refresh the whole range: the demo backfills history rather than
            # streaming it, so the policy alone would never fill the view.
            cur.execute("CALL refresh_continuous_aggregate("
                        "'detection_intensity', NULL, NULL);")
    return 'schema ready'


def ingest(payload, fire_id):
    """Write one risk payload -- detections and band areas -- as history.

    Returns (detections, bands) offered. Re-ingesting is safe: band areas are
    replaced for that frame and duplicate detections are dropped, so seeding
    twice leaves the same history rather than twice as much of it.
    """
    # Two different clocks, and mixing them up collapses the series. The
    # detections are stamped when the satellite saw them; the modelled bands
    # are valid at the frame's own time, which for a replay is the offset
    # hour. Two frames can share a satellite pass while modelling +3h and +6h.
    observed = payload['data_as_of']['firms']
    valid_at = payload.get('replay', {}).get('at') or observed
    summary = payload['summary']
    points = [
        (feature['properties'].get('acq_time') or observed, fire_id,
         feature['geometry']['coordinates'][1], feature['geometry']['coordinates'][0],
         feature['properties'].get('frp'), feature['properties'].get('confidence'),
         feature['properties'].get('sensor'))
        for feature in payload['fire_points']['features']
    ]
    areas = [(valid_at, fire_id, band, km2,
              summary.get('wind_speed_kmh'), summary.get('wind_toward_deg'))
             for band, km2 in summary['area_km2'].items()]

    with connect() as db:
        with db.cursor() as cur:
            cur.executemany(
                'INSERT INTO fire_detections (observed_at, fire_id, lat, lon, '
                'frp, confidence, sensor) VALUES (%s, %s, %s, %s, %s, %s, %s) '
                'ON CONFLICT (fire_id, observed_at, lat, lon) DO NOTHING',
                points)
            cur.executemany(
                'INSERT INTO risk_area (observed_at, fire_id, band, area_km2, '
                'wind_speed_kmh, wind_toward_deg) VALUES (%s, %s, %s, %s, %s, %s) '
                'ON CONFLICT (fire_id, band, observed_at) DO UPDATE '
                'SET area_km2 = EXCLUDED.area_km2',
                areas)
        db.commit()
    return len(points), len(areas)


def clear(fire_id):
    with connect() as db:
        with db.cursor() as cur:
            cur.execute('DELETE FROM fire_detections WHERE fire_id = %s', (fire_id,))
            cur.execute('DELETE FROM risk_area WHERE fire_id = %s', (fire_id,))
        db.commit()


def growth(fire_id):
    """The growth series for one fire: burn intensity and modelled area.

    Intensity comes from the continuous aggregate rather than the raw table --
    that is the point of keeping one -- and the band areas are read directly,
    since there are four rows per frame and nothing to roll up.
    """
    with connect() as db:
        with db.cursor() as cur:
            cur.execute(
                'SELECT bucket, detections, total_frp, peak_frp '
                'FROM detection_intensity WHERE fire_id = %s ORDER BY bucket',
                (fire_id,))
            intensity = [
                {'bucket': b.isoformat(), 'detections': d,
                 'total_frp': round(t, 2) if t else 0,
                 'peak_frp': round(p, 2) if p else 0}
                for b, d, t, p in cur.fetchall()]

            cur.execute(
                'SELECT observed_at, band, area_km2, wind_speed_kmh '
                'FROM risk_area WHERE fire_id = %s ORDER BY observed_at, band',
                (fire_id,))
            area = [
                {'observed_at': o.isoformat(), 'band': b,
                 'area_km2': round(a, 1), 'wind_speed_kmh': w}
                for o, b, a, w in cur.fetchall()]

    if not intensity and not area:
        raise DatabaseUnavailable(
            f'No history stored for {fire_id!r}. Run '
            'python -m backend.api.timeseries seed')
    return {'fire_id': fire_id, 'intensity': intensity, 'area': area}


def fires():
    with connect() as db:
        with db.cursor() as cur:
            cur.execute('SELECT fire_id, count(*), min(observed_at), max(observed_at) '
                        'FROM fire_detections GROUP BY fire_id ORDER BY fire_id')
            return [{'fire_id': f, 'detections': n,
                     'first': a.isoformat(), 'last': b.isoformat()}
                    for f, n, a, b in cur.fetchall()]


def seed():
    """Load the bundled Camp Fire replay. Idempotent."""
    import json
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    frames = json.loads((root / 'demo_data' / 'risk_replay.json')
                        .read_text(encoding='utf-8'))
    # Clear before the schema runs: the dedupe index cannot be created over
    # rows that already violate it, which is exactly what an older seed leaves.
    try:
        clear('camp-2018')
    except psycopg.errors.UndefinedTable:
        pass  # First run; nothing to clear.
    print(ensure_schema())
    total = 0
    for frame in frames:
        points, bands = ingest(frame, 'camp-2018')
        total += points
        print(f"  {frame['data_as_of']['firms']}  {points} detections, {bands} bands")
    with connect() as db:
        db.autocommit = True
        with db.cursor() as cur:
            cur.execute("CALL refresh_continuous_aggregate("
                        "'detection_intensity', NULL, NULL);")
    print(f'{total} detections across {len(frames)} frames')
    return total


if __name__ == '__main__':
    import sys

    command = sys.argv[1] if len(sys.argv) > 1 else 'seed'
    if command == 'seed':
        seed()
    elif command == 'schema':
        print(ensure_schema())
    elif command == 'show':
        print(json.dumps(growth(sys.argv[2] if len(sys.argv) > 2 else 'camp-2018'),
                         indent=2)[:2000])
    else:
        print(__doc__)
