export default function RoutePanel({ plan, offline }) {
  return <section className="route-panel" aria-labelledby="routes-title">
    <div className="section-heading"><h2 id="routes-title">Compare your options</h2><span className="eyebrow">{offline ? 'BUNDLED FICTIONAL PLAN' : 'COMPUTED ON SYNTHETIC ROADS'}</span></div>
    <div className="route-grid">{plan.routes.map(route => <article className={`route-card ${route.type}`} key={route.type}>
      <div className="route-title"><span className="route-line" /><h3>{route.type === 'recommended' ? 'Recommended' : 'Fastest alternative'}</h3></div>
      <p className="metrics"><strong>{route.travel_time_min}<small> min</small></strong><span>{route.distance_km} km</span></p>
      <p>{route.named_roads.join(' → ')}</p>
      <p className="exposure">Modeled exposure score <strong>{route.exposure.toFixed(3)}</strong></p>
      <details><summary>Exposure by modeled region</summary>
        {Object.entries(route.exposure_breakdown_km).map(([band, km]) => <p key={band}>{band} region: {Number(km.toFixed(3))} km</p>)}
        <p>{offline ? 'Illustrative fixture values; not calculated from a road network.' : 'Each road edge is assigned to its most severe intersecting risk band. Only its intersection length in that band counts; lower bands on the same edge are omitted.'}</p>
      </details>
    </article>)}</div>
    {!offline && <details className="exposure-method"><summary>How the backend compares routes</summary>
      <p>Weighted km = 10 × h1 km + 4 × h3 km + h6 km. Exposure score = weighted km ÷ (10 × route distance km), limited to 0–1. It is not a probability.</p>
      <p>Recommended minimizes travel minutes + 4 × weighted km. Fastest minimizes travel time to the same selected eligible shelter. Edges intersecting current fire are blocked for both.</p>
    </details>}
    {plan.warnings.map(warning => <p className="route-warning" key={warning}>{warning}</p>)}
  </section>
}
