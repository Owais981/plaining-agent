export interface Project {
  id: string
  code: string
  name: string
  client_id: string | null
  start_date: string
  end_date: string
  deadline: string | null
  priority: number
  budget_total: number | null
  currency: string
  status: string
}

export interface CrewMember {
  id: string
  employee_code: string
  full_name: string
  primary_role_id: string
  home_location_id: string | null
  standard_rate: number
  overtime_rate: number
  is_active: boolean
}

export interface EquipmentItem {
  id: string
  asset_code: string
  name: string
  category_id: string
  current_location_id: string | null
  daily_operating_cost: number | null
  ownership: string
  is_active: boolean
}

export interface Location {
  id: string
  name: string
  address: string
  latitude: number
  longitude: number
  site_type: string
}

export interface JobStatus {
  status: 'queued' | 'running' | 'done' | 'error'
  stage?: string
  plan_id?: string
  result?: PlanSummary
  error?: string
}

export interface PlanSummary {
  plan_id: string
  status: string
  objective_value?: number
  solve_seconds?: number
  total_cost?: number
  schedule?: ScheduleEntry[]
  blocking_constraints?: string[]
  suggestions?: string[]
}

export interface ScheduleEntry {
  task_id: string
  start: string
  end: string
  crew: string[]
  equipment: string[]
}

export interface Plan {
  id: string
  project_id: string
  version: number
  scenario_label: string
  status: string
  solver_status: string | null
  objective_value: number | null
  total_cost: number | null
  total_travel_km: number | null
  total_overtime_hrs: number | null
  solve_seconds: number | null
  parent_plan_id: string | null
  stale: boolean
  created_at: string
}

export interface Conflict {
  severity: 'critical' | 'warning' | 'info'
  conflict_type: string
  entity_type: string | null
  entity_id: string | null
  description: string
  suggested_fix: string
}

export interface Risk {
  risk_type: string
  severity: 'high' | 'medium' | 'low'
  entity_type: string | null
  entity_id: string | null
  description: string
  mitigation: string
}

export interface CostBreakdown {
  labour: number
  overtime: number
  equipment: number
  fuel: number
  transport: number
  tolls: number
  accommodation: number
  total: number
}

export interface TravelLegOut {
  crew_member_id: string | null
  from_location_id: string
  to_location_id: string
  departure_time: string
  arrival_time: string
  distance_km: number
  transport_mode: string
  estimated_cost: number | null
  data_source: string
  confidence: 'measured' | 'estimated'
}

export interface ChatToolCall {
  tool: string
  status: 'ok' | 'error'
}

export interface ChatResponse {
  response: string
  tool_calls: ChatToolCall[]
}
