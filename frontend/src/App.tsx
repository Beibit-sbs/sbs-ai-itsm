import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import RequireAuth from './auth/RequireAuth'
import { useTenantExperience } from './experience/TenantExperienceContext'
import LoginPage from './pages/LoginPage'

const DashboardPage = lazy(() => import('./pages/DashboardPage'))
const AccountPage = lazy(() => import('./pages/AccountPage'))
const MonitoringPage = lazy(() => import('./pages/MonitoringPage'))
const EventOperationsPage = lazy(() => import('./pages/EventOperationsPage'))
const AdminPage = lazy(() => import('./pages/AdminPage'))
const AdminSystemPage = lazy(() => import('./pages/AdminSystemPage'))
const DataGovernancePage = lazy(() => import('./pages/DataGovernancePage'))
const IntegrationsPage = lazy(() => import('./pages/IntegrationsPage'))
const AssetsPage = lazy(() => import('./pages/AssetsPage'))
const SoftwareAssetsPage = lazy(() => import('./pages/SoftwareAssetsPage'))
const TicketsPage = lazy(() => import('./pages/TicketsPage'))
const MajorIncidentsPage = lazy(() => import('./pages/MajorIncidentsPage'))
const ChangesPage = lazy(() => import('./pages/ChangesPage'))
const ChangeGovernancePage = lazy(() => import('./pages/ChangeGovernancePage'))
const ReleasesPage = lazy(() => import('./pages/ReleasesPage'))
const ProblemsPage = lazy(() => import('./pages/ProblemsPage'))
const ProblemGovernancePage = lazy(() => import('./pages/ProblemGovernancePage'))
const CatalogPage = lazy(() => import('./pages/CatalogPage'))
const RequestsPage = lazy(() => import('./pages/RequestsPage'))
const SlaPage = lazy(() => import('./pages/SlaPage'))
const CopilotPage = lazy(() => import('./pages/CopilotPage'))
const KnowledgePage = lazy(() => import('./pages/KnowledgePage'))
const NotificationsPage = lazy(() => import('./pages/NotificationsPage'))
const EmailLogPage = lazy(() => import('./pages/EmailLogPage'))
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'))
const AutomationPage = lazy(() => import('./pages/AutomationPage'))
const IdentityProvisioningPage = lazy(() => import('./pages/IdentityProvisioningPage'))
const EmailOperationsPage = lazy(() => import('./pages/EmailOperationsPage'))
const TeamsCollaborationPage = lazy(() => import('./pages/TeamsCollaborationPage'))
const CustomFieldsPage = lazy(() => import('./pages/CustomFieldsPage'))
const ConfigurationPackagesPage = lazy(
  () => import('./pages/ConfigurationPackagesPage'),
)

export default function App() {
  const { t } = useTenantExperience()

  return (
    <Suspense fallback={<div className="page-loading" role="status" aria-live="polite">{t('app.loadingWorkspace')}</div>}>
      <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/account"
        element={
          <RequireAuth>
            <AccountPage />
          </RequireAuth>
        }
      />
      <Route
        path="/dashboard"
        element={
          <RequireAuth>
            <DashboardPage />
          </RequireAuth>
        }
      />
      <Route
        path="/monitoring"
        element={
          <RequireAuth>
            <MonitoringPage />
          </RequireAuth>
        }
      />
      <Route
        path="/events"
        element={
          <RequireAuth>
            <EventOperationsPage />
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
        path="/major-incidents"
        element={
          <RequireAuth>
            <MajorIncidentsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/catalog"
        element={
          <RequireAuth>
            <CatalogPage />
          </RequireAuth>
        }
      />
      <Route
        path="/requests"
        element={
          <RequireAuth>
            <RequestsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/changes"
        element={
          <RequireAuth>
            <ChangesPage />
          </RequireAuth>
        }
      />
      <Route
        path="/change-calendar"
        element={
          <RequireAuth>
            <ChangeGovernancePage />
          </RequireAuth>
        }
      />
      <Route
        path="/releases"
        element={
          <RequireAuth>
            <ReleasesPage />
          </RequireAuth>
        }
      />
      <Route
        path="/problems"
        element={
          <RequireAuth>
            <ProblemsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/problem-governance"
        element={
          <RequireAuth>
            <ProblemGovernancePage />
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
        path="/software-assets"
        element={
          <RequireAuth>
            <SoftwareAssetsPage />
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
      <Route
        path="/admin/data-governance"
        element={
          <RequireAuth>
            <DataGovernancePage />
          </RequireAuth>
        }
      />
      <Route
        path="/identity-provisioning"
        element={
          <RequireAuth>
            <IdentityProvisioningPage />
          </RequireAuth>
        }
      />
      <Route
        path="/email-operations"
        element={
          <RequireAuth>
            <EmailOperationsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/teams-collaboration"
        element={
          <RequireAuth>
            <TeamsCollaborationPage />
          </RequireAuth>
        }
      />
      <Route
        path="/admin/custom-fields"
        element={
          <RequireAuth>
            <CustomFieldsPage />
          </RequireAuth>
        }
      />
      <Route
        path="/admin/configuration-packages"
        element={
          <RequireAuth>
            <ConfigurationPackagesPage />
          </RequireAuth>
        }
      />
      <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </Suspense>
  )
}
