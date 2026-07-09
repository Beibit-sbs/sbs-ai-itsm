import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchAdminAuditLogs,
  fetchAdminRoles,
  fetchAdminUsers,
  fetchAnalyticsOverview,
  fetchAssets,
  fetchEmailLog,
  fetchKnowledgeArticles,
  fetchNotificationUnreadCount,
  fetchNotifications,
  fetchSecurityRiskSummary,
  fetchSlaOverview,
  fetchTickets,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'

function isClosedStatus(status: string) {
  return ['RESOLVED', 'CLOSED'].includes(status)
}

function formatMinutes(minutes: number | null) {
  if (minutes == null) return '—'
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`
}

export default function DashboardPage() {
  const { session } = useAuth()
  const isAdminContext = ['saas_root', 'organization_admin', 'security_officer'].includes(session?.user.role ?? '')
  const ticketsQuery = useQuery({
    queryKey: ['dashboard-tickets', session?.access_token],
    queryFn: () => fetchTickets(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const assetsQuery = useQuery({
    queryKey: ['dashboard-assets', session?.access_token],
    queryFn: () => fetchAssets(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const slaOverviewQuery = useQuery({
    queryKey: ['dashboard-sla-overview', session?.access_token],
    queryFn: () => fetchSlaOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const knowledgeQuery = useQuery({
    queryKey: ['dashboard-knowledge', session?.access_token],
    queryFn: () => fetchKnowledgeArticles(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const notificationsQuery = useQuery({
    queryKey: ['dashboard-notifications', session?.access_token],
    queryFn: () => fetchNotifications(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const unreadNotificationsQuery = useQuery({
    queryKey: ['dashboard-notifications-unread', session?.access_token],
    queryFn: () => fetchNotificationUnreadCount(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const emailLogQuery = useQuery({
    queryKey: ['dashboard-email-log', session?.access_token],
    queryFn: () => fetchEmailLog(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const adminUsersQuery = useQuery({
    queryKey: ['dashboard-admin-users', session?.access_token],
    queryFn: () => fetchAdminUsers(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && isAdminContext),
  })
  const adminRolesQuery = useQuery({
    queryKey: ['dashboard-admin-roles', session?.access_token],
    queryFn: () => fetchAdminRoles(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && isAdminContext),
  })
  const adminAuditQuery = useQuery({
    queryKey: ['dashboard-admin-audit', session?.access_token],
    queryFn: () => fetchAdminAuditLogs(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && isAdminContext),
  })
  const adminRiskQuery = useQuery({
    queryKey: ['dashboard-admin-risk', session?.access_token],
    queryFn: () => fetchSecurityRiskSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && isAdminContext),
  })
  const executiveOverviewQuery = useQuery({
    queryKey: ['dashboard-executive-overview', session?.access_token],
    queryFn: () => fetchAnalyticsOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && isAdminContext),
  })

  const tickets = ticketsQuery.data ?? []
  const assets = assetsQuery.data ?? []
  const articles = knowledgeQuery.data ?? []
  const notifications = notificationsQuery.data?.items ?? []
  const emailLog = emailLogQuery.data ?? []
  const overview = slaOverviewQuery.data

  const metrics = useMemo(() => {
    const openTickets = tickets.filter((ticket) => !isClosedStatus(ticket.status)).length
    const overdue = tickets.filter((ticket) => ticket.sla_due_at && new Date(ticket.sla_due_at).getTime() < Date.now() && !isClosedStatus(ticket.status)).length
    const critical = tickets.filter((ticket) => ticket.priority === 'CRITICAL' && !isClosedStatus(ticket.status)).length
    const today = tickets.filter((ticket) => new Date(ticket.created_at).toDateString() === new Date().toDateString()).length
    const responseValues = tickets.map((ticket) => ticket.response_minutes ?? 0).filter((value) => value > 0)
    const avgResponse = responseValues.length === 0 ? null : Math.round(responseValues.reduce((sum, value) => sum + value, 0) / responseValues.length)
    const workload = tickets
      .filter((ticket) => !isClosedStatus(ticket.status))
      .reduce<Record<string, number>>((accumulator, ticket) => {
        const assignee = ticket.assignee_name ?? 'Не назначен'
        accumulator[assignee] = (accumulator[assignee] ?? 0) + 1
        return accumulator
      }, {})
    const topCategories = tickets.reduce<Record<string, number>>((accumulator, ticket) => {
      accumulator[ticket.category_label] = (accumulator[ticket.category_label] ?? 0) + 1
      return accumulator
    }, {})
    const topCategoryCodes = tickets.reduce<Record<string, number>>((accumulator, ticket) => {
      accumulator[ticket.category] = (accumulator[ticket.category] ?? 0) + 1
      return accumulator
    }, {})
    const topHardware = tickets.reduce<Record<string, number>>((accumulator, ticket) => {
      const assetLabel = ticket.asset_tag ? `${ticket.asset_tag} · ${ticket.asset_name ?? 'Актив'}` : 'Без актива'
      accumulator[assetLabel] = (accumulator[assetLabel] ?? 0) + 1
      return accumulator
    }, {})
    const aiConfidenceHints: Record<string, number> = {
      NETWORK_INTERNET: 0.88,
      NETWORK_WIFI: 0.86,
      PRINTING: 0.79,
      ACCOUNT_PASSWORD: 0.84,
      ACCESS_PLATONUS: 0.82,
      ACCESS_MOODLE: 0.81,
      MAIL: 0.77,
      SECURITY_PHISHING: 0.94,
      HARDWARE_WORKSTATION: 0.83,
      AV_PROJECTOR: 0.78,
    }
    const confidenceValues = tickets.map((ticket) => aiConfidenceHints[ticket.category] ?? 0.62)
    const aiConfidenceAverage = confidenceValues.length === 0 ? 0 : Math.round((confidenceValues.reduce((sum, value) => sum + value, 0) / confidenceValues.length) * 100)
    const articleByTicketCategory = articles.reduce<Record<string, number>>((accumulator, article) => {
      const key = article.ticket_category ?? 'UNKNOWN'
      accumulator[key] = (accumulator[key] ?? 0) + 1
      return accumulator
    }, {})
    const lackingInstructions = Object.entries(topCategoryCodes)
      .filter(([category]) => (articleByTicketCategory[category] ?? 0) === 0)
      .map(([category, count]) => ({ category, count }))

    return {
      openTickets,
      overdue,
      critical,
      today,
      avgResponse,
      workload: Object.entries(workload)
        .map(([assignee, count]) => ({ assignee, count }))
        .sort((left, right) => right.count - left.count),
      topCategories: Object.entries(topCategories)
        .map(([category, count]) => ({ category, count }))
        .sort((left, right) => right.count - left.count),
      topHardware: Object.entries(topHardware)
        .map(([hardware, count]) => ({ hardware, count }))
        .sort((left, right) => right.count - left.count),
      problemAssets: assets.filter((asset) => ['broken', 'in_repair', 'maintenance'].includes(asset.status)),
      warrantySoon: assets.filter((asset) => asset.warranty_until && new Date(asset.warranty_until).getTime() < Date.now() + 1000 * 60 * 60 * 24 * 45),
      topArticles: [...articles].sort((left, right) => right.helpful_count - left.helpful_count).slice(0, 5),
      resolvedViaKnowledge: tickets.filter((ticket) => isClosedStatus(ticket.status) && Object.keys(articleByTicketCategory).includes(ticket.category)).length,
      aiConfidenceAverage,
      lackingInstructions,
      emailQueue: emailLog.filter((item) => item.status === 'PENDING').length,
      emailSent: emailLog.filter((item) => item.status === 'SENT').length,
      emailErrors: emailLog.filter((item) => item.status === 'FAILED').length,
      latestNotificationEvents: notifications.slice(0, 6),
    }
  }, [assets, tickets, articles, notifications, emailLog])

  return (
    <AppShell
      title="Добро пожаловать в SBS AI ITSM"
      subtitle="Основа платформы уже работает: заявки, активы, SLA и операционный обзор доступны прямо сейчас."
    >
      <header className="topbar-card">
        <HealthBadge />
      </header>

      <section className="metric-grid dashboard-metrics">
        <article className="metric-card">
          <span>Открытых заявок</span>
          <strong>{ticketsQuery.isPending ? '…' : metrics.openTickets}</strong>
          <p>Все не закрытые обращения.</p>
        </article>
        <article className="metric-card">
          <span>Просрочено SLA</span>
          <strong>{ticketsQuery.isPending ? '…' : metrics.overdue}</strong>
          <p>Заявки, перешагнувшие срок due date.</p>
        </article>
        <article className="metric-card">
          <span>Проблемные активы</span>
          <strong>{assetsQuery.isPending ? '…' : metrics.problemAssets.length}</strong>
          <p>Неисправные и ремонтируемые устройства.</p>
        </article>
        <article className="metric-card">
          <span>Скоро истекает гарантия</span>
          <strong>{assetsQuery.isPending ? '…' : metrics.warrantySoon.length}</strong>
          <p>Активы в окне ближайших 45 дней.</p>
        </article>
        <article className="metric-card">
          <span>Нарушения SLA</span>
          <strong>{slaOverviewQuery.isPending ? '…' : overview?.breached_tickets ?? 0}</strong>
          <p>Текущие breach-ы в рабочем контуре.</p>
        </article>
        <article className="metric-card">
          <span>Среднее время реакции</span>
          <strong>{ticketsQuery.isPending ? '…' : formatMinutes(metrics.avgResponse)}</strong>
          <p>Считается по seeded response history.</p>
        </article>
        <article className="metric-card">
          <span>Решено через базу знаний</span>
          <strong>{knowledgeQuery.isPending ? '…' : metrics.resolvedViaKnowledge}</strong>
          <p>Закрытые заявки, попавшие в покрытые KB-категории.</p>
        </article>
        <article className="metric-card">
          <span>AI confidence average</span>
          <strong>{ticketsQuery.isPending ? '…' : `${metrics.aiConfidenceAverage}%`}</strong>
          <p>Средняя уверенность mock-рекомендаций по потоку заявок.</p>
        </article>
        <article className="metric-card">
          <span>Непрочитанные уведомления</span>
          <strong>{unreadNotificationsQuery.isPending ? '…' : unreadNotificationsQuery.data?.unread_count ?? 0}</strong>
          <p>Требуют внимания в Notification Center.</p>
        </article>
        <article className="metric-card">
          <span>Email в очереди</span>
          <strong>{emailLogQuery.isPending ? '…' : metrics.emailQueue}</strong>
          <p>Mock email со статусом PENDING.</p>
        </article>
        <article className="metric-card">
          <span>Отправлено mock email</span>
          <strong>{emailLogQuery.isPending ? '…' : metrics.emailSent}</strong>
          <p>Логи со статусом SENT.</p>
        </article>
        <article className="metric-card">
          <span>Ошибки отправки</span>
          <strong>{emailLogQuery.isPending ? '…' : metrics.emailErrors}</strong>
          <p>Логи со статусом FAILED.</p>
        </article>
      </section>

      {isAdminContext ? (
        <section className="foundation-card dashboard-split admin-kpi-block">
          <div>
            <p className="eyebrow">WORKFLOW AUTOMATION</p>
            <h2>Состояние автоматизации процессов</h2>
            <div className="mini-bars">
              <div className="mini-bar-row"><span>Active rules</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.automation.active_rules ?? 0}</strong></div>
              <div className="mini-bar-row"><span>Runs today</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.automation.runs_today ?? 0}</strong></div>
              <div className="mini-bar-row"><span>Success rate</span><strong>{executiveOverviewQuery.isPending ? '…' : `${executiveOverviewQuery.data?.automation.automation_success_rate ?? 0}%`}</strong></div>
              <div className="mini-bar-row"><span>Pending approvals</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.automation.pending_approvals ?? 0}</strong></div>
              <div className="mini-bar-row"><span>Runbooks</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.automation.runbooks_available ?? 0}</strong></div>
            </div>
          </div>
          <div className="status-column">
            <p className="eyebrow">TOP TRIGGERED RULES</p>
            <div className="activity-list">
              {(executiveOverviewQuery.data?.automation.top_triggered_rules ?? []).map((item) => (
                <article className="activity-item" key={item.rule_id}>
                  <header>
                    <strong>{item.rule_name}</strong>
                    <span>{item.count}</span>
                  </header>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {isAdminContext ? (
        <section className="foundation-card dashboard-split admin-kpi-block">
          <div>
            <p className="eyebrow">INTEGRATION HEALTH</p>
            <h2>Состояние интеграционного слоя</h2>
            <div className="mini-bars">
              <div className="mini-bar-row"><span>Enabled systems</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.integrations.enabled_systems ?? 0}</strong></div>
              <div className="mini-bar-row"><span>Systems with errors</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.integrations.systems_with_errors ?? 0}</strong></div>
              <div className="mini-bar-row"><span>Last health check</span><strong>{executiveOverviewQuery.isPending ? '…' : (executiveOverviewQuery.data?.integrations.last_health_check ? new Date(executiveOverviewQuery.data.integrations.last_health_check).toLocaleString('ru-RU') : '—')}</strong></div>
              <div className="mini-bar-row"><span>Active import jobs</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.integrations.active_import_jobs ?? 0}</strong></div>
            </div>
          </div>
          <div className="status-column">
            <p className="eyebrow">RECENT INTEGRATION EVENTS</p>
            <div className="activity-list">
              {(executiveOverviewQuery.data?.integrations.recent_integration_events ?? []).map((item) => (
                <article className="activity-item" key={item.id}>
                  <header>
                    <strong>{item.event_type}</strong>
                    <span>{item.status}</span>
                  </header>
                  <small>{new Date(item.created_at).toLocaleString('ru-RU')}</small>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {isAdminContext ? (
        <section className="foundation-card dashboard-split admin-kpi-block">
          <div>
            <p className="eyebrow">EXECUTIVE SUMMARY</p>
            <h2>Короткий управленческий срез</h2>
            <div className="mini-bars">
              <div className="mini-bar-row"><span>Health score</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.executive_summary.health_score ?? 0}</strong></div>
              <div className="mini-bar-row"><span>SLA compliance</span><strong>{executiveOverviewQuery.isPending ? '…' : `${executiveOverviewQuery.data?.sla.sla_compliance_percent ?? 0}%`}</strong></div>
              <div className="mini-bar-row"><span>Open critical tickets</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.tickets.open_critical_tickets ?? 0}</strong></div>
              <div className="mini-bar-row"><span>Security risk</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.executive_summary.security_risk_score ?? 0}</strong></div>
              <div className="mini-bar-row"><span>AI confidence</span><strong>{executiveOverviewQuery.isPending ? '…' : `${executiveOverviewQuery.data?.ai.average_confidence_percent ?? 0}%`}</strong></div>
              <div className="mini-bar-row"><span>Asset risk</span><strong>{executiveOverviewQuery.isPending ? '…' : executiveOverviewQuery.data?.executive_summary.asset_risk_score ?? 0}</strong></div>
            </div>
          </div>
          <div className="status-column">
            <p className="eyebrow">TOP RECOMMENDATIONS</p>
            <div className="activity-list">
              {(executiveOverviewQuery.data?.executive_summary.top_5_recommendations ?? []).slice(0, 5).map((item) => (
                <article className="activity-item" key={item}>
                  <p>{item}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {isAdminContext ? (
        <section className="foundation-card dashboard-split admin-kpi-block">
          <div>
            <p className="eyebrow">ADMIN KPI</p>
            <h2>Администрирование и безопасность</h2>
            <div className="mini-bars">
              <div className="mini-bar-row">
                <span>Active users</span>
                <strong>
                  {adminUsersQuery.isPending
                    ? '…'
                    : (adminUsersQuery.data ?? []).filter((user) => user.is_active).length}
                </strong>
              </div>
              <div className="mini-bar-row">
                <span>Inactive users</span>
                <strong>
                  {adminUsersQuery.isPending
                    ? '…'
                    : (adminUsersQuery.data ?? []).filter((user) => !user.is_active).length}
                </strong>
              </div>
              <div className="mini-bar-row">
                <span>Roles count</span>
                <strong>{adminRolesQuery.isPending ? '…' : adminRolesQuery.data?.length ?? 0}</strong>
              </div>
              <div className="mini-bar-row">
                <span>Failed login attempts</span>
                <strong>{adminRiskQuery.isPending ? '…' : adminRiskQuery.data?.failed_logins_24h ?? 0}</strong>
              </div>
              <div className="mini-bar-row">
                <span>Admin changes today</span>
                <strong>
                  {adminAuditQuery.isPending
                    ? '…'
                    : (adminAuditQuery.data ?? []).filter(
                        (item) =>
                          item.action.startsWith('user_') ||
                          item.action.startsWith('role_') ||
                          item.action.startsWith('setting_'),
                      ).length}
                </strong>
              </div>
              <div className="mini-bar-row">
                <span>Risk summary</span>
                <strong>{adminRiskQuery.isPending ? '…' : (adminRiskQuery.data?.risk_level ?? 'n/a').toUpperCase()}</strong>
              </div>
            </div>
          </div>
          <div className="status-column">
            <p className="eyebrow">LATEST AUDIT EVENTS</p>
            <div className="activity-list">
              {(adminAuditQuery.data ?? []).slice(0, 6).map((item) => (
                <article className="activity-item" key={item.id}>
                  <header>
                    <strong>{item.action}</strong>
                    <span>{item.entity_type}</span>
                  </header>
                  <p>{item.actor_email}</p>
                  <small>{new Date(item.created_at).toLocaleString('ru-RU')}</small>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      <section className="foundation-card dashboard-split">
        <div>
          <p className="eyebrow">TOP CATEGORIES</p>
          <h2>Топ категорий обращений</h2>
          <div className="mini-bars">
            {metrics.topCategories.slice(0, 5).map((item) => (
              <div className="mini-bar-row" key={item.category}>
                <span>{item.category}</span>
                <div className="mini-bar-track">
                  <div className="mini-bar-fill" style={{ width: `${Math.max(14, (item.count / Math.max(1, tickets.length)) * 100)}%` }} />
                </div>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="status-column">
          <p className="eyebrow">WORKLOAD</p>
          <div className="workload-list">
            {metrics.workload.slice(0, 5).map((item) => (
              <article className="workload-card" key={item.assignee}>
                <span>{item.assignee}</span>
                <strong>{item.count}</strong>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="foundation-card dashboard-split">
        <div>
          <p className="eyebrow">LATEST EVENTS</p>
          <h2>Последние notification события</h2>
          <div className="activity-list">
            {metrics.latestNotificationEvents.length === 0 ? (
              <p className="muted">Событий пока нет.</p>
            ) : (
              metrics.latestNotificationEvents.map((item) => (
                <article className="activity-item" key={item.id}>
                  <header>
                    <strong>{item.title}</strong>
                    <span>{item.status}</span>
                  </header>
                  <p>{item.message}</p>
                  <small>{new Date(item.created_at).toLocaleString('ru-RU')}</small>
                </article>
              ))
            )}
          </div>
        </div>
        <div className="status-column">
          <p className="eyebrow">EMAIL PIPELINE</p>
          <div className="status-list">
            <span>Queue: {metrics.emailQueue}</span>
            <span>Sent: {metrics.emailSent}</span>
            <span>Failed: {metrics.emailErrors}</span>
          </div>
        </div>
      </section>

      <section className="foundation-card dashboard-split">
        <div>
          <p className="eyebrow">TOP KNOWLEDGE</p>
          <h2>Топ статей базы знаний</h2>
          <div className="mini-bars">
            {metrics.topArticles.map((article) => (
              <div className="mini-bar-row" key={article.id}>
                <span>{article.article_number}</span>
                <div className="mini-bar-track">
                  <div className="mini-bar-fill" style={{ width: `${Math.max(14, article.helpful_count * 10)}%` }} />
                </div>
                <strong>{article.helpful_count}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="status-column">
          <p className="eyebrow">KNOWLEDGE GAPS</p>
          <div className="activity-list">
            {metrics.lackingInstructions.length === 0 ? (
              <p className="muted">Критичных пробелов в инструкциях не найдено.</p>
            ) : (
              metrics.lackingInstructions.slice(0, 5).map((item) => (
                <article className="activity-item" key={item.category}>
                  <header>
                    <strong>{item.category}</strong>
                    <span>{item.count}</span>
                  </header>
                  <p>Тема обращений без достаточного покрытия в базе знаний.</p>
                </article>
              ))
            )}
          </div>
        </div>
      </section>

      <section className="foundation-card dashboard-split">
        <div>
          <p className="eyebrow">TOP HARDWARE</p>
          <h2>Активы по числу заявок</h2>
          <div className="mini-bars">
            {metrics.topHardware.slice(0, 5).map((item) => (
              <div className="mini-bar-row" key={item.hardware}>
                <span>{item.hardware}</span>
                <div className="mini-bar-track">
                  <div className="mini-bar-fill" style={{ width: `${Math.max(14, (item.count / Math.max(1, tickets.length)) * 100)}%` }} />
                </div>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </div>

        <div className="status-column">
          <p className="eyebrow">PROBLEM ASSETS</p>
          <div className="activity-list">
            {metrics.problemAssets.slice(0, 5).map((asset) => (
              <article className="activity-item" key={asset.id}>
                <header>
                  <strong>{asset.asset_tag}</strong>
                  <span>{asset.status}</span>
                </header>
                <p>{asset.name}</p>
                <small>{asset.assigned_to_name ?? 'Не назначен'} · {asset.location}</small>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="foundation-card">
        <div>
          <p className="eyebrow">СИСТЕМНЫЙ СТАТУС</p>
          <h2>Основа платформы готова</h2>
          <p>
            Frontend подключён к FastAPI. PostgreSQL и Redis описаны в Docker Compose. Теперь Service Desk, активы и SLA работают вместе как единый поток.
          </p>
        </div>
        <div className="status-list">
          <span>✓ React shell</span>
          <span>✓ FastAPI health</span>
          <span>✓ Service Desk workflow</span>
          <span>✓ Asset linkage</span>
          <span>✓ SLA overview</span>
        </div>
      </section>
    </AppShell>
  )
}
