// Deliberately limited local demo parser. It extracts explicit statements only;
// unknown or contradictory values must be resolved in the editable review.
export const emptyHousehold = { wheelchair_required: null, pets_required: null, occupants: '', has_vehicle: null }
const numberWords = { zero: 0, one: 1, two: 2, three: 3, four: 4, five: 5, six: 6, seven: 7, eight: 8, nine: 9, ten: 10, eleven: 11, twelve: 12, thirteen: 13, fourteen: 14, fifteen: 15, sixteen: 16, seventeen: 17, eighteen: 18, nineteen: 19, twenty: 20 }
const number = '(?:\\d+|' + Object.keys(numberWords).join('|') + ')'
const asNumber = value => numberWords[value] ?? Number(value)

export function missingField(household) {
  if (!Number.isInteger(household.occupants) || household.occupants < 1) return 'occupants'
  return ['wheelchair_required', 'pets_required', 'has_vehicle'].find(field => typeof household[field] !== 'boolean') ?? null
}

export function followUp(household) {
  const questions = {
    occupants: 'How many people are evacuating?',
    wheelchair_required: 'Does the destination need to be marked wheelchair accessible?',
    pets_required: 'Does the destination need to accept pets?',
    has_vehicle: 'Does your household have a vehicle available?',
  }
  return questions[missingField(household)] ?? 'Review the extracted values below, correct anything needed, then confirm to find a demo route.'
}

export function extractHousehold(message, current = emptyHousehold) {
  const text = message.toLowerCase().replace(/[’‘]/g, "'").replace(/wheel chair/g, 'wheelchair').trim()
  const patch = {}
  const notes = []
  const rules = [
    ['wheelchair_required', /\b(?:(?:no|without) (?:a )?wheelchair(?: access(?:ibility)?)?(?: (?:needs?|required))?|(?:do not|don't|does not|doesn't) (?:need|require|use) (?:a )?wheelchair(?: access(?:ibility)?)?|wheelchair (?:access(?:ibility) )?(?:is )?not (?:needed|required))\b/g, /\bwheelchair\b/],
    ['pets_required', /\b(?:(?:no|without|zero|0) (?:pets?|dogs?|cats?|animals?)|(?:do not|don't|does not|doesn't) (?:have|need|bring) (?:any |a )?(?:pets?|dogs?|cats?|animals?))\b/g, /\b(?:pets?|dogs?|cats?)\b/],
    ['has_vehicle', /\b(?:(?:no|without|zero|0) (?:a )?(?:cars?|vehicles?)|(?:do not|don't|does not|doesn't) have (?:a |any )?(?:cars?|vehicles?)|(?:our|my|the) car (?:is broken|broke down|is unavailable))\b/g, /\b(?:cars?|vehicles?)\b/],
  ]
  for (const [field, negative, positive] of rules) {
    const negatives = [...text.matchAll(negative)]
    const remainder = text.replace(negative, '')
    const hasPositive = positive.test(remainder)
    if (!negatives.length && !hasPositive) continue
    // Speculative wording is left for confirmation, never treated as certainty.
    if ((negatives.length && hasPositive) || /\b(?:maybe|might|possibly|unsure|not sure|not certain)\b/.test(text) || text.endsWith('?')) {
      patch[field] = null
      notes.push('Some wording is uncertain or conflicting. Please confirm the affected field below.')
    } else patch[field] = !negatives.length
  }
  // A walker or mobility limitation is not automatically a wheelchair requirement.
  if (patch.wheelchair_required === undefined && /\b(?:walker|mobility|crutches)\b/.test(text)) {
    patch.wheelchair_required = null
    notes.push('Mobility needs were mentioned. Please confirm whether the destination must be marked wheelchair accessible; road accessibility is not modeled.')
  }
  const counts = []
  const patterns = [
    new RegExp(`\\b(${number})\\s+(?:people|persons|occupants|adults|children|kids)\\b`, 'g'),
    new RegExp(`\\b(?:there are|we are|there's|there are now)\\s+(${number})(?:\\s+of us)?\\b`, 'g'),
    new RegExp(`\\b(?:family|household|group) of\\s+(${number})\\b`, 'g'),
    new RegExp(`\\b(${number})\\s+of us\\b`, 'g'),
  ]
  for (const pattern of patterns) for (const match of text.matchAll(pattern)) counts.push(asNumber(match[1]))
  if (/\b(?:i am|i'm) (?:evacuating |traveling )?alone\b/.test(text)) counts.push(1)
  const pending = missingField(current)
  if (pending === 'occupants') {
    const bare = text.match(new RegExp(`^(?:actually,?\\s*)?(${number})(?:\\s+(?:total|in total))?[.!]?$`))
    if (bare) counts.push(asNumber(bare[1]))
  }
  if (counts.length) {
    // Do not sum relatives or subgroups, or guess which contradictory count wins.
    const subgroups = text.match(/\b(?:adults|children|kids)\b/g) ?? []
    patch.occupants = new Set(counts).size === 1 && subgroups.length < 2 && !/\b(?:maybe|might|about|approximately)\b/.test(text)
      ? counts[0] : ''
    if (patch.occupants === '') notes.push('Please confirm the total number of people evacuating.')
  }
  if (pending && pending !== 'occupants' && Object.keys(patch).length === 0) {
    if (/^(?:yes|yeah|yes please)[.!]?$/.test(text)) patch[pending] = true
    else if (/^(?:no|nope|no thanks)[.!]?$/.test(text)) patch[pending] = false
  }
  const household = { ...current, ...patch }
  return { household, patch, notes: [...new Set(notes)], reply: followUp(household) }
}
