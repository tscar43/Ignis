"""Live caching and read-only access to the fire team's published fixtures."""
from copy import deepcopy
from dataclasses import dataclass
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


@dataclass(frozen=True)
class FireResult:
    payload: dict
    source: str
    stale: bool = False
    age_seconds: int = 0


class LiveFireCache:
    def __init__(self, loader=live_loader, ttl=300, retry_delay=30, clock=monotonic,
                 checker=checked):
        self.loader, self.ttl, self.retry_delay, self.clock = loader, ttl, retry_delay, clock
        self.checker = checker
        self._lock = Lock()
        self._state = None
        self._retry_at = 0.0

    def _result(self, now):
        payload, fetched_at = self._state
        return FireResult(deepcopy(payload), 'live', now >= fetched_at + self.ttl,
                          max(0, int(now - fetched_at)))

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
    return checked(json.loads((DATA_DIR / 'risk_demo.json').read_text(encoding='utf-8')))


@lru_cache(maxsize=1)
def _replay():
    frames = json.loads((DATA_DIR / 'risk_replay.json').read_text(encoding='utf-8'))
    return {frame['replay']['offset_h']: checked(frame) for frame in frames}


live_cache = LiveFireCache()

# A national run models a dozen fires against LANDFIRE, HRRR and GOES, so it
# costs ~40 s cold and the satellite passes behind it are hours apart. A
# 5-minute TTL would just refetch the same answer.
national_cache = LiveFireCache(loader=national_loader, ttl=900,
                               checker=checked_national)


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
    return json.loads((DATA_DIR / 'palisades_replay.json').read_text(encoding='utf-8'))


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
        return FireResult(deepcopy(_replay()[offset]), 'replay')
    raise ValueError('Unknown fire data mode')
