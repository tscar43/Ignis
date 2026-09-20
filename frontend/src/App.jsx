import { useState } from 'react'
import Map from './components/Map'
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

function App() {
  const [mode, setMode] = useState(import.meta.env.VITE_OFFLINE === 'true' ? 'offline' : 'demo')
  const [revision, setRevision] = useState(0)
  const [layers, setLayers] = useState({ active: true, spread: true, recommended: true, alternative: true, fuel: false, wind: true })
  const [basemap, setBasemap] = useState(import.meta.env.VITE_OFFLINE !== 'true')
  const data = useEvacuationData(mode, revision)
  const { fire, plan, loading } = data
  const refresh = () => setRevision(value => value + 1)
  const retry = <button type="button" onClick={refresh}>Retry requests</button>

  return <>
    <header className="app-header">
      <a className="brand" href="#main"><span aria-hidden="true">◈</span> ignis<span className="brand-caption">EVACUATION INTELLIGENCE</span></a>
      <span className="demo-badge">{mode === 'live' ? 'Live fire · synthetic roads' : 'Demo workspace'}</span>
    </header>
    <main id="main">
      <div className="page-heading"><div><p className="eyebrow">BUTTE COUNTY, CALIFORNIA</p>
        <h1>A clearer view of what’s ahead.</h1><p>Explore projected fire risk and compare evacuation options.</p>
      </div><span className="scenario-label">Engine coverage<br /><strong>Concow / Paradise</strong></span></div>
      <div className="data-controls">
        <label>Data source <select value={mode} onChange={event => setMode(event.target.value)}>
          <option value="demo">Backend demo</option><option value="live">Live fire / synthetic roads</option>
          <option value="offline">Offline bundled demo</option>
        </select></label>
        <button type="button" onClick={refresh} disabled={loading || mode === 'offline'}>Refresh data</button>
        <p>{mode === 'offline' ? 'Explicit offline preview: fictional fire and route fixtures.'
          : 'Origin: 39.76, −121.62 · One occupant with a vehicle · Synthetic roads and fictional shelters.'}</p>
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
          <div className="context-block"><span className="step">02</span><h3>Compare the tradeoff</h3><p>Recommended balances travel time and modeled exposure. Fastest minimizes time to the same destination. Both routes can be identical.</p></div>
          {plan && <div className="destination"><p className="eyebrow">FICTIONAL SHELTER</p><h3>{plan.destination.name}</h3>
            <div className="badges"><span>{plan.destination.accepts_pets ? 'Pets welcome' : 'Does not accept pets'}</span><span>{plan.destination.accessible ? 'Accessible' : 'Not marked accessible'}</span></div>
            {plan.destination.capacity !== undefined && <p>Listed capacity: {plan.destination.capacity}</p>}
            <p>Availability is not verified. Roads and shelters are synthetic even when fire data is live.</p>
          </div>}
        </aside>
      </div>
    </main>
    <footer>Experimental decision-support tool. Follow official evacuation orders if they differ.</footer>
  </>
}
export default App
