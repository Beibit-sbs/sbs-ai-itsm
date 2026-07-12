import { Navigate, Route, Routes } from 'react-router-dom'
import RequireAuth from './auth/RequireAuth'
import LoginPage from './pages/LoginPage'
import DashboardPage from './pages/DashboardPage'
import AdminPage from './pages/AdminPage'
import AdminSystemPage from './pages/AdminSystemPage'
import IntegrationsPage from './pages/IntegrationsPage'
import AssetsPage from './pages/AssetsPage'
import TicketsPage from './pages/TicketsPage'
import SlaPage from './pages/SlaPage'
import CopilotPage from './pages/CopilotPage'
import KnowledgePage from './pages/KnowledgePage'
import NotificationsPage from './pages/NotificationsPage'
import EmailLogPage from './pages/EmailLogPage'
import AnalyticsPage from './pages/AnalyticsPage'
import AutomationPage from './pages/AutomationPage'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      <Route
        path="/tickets"
        element={
          <RequireAuth>
            <TicketsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/integrations"
        element={
          <RequireAuth>
            <IntegrationsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/assets"
        element={
          <RequireAuth>
            <AssetsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/sla"
        element={
          <RequireAuth>
            <SlaPage />
          </RequireAuth>
        }
      />
      <Route
        path="/knowledge"
        element={
          <RequireAuth>
            <KnowledgePage />
          </RequireAuth>
        }
      />
      <Route
        path="/copilot"
        element={
          <RequireAuth>
            <CopilotPage />
          </RequireAuth>
        }
      />
      <Route
        path="/notifications"
        element={
          <RequireAuth>
            <NotificationsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/notifications/email-log"
        element={
          <RequireAuth>
            <EmailLogPage />
          </RequireAuth>
        }
      />
      <Route
        path="/analytics"
        element={
          <RequireAuth>
            <AnalyticsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/automation"
        element={
          <RequireAuth>
            <AutomationPage />
          </RequireAuth>
        }
      />
      <Route
        path="/admin"
        element={
          <RequireAuth>
            <AdminPage />
          </RequireAuth>
        }
      />
      <Route
        path="/admin/system"
        element={
          <RequireAuth>
            <AdminSystemPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}