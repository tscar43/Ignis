import { useRef, useState } from 'react'

// The assistant plans through the same POST /plan the map uses, so a route it
// describes is a route the router actually produced. When it returns one, it is
// handed up so the map draws exactly what is being talked about.
export default function EvacuationChat({ api, mode = 'demo', onPlan }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const log = useRef(null)

  async function send(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || pending) return
    // The whole conversation goes up each turn; the API is stateless.
    const next = [...messages, { role: 'user', content: text }]
    setMessages(next)
    setDraft('')
    setError(null)
    setPending(true)
    try {
      const response = await fetch(`${api}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ messages: next, mode }),
      })
      const body = await response.json()
      if (!response.ok) throw new Error(body.detail ?? `Chat failed (${response.status}).`)
      setMessages([...next, { role: 'assistant', content: body.reply }])
      if (body.plan) onPlan?.(body.plan)
    } catch (failure) {
      // The user's turn stays in the log; retrying resends it rather than
      // silently dropping what they typed.
      setError(failure.message)
    } finally {
      setPending(false)
      log.current?.scrollTo(0, log.current.scrollHeight)
    }
  }

  return <section className="evacuation-chat" aria-labelledby="chat-title">
    <h3 id="chat-title">Household assistant</h3>
    <p className="chat-disclaimer">
      An AI assistant. It routes with the same model as the map, but it can still be
      wrong about everything else — messages are sent to Anthropic to generate a reply.
      Modeled and historical data, not an official source. Follow official evacuation
      orders, and call 911 if you are in immediate danger.
    </p>
    <div className="chat-log" role="log" aria-label="Conversation" aria-live="polite" ref={log}>
      {messages.length === 0 && <p className="chat-empty">
        Tell it where you are and who is with you — for the bundled scenario, try
        “I’m at 39.76, -121.62 with two people, a dog and one car.”
      </p>}
      {messages.map((item, index) => <p className={`chat-message ${item.role}`} key={index}>
        <strong>{item.role === 'user' ? 'You' : 'Assistant'}: </strong>{item.content}
      </p>)}
      {pending && <p className="chat-message assistant" role="status">Planning a route…</p>}
    </div>
    {error && <p className="route-warning" role="alert">{error}</p>}
    <form onSubmit={send} className="chat-composer">
      <label htmlFor="chat-input">Message the assistant</label>
      <textarea id="chat-input" value={draft} rows={2} maxLength={4000} disabled={pending}
        placeholder="Where are you, and who is evacuating with you?"
        onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {
          // Enter sends, Shift+Enter is a newline: this is a chat box, not a form field.
          if (event.key === 'Enter' && !event.shiftKey) send(event)
        }} />
      <button type="submit" disabled={pending || !draft.trim()}>
        {pending ? 'Planning…' : 'Send'}
      </button>
    </form>
  </section>
}
