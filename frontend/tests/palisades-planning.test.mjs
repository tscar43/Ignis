import test from 'node:test'
import assert from 'node:assert/strict'
import { eligibleDestinations, planForHousehold } from '../src/palisades-planning.js'
import { palisadesDestinations } from '../src/data/palisades-destinations.js'

const household = { wheelchair_required: false, pets_required: false, occupants: 1, has_vehicle: true }
const ids = changes => eligibleDestinations({ ...household, ...changes }).map(item => item.id)
test('wheelchair filters destinations', () => assert.deepEqual(ids({ wheelchair_required: true }), ['demo-b', 'demo-d']))
test('pets filter destinations', () => assert.deepEqual(ids({ pets_required: true }), ['demo-c', 'demo-d']))
test('wheelchair and pets must both match', () => assert.deepEqual(ids({ wheelchair_required: true, pets_required: true }), ['demo-d']))
test('capacity includes exact fit and excludes undersized destinations', () => {
  assert.deepEqual(ids({ occupants: 8 }), ['demo-c', 'demo-d'])
  assert.deepEqual(ids({ occupants: 9 }), ['demo-d'])
  assert.deepEqual(ids({ occupants: 12 }), ['demo-d'])
})
test('priority is deterministic regardless of catalogue order', () => {
  assert.deepEqual(eligibleDestinations(household, [...palisadesDestinations].reverse()).map(item => item.id), ids({}))
})
const neverSend = () => { throw new Error('Endpoint must not be called') }
test('no matching destination makes no request', async () => {
  assert.equal((await planForHousehold({ ...household, occupants: 13 }, { send: neverSend })).status, 'no-match')
})
test('no vehicle stops before planning', async () => {
  const result = await planForHousehold({ ...household, has_vehicle: false }, { send: neverSend })
  assert.equal(result.status, 'blocked')
  assert.match(result.message, /only supports driving/)
})
test('invalid occupants cannot silently default to one', async () => {
  for (const occupants of ['', 0, -1, 1.5, NaN]) assert.equal((await planForHousehold({ ...household, occupants }, { send: neverSend })).status, 'blocked')
})
test('first rejected eligible candidate advances without relaxing constraints; exact endpoint body', async () => {
  const calls = []
  const result = await planForHousehold({ ...household, wheelchair_required: true }, {
    send: async (path, options) => {
      calls.push({ path, body: options.body })
      if (calls.length === 1) throw Object.assign(new Error('Destination is blocked'), { status: 422 })
      return { payload: { routes: [{ type: 'recommended' }] } }
    },
  })
  assert.equal(result.status, 'success')
  assert.equal(result.destination.id, 'demo-d')
  assert.equal(result.attempts[0].id, 'demo-b')
  assert.deepEqual(calls, ['demo-b', 'demo-d'].map(id => {
    const { lat, lon, label } = palisadesDestinations.find(item => item.id === id)
    return { path: '/demo/palisades/plan', body: { destination: { lat, lon, label } } }
  }))
})
test('all eligible routes rejected yields unavailable; no ineligible fallback', async () => {
  let count = 0
  const result = await planForHousehold({ ...household, wheelchair_required: true, pets_required: true }, {
    send: async () => { count++; throw Object.assign(new Error('No path'), { status: 422 }) },
  })
  assert.equal(result.status, 'unavailable')
  assert.equal(count, 1)
})
test('outages do not trigger destination fallback', async () => {
  let count = 0
  await assert.rejects(planForHousehold(household, { send: async () => { count++; throw Object.assign(new Error('Server unavailable'), { status: 503 }) } }), /Server unavailable/)
  assert.equal(count, 1)
})
test('aborted planning does not try further candidates', async () => {
  const controller = new AbortController()
  let count = 0
  await assert.rejects(planForHousehold(household, { signal: controller.signal, send: async () => {
    count++; controller.abort(); throw Object.assign(new Error('Rejected'), { status: 422 })
  } }), { name: 'AbortError' })
  assert.equal(count, 1)
})
