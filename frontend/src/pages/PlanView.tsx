import React, { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { Plan, Conflict, Risk, CostBreakdown, TravelLegOut } from '../types'

interface ScheduleRow {
  task_id: string
  crew_member_id: string | null
  equipment_id: string | null
  scheduled_start: string
  scheduled_end: string
  is_overtime: boolean
  overtime_minutes: number
  assignment_reason: string
}

type Tab = 'schedule' | 'crew' | 'equipment' | 'travel' | 'costs' | 'conflicts' | 'risks'

const TABS: { key: Tab; label: string }[] = [
  { key: 'schedule', label: 'Schedule' },
  { key: 'crew', label: 'Crew Allocation' },
  { key: 'equipment', label: 'Equipment Allocation' },
  { key: 'travel', label: 'Travel Plan' },
  { key: 'costs', label: 'Cost Breakdown' },
  { key: 'conflicts', label: 'Conflicts' },
  { key: 'risks', label: 'Risks' },
]

export default function PlanView() {
  const { planId } = useParams<{ planId: string }>()
  const [plan, setPlan] = useState<Plan | null>(null)
  const [tab, setTab] = useState<Tab>('schedule')
  const [schedule, setSchedule] = useState<ScheduleRow[]>([])
  const [conflicts, setConflicts] = useState<Conflict[]>([])
  const [risks, setRisks] = useState<Risk[]>([])
  const [costs, setCosts] = useState<CostBreakdown | null>(null)
  const [travel, setTravel] = useState<TravelLegOut[]>([])
  const [crewAlloc, setCrewAlloc] = useState<Record<string, any[]>>({})
  const [equipAlloc, setEquipAlloc] = useState<Record<string, any[]>>({})
  const [approveError, setApproveError] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)

  useEffect(() => {
    if (!planId) return
    api.get<Plan>(`/plans/${planId}`).then(setPlan)
    api.get<ScheduleRow[]>(`/plans/${planId}/schedule`).then(setSchedule)
    api.get<Conflict[]>(`/plans/${planId}/conflicts`).then(setConflicts)
    api.get<Risk[]>(`/plans/${planId}/risks`).then(setRisks)
    api.get<CostBreakdown>(`/plans/${planId}/costs`).then(setCosts)
    api.get<TravelLegOut[]>(`/plans/${planId}/travel`).then(setTravel)
    api.get<Record<string, any[]>>(`/plans/${planId}/crew`).then(setCrewAlloc)
    api.get<Record<string, any[]>>(`/plans/${planId}/equipment`).then(setEquipAlloc)
  }, [planId])

  const criticalCount = conflicts.filter((c) => c.severity === 'critical').length

  async function approve() {
    if (!planId) return
    setApproveError(null)
    setApproving(true)
    try {
      await api.post(`/plans/${planId}/approve`)
      const updated = await api.get<Plan>(`/plans/${planId}`)
      setPlan(updated)
    } catch (err) {
      setApproveError(err instanceof ApiError ? err.message : 'Approval failed')
    } finally {
      setApproving(false)
    }
  }

  if (!plan) return <p>Loading…</p>

  return (
    <div>
      <div className="topbar">
        <h2 style={{ margin: 0 }}>
          Plan v{plan.version} <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>({plan.scenario_label})</span>
        </h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <span className={`badge ${plan.status === 'approved' ? 'ok' : 'info'}`}>{plan.status}</span>
          {criticalCount > 0 && <span className="badge critical">{criticalCount} critical conflict{criticalCount > 1 ? 's' : ''}</span>}
          {plan.status !== 'approved' && (
            <button onClick={approve} disabled={approving || criticalCount > 0 || plan.solver_status === 'INFEASIBLE'}>
              {approving ? 'Approving…' : 'Approve plan'}
            </button>
          )}
        </div>
      </div>
      {approveError && <div className="error-banner">{approveError}</div>}
      {criticalCount > 0 && (
        <div className="error-banner">This plan has unresolved critical conflicts and cannot be approved until they are fixed.</div>
      )}

      <div className="grid" style={{ marginBottom: 16 }}>
        <div className="card stat"><span className="value">${(plan.total_cost ?? 0).toLocaleString()}</span><span className="label">Total cost</span></div>
        <div className="card stat"><span className="value">{(plan.total_travel_km ?? 0).toFixed(0)} km</span><span className="label">Total travel</span></div>
        <div className="card stat"><span className="value">{(plan.total_overtime_hrs ?? 0).toFixed(1)} hrs</span><span className="label">Overtime</span></div>
        <div className="card stat"><span className="value">{plan.solve_seconds?.toFixed(2)}s</span><span className="label">Solve time</span></div>
      </div>

      <div className="tabs">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? 'active' : ''} onClick={() => setTab(t.key)}>{t.label}</button>
        ))}
      </div>

      <div className="card">
        {tab === 'schedule' && (
          schedule.length === 0 ? <div className="empty-state">No assignments.</div> : (
            <table>
              <thead><tr><th>Task</th><th>Crew</th><th>Equipment</th><th>Start</th><th>End</th><th>Overtime</th><th>Why</th></tr></thead>
              <tbody>
                {schedule.map((r, i) => (
                  <tr key={i}>
                    <td>{r.task_id.slice(0, 8)}</td>
                    <td>{r.crew_member_id?.slice(0, 8) ?? '—'}</td>
                    <td>{r.equipment_id?.slice(0, 8) ?? '—'}</td>
                    <td>{new Date(r.scheduled_start).toLocaleString()}</td>
                    <td>{new Date(r.scheduled_end).toLocaleString()}</td>
                    <td>{r.is_overtime ? <span className="badge warning">{r.overtime_minutes}m OT</span> : '—'}</td>
                    <td style={{ fontSize: 12, color: 'var(--text-muted)' }}>{r.assignment_reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}

        {tab === 'crew' && (
          Object.keys(crewAlloc).length === 0 ? <div className="empty-state">No crew allocated.</div> : (
            Object.entries(crewAlloc).map(([crewId, rows]) => (
              <div key={crewId} style={{ marginBottom: 16 }}>
                <strong>{crewId.slice(0, 8)}</strong>
                <table>
                  <thead><tr><th>Task</th><th>Start</th><th>End</th><th>Overtime</th></tr></thead>
                  <tbody>
                    {rows.map((r: any, i: number) => (
                      <tr key={i}>
                        <td>{r.task_id.slice(0, 8)}</td>
                        <td>{new Date(r.start).toLocaleString()}</td>
                        <td>{new Date(r.end).toLocaleString()}</td>
                        <td>{r.is_overtime ? `${r.overtime_minutes}m` : '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))
          )
        )}

        {tab === 'equipment' && (
          Object.keys(equipAlloc).length === 0 ? <div className="empty-state">No equipment allocated.</div> : (
            Object.entries(equipAlloc).map(([equipId, rows]) => (
              <div key={equipId} style={{ marginBottom: 16 }}>
                <strong>{equipId.slice(0, 8)}</strong>
                <table>
                  <thead><tr><th>Task</th><th>Start</th><th>End</th></tr></thead>
                  <tbody>
                    {rows.map((r: any, i: number) => (
                      <tr key={i}><td>{r.task_id.slice(0, 8)}</td><td>{new Date(r.start).toLocaleString()}</td><td>{new Date(r.end).toLocaleString()}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))
          )
        )}

        {tab === 'travel' && (
          travel.length === 0 ? <div className="empty-state">No travel legs required.</div> : (
            <table>
              <thead><tr><th>Crew</th><th>From</th><th>To</th><th>Depart</th><th>Arrive</th><th>Distance</th><th>Source</th></tr></thead>
              <tbody>
                {travel.map((t, i) => (
                  <tr key={i}>
                    <td>{t.crew_member_id?.slice(0, 8) ?? '—'}</td>
                    <td>{t.from_location_id.slice(0, 8)}</td>
                    <td>{t.to_location_id.slice(0, 8)}</td>
                    <td>{new Date(t.departure_time).toLocaleString()}</td>
                    <td>{new Date(t.arrival_time).toLocaleString()}</td>
                    <td>{t.distance_km.toFixed(1)} km</td>
                    <td><span className={`badge ${t.confidence}`}>{t.confidence}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}

        {tab === 'costs' && costs && (
          <table>
            <tbody>
              {(['labour', 'overtime', 'equipment', 'fuel', 'transport', 'tolls', 'accommodation'] as const).map((k) => (
                <tr key={k}><td style={{ textTransform: 'capitalize' }}>{k}</td><td>${costs[k].toLocaleString()}</td></tr>
              ))}
              <tr><td><strong>Total</strong></td><td><strong>${costs.total.toLocaleString()}</strong></td></tr>
            </tbody>
          </table>
        )}

        {tab === 'conflicts' && (
          conflicts.length === 0 ? <div className="empty-state">No conflicts detected.</div> : (
            <table>
              <thead><tr><th>Severity</th><th>Type</th><th>Description</th><th>Suggested fix</th></tr></thead>
              <tbody>
                {conflicts.map((c, i) => (
                  <tr key={i}>
                    <td><span className={`badge ${c.severity}`}>{c.severity}</span></td>
                    <td>{c.conflict_type}</td>
                    <td>{c.description}</td>
                    <td style={{ color: 'var(--text-muted)' }}>{c.suggested_fix}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}

        {tab === 'risks' && (
          risks.length === 0 ? <div className="empty-state">No risks flagged.</div> : (
            <table>
              <thead><tr><th>Severity</th><th>Type</th><th>Description</th><th>Mitigation</th></tr></thead>
              <tbody>
                {risks.map((r, i) => (
                  <tr key={i}>
                    <td><span className={`badge ${r.severity}`}>{r.severity}</span></td>
                    <td>{r.risk_type}</td>
                    <td>{r.description}</td>
                    <td style={{ color: 'var(--text-muted)' }}>{r.mitigation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )
        )}
      </div>
    </div>
  )
}
