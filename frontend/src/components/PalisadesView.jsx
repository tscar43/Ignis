import { useState } from 'react'
import { GeoJSON, MapContainer, TileLayer, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { utc } from '../bands'

// Fixed frame across every pass: the whole point is watching the footprint
// grow, and a map that refits its bounds each step hides exactly that. So the
// bounds are taken over every window at once, not the one on screen.
function framing(windows) {
  const points = windows.flatMap(window => [window.observed, ...Object.values(window.predictions)]
    .flatMap(collection => collection.features.flatMap(feature => feature.geometry.coordinates.flat())))
  const lats = points.map(point => point[1])
  const lons = points.map(point => point[0])
  return [[Math.min(...lats), Math.min(...lons)], [Math.max(...lats), Math.max(...lons)]]
}
const BASEMAP = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}'
const LABELS = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}'
const CREDIT = 'Tiles &copy; <a href="https://www.esri.com/">Esri</a> — Esri, DeLorme, NAVTEQ'
const FARSITE = 'FARSITE-class'
const IGNIS = 'Ignis'

const km2 = value => `${value.toFixed(0)} km²`

export default function PalisadesView({ data, basemap, onBasemap }) {
  const [step, setStep] = useState(0)
  const [showFarsite, setShowFarsite] = useState(true)
  const [tileError, setTileError] = useState(false)
  const passes = data.windows
  const pass = passes[step]
  const fitted = pass.role === 'fit'
  const colors = data.colors
  const bounds = framing(passes)
  // Named in the copy so the weakest pass cannot quietly stop being named if
  // WINDOWS moves and the ordering changes.
  const scored = passes.map((window, index) => index).filter(index => passes[index].role !== 'fit')
  const weakest = scored.reduce((worst, index) => passes[index].models[IGNIS].iou_growth < passes[worst].models[IGNIS].iou_growth ? index : worst, scored[0])
  // Drawn largest-claim-first so the smaller footprints stay readable: seed
  // underneath, then each prediction, then the truth outline on top of both.
  const layers = [
    ['seed', pass.seed, colors.seed, 0.55, 1, 'Seed footprint · observed detections at the seed pass'],
    ...(showFarsite ? [[FARSITE, pass.predictions[FARSITE], colors[FARSITE], 0.12, 2, `${FARSITE} prediction`]] : []),
    [IGNIS, pass.predictions[IGNIS], colors[IGNIS], 0.16, 2, 'Ignis prediction'],
    ['observed', pass.observed, colors.observed, 0, 2.5, 'Observed burn at the validation pass'],
  ]

  return <div className="workspace">
    <section className="map-section" aria-label="Palisades Fire, model against observed burn">
      <div className="map-heading">
        <h2>Pass {step + 1} of {passes.length} <small style={{ fontWeight: 400, color: fitted ? '#8a6d1f' : '#52514e' }}>· {fitted ? 'calibration window — not a score' : 'held out of calibration'}</small></h2>
        <label><input type="checkbox" checked={basemap} onChange={event => onBasemap(event.target.checked)} /> Street basemap</label>
      </div>

      <div className="view-tabs" role="group" aria-label="Step through passes">
        <button type="button" onClick={() => setStep(step - 1)} disabled={step === 0}>‹ Previous pass</button>
        {passes.map((window, index) => <button key={window.seed_at} type="button" className={index === step ? 'active' : undefined} aria-pressed={index === step} onClick={() => setStep(index)}>{index + 1}{window.role === 'fit' ? ' · fit' : ''}</button>)}
        <button type="button" onClick={() => setStep(step + 1)} disabled={step === passes.length - 1}>Next pass ›</button>
      </div>

      <div className="map-wrap">
        <MapContainer bounds={bounds} scrollWheelZoom={false} aria-label={`Modeled and observed burn for pass ${step + 1}`}>
          {basemap && <TileLayer attribution={CREDIT} url={BASEMAP} eventHandlers={{ tileerror: () => setTileError(true) }} />}
          {basemap && <TileLayer url={LABELS} />}
          {layers.map(([key, geojson, color, fillOpacity, weight, label]) => <GeoJSON key={`${step}-${key}`} data={geojson} style={{ color, weight, fillOpacity, fillColor: color }}><Tooltip>{label}</Tooltip></GeoJSON>)}
        </MapContainer>
        <div className="wind"><span aria-hidden="true" style={{ transform: `rotate(${pass.wind_toward}deg)` }}>↑</span><div><strong>{pass.wind_kmh} km/h</strong><small>Toward {pass.wind_toward}°</small></div></div>
        {(!basemap || tileError) && <div className="map-notice">{basemap ? 'Basemap unavailable.' : 'Offline map.'} Fire overlays remain available.</div>}
        <div className="map-legend">
          <strong>Seeded {utc(pass.seed_at)} → validated {utc(pass.validate_at)} <span style={{ fontWeight: 400 }}>(+{pass.gap_h} h)</span></strong>
          <div>
            <span><i style={{ background: colors.seed }} />Seed · {km2(pass.seed_km2)}</span>
            <span><i style={{ background: colors[IGNIS] }} />Ignis · {km2(pass.models[IGNIS].predicted_km2)}</span>
            {showFarsite && <span><i style={{ background: colors[FARSITE] }} />{FARSITE} · {km2(pass.models[FARSITE].predicted_km2)}</span>}
            <span><i style={{ background: colors.observed }} />Observed · {km2(pass.observed_km2)}</span>
          </div>
          <small>Observed burn is the union of VIIRS detections up to the validation pass. A detection is an actively burning pixel, so it understates burned area and every IoU here is pessimistic.</small>
        </div>
      </div>

      <table className="incident-table">
        <caption className="eyebrow" style={{ textAlign: 'left', paddingBottom: '0.4rem' }}>{fitted ? 'FITTED ON THIS WINDOW — SHOWN FOR COMPLETENESS, NOT AS A SCORE' : `SCORED ON THIS WINDOW · PASS ${step + 1} OF ${passes.length}`}</caption>
        <thead><tr><th scope="col">Model</th><th scope="col">Predicted</th><th scope="col">Growth IoU</th><th scope="col">IoU</th></tr></thead>
        <tbody>{Object.entries(pass.models).map(([name, stats]) => <tr key={name}>
          <th scope="row"><span style={{ background: colors[name] ?? '#999', display: 'inline-block', width: '0.7rem', height: '0.7rem', borderRadius: '2px', marginRight: '0.5rem' }} />{name}</th>
          <td>{km2(stats.predicted_km2)}</td>
          <td><strong>{fitted ? <span className="muted">{stats.iou_growth.toFixed(3)} (fitted)</span> : stats.iou_growth.toFixed(3)}</strong></td>
          <td>{fitted ? <span className="muted">{stats.iou.toFixed(3)} (fitted)</span> : stats.iou.toFixed(3)}</td>
        </tr>)}</tbody>
      </table>

      <div className="layers" style={{ marginTop: '0.75rem' }}>
        <label><input type="checkbox" checked={showFarsite} onChange={event => setShowFarsite(event.target.checked)} /> Show the {FARSITE} baseline on the map</label>
      </div>
    </section>

    <aside className="context-panel">
      <p className="eyebrow">WHAT YOU ARE LOOKING AT</p>
      <h2>The model, graded against reality.</h2>
      <p>One real fire, replayed as {passes.length} passes. Each pass seeds the engine from the satellite footprint at one overpass, projects ~12 hours forward, and scores that projection against what actually burned by the next overpass.</p>
      <div className="context-block"><span className="step">01</span><h3>Every pass re-seeds from the truth</h3><p>{data.reseeding}</p></div>
      <div className="context-block"><span className="step">02</span><h3>Pass 1 is the calibration window</h3><p>Spread rate R₀ is fitted once, on pass 1, to match its observed area — so pass 1&rsquo;s IoU restates the fit and is not a score. Passes 2–{passes.length} were never seen by the calibration. R₀: {Object.entries(data.r0_m_per_min).map(([name, value]) => `${name} ${value}`).join(', ')} m/min.</p></div>
      <div className="context-block"><span className="step">03</span><h3>Nothing is cherry-picked</h3><p>Every pass is on the strip above, good and bad. Pass {weakest + 1} scores worst — Ignis at {passes[weakest].models[IGNIS].iou_growth.toFixed(3)} growth IoU — and is one click away at the same size as the rest.</p></div>
      <div className="context-block"><span className="step">04</span><h3>The baseline is a formulation, not a product</h3><p>{FARSITE} is the published Alexander/Finney ellipse run through this engine&rsquo;s own solver on the same seed, wind and grid — the formulation commercial tools are built on, not any vendor&rsquo;s output.</p></div>
      <div className="pending"><h3>On the NIFC perimeter</h3><p>{data.perimeter}</p></div>
    </aside>
  </div>
}
