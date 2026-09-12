// In local dev, Vite's dev-server proxy (vite.config.ts) forwards /api to
// the backend. In a Docker Compose / static-hosting deployment there is no
// such proxy, so set VITE_API_BASE_URL at build time to the backend's
// public URL (e.g. http://localhost:8000/api/v1).
const API_BASE = (import.meta as any).env?.VITE_API_BASE_URL || '/api/v1'

const TOKEN_KEY = 'planning_agent_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function setToken(token: string | null) {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  status: number
  code: string
  details: unknown
  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken()
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> | undefined),
  }
  if (token) headers.Authorization = `Bearer ${token}`

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (resp.status === 204) return undefined as T

  const isJson = resp.headers.get('content-type')?.includes('application/json')
  const body = isJson ? await resp.json() : await resp.text()

  if (!resp.ok) {
    const message = typeof body === 'object' && body && 'message' in body ? String((body as any).message) : String(body)
    const code = typeof body === 'object' && body && 'error' in body ? String((body as any).error) : 'ERROR'
    throw new ApiError(resp.status, code, message, body)
  }
  return body as T
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: 'GET' }),
  post: <T>(path: string, data?: unknown) => request<T>(path, { method: 'POST', body: data !== undefined ? JSON.stringify(data) : undefined }),
  patch: <T>(path: string, data?: unknown) => request<T>(path, { method: 'PATCH', body: data !== undefined ? JSON.stringify(data) : undefined }),
}
