import React, { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { Project, CrewMember, EquipmentItem } from '../types'

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[] | null>(null)
  const [crew, setCrew] = useState<CrewMember[] | null>(null)
  const [equipment, setEquipment] = useState<EquipmentItem[] | null>(null)

  useEffect(() => {
    api.get<Project[]>('/projects').then(setProjects).catch(() => setProjects([]))
    api.get<CrewMember[]>('/crew').then(setCrew).catch(() => setCrew([]))
    api.get<EquipmentItem[]>('/equipment').then(setEquipment).catch(() => setEquipment([]))
  }, [])

  return (
    <div>
      <h2>Dashboard</h2>

      <div className="grid" style={{ marginBottom: 20 }}>
        <div className="card stat">
          <span className="value">{projects?.length ?? '—'}</span>
          <span className="label">Projects</span>
        </div>
        <div className="card stat">
          <span className="value">{crew?.length ?? '—'}</span>
          <span className="label">Active Crew</span>
        </div>
        <div className="card stat">
          <span className="value">{equipment?.length ?? '—'}</span>
          <span className="label">Active Equipment</span>
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Projects</h3>
        {projects === null && <p>Loading…</p>}
        {projects?.length === 0 && <div className="empty-state">No projects yet. Create one on the Projects page.</div>}
        {projects && projects.length > 0 && (
          <table>
            <thead><tr><th>Code</th><th>Name</th><th>Status</th><th>Dates</th><th>Priority</th></tr></thead>
            <tbody>
              {projects.map((p) => (
                <tr key={p.id}>
                  <td><Link to={`/projects/${p.id}`}>{p.code}</Link></td>
                  <td>{p.name}</td>
                  <td><span className="badge info">{p.status}</span></td>
                  <td>{p.start_date} → {p.end_date}</td>
                  <td>{p.priority}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Getting started</h3>
        <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
          Use <Link to="/chat">Planning Chat</Link> to describe a planning request in natural language,
          or open a project below to run <code>optimize_schedule</code> directly and review the resulting
          plan's schedule, crew &amp; equipment allocation, travel, costs, conflicts and risks.
        </p>
      </div>
    </div>
  )
}
