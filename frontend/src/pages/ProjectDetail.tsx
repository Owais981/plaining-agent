import React, { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import { Project, JobStatus } from '../types'

interface TaskOut {
  id: string
  name: string
  duration_minutes: number
  earliest_start: string | null
  latest_finish: string | null
  status: string
}

const STAGE_LABELS: Record<string, string> = {
  queued: 'Queued…',
  validating_planning_data: 'Validating planning data…',
  building_travel_matrix: 'Building travel matrix…',
  verifying_conflicts: 'Verifying conflicts…',
  assessing_risks: 'Assessing risks…',
  complete: 'Complete',
  failed: 'Failed',
}

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [tasks, setTasks] = useState<TaskOut[]>([])
  const [job, setJob] = useState<JobStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [profile, setProfile] = useState('balanced')
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    if (!projectId) return
    api.get<Project>(`/projects/${projectId}`).then(setProject).catch(() => setProject(null))
    api.get<TaskOut[]>(`/tasks?project_id=${projectId}`).then(setTasks).catch(() => setTasks([]))
    return () => { if (pollRef.current) window.clearInterval(pollRef.current) }
  }, [projectId])

  async function runOptimize() {
    if (!projectId) return
    setError(null)
    setJob({ status: 'queued', stage: 'queued' })
    try {
      const res = await api.post<{ job_id: string }>('/plans/optimize', { project_id: projectId, objective_profile: profile })
      pollRef.current = window.setInterval(async () => {
        try {
          const status = await api.get<JobStatus>(`/jobs/${res.job_id}`)
          setJob(status)
          if (status.status === 'done' || status.status === 'error') {
            if (pollRef.current) window.clearInterval(pollRef.current)
            if (status.status === 'done' && status.result?.plan_id && status.result.status !== 'INFEASIBLE') {
              navigate(`/plans/${status.result.plan_id}`)
            }
          }
        } catch {
          if (pollRef.current) window.clearInterval(pollRef.current)
        }
      }, 800)
    } catch (err) {
      setError(err instanceof ApiError ? err.message + (err.details && (err.details as any).details?.missing ? `: ${(err.details as any).details.missing.join(', ')}` : '') : 'Failed to submit optimization')
      setJob(null)
    }
  }

  if (!project) return <p>Loading…</p>

  return (
    <div>
      <div className="topbar">
        <h2 style={{ margin: 0 }}>{project.name} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({project.code})</span></h2>
      </div>

      <div className="card">
        <div className="grid">
          <div className="stat"><span className="value">{project.status}</span><span className="label">Status</span></div>
          <div className="stat"><span className="value">{project.start_date} → {project.end_date}</span><span className="label">Dates</span></div>
          <div className="stat"><span className="value">{project.budget_total ? `${project.currency} ${project.budget_total.toLocaleString()}` : '—'}</span><span className="label">Budget</span></div>
          <div className="stat"><span className="value">{tasks.length}</span><span className="label">Tasks</span></div>
        </div>
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Run optimization</h3>
        {error && <div className="error-banner">{error}</div>}
        <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 10 }}>
          <select value={profile} onChange={(e) => setProfile(e.target.value)}>
            <option value="balanced">Balanced</option>
            <option value="minimize_cost">Minimize cost</option>
            <option value="minimize_travel">Minimize travel</option>
            <option value="minimize_overtime">Minimize overtime</option>
            <option value="earliest_finish">Earliest finish</option>
          </select>
          <button onClick={runOptimize} disabled={job?.status === 'queued' || job?.status === 'running'}>
            {job?.status === 'queued' || job?.status === 'running' ? 'Optimizing…' : 'Optimize schedule'}
          </button>
        </div>
        {job && (
          <p style={{ fontSize: 13, color: 'var(--text-muted)' }}>
            {STAGE_LABELS[job.stage ?? ''] ?? job.stage}
          </p>
        )}
        {job?.status === 'done' && job.result?.status === 'INFEASIBLE' && (
          <div className="error-banner">
            <strong>No feasible plan found.</strong>
            <ul>{job.result.blocking_constraints?.slice(0, 6).map((b, i) => <li key={i}>{b}</li>)}</ul>
            {job.result.suggestions && job.result.suggestions.length > 0 && (
              <>
                <strong>Suggestions:</strong>
                <ul>{job.result.suggestions.slice(0, 6).map((s, i) => <li key={i}>{s}</li>)}</ul>
              </>
            )}
          </div>
        )}
        {job?.status === 'error' && <div className="error-banner">{job.error}</div>}
      </div>

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Tasks</h3>
        {tasks.length === 0 ? (
          <div className="empty-state">No tasks defined yet.</div>
        ) : (
          <table>
            <thead><tr><th>Name</th><th>Duration</th><th>Window</th><th>Status</th></tr></thead>
            <tbody>
              {tasks.map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td>{(t.duration_minutes / 60).toFixed(1)}h</td>
                  <td>{t.earliest_start ? new Date(t.earliest_start).toLocaleString() : '—'} → {t.latest_finish ? new Date(t.latest_finish).toLocaleString() : '—'}</td>
                  <td><span className="badge info">{t.status}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
