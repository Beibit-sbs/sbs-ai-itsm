import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'
import {
  createReportSnapshot,
  createSavedReport,
  fetchAutomationAnalytics,
  fetchAnalyticsOverview,
  fetchAssetAnalytics,
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
  { key: 'ai', label: 'AI & Knowledge' },
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
  const securityQuery = useQuery({
    queryKey: ['analytics-security', session?.access_token],
    queryFn: () => fetchSecurityAnalytics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const automationQuery = useQuery({
    queryKey: ['analytics-automation', session?.access_token],
    queryFn: () => fetchAutomationAnalytics(session?.access_token ?? ''),
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
      return createReportSnapshot(session.access_token, { report_type: 'executive-summary' })
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
        report_type: 'executive-summary',
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
  const security = securityQuery.data
  const automation = automationQuery.data

  return (
    <AppShell title="Аналитика" subtitle="Executive dashboard, SLA, активы, AI, безопасность и demo-отчёты для управленческого контура.">
      <section className="foundation-card">
        <div>
          <p className="eyebrow">EXECUTIVE ANALYTICS</p>
          <h2>Управленческий обзор ITSM</h2>
          <p>Срез для руководства по нагрузке ИТ-службы, SLA-рискам, активам, AI adoption и security posture.</p>
        </div>
        <div className="status-column">
          <HealthBadge />
          <div className="status-list">
            <span>✓ Executive summary</span>
            <span>✓ Demo reports</span>
            <span>✓ Permission-guarded analytics</span>
          </div>
        </div>
      </section>

      <section className="metric-grid dashboard-metrics">
        <article className="metric-card">
          <span>Health score</span>
          <strong>{executiveQuery.isPending ? '…' : executive?.health_score ?? 0}</strong>
          <p>Сводный health score по операционному контуру.</p>
        </article>
        <article className="metric-card">
          <span>SLA compliance</span>
          <strong>{overviewQuery.isPending ? '…' : `${overview?.sla.sla_compliance_percent ?? 0}%`}</strong>
          <p>Процент соблюдения SLA по tracked ticket pool.</p>
        </article>
        <article className="metric-card">
          <span>Open critical</span>
          <strong>{ticketQuery.isPending ? '…' : tickets?.open_critical_tickets ?? 0}</strong>
          <p>Критические заявки, требующие контроля.</p>
        </article>
        <article className="metric-card">
          <span>Security risk</span>
          <strong>{executiveQuery.isPending ? '…' : executive?.security_risk_score ?? 0}</strong>
          <p>Оценка security risk на базе логинов и audit.</p>
        </article>
        <article className="metric-card">
          <span>AI confidence</span>
          <strong>{overviewQuery.isPending ? '…' : `${overview?.ai.average_confidence_percent ?? 0}%`}</strong>
          <p>Средняя уверенность AI suggestions.</p>
        </article>
        <article className="metric-card">
          <span>Asset risk</span>
          <strong>{executiveQuery.isPending ? '…' : executive?.asset_risk_score ?? 0}</strong>
          <p>Сводная оценка рисков по парку активов.</p>
        </article>
        <article className="metric-card">
          <span>Automation score</span>
          <strong>{executiveQuery.isPending ? '…' : executive?.workflow_automation_score ?? 0}</strong>
          <p>Индекс зрелости workflow automation.</p>
        </article>
      </section>

      <section className="foundation-card admin-panel">
        <div>
          <p className="eyebrow">ANALYTICS TABS</p>
          <h2>Детализация отчётности</h2>
        </div>
        <div className="notification-tabs">
          {tabs.map((tab) => (
            <button type="button" className={activeTab === tab.key ? 'admin-tab-active' : 'ghost-button'} key={tab.key} onClick={() => setActiveTab(tab.key)}>
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      {activeTab === 'executive' ? (
        <section className="foundation-card dashboard-split admin-panel">
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
      ) : null}

      {activeTab === 'tickets' ? (
        <>
          <section className="metric-grid dashboard-metrics">
            <article className="metric-card"><span>Всего</span><strong>{tickets?.total_tickets ?? 0}</strong><p>Общий объём заявок.</p></article>
            <article className="metric-card"><span>Открытые</span><strong>{tickets?.open_tickets ?? 0}</strong><p>Текущая операционная нагрузка.</p></article>
            <article className="metric-card"><span>Закрытые</span><strong>{tickets?.closed_tickets ?? 0}</strong><p>Решённые обращения.</p></article>
            <article className="metric-card"><span>За сегодня</span><strong>{tickets?.tickets_today ?? 0}</strong><p>Новые заявки за текущий день.</p></article>
          </section>
          <section className="foundation-card dashboard-split admin-panel">
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
        <section className="foundation-card dashboard-split admin-panel">
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
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">ASSET ANALYTICS</p>
            <h2>Активы по типам и статусам</h2>
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
          </div>
          <div>
            <p className="eyebrow">RISK ZONES</p>
            <h2>Проблемные активы</h2>
            <div className="activity-list">
              {(assets?.problem_assets ?? []).map((item) => (
                <article className="activity-item" key={item.asset_tag}>
                  <header><strong>{item.asset_tag}</strong><span className="badge badge-danger">{item.status}</span></header>
                  <p>{item.name}</p>
                </article>
              ))}
            </div>
            <p className="eyebrow analytics-subsection">Гарантия скоро истекает</p>
            <div className="activity-list">
              {(assets?.warranty_expiring_soon ?? []).map((item) => (
                <article className="activity-item" key={item.asset_tag}>
                  <header><strong>{item.asset_tag}</strong><span>{formatDateTime(item.warranty_until)}</span></header>
                  <p>{item.name}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'ai' ? (
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">AI USAGE</p>
            <h2>AI adoption и confidence</h2>
            <div className="metric-grid analytics-mini-grid">
              <article className="metric-card"><span>AI analyses</span><strong>{overview?.ai.total_ai_analyses ?? 0}</strong><p>Всего AI-анализов.</p></article>
              <article className="metric-card"><span>Confidence</span><strong>{`${overview?.ai.average_confidence_percent ?? 0}%`}</strong><p>Средняя AI confidence.</p></article>
              <article className="metric-card"><span>Applied demo</span><strong>{overview?.ai.ai_suggestions_applied_demo ?? 0}</strong><p>Applied/demo suggestions.</p></article>
              <article className="metric-card"><span>KB resolved</span><strong>{knowledge?.tickets_resolved_via_knowledge_demo ?? 0}</strong><p>Заявки, решённые через KB/demo.</p></article>
            </div>
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>AI category</th><th>Count</th></tr></thead>
                <tbody>{(overview?.ai.recommendations_by_category ?? []).map((item) => <tr key={item.category}><td>{item.category}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
          <div>
            <p className="eyebrow">KNOWLEDGE</p>
            <h2>Топ статьи и пробелы</h2>
            <div className="activity-list">
              {(knowledge?.top_helpful_articles ?? []).map((item) => (
                <article className="activity-item" key={item.article_number}>
                  <header><strong>{item.article_number}</strong><span>{item.helpful_count}</span></header>
                  <p>{item.title}</p>
                </article>
              ))}
            </div>
            <p className="eyebrow analytics-subsection">Категории без статей</p>
            <div className="activity-list">
              {(knowledge?.categories_without_articles ?? []).map((item) => (
                <article className="activity-item" key={item.code}><header><strong>{item.code}</strong><span>{item.name}</span></header></article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'security' ? (
        <section className="foundation-card dashboard-split admin-panel">
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

      {activeTab === 'automation' ? (
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">WORKFLOW AUTOMATION</p>
            <h2>Rules, runs, approvals</h2>
            <div className="metric-grid analytics-mini-grid">
              <article className="metric-card"><span>Active rules</span><strong>{automation?.active_rules ?? 0}</strong><p>Количество активных правил.</p></article>
              <article className="metric-card"><span>Runs today</span><strong>{automation?.runs_today ?? 0}</strong><p>Прогоны за текущий день.</p></article>
              <article className="metric-card"><span>Failed runs</span><strong>{automation?.failed_runs ?? 0}</strong><p>Ошибки и run with errors.</p></article>
              <article className="metric-card"><span>Pending approvals</span><strong>{automation?.pending_approvals ?? 0}</strong><p>Approval requests в ожидании.</p></article>
              <article className="metric-card"><span>Runbooks</span><strong>{automation?.runbooks_available ?? 0}</strong><p>Доступные runbooks.</p></article>
              <article className="metric-card"><span>Success rate</span><strong>{`${automation?.automation_success_rate ?? 0}%`}</strong><p>Процент успешных действий.</p></article>
            </div>
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>Trigger</th><th>Count</th></tr></thead>
                <tbody>{(automation?.triggers ?? []).map((item) => <tr key={item.trigger_type}><td>{item.trigger_type}</td><td>{item.count}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
          <div>
            <p className="eyebrow">TOP RULES</p>
            <h2>Наиболее часто запускаемые</h2>
            <div className="activity-list">
              {(automation?.top_triggered_rules ?? []).map((item) => (
                <article className="activity-item" key={item.rule_id}>
                  <header><strong>{item.rule_name}</strong><span>{item.count}</span></header>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'reports' ? (
        <section className="foundation-card dashboard-split admin-panel">
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
              <button type="button" onClick={() => exportMutation.mutate()} disabled={exportMutation.isPending}>
                {exportMutation.isPending ? 'Экспорт…' : 'Demo export'}
              </button>
            </div>
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>Saved report</th><th>Type</th><th>Updated</th></tr></thead>
                <tbody>{(savedReportsQuery.data ?? []).map((item) => <tr key={item.id}><td>{item.name}</td><td>{item.report_type}</td><td>{formatDateTime(item.updated_at)}</td></tr>)}</tbody>
              </table>
            </div>
            <div className="ticket-table-wrap analytics-table-space">
              <table className="ticket-table">
                <thead><tr><th>Snapshot</th><th>Type</th><th>Created</th></tr></thead>
                <tbody>{(snapshotsQuery.data ?? []).map((item) => <tr key={item.id}><td>{item.created_by}</td><td>{item.report_type}</td><td>{formatDateTime(item.created_at)}</td></tr>)}</tbody>
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
    </AppShell>
  )
}
