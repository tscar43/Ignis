import { useEffect, useRef, useState } from 'react'
import { request } from '../api'
import { eligibleDestinations, householdProblem, planForHousehold } from '../palisades-planning'
import { palisadesDestinations } from '../data/palisades-destinations'
import PalisadesRouteMap from './PalisadesRouteMap'
import RoutePanel from './RoutePanel'
import HouseholdIntake from './HouseholdIntake'
import { emptyHousehold, missingField } from '../household-intake'

export default function PalisadesEvacuation({ basemap, onBasemap }) {
  const [household, setHousehold] = useState({ ...emptyHousehold })
  const [scenario, setScenario] = useState(null)
  const [scenarioError, setScenarioError] = useState(null)
  const [revision, setRevision] = useState(0)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState('')
  const active = useRef(null)
  useEffect(() => {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), 30000)
    let cancelled = false
    request('/demo/palisades', { signal: controller.signal }).then(({ payload }) => {
      if (!cancelled) setScenario(payload)
    }).catch(failure => {
      if (!cancelled) setScenarioError(controller.signal.aborted ? 'Historical scenario request timed out.' : failure.message)
    }).finally(() => clearTimeout(timer))
    return () => { cancelled = true; clearTimeout(timer); controller.abort() }
  }, [revision])
  useEffect(() => () => active.current?.abort(), [])

  function update(patch) {
    active.current?.abort()
    setHousehold(previous => ({ ...previous, ...patch }))
    setPending(''); setResult(null); setError(null)
  }
  async function submit(event) {
    event.preventDefault()
    if (missingField(household)) return
    active.current?.abort()
    const controller = new AbortController()
    active.current = controller
    setResult(null); setError(null); setPending('Checking household requirements…')
    const timer = setTimeout(() => {
      controller.abort()
      if (active.current === controller) { setError('Planning timed out. Retry to try again.'); setPending('') }
    }, 90000)
    try {
      const next = await planForHousehold(household, {
        signal: controller.signal,
        onAttempt: destination => setPending(`Trying ${destination.label}…`),
      })
      if (!controller.signal.aborted) setResult(next)
    } catch (failure) {
      if (!controller.signal.aborted) setError(`Planning service unavailable: ${failure.message}. No substitute route was selected.`)
    } finally {
      clearTimeout(timer)
      if (active.current === controller && !controller.signal.aborted) setPending('')
    }
  }
  const problem = household.has_vehicle === false
    ? 'This demo only supports driving evacuation. No driving plan will be requested without a vehicle.'
    : missingField(household) ? 'Complete and review all household constraints before planning.' : householdProblem(household)
  const eligible = eligibleDestinations(household)
  const banner = result?.plan?.banner ?? scenario?.banner
  return <section aria-label="Household-aware Palisades demo">
    <p className="route-warning">Historical Palisades scenario · January 8, 2025. Every destination and its accessibility, pet policy and capacity below are fictional demo attributes, not verified shelter information.</p>
    {banner && <div className="request-state"><h2>{banner.title}</h2><p>{banner.message}</p><p>Archive as of {banner.as_of} · <a href={banner.source_url} target="_blank" rel="noreferrer">Archive source</a></p></div>}
    <HouseholdIntake household={household} onChange={update} />
    <form className="household-form" onSubmit={submit}>
      {problem && <p role="status">{problem}</p>}
      {!problem && !eligible.length && <p role="status">No fictional destination matches all household requirements. No requirements will be relaxed.</p>}
      <button type="submit" disabled={!scenario || !!pending || !!problem || !eligible.length}>Confirm constraints and find demo route</button>
    </form>
    <details className="demo-catalogue"><summary>Fictional destination catalogue · fixed priority order</summary>
      {palisadesDestinations.map(destination => <p key={destination.id}>{destination.priority}. {destination.label} · {destination.wheelchair_accessible ? 'Marked wheelchair accessible' : 'Not marked wheelchair accessible'} · {destination.accepts_pets ? 'Accepts pets' : 'No pets'} · Capacity {destination.capacity}</p>)}
    </details>
    {scenarioError && <div role="alert" className="request-state error"><p>{scenarioError}</p><button onClick={() => { setScenarioError(null); setRevision(value => value + 1) }}>Retry scenario</button></div>}
    {!scenario && !scenarioError && <p role="status">Loading historical fire and evacuation areas…</p>}
    {pending && <p role="status">{pending}</p>}
    {error && <p role="alert">{error} Confirm the reviewed constraints again to retry.</p>}
    {result?.message && <p role="status">{result.message}</p>}
    {result?.attempts.map(attempt => <p className="route-warning" key={attempt.id}>{attempt.label}: {attempt.reason} Household requirements were preserved.</p>)}
    {result?.destination && <div className="destination" aria-live="polite"><h2>{result.destination.label}</h2>
      <p>Fictional destination selected by fixed priority after household filtering.</p>
      <p>{result.destination.wheelchair_accessible ? 'Selected destination is marked wheelchair accessible.' : 'Selected destination is not marked wheelchair accessible.'} {result.destination.accepts_pets ? 'Marked as accepting pets.' : 'Marked as not accepting pets.'} Demo capacity: {result.destination.capacity}.</p>
      <p>These attributes come from the frontend demo catalogue. Road-route accessibility has not been assessed. Backend destination attributes are generic placeholders.</p>
    </div>}
    {scenario && <section className="map-section"><div className="map-heading"><h2>Historical fire and driving route</h2><label><input type="checkbox" checked={basemap} onChange={event => onBasemap(event.target.checked)} /> Street basemap</label></div>
      <PalisadesRouteMap key={result?.plan?.generated_at ?? 'unplanned'} scenario={scenario} result={result?.status === 'success' ? result : null} basemap={basemap} />
      <div className="timestamps"><span>Satellite detections as of {scenario.fire.data_as_of.firms}</span><span>Weather as of {scenario.fire.data_as_of.weather}</span><span>Source: Palisades historical scenario, not live</span></div>
      {result?.plan && <RoutePanel plan={result.plan} />}
    </section>}
  </section>
}
