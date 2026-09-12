import React from 'react'
import { BrowserRouter, Routes, Route, Navigate, NavLink } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Projects from './pages/Projects'
import ProjectDetail from './pages/ProjectDetail'
import Crew from './pages/Crew'
import Equipment from './pages/Equipment'
import PlanningChat from './pages/PlanningChat'
import PlanView from './pages/PlanView'

function Shell({ children }: { children: React.ReactNode }) {
  const { logout } = useAuth()
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <h1>Crew &amp; Equipment
          <br />Planning Agent</h1>
        <nav>
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/projects">Projects</NavLink>
          <NavLink to="/crew">Crew</NavLink>
          <NavLink to="/equipment">Equipment</NavLink>
          <NavLink to="/chat">Planning Chat</NavLink>
        </nav>
      </aside>
      <main className="main">
        <div className="topbar">
          <div />
          <button className="secondary" onClick={logout}>Sign out</button>
        </div>
        {children}
      </main>
    </div>
  )
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { isAuthenticated } = useAuth()
  if (!isAuthenticated) return <Navigate to="/login" replace />
  return <Shell>{children}</Shell>
}

export default function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
          <Route path="/projects" element={<RequireAuth><Projects /></RequireAuth>} />
          <Route path="/projects/:projectId" element={<RequireAuth><ProjectDetail /></RequireAuth>} />
          <Route path="/crew" element={<RequireAuth><Crew /></RequireAuth>} />
          <Route path="/equipment" element={<RequireAuth><Equipment /></RequireAuth>} />
          <Route path="/chat" element={<RequireAuth><PlanningChat /></RequireAuth>} />
          <Route path="/plans/:planId" element={<RequireAuth><PlanView /></RequireAuth>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  )
}
