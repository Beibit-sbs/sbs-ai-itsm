import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import {
  createReportSnapshot,
  createSavedReport,
  fetchAiAnalytics,
  fetchAnalyticsOverview,
  fetchAssetAnalytics,
  fetchAutomationAnalytics,
  fetchDemoExport,
  fetchExecutiveSummary,
  fetchKnowledgeAnalytics,
  fetchReportSnapshots,
  fetchSavedReports,
  fetchSecurityAnalytics,
  fetchSlaAnalytics,
  fetchTicketAnalytics,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'

const tabs = [
  { key: 'executive', label: 'Executive' },
  { key: 'tickets', label: 'Tickets' },
  { key: 'sla', label: 'SLA' },
  { key: 'assets', label: 'Assets' },
  { key: 'knowledge', label: 'Knowledge' },
  { key: 'ai', label: 'AI' },
  { key: 'security', label: 'Security' },
  { key: 'automation', label: 'Automation' },
  { key: 'reports', label: 'Reports' },
] as const

type TabKey = (typeof tabs)[number]['key']

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function scoreTone(value: number) {
  if (value >= 80) return 'badge-positive'
  if (value >= 60) return 'badge-warning'
  return 'badge-danger'
}

export default function AnalyticsPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabKey>('executive')
  const [exportPayload, setExportPayload] = useState<string>('')

  const overviewQuery = useQuery({
    queryKey: ['analytics-overview', session?.access_token],
    queryFn: () => fetchAnalyticsOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const executiveQuery = useQuery({
    queryKey: ['analytics-executive', session?.access_token],
    queryFn: () => fetchExecutiveSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const ticketQuery = useQuery({
    queryKey: ['analytics-tickets', session?.access_token],
    queryFn: () => fetchTicketAnalytics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const slaQuery = useQuery({
    queryKey: ['analytics-sla', session?.access_token],
    queryFn: () => fetchSlaAnalytics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const assetQuery = useQuery({
    queryKey: ['analytics-assets', session?.access_token],
    queryFn: () => fetchAssetAnalytics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const knowledgeQuery = useQuery({
    queryKey: ['analytics-knowledge', session?.access_token],
    queryFn: () => fetchKnowledgeAnalytics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const aiQuery = useQuery({
    queryKey: ['analytics-ai', session?.access_token],
    queryFn: () => fetchAiAnalytics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const automationQuery = useQuery({
    queryKey: ['analytics-automation', session?.access_token],
    queryFn: () => fetchAutomationAnalytics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const securityQuery = useQuery({
    queryKey: ['analytics-security', session?.access_token],
    queryFn: () => fetchSecurityAnalytics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const savedReportsQuery = useQuery({
    queryKey: ['reports-saved', session?.access_token],
    queryFn: () => fetchSavedReports(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const snapshotsQuery = useQuery({
    queryKey: ['reports-snapshots', session?.access_token],
    queryFn: () => fetchReportSnapshots(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const createSnapshotMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      return createReportSnapshot(session.access_token, { report_type: 'executive' })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['reports-snapshots'] })
    },
  })

  const createSavedMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      return createSavedReport(session.access_token, {
        name: 'Executive Pulse Report',
        report_type: 'executive',
        filters_json: { period: '30d', scope: 'executive' },
      })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['reports-saved'] })
    },
  })

  const exportMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      return fetchDemoExport(session.access_token, { report_type: 'overview', format: 'csv' })
    },
    onSuccess: (data) => {
      setExportPayload(JSON.stringify(data.payload, null, 2))
    },
  })

  const overview = overviewQuery.data
  const executive = executiveQuery.data
  const tickets = ticketQuery.data
  const sla = slaQuery.data
  const assets = assetQuery.data
  const knowledge = knowledgeQuery.data
  const ai = aiQuery.data
  const automation = automationQuery.data
  const security = securityQuery.data
  const hasTabError =
    overviewQuery.isError ||
    executiveQuery.isError ||
    ticketQuery.isError ||
    slaQuery.isError ||
    assetQuery.isError ||
    aiQuery.isError ||
    knowledgeQuery.isError ||
    automationQuery.isError ||
    securityQuery.isError

  return (
    <AppShell title="Аналитика" subtitle="Управленческие метрики по заявкам, SLA, активам, AI, безопасности и автоматизации.">
      <nav className="module-subnav" aria-label="Analytics navigation">
        {tabs.map((tab) => (
          <button type="button" className={`module-subnav-tab ${activeTab === tab.key ? 'active' : ''}`} key={tab.key} onClick={() => setActiveTab(tab.key)}>
            {tab.label}
          </button>
        ))}
      </nav>

      {hasTabError ? <p className="error-state">Часть аналитических данных временно недоступна. Повторите загрузку.</p> : null}

      <section className="module-content">

      {activeTab === 'executive' ? (
        <>
        <section className="module-overview-grid">
          <article className="metric-card"><span>Health score</span><strong>{executiveQuery.isPending ? '…' : executive?.health_score ?? 0}</strong><p>Сводный health score.</p></article>
          <article className="metric-card"><span>SLA compliance</span><strong>{overviewQuery.isPending ? '…' : `${overview?.sla.sla_compliance_percent ?? 0}%`}</strong><p>Соблюдение SLA.</p></article>
          <article className="metric-card"><span>Open critical</span><strong>{ticketQuery.isPending ? '…' : tickets?.open_critical_tickets ?? 0}</strong><p>Критические заявки.</p></article>
          <article className="metric-card"><span>Security risk</span><strong>{executiveQuery.isPending ? '…' : executive?.security_risk_score ?? 0}</strong><p>Риск безопасности.</p></article>
        </section>
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">SCORES</p>
            <h2>Executive scorecard</h2>
            <div className="analytics-score-grid">
              {[
                ['Health score', executive?.health_score ?? 0],
                ['IT workload', executive?.it_workload_score ?? 0],
                ['SLA risk', executive?.sla_risk_score ?? 0],
                ['Asset risk', executive?.asset_risk_score ?? 0],
                ['Security risk', executive?.security_risk_score ?? 0],
                ['AI maturity', executive?.ai_maturity_score ?? 0],
                ['Integrations health', executive?.integrations_health_score ?? 0],
              ].map(([label, value]) => (
                <article className="score-card" key={String(label)}>
                  <header>
                    <span>{label}</span>
                    <strong className={scoreTone(Number(value))}>{value}</strong>
                  </header>
                  <div className="progress-strip">
                    <div className="progress-strip-fill" style={{ width: `${Math.max(6, Number(value))}%` }} />
                  </div>
                </article>
              ))}
            </div>
          </div>
          <div>
            <p className="eyebrow">RECOMMENDATIONS</p>
            <h2>Рекомендации руководителю</h2>
            <div className="activity-list">
              {executiveQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка рекомендаций…</p> : null}
              {!executiveQuery.isPending && (executive?.top_5_recommendations ?? []).length === 0 ? <p className="state-panel state-panel-empty">Рекомендации отсутствуют.</p> : null}
              {(executive?.top_5_recommendations ?? []).map((item) => (
                <article className="activity-item" key={item}>
                  <p>{item}</p>
                </article>
              ))}
            </div>
            <p className="eyebrow analytics-subsection">INTEGRATIONS SNAPSHOT</p>
            <div className="status-list analytics-inline-list">
              <span>Health score: {overview?.integrations.integrations_health_score ?? 0}</span>
              <span>Events: {overview?.integrations.integration_events_count ?? 0}</span>
              <span>Failed events: {overview?.integrations.failed_integration_events ?? 0}</span>
              <span>Import success rate: {overview?.integrations.import_success_rate ?? 0}%</span>
            </div>
            <p className="eyebrow analytics-subsection">TOP-5 PROBLEMS</p>
            <div className="activity-list">
              {!executiveQuery.isPending && (executive?.top_5_problems ?? []).length === 0 ? <p className="state-panel state-panel-empty">Проблемы не выявлены.</p> : null}
              {(executive?.top_5_problems ?? []).map((item) => (
                <article className="activity-item" key={item.title}>
                  <header>
                    <strong>{item.title}</strong>
                    <span>{item.value}</span>
                  </header>
                </article>
              ))}
            </div>
          </div>
        </section>
        </>
      ) : null}

      {activeTab === 'tickets' ? (
        <>
          <section className="metric-grid dashboard-metrics">
            <article className="metric-card"><span>Всего</span><strong>{tickets?.total_tickets ?? 0}</strong><p>Общий объём заявок.</p></article>
            <article className="metric-card"><span>Открытые</span><strong>{tickets?.open_tickets ?? 0}</strong><p>Текущая операционная нагрузка.</p></article>
            <article className="metric-card"><span>Закрытые</span><strong>{tickets?.closed_tickets ?? 0}</strong><p>Решённые обращения.</p></article>
            <article className="metric-card"><span>За сегодня</span><strong>{tickets?.tickets_today ?? 0}</strong><p>Новые заявки за текущий день.</p></article>
          </section>
          <section className="foundation-card dashboard-split">
            <div>
              <p className="eyebrow">STATUS / CATEGORY</p>
              <h2>Распределение заявок</h2>
              <div className="mini-bars">
                {(tickets?.by_status ?? []).map((item) => (
                  <div className="mini-bar-row" key={item.status}>
                    <span>{item.status}</span>
                    <div className="mini-bar-track"><div className="mini-bar-fill" style={{ width: `${Math.max(10, item.count * 8)}%` }} /></div>
                    <strong>{item.count}</strong>
                  </div>
                ))}
              </div>
              <div className="ticket-table-wrap analytics-table-space">
                <table className="ticket-table">
                  <thead><tr><th>Категория</th><th>Count</th></tr></thead>
                  <tbody>
                    {(tickets?.by_category ?? []).map((item) => (
                      <tr key={item.category}><td>{item.category}</td><td>{item.count}</td></tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
            <div>
              <p className="eyebrow">TOP PEOPLE</p>
              <h2>Исполнители и заявители</h2>
              <div className="ticket-table-wrap">
                <table className="ticket-table">
                  <thead><tr><th>Топ исполнители</th><th>Count</th></tr></thead>
                  <tbody>{(tickets?.top_assignees ?? []).map((item) => <tr key={item.name}><td>{item.name}</td><td>{item.count}</td></tr>)}</tbody>
                </table>
              </div>
              <div className="ticket-table-wrap analytics-table-space">
                <table className="ticket-table">
                  <thead><tr><th>Топ заявители</th><th>Count</th></tr></thead>
                  <tbody>{(tickets?.top_requesters ?? []).map((item) => <tr key={item.name}><td>{item.name}</td><td>{item.count}</td></tr>)}</tbody>
                </table>
              </div>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === 'sla' ? (
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">SLA CONTROL</p>
            <h2>Compliance и breaches</h2>
            <div className="analytics-score-grid">
              {[
                ['Compliance %', sla?.sla_compliance_percent ?? 0],
                ['Response breaches', sla?.response_breaches ?? 0],
                ['Resolution breaches', sla?.resolution_breaches ?? 0],
                ['Tickets at risk', sla?.tickets_at_risk ?? 0],
                ['Critical breaches', sla?.critical_sla_breaches ?? 0],
              ].map(([label, value]) => (
                <article className="score-card" key={String(label)}>
                  <header><span>{label}</span><strong>{value}</strong></header>
                </article>
              ))}
            </div>
          </div>
          <div>
            <p className="eyebrow">VIOLATIONS</p>
            <h2>Нарушения по приоритетам</h2>
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead><tr><th>Приоритет</th><th>Count</th></tr></thead>
                <tbody>{(sla?.violations_by_priority ?? []).map((item) => <tr key={item.priority}><td>{item.priority}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'assets' ? (
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">ASSET ANALYTICS</p>
            <h2>Активы по типам и статусам</h2>
            <div className="metric-grid analytics-mini-grid">
              <article className="metric-card"><span>Imported</span><strong>{assets?.imported_assets_count ?? 0}</strong></article>
              <article className="metric-card"><span>Missing location</span><strong>{assets?.assets_missing_location_count ?? 0}</strong></article>
              <article className="metric-card"><span>Disposed</span><strong>{assets?.disposed_assets_count ?? 0}</strong></article>
              <article className="metric-card"><span>Duplicate inventory</span><strong>{assets?.duplicate_inventory_numbers?.length ?? 0}</strong></article>
            </div>
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead><tr><th>Тип</th><th>Count</th></tr></thead>
                <tbody>{(assets?.assets_by_type ?? []).map((item) => <tr key={item.type}><td>{item.type}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>Статус</th><th>Count</th></tr></thead>
                <tbody>{(assets?.assets_by_status ?? []).map((item) => <tr key={item.status}><td>{item.status}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>Источник</th><th>Count</th></tr></thead>
                <tbody>{(assets?.assets_by_source ?? []).map((item) => <tr key={item.source}><td>{item.source}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
          <div>
            <p className="eyebrow">RISK ZONES</p>
            <h2>Проблемные активы</h2>
            <div className="activity-list">
              {!assetQuery.isPending && (assets?.problem_assets ?? []).length === 0 ? <p className="state-panel state-panel-empty">Проблемные активы не найдены.</p> : null}
              {(assets?.problem_assets ?? []).map((item) => (
                <article className="activity-item" key={item.asset_tag}>
                  <header><strong>{item.asset_tag}</strong><span className="badge badge-danger">{item.status}</span></header>
                  <p>{item.name}</p>
                </article>
              ))}
            </div>
            <p className="eyebrow analytics-subsection">Гарантия скоро истекает</p>
            <div className="activity-list">
              {!assetQuery.isPending && (assets?.warranty_expiring_soon ?? []).length === 0 ? <p className="state-panel state-panel-empty">Активов с ближайшим окончанием гарантии нет.</p> : null}
              {(assets?.warranty_expiring_soon ?? []).map((item) => (
                <article className="activity-item" key={item.asset_tag}>
                  <header><strong>{item.asset_tag}</strong><span>{formatDateTime(item.warranty_until)}</span></header>
                  <p>{item.name}</p>
                </article>
              ))}
            </div>
            <p className="eyebrow analytics-subsection">Топ ответственные (МОЛ)</p>
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead><tr><th>МОЛ</th><th>Count</th></tr></thead>
                <tbody>{(assets?.top_responsible_persons ?? []).map((item) => <tr key={item.name}><td>{item.name}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'knowledge' ? (
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">KNOWLEDGE</p>
            <h2>Топ статьи и пробелы</h2>
            <div className="activity-list">
              {!knowledgeQuery.isPending && (knowledge?.top_helpful_articles ?? []).length === 0 ? <p className="state-panel state-panel-empty">Полезные статьи пока отсутствуют.</p> : null}
              {(knowledge?.top_helpful_articles ?? []).map((item) => (
                <article className="activity-item" key={item.article_number}>
                  <header><strong>{item.article_number}</strong><span>{item.helpful_count}</span></header>
                  <p>{item.title}</p>
                </article>
              ))}
            </div>
          </div>
          <div>
            <p className="eyebrow">COVERAGE</p>
            <h2>Knowledge KPI</h2>
            <div className="metric-grid analytics-mini-grid">
              <article className="metric-card"><span>Всего статей</span><strong>{knowledge?.total_articles ?? 0}</strong></article>
              <article className="metric-card"><span>Опубликовано</span><strong>{knowledge?.published_articles ?? 0}</strong></article>
              <article className="metric-card"><span>Negative feedback</span><strong>{knowledge?.articles_with_negative_feedback?.length ?? 0}</strong></article>
              <article className="metric-card"><span>KB resolved</span><strong>{knowledge?.tickets_resolved_via_knowledge_demo ?? 0}</strong></article>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'ai' ? (
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">AI USAGE</p>
            <h2>AI adoption и confidence</h2>
            <div className="metric-grid analytics-mini-grid">
              <article className="metric-card"><span>AI analyses</span><strong>{ai?.total_ai_analyses ?? 0}</strong><p>Всего AI-анализов.</p></article>
              <article className="metric-card"><span>Confidence</span><strong>{`${ai?.average_confidence_percent ?? 0}%`}</strong><p>Средняя AI confidence.</p></article>
              <article className="metric-card"><span>Applied demo</span><strong>{ai?.ai_suggestions_applied_demo ?? 0}</strong><p>Applied/demo suggestions.</p></article>
              <article className="metric-card"><span>KB resolved</span><strong>{knowledge?.tickets_resolved_via_knowledge_demo ?? 0}</strong><p>Заявки, решённые через KB/demo.</p></article>
            </div>
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>AI category</th><th>Count</th></tr></thead>
                <tbody>{(ai?.recommendations_by_category ?? []).map((item) => <tr key={item.category}><td>{item.category}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
          <div>
            <p className="eyebrow">AI PRIORITIES</p>
            <h2>Приоритеты рекомендаций</h2>
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead><tr><th>Priority</th><th>Count</th></tr></thead>
                <tbody>{(ai?.recommendations_by_priority ?? []).map((item) => <tr key={item.priority}><td>{item.priority}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'automation' ? (
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">AUTOMATION KPIs</p>
            <h2>Rules, runs and approvals</h2>
            <div className="metric-grid analytics-mini-grid">
              <article className="metric-card"><span>Active rules</span><strong>{automation?.active_rules ?? 0}</strong></article>
              <article className="metric-card"><span>Runs today</span><strong>{automation?.runs_today ?? 0}</strong></article>
              <article className="metric-card"><span>Failed runs</span><strong>{automation?.failed_runs ?? 0}</strong></article>
              <article className="metric-card"><span>Pending approvals</span><strong>{automation?.pending_approvals ?? 0}</strong></article>
            </div>
          </div>
          <div>
            <p className="eyebrow">EFFICIENCY</p>
            <h2>Automation effectiveness</h2>
            <div className="metric-grid analytics-mini-grid">
              <article className="metric-card"><span>Success rate</span><strong>{automation?.automation_success_rate ?? 0}%</strong></article>
              <article className="metric-card"><span>Runs total</span><strong>{automation?.automation_runs_count ?? 0}</strong></article>
              <article className="metric-card"><span>Runbooks</span><strong>{automation?.runbooks_available ?? 0}</strong></article>
              <article className="metric-card"><span>Runbook exec</span><strong>{automation?.runbook_execution_count ?? 0}</strong></article>
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'security' ? (
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">SECURITY</p>
            <h2>Security analytics</h2>
            <div className="metric-grid analytics-mini-grid">
              <article className="metric-card"><span>Login success</span><strong>{security?.login_success ?? 0}</strong><p>Успешные входы.</p></article>
              <article className="metric-card"><span>Login failed</span><strong>{security?.login_failed ?? 0}</strong><p>Неуспешные входы.</p></article>
              <article className="metric-card"><span>Audit events</span><strong>{security?.audit_events_count ?? 0}</strong><p>Всего audit events.</p></article>
              <article className="metric-card"><span>Admin changes</span><strong>{security?.admin_changes_today ?? 0}</strong><p>Изменения за сегодня.</p></article>
            </div>
            <article className="foundation-card analytics-inline-card">
              <div>
                <p className="eyebrow">RISK SUMMARY</p>
                <h2>{(security?.risk_summary.risk_level ?? 'n/a').toUpperCase()}</h2>
                <p>Sensitive settings count: {security?.sensitive_settings_count ?? 0}</p>
              </div>
            </article>
          </div>
          <div>
            <p className="eyebrow">RECENT EVENTS</p>
            <h2>Последние security события</h2>
            <div className="activity-list">
              {!securityQuery.isPending && (security?.risk_summary?.recent_security_events ?? []).length === 0 ? <p className="state-panel state-panel-empty">Недавних security событий нет.</p> : null}
              {(security?.risk_summary.recent_security_events ?? []).map((item, index) => (
                <article className="activity-item" key={String(item.id ?? index)}>
                  <header><strong>{String(item.action ?? 'security.event')}</strong><span>{String(item.actor_email ?? 'n/a')}</span></header>
                  <p>{formatDateTime(String(item.created_at ?? null))}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'reports' ? (
        <section className="foundation-card dashboard-split">
          <div>
            <p className="eyebrow">SAVED REPORTS</p>
            <h2>Шаблоны и snapshots</h2>
            <div className="analytics-actions">
              <button type="button" onClick={() => createSavedMutation.mutate()} disabled={createSavedMutation.isPending}>
                {createSavedMutation.isPending ? 'Создание…' : 'Создать saved report'}
              </button>
              <button type="button" onClick={() => createSnapshotMutation.mutate()} disabled={createSnapshotMutation.isPending}>
                {createSnapshotMutation.isPending ? 'Создание…' : 'Создать snapshot'}
              </button>
              <button
                type="button"
                onClick={() => {
                  const confirmed = window.confirm('Сформировать demo export payload?')
                  if (!confirmed) return
                  exportMutation.mutate()
                }}
                disabled={exportMutation.isPending}
              >
                {exportMutation.isPending ? 'Экспорт…' : 'Demo export'}
              </button>
            </div>
            {createSavedMutation.isError || createSnapshotMutation.isError || exportMutation.isError ? (
              <p className="error-message">Одна из операций отчётности завершилась ошибкой.</p>
            ) : null}
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>Saved report</th><th>Type</th><th>Updated</th></tr></thead>
                <tbody>
                  {savedReportsQuery.isPending ? <tr><td colSpan={3}><p className="state-panel state-panel-loading">Загрузка сохранённых отчётов…</p></td></tr> : null}
                  {!savedReportsQuery.isPending && (savedReportsQuery.data ?? []).length === 0 ? <tr><td colSpan={3}><p className="state-panel state-panel-empty">Сохранённые отчёты отсутствуют.</p></td></tr> : null}
                  {(savedReportsQuery.data ?? []).map((item) => <tr key={item.id}><td>{item.name}</td><td>{item.report_type}</td><td>{formatDateTime(item.updated_at)}</td></tr>)}
                </tbody>
              </table>
            </div>
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>Snapshot</th><th>Type</th><th>Created</th></tr></thead>
                <tbody>
                  {snapshotsQuery.isPending ? <tr><td colSpan={3}><p className="state-panel state-panel-loading">Загрузка snapshots…</p></td></tr> : null}
                  {!snapshotsQuery.isPending && (snapshotsQuery.data ?? []).length === 0 ? <tr><td colSpan={3}><p className="state-panel state-panel-empty">Снимки отчётов отсутствуют.</p></td></tr> : null}
                  {(snapshotsQuery.data ?? []).map((item) => <tr key={item.id}><td>{item.created_by}</td><td>{item.report_type}</td><td>{formatDateTime(item.created_at)}</td></tr>)}
                </tbody>
              </table>
            </div>
          </div>
          <div>
            <p className="eyebrow">DEMO EXPORT PAYLOAD</p>
            <h2>JSON/CSV-like preview</h2>
            <pre className="analytics-export-preview">{exportPayload || 'Запустите Demo export для предпросмотра payload.'}</pre>
          </div>
        </section>
      ) : null}
      </section>
    </AppShell>
  )
}
