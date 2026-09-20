const W = 760
const H = 210
const PAD = { top: 14, right: 16, bottom: 46, left: 44 }

// Pass 1 is the calibration window: R0 was fitted on it, so its bars restate
// the fit rather than scoring it. Hatched, not hidden -- dropping it would be
// the cherry-pick the tab explicitly promises not to make.
const HATCH = 'fitted-hatch'

export default function PalisadesScores({ data, step, onStep }) {
  const windows = data.windows
  const models = Object.keys(windows[0].models)
  const top = Math.max(...windows.flatMap(w => models.map(m => w.models[m].iou_growth)))
  const max = Math.ceil(top * 10) / 10 + 0.1
  const y = value => (H - PAD.bottom) - (value / max) * (H - PAD.bottom - PAD.top)

  const groupW = (W - PAD.left - PAD.right) / windows.length
  const barW = Math.min(30, (groupW - 18) / models.length)

  return <figure className="palisades-scores">
    <figcaption>Growth IoU by pass — higher is better</figcaption>
    <svg viewBox={`0 0 ${W} ${H}`} role="img"
      aria-label={`Growth IoU for ${models.length} models across ${windows.length} validation passes.`}>
      <defs>
        <pattern id={HATCH} width="6" height="6" patternTransform="rotate(45)"
          patternUnits="userSpaceOnUse">
          <rect width="6" height="6" fill="#fff" />
          <line x1="0" y1="0" x2="0" y2="6" stroke="currentColor" strokeWidth="3" />
        </pattern>
      </defs>

      {[0, max / 2, max].map(value => <g key={value}>
        <line className="grid" x1={PAD.left} x2={W - PAD.right} y1={y(value)} y2={y(value)} />
        <text className="tick" x={PAD.left - 8} y={y(value) + 4} textAnchor="end">
          {value.toFixed(1)}
        </text>
      </g>)}

      {windows.map((window, index) => {
        const x0 = PAD.left + index * groupW
        const fitted = window.role === 'fit'
        return <g key={index}>
          {/* The whole group is the hit target, so clicking the chart moves
              the stepper below it rather than being a dead picture. */}
          <rect className={`group-hit ${index === step ? 'active' : ''}`}
            x={x0 + 2} y={PAD.top - 6} width={groupW - 4}
            height={H - PAD.bottom - PAD.top + 12} rx="6"
            onClick={() => onStep(index)} role="button" tabIndex={0}
            onKeyDown={event => event.key === 'Enter' && onStep(index)}>
            <title>Pass {index + 1} — {fitted ? 'calibration window' : 'held out'}</title>
          </rect>
          {models.map((model, m) => {
            const value = window.models[model].iou_growth
            const x = x0 + (groupW - barW * models.length - 4) / 2 + m * (barW + 2)
            return <g key={model} style={{ color: data.colors[model] }}>
              <rect x={x} y={y(value)} width={barW}
                height={Math.max(1, (H - PAD.bottom) - y(value))} rx="4"
                fill={fitted ? `url(#${HATCH})` : data.colors[model]}
                stroke={data.colors[model]} strokeWidth={fitted ? 1.5 : 0}>
                <title>{model} · pass {index + 1} · growth IoU {value.toFixed(3)}
                  {fitted ? ' (fitted, not a score)' : ''}</title>
              </rect>
            </g>
          })}
          <text className="tick" x={x0 + groupW / 2} y={H - PAD.bottom + 16}
            textAnchor="middle">Pass {index + 1}</text>
          <text className="role-tick" x={x0 + groupW / 2} y={H - PAD.bottom + 30}
            textAnchor="middle">{fitted ? 'calibration' : `+${window.gap_h}h held out`}</text>
        </g>
      })}
    </svg>

    <div className="scores-legend">
      {models.map(model => <span key={model}>
        <i style={{ background: data.colors[model] }} />{model}
      </span>)}
      <span className="legend-note"><i className="hatched" />Calibration window — restates the fit, not a score</span>
    </div>
  </figure>
}
