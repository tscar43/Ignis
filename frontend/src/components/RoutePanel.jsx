const routeLabels = {
  recommended: 'Recommended',
  alternative: 'Alternative',
  comparison: 'Comparison only',
  fastest: 'Fastest', // Retained for the explicitly selected offline fixture.
}

function routeLabel(route) {
  return routeLabels[route.type] ?? route.type ?? 'Route'
}

export default function RoutePanel({ plan, offline }) {
  const routes = plan?.routes ?? []
  const warnings = plan?.warnings ?? []
  const geometryKeys = routes.map(route => route.geometry?.coordinates?.length
    ? JSON.stringify(route.geometry) : null)
  const hasComparison = routes.some(route => route.type === 'comparison')

  return <section className="route-panel" aria-labelledby="routes-title">
    <div className="section-heading">
      <h2 id="routes-title">{routes.length > 1 ? 'Compare your options' : 'Route plan'}</h2>
      <span className="eyebrow">{offline ? 'BUNDLED FICTIONAL PLAN' : 'BACKEND ROUTE PLAN'}</span>
    </div>
    {routes.length === 0 && <p role="status">No route is available in this plan. No substitute route is shown.</p>}
    {routes.length === 1 && <p className="route-warning">One route returned; no separate alternative was provided.</p>}
    {hasComparison && <p className="route-warning">Comparison only: evacuation restrictions were not applied to the comparison route. It is not an evacuation recommendation.</p>}
    <div className="route-grid">{routes.map((route, index) => {
      const sameAs = geometryKeys[index] === null ? -1 : geometryKeys.indexOf(geometryKeys[index])
      return <article className={`route-card ${route.type}`} key={`${route.type}-${index}`}>
        <div className="route-title"><span className="route-line" /><h3>{routeLabel(route)}</h3></div>
        {sameAs >= 0 && sameAs < index && <p className="route-warning">Same geometry as {routeLabel(routes[sameAs])}; not a distinct route option.</p>}
        <p className="metrics"><strong>{route.travel_time_min}<small> min</small></strong><span>{route.distance_km} km</span></p>
        <p>{route.named_roads?.length ? route.named_roads.join(' → ') : 'Road names not provided.'}</p>
        <p className="exposure">Modeled exposure score <strong>{route.exposure.toFixed(3)}</strong></p>
        <details><summary>Exposure by modeled region</summary>
          {Object.entries(route.exposure_breakdown_km).map(([band, km]) => <p key={band}>{band} region: {Number(km.toFixed(3))} km</p>)}
          <p>{offline ? 'Illustrative fixture values; not calculated from a road network.' : 'Each road segment contributes only to its most severe risk band. Higher-risk regions are subtracted from lower-risk regions, so overlapping cumulative bands do not double-count distance. Different portions of one road edge can contribute to different bands.'}</p>
        </details>
      </article>
    })}</div>
    {!offline && routes.length > 0 && <details className="exposure-method"><summary>How the backend compares routes</summary>
      <p>Weighted km = 10 × h1 km + 4 × h3 km + h6 km. Exposure score = weighted km ÷ (10 × route distance km), limited to 0–1. A zero-distance route has score 0. It is not a probability; displayed distances are rounded.</p>
      <p>The backend excludes current fire and 1-hour risk, then selects the shortest travel time among eligible shelters and permitted routes. The exposure score describes the returned route; it is not the route-selection cost.</p>
      <p>Recommended routes apply supplied evacuation restrictions. A distinct alternative may be returned when evacuation information is fresh or historical and the routing policy permits it. Comparison routes omit evacuation restrictions and are not recommendations.</p>
    </details>}
    {warnings.map((warning, index) => <p className="route-warning" key={index}>{warning}</p>)}
  </section>
}
