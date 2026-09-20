import { CircleMarker, GeoJSON, MapContainer, Pane, TileLayer, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { bands } from '../bands'

export default function PalisadesRouteMap({ scenario, result, basemap }) {
  const origin = scenario.defaults.origin
  const destination = result?.destination ?? scenario.defaults.destination
  return <div className="map-wrap">
    <MapContainer bounds={[[origin.lat - 0.01, Math.min(origin.lon, destination.lon) - 0.02], [Math.max(origin.lat, destination.lat) + 0.01, Math.max(origin.lon, destination.lon) + 0.02]]} scrollWheelZoom={false} aria-label="Historical Palisades evacuation map">
      {basemap && <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />}
      {bands.map(([band, color, fillOpacity], index) => <Pane key={band} name={`risk-${band}`} style={{ zIndex: 400 + index }}><GeoJSON data={scenario.fire.risk_polygons[band]} style={{ color, fillOpacity, weight: 1 }} /></Pane>)}
      <Pane name="orders" style={{ zIndex: 410 }}><GeoJSON data={scenario.evacuations} style={{ color: '#754489', fillOpacity: 0.06, dashArray: '5 5', weight: 2 }} onEachFeature={(feature, layer) => {
        const text = document.createElement('span')
        text.textContent = `${feature.properties.zone} · ${feature.properties.level} · ${feature.properties.instructions ?? ''}`
        layer.bindTooltip(text)
      }} /></Pane>
      <Pane name="routes" style={{ zIndex: 450 }}>{result?.plan.routes.map((route, index) => <GeoJSON key={index} data={route.geometry} style={{ color: route.type === 'recommended' ? '#146b70' : '#665676', weight: 5, dashArray: route.type === 'alternative' ? '8 9' : undefined }}><Tooltip>{route.type} · {route.travel_time_min} min</Tooltip></GeoJSON>)}</Pane>
      <Pane name="points" style={{ zIndex: 460 }}>
        {scenario.fire.fire_points.features.map((point, index) => <CircleMarker key={index} center={[point.geometry.coordinates[1], point.geometry.coordinates[0]]} radius={4} pathOptions={{ color: '#bd3926' }}><Tooltip>Historical satellite detection</Tooltip></CircleMarker>)}
        <CircleMarker center={[origin.lat, origin.lon]} radius={6}><Tooltip>Historical demo origin</Tooltip></CircleMarker>
        {result?.destination && <CircleMarker center={[destination.lat, destination.lon]} radius={8} pathOptions={{ color: '#146b70' }}><Tooltip permanent>{destination.label} · fictional</Tooltip></CircleMarker>}
      </Pane>
    </MapContainer>
    <div className="map-legend"><strong>Modeled risk regions</strong><div>{bands.toReversed().map(([band, color]) => <span key={band}><i style={{ background: color }} />{band === 'current' ? 'Current' : `+${band.slice(1)}h`}</span>)}</div><small>Purple dashed: archived evacuation areas · historical demonstration</small></div>
  </div>
}
