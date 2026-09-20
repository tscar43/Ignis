import NationalMap from './NationalMap'
import { relative, utc } from '../bands'

// Every feed behind a fire, said once, where a judge can see it rather than
// having to be told.
const SOURCES = 'NASA FIRMS (VIIRS) · GOES ABI · NIFC WFIGS · LANDFIRE fuel & terrain · NOAA HRRR wind'

const acres = value => (value ? `${value.toLocaleString()} ac` : null)

function Stat({ label, children, wide }) {
  return <div className={`stat${wide ? ' wide' : ''}`}><span className="stat-label">{label}</span><div className="stat-value">{children}</div></div>
}

function Field({ label, children }) {
  return children ? <p className="field"><span>{label}</span><strong>{children}</strong></p> : null
}

/** One fire, in the depth the table cannot hold. */
function FireDetail({ fire, onClear }) {
  const { incident, summary, data_as_of: asOf } = fire
  const contained = incident.contained_pct
  return <aside className="context-panel detail">
    <div className="detail-head">
      <div>
        <p className="eyebrow">{incident.name ? 'NIFC INCIDENT' : 'UNFILED DETECTION CLUSTER'}</p>
        <h2>{incident.name ?? incident.id}</h2>
        <p className="detail-where">{incident.place ?? `${Math.abs(incident.lat).toFixed(2)}°${incident.lat >= 0 ? 'N' : 'S'} ${Math.abs(incident.lon).toFixed(2)}°${incident.lon >= 0 ? 'E' : 'W'}`}{incident.agency ? ` · ${incident.agency}` : ''}</p>
      </div>
      <button type="button" className="detail-close" onClick={onClear} aria-label="Close fire details">×</button>
    </div>

    <div className="stat-grid">
      <Stat label="Status"><span className="chip active">ACTIVE</span></Stat>
      <Stat label="Size">{acres(incident.acres) ?? <span className="muted">not reported</span>}</Stat>
      <Stat label="Containment">{contained == null ? <span className="muted">unreported</span> : <><span className="bar"><i style={{ width: `${contained}%` }} /></span>{contained}%</>}</Stat>
      <Stat label="Detections">{incident.detections}</Stat>
    </div>

    <h3 className="detail-section">Next 6 hours <small>modeled</small></h3>
    <div className="stat-grid projection">
      {['current', 'h1', 'h3', 'h6'].map(key => <Stat key={key} label={key === 'current' ? 'Now' : `+${key.slice(1)}h`}>{summary.area_km2[key]}<small> km²</small></Stat>)}
    </div>
    <p className="detail-note">Cumulative regions the routing engine avoids, not a fire boundary. Wind {summary.wind_speed_kmh} km/h toward {summary.primary_spread_direction}; fuel {summary.dominant_fuels.join(', ') || 'unclassified'}.</p>

    <h3 className="detail-section">How fresh is this</h3>
    <p className="field"><span>Satellite detections</span><strong title={utc(asOf.firms)}>{relative(asOf.firms)}</strong></p>
    <p className="field"><span>Wind</span><strong title={utc(asOf.weather)}>{relative(asOf.weather)}</strong></p>
    <p className="field"><span>Seeded from</span><strong>{incident.has_perimeter ? 'official perimeter + detections' : 'detections only'}</strong></p>

    {incident.name && <>
      <h3 className="detail-section">Official record</h3>
      <Field label="Reported">{incident.discovered ? <span title={utc(incident.discovered)}>{relative(incident.discovered)}</span> : null}</Field>
      <Field label="Record updated">{incident.updated ? <span title={utc(incident.updated)}>{relative(incident.updated)}</span> : null}</Field>
      <Field label="IRWIN">{incident.irwin_id?.replace(/[{}]/g, '').slice(0, 8)}</Field>
    </>}
  </aside>
}

export default function NationalView({ data, basemap, onBasemap, selected, onSelect }) {
  const fire = data.fires.find(item => item.incident.id === selected)
  return <div className="workspace">
    <section className="map-section" aria-label="Live national fire activity">
      <div className="map-heading"><h2>Every active fire · contiguous US</h2><label><input type="checkbox" checked={basemap} onChange={() => onBasemap(!basemap)} /> Street basemap</label></div>
      <NationalMap data={data} basemap={basemap} selected={selected} onSelect={onSelect} />
      <div className="timestamps">
        <span>Modeled <strong title={utc(data.generated_at)}>{relative(data.generated_at)}</strong></span>
        <span>{SOURCES}</span>
      </div>

      <section className="route-panel" aria-labelledby="incidents-title">
        <div className="section-heading">
          <h2 id="incidents-title">{data.fires.length} fires modeled</h2>
          <span className="eyebrow">{data.incidents_active} ACTIVE OF {data.incidents_found} CLUSTERS · {data.named_by_wfigs} MATCHED TO NIFC</span>
        </div>
        <table className="incident-table">
          <thead><tr><th scope="col">Fire</th><th scope="col">Size</th><th scope="col">Modeled +6h</th><th scope="col">Detections</th></tr></thead>
          <tbody>{data.fires.map(item => {
            const { incident, summary, data_as_of: asOf } = item
            return <tr key={incident.id} className={incident.id === selected ? 'selected' : undefined}>
              <th scope="row">
                <button type="button" onClick={() => onSelect(incident.id === selected ? null : incident.id)}>{incident.name ?? incident.id}</button>
                <small>{incident.place ?? 'no incident filed'}{incident.has_perimeter && <span className="badge-perimeter">perimeter-seeded</span>}</small>
              </th>
              <td>{acres(incident.acres) ?? <span className="unmatched">unreported</span>}{incident.contained_pct != null && <small className="contained">{incident.contained_pct}% contained</small>}</td>
              <td><strong>{summary.area_km2.h6}</strong> km²</td>
              <td title={utc(asOf.firms)}>{relative(asOf.firms)}</td>
            </tr>
          })}</tbody>
        </table>
        {Object.keys(data.excluded ?? {}).length > 0 && <p className="excluded-note">Excluded from the map: {Object.entries(data.excluded).map(([reason, count]) => `${count} ${reason}`).join(', ')}. Contained fires still smoulder and industrial flares burn every night, so both keep showing up on satellite long after they stop being something to evacuate from.</p>}
        {data.failed.length > 0 && <p className="route-warning">{data.failed.length} more {data.failed.length === 1 ? 'fire' : 'fires'} could not be modeled this run ({data.failed.map(item => item.name ?? item.id).join(', ')}) — a live run depends on LANDFIRE, HRRR and GOES all answering.</p>}
      </section>
    </section>

    {fire ? <FireDetail fire={fire} onClear={() => onSelect(null)} /> : <aside className="context-panel">
      <p className="eyebrow">WHAT YOU ARE LOOKING AT</p>
      <h2>The whole country, same model.</h2>
      <p>One satellite sweep of the lower 48, clustered into incidents, each run through the spread model the scenario view uses.</p>
      <div className="context-block"><span className="step">01</span><h3>Pick a fire</h3><p>Select a row or a marker to fly to that incident and see its detections, wind and modeled regions.</p></div>
      <div className="context-block"><span className="step">02</span><h3>Only what is burning now</h3><p>Fully contained fires, incidents nobody has updated in a week, and industrial heat sources that burn every night are all detected and then excluded. What is left is {data.incidents_active} currently active clusters.</p></div>
      <div className="context-block"><span className="step">03</span><h3>Official ground truth</h3><p>Names, acreage and containment come from NIFC WFIGS. Where an agency has mapped a perimeter we seed the model from it instead of satellite pixels alone, so the projection starts at the real fire edge.</p></div>
      <div className="destination">
        <p className="eyebrow">COVERAGE</p>
        <h3>Contiguous US only</h3>
        <div className="badges"><span>{data.incidents_active} active</span><span>{data.named_by_wfigs} NIFC-matched</span><span>{data.fires.length} modeled</span></div>
        <p>Alaska and Hawaii need separate fuel layers and are not included.</p>
      </div>
    </aside>}
  </div>
}
