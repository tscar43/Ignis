import { useEffect, useState } from 'react'
import { CircleMarker, GeoJSON, MapContainer, TileLayer, Tooltip, useMap } from 'react-leaflet'
import 'leaflet/dist/leaflet.css'
import { bands, detectionAge, DETECTION_AGES } from '../bands'

const CONUS = { center: [39.5, -98.5], zoom: 4 }
// Desaturated basemap on purpose: the bands and the detections are the only
// saturated things on the map, so they read as the subject instead of
// competing with road casings and landuse fills.
// Esri's Light Gray Canvas, base plus a separate labels layer. Keyless --
// CARTO's light_all now stamps "API KEY REQUIRED" across every tile, which is
// the kind of thing you only find by looking at the rendered map.
const BASEMAP = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}'
const LABELS = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}'
const CREDIT = 'Tiles &copy; <a href="https://www.esri.com/">Esri</a> — Esri, DeLorme, NAVTEQ'

// A 2 km risk region is smaller than a pixel at zoom 4, so every fire also
// gets a marker. The polygons are the answer; the marker is how you find it,
// and its size carries the fire's reported acreage -- a 50,000-acre incident
// and a 30-acre one are not the same dot. Square-rooted because acreage is an
// area and the marker is read as one, capped so a megafire does not swallow a
// state.
function radiusFor(incident, selected) {
  const acres = incident.acres ?? 0
  const base = acres > 0 ? 4 + Math.min(11, Math.sqrt(acres) / 11) : 5
  return selected ? base + 3 : base
}

function FlyTo({ bbox }) {
  const map = useMap()
  useEffect(() => {
    if (bbox) map.flyToBounds([[bbox[1], bbox[0]], [bbox[3], bbox[2]]], { maxZoom: 11 })
    else map.flyTo(CONUS.center, CONUS.zoom)
  }, [bbox, map])
  return null
}

export default function NationalMap({ data, basemap, selected, onSelect }) {
  const [tileError, setTileError] = useState(false)
  const active = data.fires.find(fire => fire.incident.id === selected)
  return <div className="map-wrap">
    <MapContainer center={CONUS.center} zoom={CONUS.zoom} scrollWheelZoom={false} aria-label="Modeled risk regions for every active fire in the contiguous United States">
      {basemap && <TileLayer attribution={CREDIT} url={BASEMAP} eventHandlers={{ tileerror: () => setTileError(true) }} />}
      {basemap && <TileLayer url={LABELS} />}
      <FlyTo bbox={active?.incident.bbox} />
      {data.fires.map(fire => bands.map(([key, color, fillOpacity]) => <GeoJSON key={`${fire.incident.id}-${key}`} data={fire.risk_polygons[key]} style={{ color, weight: 1.5, fillOpacity }} eventHandlers={{ click: () => onSelect(fire.incident.id) }}><Tooltip>{fire.incident.name ?? fire.incident.id} · {key === 'current' ? 'current modeled risk region' : `modeled risk region · +${key.slice(1)}h`}</Tooltip></GeoJSON>))}
      {active?.fire_points.features.map((feature, i) => {
        const age = detectionAge(feature.properties.acq_time)
        return <CircleMarker key={i} center={[feature.geometry.coordinates[1], feature.geometry.coordinates[0]]} radius={4} pathOptions={{ color: '#fff', weight: 1, fillColor: age.color, fillOpacity: 1 }}><Tooltip>Satellite detection · {age.label} · {feature.properties.frp} MW</Tooltip></CircleMarker>
      })}
      {data.fires.map(fire => {
        const chosen = fire.incident.id === selected
        return <CircleMarker key={fire.incident.id} center={[fire.incident.lat, fire.incident.lon]} radius={radiusFor(fire.incident, chosen)} pathOptions={{ color: '#fff', weight: chosen ? 3 : 1.5, fillColor: '#bd3926', fillOpacity: chosen ? 1 : 0.9 }} eventHandlers={{ click: () => onSelect(fire.incident.id) }}><Tooltip>{fire.incident.name ?? fire.incident.id}{fire.incident.acres ? ` · ${fire.incident.acres.toLocaleString()} ac` : ''} · {fire.summary.area_km2.h6} km² modeled at +6h</Tooltip></CircleMarker>
      })}
    </MapContainer>
    {active && <div className="wind"><span aria-hidden="true" style={{ transform: `rotate(${active.summary.wind_toward_deg}deg)` }}>↑</span><div><strong>{active.summary.wind_speed_kmh} km/h</strong><small>Toward {active.summary.primary_spread_direction}</small></div></div>}
    {(!basemap || tileError) && <div className="map-notice">{basemap ? 'Basemap unavailable.' : 'Offline map.'} Fire overlays remain available.</div>}
    <div className="map-legend">
      <strong>Modeled risk regions</strong>
      <div>{bands.toReversed().map(([key, color]) => <span key={key}><i style={{ background: color }} />{key === 'current' ? 'Current' : `+${key.slice(1)}h`}</span>)}</div>
      <small>Cumulative: +6h contains +3h contains +1h. Modeled from satellite detections, wind, fuel and terrain — not a fire boundary.</small>
      {active && <><strong className="legend-sub">Detections, by age</strong><div>{DETECTION_AGES.map(([label, color]) => <span key={label}><i className="dot" style={{ background: color }} />{label}</span>)}</div></>}
      <small>Marker size is the fire&rsquo;s reported acreage.</small>
    </div>
  </div>
}
