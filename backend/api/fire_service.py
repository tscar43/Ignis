"""Live caching and read-only access to the fire team's published fixtures."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import json
import logging
from pathlib import Path
from threading import Lock
from time import monotonic

from backend.fire.contract import validate

DATA_DIR = Path(__file__).resolve().parents[2] / 'demo_data'
logger = logging.getLogger(__name__)


class FireUnavailable(RuntimeError):
    """No successfully validated payload is available."""


def checked(payload):
    problems = validate(payload)
    if problems:
        raise ValueError('Invalid fire payload: ' + '; '.join(problems))
    return payload


def load_asset(path, label):
    """Read and contract-check a bundled fixture, or raise FireUnavailable.

    Every way a fixture can fail is the same kind of failure -- the service
    cannot answer -- and none of them are the caller's fault. Letting OSError
    through produced a 500, and letting the ValueError from `checked` through
    produced a 422, which tells a client its request was malformed when what
    actually happened is that a file on the server is missing or corrupt.
    """
    try:
        return checked(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FireUnavailable(f'{label} is missing or invalid') from exc


def observation_age_seconds(payload, now=None):
    """Seconds since the newest observation in `payload`, or None if unreadable.

    Cache age answers "when did we last fetch", which is not the same question
    as "how old is the data". A loader that keeps returning a valid but frozen
    payload has an age of zero and observations from yesterday.
    """
    stamp = (payload or {}).get('data_as_of', {}).get('firms')
    try:
        observed = datetime.strptime(stamp, '%Y-%m-%dT%H:%M:%SZ').replace(
            tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return max(0, int(((now or datetime.now(timezone.utc)) - observed)
                      .total_seconds()))


def live_loader():
    from backend.fire.spread import risk_payload
    return risk_payload()


def national_loader():
    from backend.fire.national import national_payload
    return national_payload()


def checked_national(payload):
    """The national payload is a list of contract payloads, so validate each.

    The engine already contract-checks every fire before returning it; this is
    the same guard the single-fire path keeps, at the boundary where a bad
    payload would otherwise reach the UI.
    """
    for fire in payload['fires']:
        checked(fire)
    return payload


# How old the newest observation may be before live routing stops trusting it.
# VIIRS overpasses are hours apart, so this is deliberately far looser than the
# cache TTL: it is a bound on the data, not on the fetch.
MAX_OBSERVATION_AGE_S = 6 * 3600


@dataclass(frozen=True)
class FireResult:
    payload: dict
    source: str
    stale: bool = False
    age_seconds: int = 0
    observation_age_seconds: int | None = None

    @property
    def observations_fresh(self) -> bool:
        """Whether the DATA is fresh, as opposed to recently fetched.

        Unknown age counts as not fresh. A payload whose `data_as_of.firms`
        cannot be read is not a payload to route an evacuation on.
        """
        return (self.observation_age_seconds is not None
                and self.observation_age_seconds <= MAX_OBSERVATION_AGE_S)


class LiveFireCache:
    def __init__(self, loader=live_loader, ttl=300, retry_delay=30, clock=monotonic,
                 checker=checked, observation_age=observation_age_seconds):
        self.loader, self.ttl, self.retry_delay, self.clock = loader, ttl, retry_delay, clock
        self.checker = checker
        self.observation_age = observation_age
        self._lock = Lock()
        self._state = None
        self._retry_at = 0.0

    def _result(self, now):
        payload, fetched_at = self._state
        return FireResult(deepcopy(payload), 'live', now >= fetched_at + self.ttl,
                          max(0, int(now - fetched_at)),
                          self.observation_age(payload))

    def get(self):
        now = self.clock()
        if self._state is not None and now < self._state[1] + self.ttl:
            return self._result(now)
        acquired = self._lock.acquire(blocking=False)
        if not acquired:
            if self._state is not None:
                return self._result(now)
            self._lock.acquire()
        try:
            now = self.clock()
            if self._state is not None and now < self._state[1] + self.ttl:
                return self._result(now)
            if now < self._retry_at:
                if self._state is None:
                    raise FireUnavailable('Live fire data is temporarily unavailable')
                return self._result(now)
            try:
                payload = deepcopy(self.checker(self.loader()))
            except Exception:
                self._retry_at = self.clock() + self.retry_delay
                logger.warning('Live fire refresh failed; retaining last good payload', exc_info=True)
                if self._state is None:
                    raise FireUnavailable('Live fire data is temporarily unavailable') from None
                return self._result(self.clock())
            self._state = (payload, self.clock())
            self._retry_at = 0
            return self._result(self.clock())
        finally:
            self._lock.release()


@lru_cache(maxsize=1)
def _demo():
    return load_asset(DATA_DIR / 'risk_demo.json', 'Demo fire fixture')


@lru_cache(maxsize=1)
def _replay():
    try:
        frames = json.loads(
            (DATA_DIR / 'risk_replay.json').read_text(encoding='utf-8'))
        return {frame['replay']['offset_h']: checked(frame) for frame in frames}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise FireUnavailable('Replay fire fixture is missing or invalid') from exc


live_cache = LiveFireCache()

def national_observation_age(payload, now=None):
    """The OLDEST fire's observation age: the sweep is only as fresh as its
    stalest member, and a national view hides that behind a dozen fresh ones."""
    ages = [observation_age_seconds(fire, now) for fire in (payload or {}).get('fires', [])]
    known = [age for age in ages if age is not None]
    if not known or len(known) != len(ages):
        return None
    return max(known)


# A national run models a dozen fires against LANDFIRE, HRRR and GOES, so it
# costs ~40 s cold and the satellite passes behind it are hours apart. A
# 5-minute TTL would just refetch the same answer.
national_cache = LiveFireCache(loader=national_loader, ttl=900,
                               checker=checked_national,
                               observation_age=national_observation_age)


def get_national_result():
    """Every active CONUS fire, modelled. Same cache and staleness rules as live."""
    return national_cache.get()


@lru_cache(maxsize=1)
def get_palisades_replay():
    """The Palisades model-vs-truth fixture, read once and served unchanged.

    Not a contract payload -- it is windows of masks and scores, not risk
    bands -- so `checked` does not apply and there is nothing to deep-copy
    for: the route only reads it.
    """
    try:
        return json.loads(
            (DATA_DIR / 'palisades_replay.json').read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise FireUnavailable(
            'Palisades replay fixture is missing or invalid') from exc


def get_fire_result(mode='demo', t='T0'):
    if mode == 'live':
        if t != 'T0':
            raise ValueError('Live mode does not accept replay offsets')
        return live_cache.get()
    if mode == 'demo':
        if t != 'T0':
            raise ValueError('Demo supports T0 only; select mode=replay for other frames')
        return FireResult(deepcopy(_demo()), 'demo')
    if mode == 'replay':
        offset = {'T0': 0, 'H1': 1, 'H3': 3, 'H6': 6}[t]
        frames = _replay()
        if offset not in frames:
            raise FireUnavailable(f'Replay fixture has no frame for {t}')
        return FireResult(deepcopy(frames[offset]), 'replay')
    raise ValueError('Unknown fire data mode')
