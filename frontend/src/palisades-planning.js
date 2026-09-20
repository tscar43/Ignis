import { request } from './api.js'
import { palisadesDestinations } from './data/palisades-destinations.js'

export function householdProblem(household) {
  if (typeof household.has_vehicle !== 'boolean' || typeof household.wheelchair_required !== 'boolean'
    || typeof household.pets_required !== 'boolean') return 'Confirm vehicle, accessibility and pet requirements.'
  if (!household.has_vehicle) return 'This demo only supports driving evacuation. Walking, pickup and assisted transport are not modeled; no driving plan was requested.'
  if (!Number.isInteger(household.occupants) || household.occupants < 1) return 'Enter a whole number of occupants greater than zero.'
  return null
}

export function eligibleDestinations(household, catalogue = palisadesDestinations) {
  if (householdProblem(household)) return []
  return catalogue.filter(destination => destination.capacity >= household.occupants
    && (!household.wheelchair_required || destination.wheelchair_accessible === true)
    && (!household.pets_required || destination.accepts_pets === true))
    .sort((a, b) => a.priority - b.priority || a.id.localeCompare(b.id))
}

export async function planForHousehold(household, {
  catalogue = palisadesDestinations, send = request, signal, onAttempt = () => {},
} = {}) {
  const problem = householdProblem(household)
  if (problem) return { status: 'blocked', message: problem, attempts: [] }
  const candidates = eligibleDestinations(household, catalogue)
  if (!candidates.length) return { status: 'no-match', message: 'No fictional destination matches all household requirements. No route was requested and no requirements were relaxed.', attempts: [] }
  const attempts = []
  for (const destination of candidates) {
    signal?.throwIfAborted()
    onAttempt(destination)
    try {
      // The endpoint supplies the historical origin and enforces evacuation
      // restrictions by default. No household or catalogue attributes are sent.
      const { payload } = await send('/demo/palisades/plan', {
        signal,
        body: { destination: { lat: destination.lat, lon: destination.lon, label: destination.label } },
      })
      signal?.throwIfAborted()
      if (payload.routes?.length) return { status: 'success', destination, plan: payload, attempts }
      attempts.push({ id: destination.id, label: destination.label, reason: 'Backend returned no route.' })
    } catch (error) {
      signal?.throwIfAborted()
      if (error.status !== 422) throw error // Outages are not destination rejections.
      attempts.push({ id: destination.id, label: destination.label, reason: error.message })
    }
  }
  return { status: 'unavailable', message: 'No route was available to any matching fictional destination. All household requirements were preserved.', attempts }
}
