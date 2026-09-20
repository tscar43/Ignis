import { useEffect, useState } from 'react'
import Map from './components/Map'
import NationalView from './components/NationalView'
import PalisadesView from './components/PalisadesView'
import PalisadesEvacuation from './components/PalisadesEvacuation'
import LayerControls from './components/LayerControls'
import RoutePanel from './components/RoutePanel'
import useEvacuationData from './useEvacuationData'
import './App.css'

function timestamp(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Unavailable' : new Intl.DateTimeFormat('en-US', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Los_Angeles',
  }).format(date) + ' PT'
}

function SourceStatus({ metadata, label }) {
  if (!metadata) return null
  return <span>{label}: {metadata.source} · {metadata.stale === 'true'
    ? 'Stale cached data — refresh failed or is in progress'
    : metadata.stale === 'false' ? 'Cache marked fresh' : 'Cache freshness not available'}
    {metadata.age !== null && ` · Cache age: ${metadata.age}s (not observation age)`}</span>
}

// Preserve main's API override for the additive views; otherwise use the
// Milestone 4 proxy/base URL configuration.
const API = (import.meta.env.VITE_API ?? import.meta.env.VITE_API_BASE_URL ?? '/api').replace(/\/$/, '')
async function json(path, signal) {
  const response = await fetch(API + path, { signal })
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : `Request failed (${response.status})`)
  return body
}
const linked = new URLSearchParams(window.location.search).get('fire')

function App() {
  const [view, setView] = useState(linked ? 'national' : import.meta.env.VITE_OFFLINE === 'true' ? 'scenario' : 'palisades-demo')
  const [mode, setMode] = useState(import.meta.env.VITE_OFFLINE === 'true' ? 'offline' : 'demo')
  const [revision, setRevision] = useState(0)
  const [layers, setLayers] = useState({ active: true, spread: true, recommended: true, alternative: true, fuel: false, wind: true })
  const [basemap, setBasemap] = useState(import.meta.env.VITE_OFFLINE !== 'true')
  const data = useEvacuationData(mode, revision, view === 'scenario')
  const { fire, plan, loading } = data
  const refresh = () => setRevision(value => value + 1)
  const retry = <button type="button" onClick={refresh}>Retry requests</button>

  const [national, setNational] = useState(null)
  const [nationalError, setNationalError] = useState(null)
  const [palisades, setPalisades] = useState(null)
  const [palisadesError, setPalisadesError] = useState(null)
  const [selected, setSelected] = useState(linked)

  // Fetch these views only when opened. Keep scenario requests in the existing
  // hook so unavailable plans do not hide fire data or activate fake routes.
  useEffect(() => {
    if (view !== 'national' || national || nationalError) return
    const controller = new AbortController()
    json('/fires', controller.signal).then(setNational).catch(error => {
      if (!controller.signal.aborted) setNationalError(error.message)
    })
    return () => controller.abort()
  }, [view, national, nationalError])
  useEffect(() => {
    if (view !== 'palisades' || palisades || palisadesError) return
    const controller = new AbortController()
    json('/palisades', controller.signal).then(setPalisades).catch(error => {
      if (!controller.signal.aborted) setPalisadesError(error.message)
    })
    return () => controller.abort()
  }, [view, palisades, palisadesError])
  const chosen = national?.fires.find(item => item.incident.id === selected)
  useEffect(() => {
    const url = new URL(window.location.href)
    if (view === 'national' && selected) url.searchParams.set('fire', selected)
    else url.searchParams.delete('fire')
    window.history.replaceState(null, '', url)
    const name = view === 'national' ? chosen?.incident.name ?? chosen?.incident.id : null
    document.title = name ? `${name} · Ignis` : 'Ignis · Evacuation intelligence'
  }, [view, selected, chosen])
  const tab = key => <button type="button" className={view === key ? 'active' : undefined} aria-pressed={view === key} onClick={() => setView(key)}>{{ 'palisades-demo': 'Palisades · household demo', scenario: 'Evacuation scenario', national: 'Live · every US fire', palisades: 'Palisades · model vs. truth' }[key]}</button>

  return <>
    <header className="app-header">
      <a className="brand" href="#main"><span aria-hidden="true">◈</span> ignis<span className="brand-caption">EVACUATION INTELLIGENCE</span></a>
      <span className="demo-badge">{view === 'national' ? 'Live national feed' : view === 'palisades-demo' ? 'Historical household demo' : view === 'palisades' ? 'Historical validation' : mode === 'live' ? 'Live fire' : 'Demo workspace'}</span>
    </header>
    <main id="main">
      <div className="page-heading"><div><p className="eyebrow">{{ 'palisades-demo': 'PALISADES · HISTORICAL DEMONSTRATION', scenario: 'BUTTE COUNTY, CALIFORNIA', national: 'CONTIGUOUS UNITED STATES · LIVE', palisades: 'LOS ANGELES COUNTY · 7–9 JANUARY 2025' }[view]}</p><h1>A clearer view of what’s ahead.</h1><p>{{ 'palisades-demo': 'Match household requirements to fictional demo destinations, then request a driving route.', scenario: 'Explore projected fire risk and compare evacuation options.', national: 'Every fire burning right now, run through the same spread model.', palisades: 'The same model, seeded from satellite truth and scored against what actually burned.' }[view]}</p></div><span className="scenario-label">{{ 'palisades-demo': <>Historical scenario<br /><strong>Fictional destinations</strong></>, scenario: <>Fictional scenario<br /><strong>Concow / Paradise</strong></>, national: <>Live satellite data<br /><strong>NASA FIRMS · GOES · NIFC · HRRR</strong></>, palisades: <>Historical validation<br /><strong>Palisades Fire · VIIRS ground truth</strong></> }[view]}</span></div>
      <div className="view-tabs" role="group" aria-label="Choose a view">{tab('palisades-demo')}{tab('scenario')}{tab('national')}{tab('palisades')}</div>
      {view === 'palisades-demo' ? <PalisadesEvacuation basemap={basemap} onBasemap={setBasemap} /> : view === 'palisades' ? <>
        {palisadesError && <p className="route-warning" role="alert">Palisades replay unavailable — {palisadesError}. No fictional data is shown in its place. <button type="button" onClick={() => setPalisadesError(null)}>Retry Palisades</button></p>}
        {!palisades ? !palisadesError && <p role="status">Loading the Palisades replay…</p> : <PalisadesView data={palisades} basemap={basemap} onBasemap={setBasemap} />}
      </> : view === 'national' ? <>
        {nationalError && <p className="route-warning" role="alert">Live national feed unavailable — {nationalError}. No fictional data is shown in its place. <button type="button" onClick={() => setNationalError(null)}>Retry national feed</button></p>}
        {!national ? !nationalError && <p role="status">Modeling every active fire in the country… the first live load can take up to a minute.</p> : <NationalView data={national} basemap={basemap} onBasemap={setBasemap} selected={selected} onSelect={setSelected} />}
      </> : <>
      <div className="data-controls">
        <label>Data source <select value={mode} onChange={event => setMode(event.target.value)}>
          <option value="demo">Backend demo</option><option value="live">Live fire</option>
          <option value="offline">Offline bundled demo</option>
        </select></label>
        <button type="button" onClick={refresh} disabled={loading || mode === 'offline'}>Refresh data</button>
        <p>{mode === 'offline' ? 'Explicit offline preview: fictional fire and route fixtures.'
          : 'Origin: 39.76, −121.62 · One occupant with a vehicle · Road network and shelter limitations are listed in the backend warnings.'}</p>
      </div>
      <div className="workspace">
        <section className="map-section" aria-label="Fire intelligence" aria-busy={loading}>
          <div className="map-heading"><h2>Fire intelligence</h2><label><input type="checkbox" checked={basemap} onChange={event => setBasemap(event.target.checked)} /> Street basemap</label></div>
          {loading && <div className="request-state" role="status">Loading fire observations and route plan…</div>}
          {data.fireError && <div className="request-state error" role="alert"><h3>Fire data unavailable</h3><p>{data.fireError}</p>{retry}<p>No route is displayed without matching fire data. You can explicitly select Offline bundled demo above.</p></div>}
          {fire && <>
            <Map key={`${mode}:${revision}`} fire={fire} plan={plan} layers={layers} basemap={basemap} offline={mode === 'offline'} source={data.metadata?.source} />
            <LayerControls layers={layers} onChange={key => setLayers(previous => ({ ...previous, [key]: !previous[key] }))} />
            <div className="timestamps" aria-live="polite">
              <span>Satellite detections as of {timestamp(fire.data_as_of.firms)}</span>
              <span>Weather as of {timestamp(fire.data_as_of.weather)}</span>
              <SourceStatus metadata={data.metadata} label="Fire source" />
              {plan && <SourceStatus metadata={data.planMetadata} label="Route hazard source" />}
            </div>
            {data.planError && <div className="request-state error" role="alert"><h3>{data.unavailable ? 'Route unavailable' : 'Route request failed'}</h3><p>{data.planError}</p>{retry}<p>No substitute route has been displayed.</p></div>}
            {plan && <RoutePanel plan={plan} offline={mode === 'offline'} />}
          </>}
        </section>
        <aside className="context-panel">
          <p className="eyebrow">YOUR EVACUATION OVERVIEW</p><h2>Understand the options.</h2>
          <p>The map brings modeled risk regions and route comparisons into one view.</p>
          <div className="context-block"><span className="step">01</span><h3>Read the fire outlook</h3><p>Colored regions show current and projected risk at one, three, and six hours. Observation timestamps show when the data was recorded.</p></div>
          <div className="context-block"><span className="step">02</span><h3>Compare the tradeoff</h3><p>Compare the routes returned by the backend, including modeled exposure and travel time. Availability depends on the routing policy and current evacuation information.</p></div>
          {plan && <div className="destination"><p className="eyebrow">{plan.destination.source === 'fema' ? 'LISTED SHELTER' : 'FICTIONAL SHELTER'}</p><h3>{plan.destination.name}</h3>
            <div className="badges"><span>{plan.destination.accepts_pets == null ? 'Pet policy unknown' : plan.destination.accepts_pets ? 'Pets welcome' : 'Does not accept pets'}</span><span>{plan.destination.accessible == null ? 'Accessibility unknown' : plan.destination.accessible ? 'Accessible' : 'Not marked accessible'}</span></div>
            {plan.destination.capacity != null && <p>Listed capacity: {plan.destination.capacity}</p>}
            <p>Follow backend warnings and official guidance; a listed shelter does not guarantee current availability.</p>
          </div>}
        </aside>
      </div>
      </>}
    </main>
    <footer>Experimental decision-support tool. Follow official evacuation orders if they differ.</footer>
  </>
}
export default App
