import React, { useEffect, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import { Project, ChatResponse, ChatToolCall } from '../types'

interface Message {
  role: 'user' | 'assistant'
  content: string
  tools?: ChatToolCall[]
}

export default function PlanningChat() {
  const [projects, setProjects] = useState<Project[]>([])
  const [projectId, setProjectId] = useState('')
  const [conversationId, setConversationId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [aiUnavailable, setAiUnavailable] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.get<Project[]>('/projects').then(setProjects).catch(() => setProjects([]))
  }, [])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages])

  async function ensureConversation(): Promise<string> {
    if (conversationId) return conversationId
    const res = await api.post<{ id: string }>('/conversations', { project_id: projectId || null, title: 'Planning chat' })
    setConversationId(res.id)
    return res.id
  }

  async function send() {
    if (!input.trim()) return
    setError(null)
    const text = input
    setInput('')
    setMessages((m) => [...m, { role: 'user', content: text }])
    setBusy(true)
    try {
      const convoId = await ensureConversation()
      const res = await api.post<ChatResponse>(`/conversations/${convoId}/messages`, { content: text })
      setMessages((m) => [...m, { role: 'assistant', content: res.response, tools: res.tool_calls }])
    } catch (err) {
      if (err instanceof ApiError && err.code === 'AI_NOT_CONFIGURED') {
        setAiUnavailable(true)
      } else {
        setError(err instanceof ApiError ? err.message : 'Something went wrong sending that message')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <h2>Planning Chat</h2>

      {aiUnavailable && (
        <div className="error-banner">
          The conversational agent needs <code>ANTHROPIC_API_KEY</code> configured on the backend.
          Until then, use the Projects page to run <code>optimize_schedule</code> directly — every other
          part of the system (solver, conflicts, costs, risks) works without it.
        </div>
      )}

      <div className="card" style={{ marginBottom: 12 }}>
        <div className="form-row">
          <label>Project context (optional)</label>
          <select value={projectId} onChange={(e) => { setProjectId(e.target.value); setConversationId(null); setMessages([]) }}>
            <option value="">No specific project</option>
            {projects.map((p) => <option key={p.id} value={p.id}>{p.code} — {p.name}</option>)}
          </select>
        </div>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="chat-window">
        <div className="chat-messages" ref={scrollRef}>
          {messages.length === 0 && (
            <div className="empty-state">
              Try: "Is there enough crew available to run this project?" or "Plan the project using the balanced objective."
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`chat-message ${m.role}`}>
              <div className="bubble">{m.content}</div>
              {m.tools && m.tools.length > 0 && (
                <div className="chat-tools">
                  {m.tools.map((t, j) => (
                    <span key={j} className={`badge ${t.status === 'ok' ? 'ok' : 'critical'}`} style={{ marginRight: 4 }}>{t.tool}</span>
                  ))}
                </div>
              )}
            </div>
          ))}
          {busy && <div className="chat-message assistant"><div className="bubble">Thinking…</div></div>}
        </div>
        <div className="chat-input">
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !busy) send() }}
            placeholder="Describe the planning request…"
            disabled={aiUnavailable}
          />
          <button onClick={send} disabled={busy || aiUnavailable}>Send</button>
        </div>
      </div>
    </div>
  )
}
