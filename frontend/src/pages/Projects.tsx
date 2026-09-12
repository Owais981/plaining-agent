import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { Project } from '../types'

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([])
  const [showForm, setShowForm] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [form, setForm] = useState({ code: '', name: '', start_date: '', end_date: '', budget_total: '' })

  function refresh() {
    api.get<Project[]>('/projects').then(setProjects).catch(() => setProjects([]))
  }

  useEffect(refresh, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await api.post('/projects', {
        code: form.code, name: form.name, start_date: form.start_date, end_date: form.end_date,
        budget_total: form.budget_total ? Number(form.budget_total) : null,
      })
      setShowForm(false)
      setForm({ code: '', name: '', start_date: '', end_date: '', budget_total: '' })
      refresh()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to create project')
    }
  }

  return (
    <div>
      <div className="topbar">
        <h2 style={{ margin: 0 }}>Projects</h2>
        <button onClick={() => setShowForm((s) => !s)}>{showForm ? 'Cancel' : 'New Project'}</button>
      </div>

      {showForm && (
        <form onSubmit={submit} className="card">
          {error && <div className="error-banner">{error}</div>}
          <div className="form-row"><label>Code</label><input required value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} /></div>
          <div className="form-row"><label>Name</label><input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div className="form-row"><label>Start date</label><input required type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} /></div>
          <div className="form-row"><label>End date</label><input required type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} /></div>
          <div className="form-row"><label>Budget (optional)</label><input type="number" value={form.budget_total} onChange={(e) => setForm({ ...form, budget_total: e.target.value })} /></div>
          <button type="submit">Create</button>
        </form>
      )}

      <div className="card">
        {projects.length === 0 ? (
          <div className="empty-state">No projects yet.</div>
        ) : (
          <table>
            <thead><tr><th>Code</th><th>Name</th><th>Status</th><th>Dates</th><th>Budget</th></tr></thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td><Link to={`/projects/${p.id}`}>{p.code}</Link></td>
                  <td>{p.name}</td>
                  <td><span className="badge info">{p.status}</span></td>
                  <td>{p.start_date} → {p.end_date}</td>
                  <td>{p.budget_total ? `${p.currency} ${p.budget_total.toLocaleString()}` : '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
