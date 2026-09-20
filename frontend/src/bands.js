// Drawn largest first: h6 -> h3 -> h1 -> current, so the inner bands stay
// visible on top of the cumulative regions that contain them.
export const bands = [['h6', '#e9b949', 0.15], ['h3', '#e88936', 0.25], ['h1', '#dc503c', 0.35], ['current', '#962f32', 0.6]]

// Detections are coloured by how old the observation is. A six-hour
// projection from a pass this morning is a different claim than the same
// projection from a two-day-old one, and the map should say which it is.
export const DETECTION_AGES = [['Under 12h', '#d7263d'], ['12–24h', '#f26419'], ['Over 24h', '#f6c85f']]

export function detectionAge(acquiredAt) {
  const hours = (Date.now() - new Date(acquiredAt)) / 3600000
  const index = hours < 12 ? 0 : hours < 24 ? 1 : 2
  return { hours, color: DETECTION_AGES[index][1], label: relative(acquiredAt) }
}

// Relative first, because "7 hours ago" is the number that decides whether you
// trust the projection; the absolute stamp goes in a title attribute for
// anyone who needs the record.
export function relative(value) {
  const minutes = (Date.now() - new Date(value)) / 60000
  if (minutes < 90) return `${Math.round(minutes)} min ago`
  if (minutes < 36 * 60) return `${Math.round(minutes / 60)} h ago`
  const days = Math.round(minutes / 1440)
  return `${days} day${days === 1 ? '' : 's'} ago`
}

export const utc = value => new Date(value).toISOString().slice(0, 16).replace('T', ' ') + 'Z'
