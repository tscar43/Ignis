"""Plain tool function for agent consumption."""
from .api.fire_service import get_fire_result


def get_fire_data(t='T0', mode='demo'):
    return get_fire_result(mode, t).payload
