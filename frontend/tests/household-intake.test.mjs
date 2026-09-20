import test from 'node:test'
import assert from 'node:assert/strict'
import { emptyHousehold, extractHousehold, followUp, missingField } from '../src/household-intake.js'
import { planForHousehold } from '../src/palisades-planning.js'

const complete = { wheelchair_required: true, pets_required: true, occupants: 3, has_vehicle: true }

test('example extracts wheelchair, pet and vehicle but never guesses occupants', () => {
  const result = extractHousehold('My mom uses a wheelchair, we have a dog, and one car.')
  assert.deepEqual(result.household, { ...complete, occupants: '' })
  assert.equal(result.reply, 'How many people are evacuating?')
})
test('short numeric follow-up completes the household', () => {
  const initial = extractHousehold('My mom uses a wheelchair, we have a dog, and one car.').household
  assert.deepEqual(extractHousehold('Three', initial).household, complete)
  assert.equal(missingField(complete), null)
})
test('explicit totals support natural-language forms', () => {
  for (const phrase of ['3 people', 'We are three', 'There are 3 of us', 'family of three', 'three of us']) {
    assert.equal(extractHousehold(phrase).household.occupants, 3, phrase)
  }
})
test('relatives, cars and pets do not establish occupant count', () => {
  for (const phrase of ['my mom and I', 'two dogs and one car', 'a family with a baby']) {
    assert.equal(extractHousehold(phrase).household.occupants, '', phrase)
  }
})
test('explicit negations are extracted as false', () => {
  assert.deepEqual(extractHousehold("Three people, no wheelchair required, we don't have pets, no car").household, {
    wheelchair_required: false, pets_required: false, occupants: 3, has_vehicle: false,
  })
})
test('unstated preferences stay unknown rather than becoming false', () => {
  assert.deepEqual(extractHousehold('3 people').household, { ...emptyHousehold, occupants: 3 })
})
test('contradictions and uncertainty require review', () => {
  assert.equal(extractHousehold('We have a car but no vehicle', complete).household.has_vehicle, null)
  assert.equal(extractHousehold('We might have a car', complete).household.has_vehicle, null)
  assert.equal(extractHousehold('2 adults and 3 children', complete).household.occupants, '')
})
test('mobility language does not invent a road or destination accessibility capability', () => {
  const result = extractHousehold('My mom uses a walker')
  assert.equal(result.household.wheelchair_required, null)
  assert.match(result.notes.join(' '), /Please confirm/)
})
test('manual corrections persist across unrelated later messages', () => {
  const corrected = { ...complete, pets_required: false }
  assert.deepEqual(extractHousehold('4 people', corrected).household, { ...corrected, occupants: 4 })
})
test('yes or no answers apply only to the pending boolean question', () => {
  const current = { ...emptyHousehold, occupants: 3 }
  assert.match(followUp(current), /wheelchair/)
  assert.equal(extractHousehold('No', current).household.wheelchair_required, false)
  assert.equal(extractHousehold('Yes').household.occupants, '')
})
test('unrecognized descriptions preserve fields and request missing count', () => {
  const result = extractHousehold('Please help us get ready')
  assert.deepEqual(result.patch, {})
  assert.equal(result.reply, 'How many people are evacuating?')
})
test('incomplete and no-vehicle intake cannot invoke the planner endpoint', async () => {
  const send = () => { throw new Error('Must not call endpoint') }
  const incomplete = extractHousehold('My mom uses a wheelchair, we have a dog, and one car.').household
  assert.equal((await planForHousehold(incomplete, { send })).status, 'blocked')
  const noVehicle = extractHousehold('No car', complete).household
  assert.equal((await planForHousehold(noVehicle, { send })).status, 'blocked')
})
test('complete corrected intake uses the unchanged deterministic selection flow', async () => {
  const extracted = extractHousehold('3 people, a wheelchair, a dog and a car').household
  const calls = []
  const result = await planForHousehold(extracted, { send: async (path, options) => {
    calls.push({ path, body: options.body })
    return { payload: { routes: [{ type: 'recommended' }] } }
  } })
  assert.equal(result.destination.id, 'demo-d')
  assert.equal(calls[0].path, '/demo/palisades/plan')
  assert.deepEqual(Object.keys(calls[0].body), ['destination'])
})
