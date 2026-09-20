import { useEffect, useState } from 'react'
import Map from './components/Map'
import NationalView from './components/NationalView'
import PalisadesView from './components/PalisadesView'
import LayerControls from './components/LayerControls'
import RoutePanel from './components/RoutePanel'
import EvacuationChat from './components/EvacuationChat'
import './App.css'

const API = import.meta.env.VITE_API ?? 'http://localhost:8000'
const ORIGIN = { lat: 39.76, lon: -121.62, label: '123 Oak St' }
const json = async (path, init) => {
  const response = await fetch(API + path, init)
  const body = await response.json()
  if (!response.ok) throw new Error(`${path} ${response.status}: ${body.detail ?? ''}`)
  return body
}
const timestamp = value => new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Los_Angeles' }).format(new Date(value)) + ' PT'
// A fire can be linked to directly: /?fire=<id> opens the national view on it,
// so a link in a chat lands on the fire being talked about.
const linked = new URLSearchParams(window.location.search).get('fire')
function App() {
  const [layers, setLayers] = useState({ active: true, spread: true, recommended: true, alternative: true, fuel: false, wind: true })
  const [basemap, setBasemap] = useState(import.meta.env.VITE_OFFLINE !== 'true')
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [view, setView] = useState(linked ? 'national' : 'scenario')
  const [national, setNational] = useState(null)
  const [nationalError, setNationalError] = useState(null)
  const [palisades, setPalisades] = useState(null)
  const [palisadesError, setPalisadesError] = useState(null)
  const [selected, setSelected] = useState(linked)
  useEffect(() => {
    Promise.all([
      json('/fire'),
      json('/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ origin: ORIGIN }) }),
    ]).then(([fire, plan]) => setData({ fire, plan })).catch(failure => setError(failure.message))
  }, [])
  // Fetched on first open, not on mount: a cold /fires is a live run over the
  // whole country and takes the better part of a minute.
  useEffect(() => {
    if (view !== 'national' || national || nationalError) return
    json('/fires').then(setNational).catch(failure => setNationalError(failure.message))
  }, [view, national, nationalError])
  // Static fixture, so it is cheap -- but still on first open rather than on
  // mount, since the scenario tab never needs it.
  useEffect(() => {
    if (view !== 'palisades' || palisades || palisadesError) return
    json('/palisades').then(setPalisades).catch(failure => setPalisadesError(failure.message))
  }, [view, palisades, palisadesError])
  const { fire, plan } = data ?? {}
  const chosen = national?.fires.find(item => item.incident.id === selected)
  useEffect(() => {
    const url = new URL(window.location.href)
    if (view === 'national' && selected) url.searchParams.set('fire', selected)
    else url.searchParams.delete('fire')
    window.history.replaceState(null, '', url)
    const name = chosen?.incident.name ?? chosen?.incident.id
    document.title = name ? `${name} · Ignis` : 'Ignis · Evacuation intelligence'
  }, [view, selected, chosen])
  const tab = key => <button type="button" className={view === key ? 'active' : undefined} aria-pressed={view === key} onClick={() => setView(key)}>{{ scenario: 'Evacuation scenario', national: 'Live · every US fire', palisades: 'Palisades · model vs. truth' }[key]}</button>
  return <>
    <header className="app-header"><a className="brand" href="#main"><span aria-hidden="true">◈</span> ignis<span className="brand-caption">EVACUATION INTELLIGENCE</span></a><span className="demo-badge">● Demo workspace</span></header>
    <main id="main"><div className="page-heading"><div><p className="eyebrow">{{ scenario: 'BUTTE COUNTY, CALIFORNIA', national: 'CONTIGUOUS UNITED STATES · LIVE', palisades: 'LOS ANGELES COUNTY · 7–9 JANUARY 2025' }[view]}</p><h1>A clearer view of what’s ahead.</h1><p>{{ scenario: 'Explore projected fire risk and compare evacuation options.', national: 'Every fire burning right now, run through the same spread model.', palisades: 'The same model, seeded from satellite truth and scored against what actually burned.' }[view]}</p></div><span className="scenario-label">{{ scenario: <>Fictional scenario<br /><strong>Concow / Paradise</strong></>, national: <>Live satellite data<br /><strong>NASA FIRMS · GOES · NIFC · HRRR</strong></>, palisades: <>Historical validation<br /><strong>Palisades Fire · VIIRS ground truth</strong></> }[view]}</span></div>
      <div className="view-tabs" role="group" aria-label="Choose a view">{tab('scenario')}{tab('national')}{tab('palisades')}</div>
      {view === 'palisades' ? <>
        {palisadesError && <p className="route-warning" role="alert">Palisades replay unavailable — {palisadesError}. Start the API with uvicorn on {API}; no fictional data is shown in its place.</p>}
        {!palisades ? !palisadesError && <p>Loading the Palisades replay…</p> : <PalisadesView data={palisades} basemap={basemap} onBasemap={setBasemap} />}
      </> : view === 'scenario' ? <>
        {error && <p className="route-warning" role="alert">Backend unavailable — {error}. Start the API with uvicorn on {API}; no fictional data is shown in its place.</p>}
        {!data ? !error && <p>Loading live backend data…</p> : <div className="workspace"><section className="map-section" aria-label="Fire intelligence"><div className="map-heading"><h2>Fire intelligence</h2><label><input type="checkbox" checked={basemap} onChange={event => setBasemap(event.target.checked)} /> Street basemap</label></div><Map fire={fire} plan={plan} layers={layers} basemap={basemap} /><LayerControls layers={layers} onChange={key => setLayers(previous => ({ ...previous, [key]: !previous[key] }))} /><div className="timestamps"><span>Satellite detections as of {timestamp(fire.data_as_of.firms)}</span><span>Weather as of {timestamp(fire.data_as_of.weather)}</span></div><RoutePanel plan={plan} /></section>
        <aside className="context-panel"><p className="eyebrow">YOUR EVACUATION OVERVIEW</p><h2>Understand the options.</h2><p>The map brings modeled risk regions and route comparisons into one view.</p><div className="context-block"><span className="step">01</span><h3>Read the fire outlook</h3><p>Colored regions show the current and projected risk at one, three, and six hours. Toggle layers to explore.</p></div><div className="context-block"><span className="step">02</span><h3>Compare the tradeoff</h3><p>The recommended demo route has lower modeled exposure. The fastest alternative takes less time.</p></div><div className="destination"><p className="eyebrow">ILLUSTRATIVE DESTINATION</p><h3>{plan.destination.name}</h3><div className="badges"><span>{plan.destination.accepts_pets ? 'Pets welcome' : 'No pets'}</span><span>{plan.destination.accessible ? 'Accessible' : 'Access not confirmed'}</span></div><p>Fictional location; availability is not verified.</p></div><EvacuationChat api={API} onPlan={next => setData(current => ({ ...current, plan: next }))} /></aside></div>}
      </> : <>
        {nationalError && <p className="route-warning" role="alert">Live national feed unavailable — {nationalError}. Start the API with uvicorn on {API}; no fictional data is shown in its place.</p>}
        {!national ? !nationalError && <p>Modeling every active fire in the country… this is a live run against NASA FIRMS, LANDFIRE, HRRR and NIFC, not a fixture, so the first load takes up to a minute.</p>
          : <NationalView data={national} basemap={basemap} onBasemap={setBasemap} selected={selected} onSelect={setSelected} />}
      </>}
    </main><footer>Experimental decision-support tool. Follow official evacuation orders if they differ.</footer>
  </>
}
export default App
