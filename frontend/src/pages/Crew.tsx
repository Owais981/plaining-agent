import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import { CrewMember } from '../types'

export default function Crew() {
  const [crew, setCrew] = useState<CrewMember[]>([])
  const [roles, setRoles] = useState<Record<string, string>>({})

  useEffect(() => {
    api.get<CrewMember[]>('/crew').then(setCrew).catch(() => setCrew([]))
    api.get<{ id: string; name: string }[]>('/reference/roles').then((rows) => {
      setRoles(Object.fromEntries(rows.map((r) => [r.id, r.name])))
    }).catch(() => {})
  }, [])

  return (
    <div>
      <h2>Crew</h2>
      <div className="card">
        {crew.length === 0 ? (
          <div className="empty-state">No crew members yet. Run the seed script or add them via the API.</div>
        ) : (
          <table>
            <thead><tr><th>Code</th><th>Name</th><th>Role</th><th>Standard rate</th><th>Overtime rate</th><th>Status</th></tr></thead>
            <tbody>
              {crew.map((c) => (
                <tr key={c.id}>
                  <td>{c.employee_code}</td>
                  <td>{c.full_name}</td>
                  <td>{roles[c.primary_role_id] ?? c.primary_role_id}</td>
                  <td>${c.standard_rate.toFixed(2)}/hr</td>
                  <td>${c.overtime_rate.toFixed(2)}/hr</td>
                  <td>{c.is_active ? <span className="badge ok">active</span> : <span className="badge critical">inactive</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
        Skills, certifications (with expiry dates) and availability windows are managed via the
        <code> /api/v1/crew</code> endpoints and drive solver eligibility directly from the database.
      </p>
    </div>
  )
}
