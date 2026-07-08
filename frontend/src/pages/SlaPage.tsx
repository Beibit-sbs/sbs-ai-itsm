import { useQuery } from '@tanstack/react-query'
import { fetchSlaBreaches, fetchSlaOverview, fetchSlaPolicies } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'

const priorityLabels: Record<string, string> = {
  critical: 'Critical',
  high: 'High',
  medium: 'Medium',
  low: 'Low',
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export default function SlaPage() {
  const { session } = useAuth()

  const policiesQuery = useQuery({
    queryKey: ['sla-policies', session?.access_token],
    queryFn: () => fetchSlaPolicies(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const overviewQuery = useQuery({
    queryKey: ['sla-overview', session?.access_token],
    queryFn: () => fetchSlaOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const breachesQuery = useQuery({
    queryKey: ['sla-breaches', session?.access_token],
    queryFn: () => fetchSlaBreaches(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const policies = policiesQuery.data ?? []
  const breaches = breachesQuery.data ?? []
  const activeCount = policies.filter((policy) => policy.is_active && policy.status === 'active').length

  return (
    <AppShell title="SLA" subtitle="Контроль реакции и решения связан с активами и проблемными заявками в реальном backend-срезе.">
      <section className="foundation-card">
        <div>
          <p className="eyebrow">SLA CONTROL</p>
          <h2>Политики и нарушения</h2>
          <p>Раздел уже показывает не только правила обслуживания, но и текущие breach-ы и операционный обзор по активам.</p>
        </div>
        <div className="status-column">
          <HealthBadge />
          <div className="status-list">
            <span>✓ SLA overview</span>
            <span>✓ Breach queue</span>
            <span>✓ Tenant-scoped policies</span>
          </div>
        </div>
      </section>

      <section className="metric-grid sla-metrics">
        <article className="metric-card">
          <span>Активные политики</span>
          <strong>{policiesQuery.isPending ? '…' : activeCount}</strong>
          <p>Действующие правила обслуживания.</p>
        </article>
        <article className="metric-card">
          <span>Нарушенные заявки</span>
          <strong>{overviewQuery.isPending ? '…' : overviewQuery.data?.breached_tickets ?? 0}</strong>
          <p>Заявки с текущим SLA breach.</p>
        </article>
        <article className="metric-card">
          <span>Проблемные активы</span>
          <strong>{overviewQuery.isPending ? '…' : overviewQuery.data?.problematic_assets ?? 0}</strong>
          <p>Устройства, которые требуют внимания.</p>
        </article>
        <article className="metric-card">
          <span>Гарантия скоро</span>
          <strong>{overviewQuery.isPending ? '…' : overviewQuery.data?.warranty_expiring ?? 0}</strong>
          <p>Активы с истекающей гарантией.</p>
        </article>
      </section>

      <section className="foundation-card dashboard-split">
        <div>
          <p className="eyebrow">SLA POLICIES</p>
          <h2>Политики обслуживания</h2>
          {policiesQuery.isPending ? (
            <p className="muted">Загрузка SLA…</p>
          ) : policiesQuery.isError ? (
            <p className="error-message">Не удалось получить список SLA-политик.</p>
          ) : (
            <div className="sla-grid">
              {policies.map((policy) => (
                <article className="sla-card" key={policy.id}>
                  <div className="sla-card-header">
                    <div>
                      <p className="eyebrow">{priorityLabels[policy.priority] ?? policy.priority}</p>
                      <h3>{policy.name}</h3>
                    </div>
                    <span className={`sla-status sla-status-${policy.status}`}>{policy.status}</span>
                  </div>
                  <p className="sla-description">{policy.description ?? 'Описание отсутствует'}</p>
                  <div className="sla-meta">
                    <span>Response: {policy.response_minutes ?? policy.target_response_minutes} min</span>
                    <span>Resolution: {policy.resolution_minutes ?? policy.target_resolution_minutes} min</span>
                    <span>Breaches: {policy.breach_count}</span>
                    <span>Tenant: {policy.tenant_name ?? 'N/A'}</span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>

        <div className="status-column">
          <p className="eyebrow">BREACH QUEUE</p>
          <h2>Нарушения SLA</h2>
          {breachesQuery.isPending ? (
            <p className="muted">Загрузка нарушений…</p>
          ) : breachesQuery.isError ? (
            <p className="error-message">Не удалось получить список нарушений SLA.</p>
          ) : breaches.length === 0 ? (
            <p className="muted">Активных нарушений сейчас нет.</p>
          ) : (
            <div className="activity-list">
              {breaches.map((breach) => (
                <article className="activity-item" key={breach.ticket_id}>
                  <header>
                    <strong>{breach.ticket_number ?? breach.ticket_id}</strong>
                    <span>{breach.sla_status ?? '—'}</span>
                  </header>
                  <p>{breach.title}</p>
                  <small>
                    {breach.priority} · {breach.status}
                  </small>
                  <small>
                    Response due: {formatDateTime(breach.response_due_at)} · Resolution due: {formatDateTime(breach.resolution_due_at)}
                  </small>
                </article>
              ))}
            </div>
          )}
        </div>
      </section>
    </AppShell>
  )
}
