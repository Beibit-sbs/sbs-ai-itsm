import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import {
  createIntegrationImportJob,
  fetchAnalyticsOverview,
  fetchIntegrationEvents,
  fetchIntegrationImportJobs,
  fetchIntegrationMappings,
  fetchIntegrationProviders,
  fetchIntegrationRuntimeCapabilities,
  fetchIntegrationSystems,
  fetchIntegrationWebhooks,
  runIntegrationHealthCheck,
  runIntegrationTestConnection,
  runMockLdapPullUsers,
  runMockMoodlePullUsers,
  runMockPlatonusPullUsers,
  runMockWebhookReceive,
  runMockZimbraPullMailboxes,
  simulateIntegrationWebhook,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import IntegrationPlatformPanel from '../components/IntegrationPlatformPanel'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const productionTabs = [
  { key: 'control-plane', label: 'Production API & Webhooks' },
] as const

const legacyTabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'systems', label: 'Системы' },
  { key: 'providers', label: 'Провайдеры' },
  { key: 'jobs', label: 'Import Jobs' },
  { key: 'webhooks', label: 'Webhooks' },
  { key: 'events', label: 'Events' },
  { key: 'mappings', label: 'Mappings' },
  { key: 'mock', label: 'Legacy Demo / Mock' },
] as const

type TabKey =
  | (typeof productionTabs)[number]['key']
  | (typeof legacyTabs)[number]['key']

function statusBadge(status: string) {
  if (['active', 'ok', 'completed', 'accepted', 'delivered', 'healthy', 'succeeded', 'success'].includes(status)) return 'badge-positive'
  if (['degraded', 'running', 'warning', 'simulated', 'mock', 'demo', 'planned', 'future', 'logged_only', 'mocked'].includes(status)) return 'badge-warning'
  return 'badge-danger'
}

export default function IntegrationsPage() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabKey>('control-plane')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [previewResult, setPreviewResult] = useState('')
  const [actionError, setActionError] = useState('')
  const root = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const has = (permission: string) => root || permissions.has(permission)
  const canReadControlPlane = root
    || Array.from(permissions).some((permission) => permission.startsWith('integration.platform.'))
  const canAccessLegacy = root
    || Array.from(permissions).some((permission) => permission.startsWith('integrations.'))
  const canReadLegacy = has('integrations.read')
  const canReadAnalytics = has('analytics.read')
  const canReadJobs = has('integrations.import_jobs.read')
  const canRunJobs = has('integrations.import_jobs.run')
  const canReadWebhooks = has('integrations.webhooks.read')
  const canManageWebhooks = has('integrations.webhooks.manage')
  const canReadEvents = has('integrations.events.read')
  const canReadMappings = has('integrations.mappings.read')
  const canRunHealthCheck = has('integrations.health_check')
  const runtimeCapabilitiesQuery = useQuery({
    queryKey: ['integration-runtime-capabilities', session?.access_token],
    queryFn: () => fetchIntegrationRuntimeCapabilities(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && canAccessLegacy,
  })
  const legacyDemoEnabled = runtimeCapabilitiesQuery.data?.legacy_demo_enabled === true
  const tabs = useMemo(() => {
    const available: Array<{ key: TabKey; label: string }> = []
    if (canReadControlPlane) available.push(...productionTabs)
    if (!legacyDemoEnabled) return available
    for (const tab of legacyTabs) {
      if (tab.key === 'overview' && canReadAnalytics) available.push(tab)
      else if ((tab.key === 'systems' || tab.key === 'providers') && canReadLegacy) available.push(tab)
      else if (tab.key === 'jobs' && canReadJobs) available.push(tab)
      else if (tab.key === 'webhooks' && canReadWebhooks) available.push(tab)
      else if (tab.key === 'events' && canReadEvents) available.push(tab)
      else if (tab.key === 'mappings' && canReadMappings) available.push(tab)
      else if (tab.key === 'mock' && (canRunJobs || canManageWebhooks)) available.push(tab)
    }
    return available
  }, [
    canManageWebhooks,
    canAccessLegacy,
    canReadAnalytics,
    canReadControlPlane,
    canReadEvents,
    canReadJobs,
    canReadLegacy,
    canReadMappings,
    canReadWebhooks,
    canRunJobs,
    legacyDemoEnabled,
  ])

  useEffect(() => {
    if (tabs.some((tab) => tab.key === activeTab)) return
    if (tabs[0]) setActiveTab(tabs[0].key)
  }, [activeTab, tabs])

  const overviewQuery = useQuery({
    queryKey: ['integration-analytics-overview', session?.access_token],
    queryFn: () => fetchAnalyticsOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && legacyDemoEnabled && canReadAnalytics)
      && activeTab === 'overview',
  })
  const systemsQuery = useQuery({
    queryKey: ['integration-systems', session?.access_token, typeFilter, statusFilter],
    queryFn: () => fetchIntegrationSystems(session?.access_token ?? '', { system_type: typeFilter, status: statusFilter }),
    enabled: Boolean(session?.access_token && legacyDemoEnabled && canReadLegacy)
      && activeTab === 'systems',
  })
  const providersQuery = useQuery({
    queryKey: ['integration-providers', session?.access_token],
    queryFn: () => fetchIntegrationProviders(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && legacyDemoEnabled && canReadLegacy)
      && activeTab === 'providers',
  })
  const jobsQuery = useQuery({
    queryKey: ['integration-jobs', session?.access_token],
    queryFn: () => fetchIntegrationImportJobs(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && legacyDemoEnabled && canReadJobs)
      && activeTab === 'jobs',
  })
  const eventsQuery = useQuery({
    queryKey: ['integration-events', session?.access_token],
    queryFn: () => fetchIntegrationEvents(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && legacyDemoEnabled && canReadEvents)
      && activeTab === 'events',
  })
  const webhooksQuery = useQuery({
    queryKey: ['integration-webhooks', session?.access_token],
    queryFn: () => fetchIntegrationWebhooks(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && legacyDemoEnabled && canReadWebhooks)
      && activeTab === 'webhooks',
  })
  const mappingsQuery = useQuery({
    queryKey: ['integration-mappings', session?.access_token],
    queryFn: () => fetchIntegrationMappings(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && legacyDemoEnabled && canReadMappings)
      && activeTab === 'mappings',
  })

  const refetchCore = async () => {
    await queryClient.invalidateQueries({ queryKey: ['integration-systems'] })
    await queryClient.invalidateQueries({ queryKey: ['integration-events'] })
    await queryClient.invalidateQueries({ queryKey: ['integration-jobs'] })
    await queryClient.invalidateQueries({ queryKey: ['integration-analytics-overview'] })
  }

  const healthMutation = useMutation({
    mutationFn: async (systemId: string) => {
      if (!session?.access_token) throw new Error('No session')
      if (!legacyDemoEnabled || !canRunHealthCheck) {
        throw new Error('Legacy demo action is unavailable')
      }
      return runIntegrationHealthCheck(session.access_token, systemId)
    },
    onSuccess: async (data) => {
      setActionError('')
      setPreviewResult(JSON.stringify(data, null, 2))
      await refetchCore()
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Health check failed'),
  })

  const testMutation = useMutation({
    mutationFn: async (systemId: string) => {
      if (!session?.access_token) throw new Error('No session')
      if (!legacyDemoEnabled || !canRunHealthCheck) {
        throw new Error('Legacy demo action is unavailable')
      }
      return runIntegrationTestConnection(session.access_token, systemId)
    },
    onSuccess: async (data) => {
      setActionError('')
      setPreviewResult(JSON.stringify(data, null, 2))
      await refetchCore()
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Connection test failed'),
  })

  const importMutation = useMutation({
    mutationFn: async (payload: { external_system_id: string; job_type: string }) => {
      if (!session?.access_token) throw new Error('No session')
      if (!legacyDemoEnabled || !canRunJobs) {
        throw new Error('Legacy demo action is unavailable')
      }
      return createIntegrationImportJob(session.access_token, payload)
    },
    onSuccess: async (data) => {
      setActionError('')
      setPreviewResult(JSON.stringify(data, null, 2))
      await refetchCore()
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Import preview failed'),
  })

  const simulateMutation = useMutation({
    mutationFn: async (webhookId: string) => {
      if (!session?.access_token) throw new Error('No session')
      if (!legacyDemoEnabled || !canManageWebhooks) {
        throw new Error('Legacy demo action is unavailable')
      }
      return simulateIntegrationWebhook(session.access_token, webhookId, { payload: { source: 'ui-demo', severity: 'high' }, create_demo_ticket: true })
    },
    onSuccess: async (data) => {
      setActionError('')
      setPreviewResult(JSON.stringify(data, null, 2))
      await refetchCore()
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Webhook simulation failed'),
  })

  const mockActionMutation = useMutation({
    mutationFn: async (action: 'ldap' | 'zimbra' | 'platonus' | 'moodle' | 'webhook') => {
      if (!session?.access_token) throw new Error('No session')
      const canRunAction = action === 'webhook' ? canManageWebhooks : canRunJobs
      if (!legacyDemoEnabled || !canRunAction) {
        throw new Error('Legacy demo action is unavailable')
      }
      if (action === 'ldap') return runMockLdapPullUsers(session.access_token)
      if (action === 'zimbra') return runMockZimbraPullMailboxes(session.access_token, true)
      if (action === 'platonus') return runMockPlatonusPullUsers(session.access_token)
      if (action === 'moodle') return runMockMoodlePullUsers(session.access_token)
      return runMockWebhookReceive(session.access_token, true)
    },
    onSuccess: async (data) => {
      setActionError('')
      setPreviewResult(JSON.stringify(data, null, 2))
      await refetchCore()
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Mock action failed'),
  })

  const overview = overviewQuery.data?.integrations
  const systems = systemsQuery.data ?? []
  const providers = providersQuery.data ?? []
  const jobs = jobsQuery.data ?? []
  const events = eventsQuery.data ?? []
  const webhooks = webhooksQuery.data ?? []
  const mappings = mappingsQuery.data ?? []

  const systemTypes = useMemo(() => ['ALL', ...Array.from(new Set(systems.map((item) => item.system_type)))], [systems])
  const statusTypes = useMemo(() => ['ALL', ...Array.from(new Set(systems.map((item) => item.status)))], [systems])

  return (
    <LocalizedContent><AppShell
      title="Интеграции"
      subtitle={legacyDemoEnabled
        ? 'Production control plane и локальные demo/mock-сценарии.'
        : 'Production API, service accounts, webhooks, delivery history и DLQ.'}
    >
      <nav className="module-subnav" aria-label="Integrations navigation">
        {tabs.map((tab) => (
          <button type="button" className={`module-subnav-tab ${activeTab === tab.key ? 'active' : ''}`} key={tab.key} onClick={() => setActiveTab(tab.key)}>
            {translate(tab.label)}
          </button>
        ))}
      </nav>

      {!runtimeCapabilitiesQuery.isPending && !legacyDemoEnabled ? (
        <p className="state-panel state-panel-neutral">
          Legacy demo/mock-коннекторы отключены. Production API, service
          accounts, исходящие webhooks, delivery history и DLQ доступны в
          рабочей панели.
        </p>
      ) : null}

      <QueryFailureNotice
        title="Часть данных Integration Operations недоступна."
        sources={[
          { label: 'runtime capabilities', query: runtimeCapabilitiesQuery },
          { label: translate('оперативная сводка'), query: overviewQuery },
          { label: translate('системы'), query: systemsQuery },
          { label: translate('провайдеры'), query: providersQuery },
          { label: 'import jobs', query: jobsQuery },
          { label: 'integration events', query: eventsQuery },
          { label: 'webhooks', query: webhooksQuery },
          { label: 'field mappings', query: mappingsQuery },
        ]}
      />
      {actionError ? <p className="error-state">{actionError}</p> : null}

      <section className="module-content">

      {activeTab === 'control-plane' ? <IntegrationPlatformPanel /> : null}

      {legacyDemoEnabled && activeTab === 'overview' ? (
        <>
        <section className="module-overview-grid">
          <article className="metric-card"><span>Активные системы</span><strong>{overviewQuery.isPending ? '…' : overview?.enabled_systems ?? 0}</strong><p>Активные connectors.</p></article>
          <article className="metric-card"><span>Системы с ошибками</span><strong>{overviewQuery.isPending ? '…' : overview?.systems_with_errors ?? 0}</strong><p>Ошибки health/status.</p></article>
          <article className="metric-card"><span>События</span><strong>{overviewQuery.isPending ? '…' : overview?.integration_events_count ?? 0}</strong><p>Всего integration events.</p></article>
          <article className="metric-card"><span>Успешность импорта</span><strong>{overviewQuery.isPending ? '…' : `${overview?.import_success_rate ?? 0}%`}</strong><p>Доля успешной mock-обработки.</p></article>
        </section>
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">SYSTEM LANDSCAPE</p>
            <h2>Статусы систем</h2>
            <div className="mini-bars">
              {(overview?.systems_by_status ?? []).map((item) => (
                <div className="mini-bar-row" key={item.status}>
                  <span>{item.status}</span>
                  <div className="mini-bar-track"><div className="mini-bar-fill" style={{ width: `${Math.max(10, item.count * 15)}%` }} /></div>
                  <strong>{item.count}</strong>
                </div>
              ))}
            </div>
          </div>
          <div>
            <p className="eyebrow">RECENT EVENTS</p>
            <h2>Последние integration события</h2>
            <div className="activity-list">
              {overviewQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка событий…</p> : null}
              {!overviewQuery.isPending && (overview?.recent_integration_events ?? []).length === 0 ? <p className="state-panel state-panel-empty">События интеграций пока отсутствуют.</p> : null}
              {(overview?.recent_integration_events ?? []).map((item) => (
                <article className="activity-item" key={item.id}>
                  <header><strong>{item.event_type}</strong><span className={`badge ${statusBadge(item.status)}`}>{item.status}</span></header>
                  <p>{item.correlation_id ?? 'No correlation id'}</p>
                  <small>{formatDateTime(item.created_at)}</small>
                </article>
              ))}
            </div>
          </div>
        </section>
        </>
      ) : null}

      {legacyDemoEnabled && activeTab === 'systems' ? (
        <>
          <section className="foundation-card table-toolbar">
            <div className="tickets-toolbar-group">
              <label className="inline-field">
                <span>Тип</span>
                <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
                  {systemTypes.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
              <label className="inline-field">
                <span>Статус</span>
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  {statusTypes.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </label>
            </div>
          </section>
          <section className="section-card">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead><tr><th>Система</th><th>Тип</th><th>Статус</th><th>Проверка</th><th>Возможности</th><th /></tr></thead>
                <tbody>
                  {systemsQuery.isPending ? <tr><td colSpan={6}><p className="state-panel state-panel-loading">Загрузка систем…</p></td></tr> : null}
                  {!systemsQuery.isPending && systems.length === 0 ? <tr><td colSpan={6}><p className="state-panel state-panel-empty">Системы по фильтрам не найдены.</p></td></tr> : null}
                  {systems.map((item) => (
                    <tr key={item.id}>
                      <td><strong>{item.name}</strong><p className="table-subtext">{item.code}</p></td>
                      <td>{item.system_type}</td>
                      <td><span className={`badge ${statusBadge(item.status)}`}>{item.status}</span></td>
                      <td>{item.last_health_status ?? '—'}<p className="table-subtext">{formatDateTime(item.last_health_checked_at)}</p></td>
                      <td>{item.capabilities.join(', ')}</td>
                      <td>
                        <div className="analytics-actions">
                          {canRunHealthCheck ? <button type="button" className="ghost-button" onClick={() => healthMutation.mutate(item.id)} disabled={healthMutation.isPending || testMutation.isPending || importMutation.isPending}>Health check</button> : null}
                          {canRunHealthCheck ? <button type="button" className="ghost-button" onClick={() => testMutation.mutate(item.id)} disabled={healthMutation.isPending || testMutation.isPending || importMutation.isPending}>Тест подключения</button> : null}
                          {canRunJobs && (item.system_type === 'ldap' || item.system_type === 'zimbra' || item.system_type === 'platonus' || item.system_type === 'moodle') ? (
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() => {
                                const confirmed = window.confirm(`${item.name}: ${translate('Запустить import preview?')}`)
                                if (!confirmed) return
                                importMutation.mutate({ external_system_id: item.id, job_type: `${item.system_type}_preview` })
                              }}
                              disabled={healthMutation.isPending || testMutation.isPending || importMutation.isPending}
                            >
                              Preview импорта
                            </button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}

      {legacyDemoEnabled && activeTab === 'providers' ? (
        <section className="section-card dashboard-split">
          <div>
            <p className="eyebrow">PROVIDER REGISTRY</p>
            <h2>Провайдеры</h2>
            <div className="activity-list">
              {providersQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка провайдеров…</p> : null}
              {!providersQuery.isPending && providers.length === 0 ? <p className="state-panel state-panel-empty">Провайдеры не найдены.</p> : null}
              {providers.map((item) => (
                <article className="activity-item" key={item.code}>
                  <header><strong>{item.name}</strong><span className={`badge ${statusBadge(item.status)}`}>{item.status}</span></header>
                  <p>{item.capabilities.join(', ')}</p>
                </article>
              ))}
            </div>
          </div>
          <div>
            <p className="eyebrow">READINESS</p>
            <h2>Mock / planned / future</h2>
            <div className="mini-bars">
              {['mock', 'planned', 'future'].map((status) => {
                const count = providers.filter((item) => item.status === status).length
                return (
                  <div className="mini-bar-row" key={status}>
                    <span>{status}</span>
                    <div className="mini-bar-track"><div className="mini-bar-fill" style={{ width: `${Math.max(10, count * 20)}%` }} /></div>
                    <strong>{count}</strong>
                  </div>
                )
              })}
            </div>
          </div>
        </section>
      ) : null}

      {legacyDemoEnabled && activeTab === 'jobs' ? (
        <section className="section-card">
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Job type</th><th>Status</th><th>Total</th><th>Success</th><th>Failed</th><th>Started</th><th>Finished</th><th>Error</th></tr></thead>
              <tbody>
                {jobsQuery.isPending ? <tr><td colSpan={8}><p className="state-panel state-panel-loading">Загрузка import jobs…</p></td></tr> : null}
                {!jobsQuery.isPending && jobs.length === 0 ? <tr><td colSpan={8}><p className="state-panel state-panel-empty">Import jobs отсутствуют.</p></td></tr> : null}
                {jobs.map((item) => (
                  <tr key={item.id}>
                    <td>{item.job_type}</td>
                    <td><span className={`badge ${statusBadge(item.status)}`}>{item.status}</span></td>
                    <td>{item.records_total}</td>
                    <td>{item.records_success}</td>
                    <td>{item.records_failed}</td>
                    <td>{formatDateTime(item.started_at)}</td>
                    <td>{formatDateTime(item.finished_at)}</td>
                    <td>{item.error_message ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {legacyDemoEnabled && activeTab === 'webhooks' ? (
        <section className="section-card">
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Name</th><th>Path</th><th>Target</th><th>Status</th><th>Secret ref</th><th /></tr></thead>
              <tbody>
                {webhooksQuery.isPending ? <tr><td colSpan={6}><p className="state-panel state-panel-loading">Загрузка webhooks…</p></td></tr> : null}
                {!webhooksQuery.isPending && webhooks.length === 0 ? <tr><td colSpan={6}><p className="state-panel state-panel-empty">Webhook endpoints отсутствуют.</p></td></tr> : null}
                {webhooks.map((item) => (
                  <tr key={item.id}>
                    <td>{item.name}</td>
                    <td>{item.path}</td>
                    <td>{item.target_system}</td>
                    <td><span className={`badge ${item.is_active ? 'badge-positive' : 'badge-danger'}`}>{item.is_active ? 'active' : 'inactive'}</span></td>
                    <td>{item.secret_ref ?? '—'}</td>
                    <td>{canManageWebhooks ? <button type="button" className="ghost-button" onClick={() => {
                      const confirmed = window.confirm(`${item.name}: ${translate('Симулировать webhook?')}`)
                      if (!confirmed) return
                      simulateMutation.mutate(item.id)
                    }} disabled={simulateMutation.isPending}>Simulate</button> : null}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {legacyDemoEnabled && activeTab === 'events' ? (
        <section className="section-card">
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Date</th><th>Direction</th><th>Type</th><th>Status</th><th>External system</th><th>Correlation</th><th>Error</th></tr></thead>
              <tbody>
                {eventsQuery.isPending ? <tr><td colSpan={7}><p className="state-panel state-panel-loading">Загрузка integration events…</p></td></tr> : null}
                {!eventsQuery.isPending && events.length === 0 ? <tr><td colSpan={7}><p className="state-panel state-panel-empty">Integration events отсутствуют.</p></td></tr> : null}
                {events.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.direction}</td>
                    <td>{item.event_type}</td>
                    <td><span className={`badge ${statusBadge(item.status)}`}>{item.status}</span></td>
                    <td>{item.external_system_id ?? 'custom'}</td>
                    <td>{item.correlation_id ?? '—'}</td>
                    <td>{item.error_message ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {legacyDemoEnabled && activeTab === 'mappings' ? (
        <section className="section-card">
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Source</th><th>Target</th><th>External system</th><th>Mapping</th><th>Status</th></tr></thead>
              <tbody>
                {mappingsQuery.isPending ? <tr><td colSpan={5}><p className="state-panel state-panel-loading">Загрузка mappings…</p></td></tr> : null}
                {!mappingsQuery.isPending && mappings.length === 0 ? <tr><td colSpan={5}><p className="state-panel state-panel-empty">Mapping-конфигурации отсутствуют.</p></td></tr> : null}
                {mappings.map((item) => (
                  <tr key={item.id}>
                    <td>{item.source_entity}</td>
                    <td>{item.target_entity}</td>
                    <td>{item.external_system_id ?? '—'}</td>
                    <td><pre className="mapping-preview">{JSON.stringify(item.mapping_json, null, 2)}</pre></td>
                    <td><span className={`badge ${item.is_active ? 'badge-positive' : 'badge-danger'}`}>{item.is_active ? 'active' : 'inactive'}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {legacyDemoEnabled && activeTab === 'mock' ? (
        <section className="section-card dashboard-split">
          <div>
            <p className="eyebrow">MOCK ACTIONS</p>
            <h2>Preview сценарии</h2>
            <div className="analytics-actions">
              {canRunJobs ? <button type="button" onClick={() => mockActionMutation.mutate('ldap')} disabled={mockActionMutation.isPending}>Pull LDAP users</button> : null}
              {canRunJobs ? <button type="button" onClick={() => mockActionMutation.mutate('zimbra')} disabled={mockActionMutation.isPending}>Pull Zimbra mailboxes</button> : null}
              {canRunJobs ? <button type="button" onClick={() => mockActionMutation.mutate('platonus')} disabled={mockActionMutation.isPending}>Pull Platonus users</button> : null}
              {canRunJobs ? <button type="button" onClick={() => mockActionMutation.mutate('moodle')} disabled={mockActionMutation.isPending}>Pull Moodle users</button> : null}
              {canManageWebhooks ? <button type="button" onClick={() => mockActionMutation.mutate('webhook')} disabled={mockActionMutation.isPending}>Simulate webhook event</button> : null}
            </div>
          </div>
          <div>
            <p className="eyebrow">PREVIEW RESULT</p>
            <h2>Последний mock ответ</h2>
            <pre className="analytics-export-preview">{previewResult || 'Результат появится после запуска mock action.'}</pre>
          </div>
        </section>
      ) : null}
      </section>
    </AppShell></LocalizedContent>
  )
}
