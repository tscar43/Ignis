import test from 'node:test'
import assert from 'node:assert/strict'
import { loadFire, loadPlan, request } from '../src/api.js'

test('fire and plan send matching selection and actual backend household schema', async () => {
  const original = globalThis.fetch
  const calls = []
  globalThis.fetch = async (url, options) => {
    calls.push({ url, ...options })
    return new Response(JSON.stringify({ data_as_of: {} }), {
      headers: { 'X-Fire-Source': 'live', 'X-Fire-Stale': 'true', 'X-Fire-Cache-Age': '350' },
    })
  }
  try {
    const controller = new AbortController()
    const selection = { mode: 'live', t: 'T0' }
    const fire = await loadFire(selection, controller.signal)
    await loadPlan(selection, controller.signal)
    assert.equal(calls[0].url, '/api/fire?mode=live&t=T0')
    const body = JSON.parse(calls[1].body)
    assert.equal(calls[1].url, '/api/plan')
    assert.equal(body.mode, selection.mode)
    assert.equal(body.t, selection.t)
    assert.deepEqual(body.origin, { lat: 39.76, lon: -121.62, label: 'Demo origin' })
    assert.deepEqual(body.household, { occupants: 1, has_vehicle: true, accepts_pets: false, wheelchair_accessible: false })
    assert.equal(calls[1].signal, controller.signal)
    assert.deepEqual(fire.metadata, { source: 'live', stale: 'true', age: '350' })
  } finally { globalThis.fetch = original }
})

test('unavailable plans preserve backend detail and HTTP status without a fallback', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: 'No reachable shelter' }), { status: 422 })
  try {
    await assert.rejects(loadPlan({ mode: 'demo', t: 'T0' }), error => error.status === 422 && error.message === 'No reachable shelter')
  } finally { globalThis.fetch = original }
})

test('invalid JSON and structured validation errors produce usable errors', async () => {
  const original = globalThis.fetch
  try {
    globalThis.fetch = async () => new Response('<html>Wrong proxy</html>')
    await assert.rejects(request('/fire'), /invalid JSON/)
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'origin'], msg: 'Field required' }] }), { status: 422 })
    await assert.rejects(request('/plan'), /body.origin: Field required/)
  } finally { globalThis.fetch = original }
})
