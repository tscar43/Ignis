import { useState } from 'react'
import { CircleMarker, GeoJSON, ImageOverlay, MapContainer, Pane, TileLayer, Tooltip } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import fuel from '../../../demo_data/fuel_overlay.json'
import fuelImage from '../../../demo_data/fuel_overlay.png'

import { bands } from '../bands'
export default function Map({ fire, plan, layers, basemap, offline, source }) {
  const [tileError, setTileError] = useState(false)
  const recommended = plan?.routes.find(route => route.type === 'recommended')
  const end = offline ? recommended?.geometry.coordinates.at(-1) : plan ? [plan.destination.lon, plan.destination.lat] : null
  return <div className="map-wrap">
    <MapContainer center={[39.759, -121.68]} zoom={12} scrollWheelZoom={false} aria-label="Fire and route map">
      {basemap && <TileLayer attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" eventHandlers={{ tileerror: () => setTileError(true) }} />}
      <Pane name="fuel" style={{ zIndex: 250 }}>{layers.fuel && <ImageOverlay url={fuelImage} bounds={fuel.bounds} opacity={0.5} />}</Pane>
      {bands.map(([key, color, fillOpacity]) => (key === 'current' ? layers.active : layers.spread) && <Pane key={key} name={`band-${key}`} style={{ zIndex: 400 + bands.findIndex(band => band[0] === key) }}><GeoJSON data={fire.risk_polygons[key]} style={{ color, weight: 1.5, fillOpacity }}><Tooltip>{key === 'current' ? 'Current modeled risk region' : `Modeled risk region · +${key.slice(1)}h`}</Tooltip></GeoJSON></Pane>)}
      <Pane name="detections" style={{ zIndex: 440 }}>{layers.active && fire.fire_points.features.map((feature, i) => <CircleMarker key={i} center={[feature.geometry.coordinates[1], feature.geometry.coordinates[0]]} radius={5} pathOptions={{ color: '#fff', weight: 1, fillColor: '#bd3926', fillOpacity: 1 }}><Tooltip>Satellite detection · {feature.properties.acq_time}</Tooltip></CircleMarker>)}</Pane>
      <Pane name="routes" style={{ zIndex: 450 }}>{(plan?.routes ?? []).map((route, i) => (route.type === 'recommended' ? layers.recommended : layers.alternative) && <GeoJSON key={i} data={route.geometry} style={{ color: route.type === 'recommended' ? '#146b70' : '#665676', weight: route.type === 'recommended' ? 6 : 4, dashArray: route.type === 'recommended' ? undefined : '8 9' }}><Tooltip>{route.type} · {route.travel_time_min} min · {offline ? 'fictional route' : 'backend route'}</Tooltip></GeoJSON>)}</Pane>
      <Pane name="destination" style={{ zIndex: 460 }}>{end && <CircleMarker center={[end[1], end[0]]} radius={9} pathOptions={{ color: '#fff', weight: 3, fillColor: '#146b70', fillOpacity: 1 }}><Tooltip permanent direction="bottom">{plan.destination.name} · {plan.destination.accepts_pets == null ? 'Pet policy unknown' : plan.destination.accepts_pets ? 'Pets welcome' : 'No pets'} · {plan.destination.accessible ? 'Accessible' : 'Access not confirmed'}</Tooltip></CircleMarker>}</Pane>
    </MapContainer>
    {layers.wind && <div className="wind"><span aria-hidden="true" style={{ transform: `rotate(${fire.summary.wind_toward_deg}deg)` }}>↑</span><div><strong>{fire.summary.wind_speed_kmh} km/h</strong><small>Toward {fire.summary.primary_spread_direction}</small></div></div>}
    {(!basemap || tileError) && <div className="map-notice">{basemap ? 'Basemap unavailable.' : 'Offline map.'} Fire and route overlays remain available.</div>}
    <div className="map-legend"><strong>Modeled risk regions</strong><div>{bands.toReversed().map(([key, color]) => <span key={key}><i style={{ background: color }} />{key === 'current' ? 'Current' : `+${key.slice(1)}h`}</span>)}</div><small>{source === 'live' ? 'Live modeled risk' : 'Hand-drawn demo'} · not a fire boundary</small>{layers.fuel && <details><summary>Fuel legend</summary>{Object.entries(fuel.legend).map(([name, color]) => <span key={name}><i style={{ background: color }} />{name}</span>)}</details>}</div>
  </div>
}
