import { useState } from 'react'
import { extractHousehold, followUp } from '../household-intake'

export default function HouseholdIntake({ household, onChange }) {
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState([])
  function send(event) {
    event.preventDefault()
    const input = message.trim()
    if (!input) return
    const extracted = extractHousehold(input, household)
    onChange(extracted.patch)
    setMessages(previous => [...previous, { role: 'You', text: input }, {
      role: 'Demo assistant', text: [...extracted.notes, extracted.reply].join(' '),
    }])
    setMessage('')
  }
  const fields = [
    ['wheelchair_required', 'Destination wheelchair accessibility', 'Required', 'Not required'],
    ['pets_required', 'Destination accepts pets', 'Required', 'Not required'],
    ['has_vehicle', 'Vehicle available', 'Yes', 'No'],
  ]
  return <section className="household-intake" aria-labelledby="intake-title">
    <h2 id="intake-title">Tell us about your household</h2>
    <p>Local rule-based demo assistant, not an AI service. It may miss phrasing; review and correct every field. Messages stay in this view and are not sent to a chat service.</p>
    <p>The historical demo origin is fixed. Accessibility refers only to the fictional destination, not the road route.</p>
    <div className="household-messages" role="log" aria-label="Household conversation" aria-live="polite">
      {messages.map((item, index) => <p className={`intake-message ${item.role === 'You' ? 'user' : 'assistant'}`} key={index}><strong>{item.role}: </strong>{item.text}</p>)}
    </div>
    <form onSubmit={send} className="intake-composer">
      <label htmlFor="household-message">Describe your household or answer the follow-up</label>
      <textarea id="household-message" value={message} maxLength={2000} rows={3} placeholder="My mom uses a wheelchair, we have a dog, and one car." onChange={event => setMessage(event.target.value)} />
      <button type="submit" disabled={!message.trim()}>Send description</button>
    </form>
    <p className="intake-followup">{followUp(household)}</p>
    <fieldset className="constraint-fields"><legend>Review and edit household constraints</legend>
      <label className="constraint-field">Occupants
        <input type="number" min="1" step="1" required value={household.occupants} placeholder="Unknown" onChange={event => onChange({ occupants: event.target.value === '' ? '' : Number(event.target.value) })} />
      </label>
      {fields.map(([field, label, yes, no]) => <label className="constraint-field" key={field}>{label}
        <select value={household[field] === null ? '' : String(household[field])} onChange={event => onChange({ [field]: event.target.value === '' ? null : event.target.value === 'true' })}>
          <option value="">Unknown — confirm</option><option value="true">{yes}</option><option value="false">{no}</option>
        </select>
      </label>)}
    </fieldset>
    <p>Sending a message does not request a route. Use the confirmation button after reviewing these values.</p>
  </section>
}
