import { useState } from 'react'
import fire from '../../demo_data/risk_demo.json'
import plan from './data/plan-demo.json'
import Map from './components/Map'
import LayerControls from './components/LayerControls'
import RoutePanel from './components/RoutePanel'
import './App.css'

const timestamp = value => new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/Los_Angeles' }).format(new Date(value)) + ' PT'
function App() {
  const [layers, setLayers] = useState({ active: true, spread: true, recommended: true, alternative: true, fuel: false, wind: true })
  const [basemap, setBasemap] = useState(import.meta.env.VITE_OFFLINE !== 'true')
  return <>
    <header className="app-header"><a className="brand" href="#main"><span aria-hidden="true">◈</span> ignis<span className="brand-caption">EVACUATION INTELLIGENCE</span></a><span className="demo-badge">● Demo workspace</span></header>
    <main id="main"><div className="page-heading"><div><p className="eyebrow">BUTTE COUNTY, CALIFORNIA</p><h1>A clearer view of what’s ahead.</h1><p>Explore projected fire risk and compare evacuation options.</p></div><span className="scenario-label">Fictional scenario<br /><strong>Concow / Paradise</strong></span></div>
      <div className="workspace"><section className="map-section" aria-label="Fire intelligence"><div className="map-heading"><h2>Fire intelligence</h2><label><input type="checkbox" checked={basemap} onChange={event => setBasemap(event.target.checked)} /> Street basemap</label></div><Map fire={fire} plan={plan} layers={layers} basemap={basemap} /><LayerControls layers={layers} onChange={key => setLayers(previous => ({ ...previous, [key]: !previous[key] }))} /><div className="timestamps"><span>Satellite detections as of {timestamp(fire.data_as_of.firms)}</span><span>Weather as of {timestamp(fire.data_as_of.weather)}</span></div><RoutePanel plan={plan} /></section>
      <aside className="context-panel"><p className="eyebrow">YOUR EVACUATION OVERVIEW</p><h2>Understand the options.</h2><p>The map brings modeled risk regions and route comparisons into one view.</p><div className="context-block"><span className="step">01</span><h3>Read the fire outlook</h3><p>Colored regions show the current and projected risk at one, three, and six hours. Toggle layers to explore.</p></div><div className="context-block"><span className="step">02</span><h3>Compare the tradeoff</h3><p>The recommended demo route has lower modeled exposure. The fastest alternative takes less time.</p></div><div className="destination"><p className="eyebrow">ILLUSTRATIVE DESTINATION</p><h3>{plan.destination.name}</h3><div className="badges"><span>Pets welcome</span><span>Accessible</span></div><p>Fictional location; availability is not verified.</p></div><div className="pending"><h3>Household assistant</h3><p>Coming after live route integration. This preview uses fictional data and does not provide evacuation directions.</p></div></aside></div>
    </main><footer>Experimental decision-support tool. Follow official evacuation orders if they differ.</footer>
  </>
}
export default App
