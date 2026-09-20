const baseUrl = (import.meta.env?.VITE_API_BASE_URL || '/api').replace(/\/$/, '')

export async function request(path, { signal, body } = {}) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: body ? 'POST' : 'GET',
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal,
    cache: 'no-store',
  })
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const detail = payload?.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail)
      ? detail.map(item => `${item.loc?.join('.')}: ${item.msg}`).join('; ')
      : `Request failed (${response.status}).`
    const error = new Error(message)
    error.status = response.status
    throw error
  }
  if (!payload) throw new Error('The backend returned an empty or invalid JSON response.')
  return {
    payload,
    metadata: {
      source: response.headers.get('X-Fire-Source') || 'unknown',
      stale: response.headers.get('X-Fire-Stale'),
      age: response.headers.get('X-Fire-Cache-Age'),
    },
  }
}

export function loadFire(selection, signal) {
  return request(`/fire?${new URLSearchParams(selection)}`, { signal })
}

export function loadPlan(selection, signal) {
  return request('/plan', {
    signal,
    body: {
      ...selection,
      origin: { lat: 39.76, lon: -121.62, label: 'Demo origin' },
      household: { occupants: 1, has_vehicle: true, accepts_pets: false, wheelchair_accessible: false },
    },
  })
}
