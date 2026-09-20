import { useEffect, useState } from 'react'
import { bands } from '../bands'

// Two charts, not one. Modelled area is km² and burn intensity is megawatts;
// putting both on one pair of axes would be a dual-axis chart, where the
// crossing point is an artefact of the two scales and means nothing. They
// share a time axis instead, so they can still be read against each other.
const W = 760
const H = 150
const PAD = { top: 12, right: 74, bottom: 26, left: 52 }

const label = key => (key === 'current' ? 'Current' : `+${key.slice(1)}h`)
const clock = iso => new Date(iso).toISOString().slice(11, 16)

function scale(domain, range) {
  const [d0, d1] = domain
  const span = d1 - d0 || 1
  return value => range[0] + ((value - d0) / span) * (range[1] - range[0])
}

export default function FireHistory({ api, fireId = 'camp-2018' }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let live = true
    fetch(`${api}/history/${fireId}`)
      .then(async response => {
        const body = await response.json()
        if (!response.ok) throw new Error(body.detail ?? `History unavailable (${response.status}).`)
        return body
      })
      .then(body => live && setData(body))
      .catch(failure => live && setError(failure.message))
    return () => { live = false }
  }, [api, fireId])

  // Absent history is not an error worth a red banner -- the database is
  // optional and the rest of the page is unaffected.
  if (error) return <section className="fire-history"><h2>Fire history</h2>
    <p className="history-empty">{error}</p></section>
  if (!data) return null

  const times = [...data.area.map(r => +new Date(r.observed_at)),
                 ...data.intensity.map(r => +new Date(r.bucket))]
  if (!times.length) return null
  const x = scale([Math.min(...times), Math.max(...times)],
                  [PAD.left, W - PAD.right])

  const series = bands.map(([key, color]) => [key, color,
    data.area.filter(r => r.band === key)
      .sort((a, b) => +new Date(a.observed_at) - +new Date(b.observed_at))])
  const areaMax = Math.max(...data.area.map(r => r.area_km2), 1)
  const yArea = scale([0, areaMax * 1.1], [H - PAD.bottom, PAD.top])

  const frpMax = Math.max(...data.intensity.map(r => r.total_frp), 1)
  const yFrp = scale([0, frpMax * 1.1], [H - PAD.bottom, PAD.top])
  const barW = Math.min(46, Math.max(6, (W - PAD.left - PAD.right) / (data.intensity.length * 2.2)))

  // Nudge the direct labels apart. The lower horizons converge at the right
  // edge, so "+1h" and "Current" land on top of each other and neither reads.
  const ends = series.filter(([, , rows]) => rows.length)
    .map(([key, color, rows]) => ({ key, color, y: yArea(rows.at(-1).area_km2) }))
    .sort((a, b) => a.y - b.y)
  ends.forEach((end, i) => {
    const previous = ends[i - 1]
    if (previous && end.y - previous.y < 13) end.y = previous.y + 13
  })

  const ticks = data.intensity.map(r => r.bucket)
  const axis = (yScale, max, unit) => [0, max / 2, max].map(value =>
    <g key={value}>
      <line className="grid" x1={PAD.left} x2={W - PAD.right}
        y1={yScale(value)} y2={yScale(value)} />
      <text className="tick" x={PAD.left - 8} y={yScale(value) + 4} textAnchor="end">
        {Math.round(value)}{value === max ? unit : ''}
      </text>
    </g>)

  return <section className="fire-history" aria-labelledby="history-title">
    <div className="history-heading">
      <div>
        <p className="eyebrow">CAMP FIRE · 8 NOVEMBER 2018</p>
        <h2 id="history-title">How the fire grew</h2>
      </div>
      <span className="history-badge">TigerData · {data.intensity.reduce((n, r) => n + r.detections, 0)} detections</span>
    </div>

    <figure>
      <figcaption>Modelled risk area, by projection horizon</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`Modelled risk area over time. Peak ${Math.round(areaMax)} square kilometres.`}>
        {axis(yArea, areaMax * 1.1, ' km²')}
        {series.map(([key, color, rows]) => rows.length > 1 && <polyline key={key}
          className="series" stroke={color}
          points={rows.map(r => `${x(+new Date(r.observed_at))},${yArea(r.area_km2)}`).join(' ')} />)}
        {series.map(([key, color, rows]) => rows.map(r => <circle key={key + r.observed_at}
          cx={x(+new Date(r.observed_at))} cy={yArea(r.area_km2)} r="4"
          fill={color} stroke="var(--surface, #fff)" strokeWidth="2">
          <title>{label(key)} · {clock(r.observed_at)}Z · {r.area_km2} km²</title>
        </circle>))}
        {/* Direct labels, because the h6 and h3 hues are close enough that
            colour alone would not separate them for every reader. */}
        {ends.map(end => <text key={end.key} className="direct-label"
          fill={end.color} x={W - PAD.right + 8} y={end.y + 4}>{label(end.key)}</text>)}
      </svg>
    </figure>

    <figure>
      <figcaption>Burn intensity — total radiative power per 30 minutes,
        from a continuous aggregate over {data.intensity.reduce((n, r) => n + r.detections, 0)} satellite detections</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} role="img"
        aria-label={`Burn intensity over time. Peak ${Math.round(frpMax)} megawatts.`}>
        {axis(yFrp, frpMax * 1.1, ' MW')}
        {data.intensity.map(r => {
          const cx = x(+new Date(r.bucket))
          return <rect key={r.bucket} x={cx - barW / 2} y={yFrp(r.total_frp)}
            width={barW} height={Math.max(0, (H - PAD.bottom) - yFrp(r.total_frp))}
            rx="4" fill="#dc503c">
            <title>{clock(r.bucket)}Z · {r.detections} detections · {Math.round(r.total_frp)} MW total</title>
          </rect>
        })}
        {ticks.map(t => <text key={t} className="tick" x={x(+new Date(t))}
          y={H - PAD.bottom + 16} textAnchor="middle">{clock(t)}Z</text>)}
      </svg>
    </figure>

    <p className="history-note">
      Observations stop after the last satellite pass; the modelled horizons continue
      past it, which is the gap on the right of the upper chart. Areas are cumulative
      — each horizon contains the ones above it, so they are not additive.
    </p>
  </section>
}
