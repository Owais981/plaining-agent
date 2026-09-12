import React, { createContext, useContext, useState } from 'react'
import { api, setToken, getToken } from './api/client'

interface AuthState {
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, role: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(!!getToken())

  async function login(email: string, password: string) {
    const res = await api.post<{ access_token: string }>('/auth/login', { email, password })
    setToken(res.access_token)
    setIsAuthenticated(true)
  }

  async function register(email: string, password: string, role: string) {
    const res = await api.post<{ access_token: string }>('/auth/register', { email, password, role })
    setToken(res.access_token)
    setIsAuthenticated(true)
  }

  function logout() {
    setToken(null)
    setIsAuthenticated(false)
  }

  return <AuthContext.Provider value={{ isAuthenticated, login, register, logout }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
