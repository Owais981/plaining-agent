import React, { useEffect, useState } from 'react'
import { api } from '../api/client'
import { EquipmentItem } from '../types'

export default function Equipment() {
  const [equipment, setEquipment] = useState<EquipmentItem[]>([])
  const [categories, setCategories] = useState<Record<string, string>>({})

  useEffect(() => {
    api.get<EquipmentItem[]>('/equipment').then(setEquipment).catch(() => setEquipment([]))
    api.get<{ id: string; name: string }[]>('/reference/equipment-categories').then((rows) => {
      setCategories(Object.fromEntries(rows.map((r) => [r.id, r.name])))
    }).catch(() => {})
  }, [])

  return (
    <div>
      <h2>Equipment</h2>
      <div className="card">
        {equipment.length === 0 ? (
          <div className="empty-state">No equipment yet. Run the seed script or add assets via the API.</div>
        ) : (
          <table>
            <thead><tr><th>Asset code</th><th>Name</th><th>Category</th><th>Daily cost</th><th>Ownership</th><th>Status</th></tr></thead>
            <tbody>
              {equipment.map((e) => (
                <tr key={e.id}>
                  <td>{e.asset_code}</td>
                  <td>{e.name}</td>
                  <td>{categories[e.category_id] ?? e.category_id}</td>
                  <td>{e.daily_operating_cost ? `$${e.daily_operating_cost.toFixed(2)}` : '—'}</td>
                  <td>{e.ownership}</td>
                  <td>{e.is_active ? <span className="badge ok">active</span> : <span className="badge critical">inactive</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
        Availability and maintenance windows are managed via <code>/api/v1/equipment/availability</code> and
        <code> /maintenance</code>, and are enforced as hard constraints by the solver (C4/C5).
      </p>
    </div>
  )
}
