import { useRef, useState } from 'react'

const EXAMPLE = 'I’m at 39.76, -121.62. Two of us, one car, no pets. My mother has asthma.'

// The assistant plans through the same POST /plan the map uses, so a route it
// describes is a route the router actually produced. When it returns one, it is
// handed up so the map draws exactly what is being talked about.
export default function EvacuationChat({ api, mode = 'demo', onPlan }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState(null)
  const log = useRef(null)

  async function ask(text) {
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
      requestAnimationFrame(() => log.current?.scrollTo(0, log.current.scrollHeight))
    }
  }

  const started = messages.length > 0 || pending

  return <section className="evacuation-chat" aria-labelledby="chat-title">
    <div className="chat-heading">
      <div>
        <p className="eyebrow">ASK THE ASSISTANT</p>
        <h2 id="chat-title">Where are you, and who is with you?</h2>
      </div>
      <span className="chat-badge">● AI · plans with the live router</span>
    </div>

    {!started && <p className="chat-intro">
      Describe your household in plain language. The assistant routes you with the
      same model the map uses — it cannot invent a road or a travel time.
    </p>}

    {started && <div className="chat-log" role="log" aria-label="Conversation"
      aria-live="polite" ref={log}>
      {messages.map((item, index) => <p className={`chat-message ${item.role}`} key={index}>
        <strong>{item.role === 'user' ? 'You' : 'Assistant'}: </strong>{item.content}
      </p>)}
      {pending && <p className="chat-message assistant pendingf" role="status">
        Planning a route…
      </p>}
    </div>}

    {error && <p className="route-warning" role="alert">{error}</p>}

    <form onSubmit={event => { event.preventDefault(); ask(draft.trim()) }}
      className="chat-composer">
      <label className="sr-only" htmlFor="chat-input">Message the evacuation assistant</label>
      <textarea id="chat-input" value={draft} rows={2} maxLength={4000} disabled={pending}
        placeholder="e.g. I’m at 39.76, -121.62 with two people and a dog."
        onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {
          // Enter sends, Shift+Enter is a newline: this is a chat box, not a form field.
          if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault()
            ask(draft.trim())
          }
        }} />
      <button type="submit" disabled={pending || !draft.trim()}>
        {pending ? 'Planning…' : 'Ask'}
      </button>
    </form>

    {!started && <button type="button" className="chat-example" disabled={pending}
      onClick={() => ask(EXAMPLE)}>Try: “{EXAMPLE}”</button>}

    <p className="chat-disclaimer">
      AI assistant on modeled and historical demo data — not an official source.
      Messages are sent to Anthropic to generate a reply. Follow official evacuation
      orders, and call 911 if you are in immediate danger.
    </p>
  </section>
}
