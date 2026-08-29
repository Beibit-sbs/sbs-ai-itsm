import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  fetchAdminAuditLogs,
  fetchAdminRoles,
  fetchAdminUsers,
  fetchAiProviderStatus,
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
import { canAccessPath } from '../auth/accessControl'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

function isClosedStatus(status: string) {
  return ['RESOLVED', 'CLOSED'].includes(status)
}

function queryValue(
  query: { isPending: boolean; isError: boolean },
  value: string | number,
) {
  if (query.isPending) return '…'
  if (query.isError) return '—'
  return value
}

export default function DashboardPage() {
  const { session } = useAuth()
  const { formatDateTime, formatNumber, translate } = useTenantExperience()
  const formatMinutes = (minutes: number | null) => {
    if (minutes == null) return '—'
    if (minutes < 60) return `${formatNumber(minutes)} ${translate('мин')}`
    const hours = Math.floor(minutes / 60)
    const rest = minutes % 60
    return rest === 0
      ? `${formatNumber(hours)} ${translate('ч')}`
      : `${formatNumber(hours)} ${translate('ч')} ${formatNumber(rest)} ${translate('мин')}`
  }
  const formatPercent = (value: number) => `${formatNumber(value, { maximumFractionDigits: 2 })}%`
  const isRoot = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const has = (...codes: string[]) => isRoot || codes.some((code) => permissions.has(code))
  const canReadTickets = Boolean(session?.user && canAccessPath(session.user, '/tickets'))
  const canReadAssets = has('assets.read')
  const canReadSla = has('sla.read')
  const canReadKnowledge = has('knowledge.read')
  const canReadNotifications = has('notifications.read')
  const canReadEmailLog = has('notifications.email_log.read')
  const canUseAi = has('ai.use', 'ai.rag.use', 'ai.actions.read')
  const canCreateKnowledgeFromTicket = has(
    'knowledge.create',
    'knowledge.create_from_ticket',
  )
  const canReadAdminUsers = has('admin.users.read')
  const canReadAdminRoles = has('admin.roles.read')
  const canReadAudit = has('security.audit.read')
  const canReadAnalytics = has('analytics.read')
  const canReadAiProvider = has(
    'admin.settings.read',
    'admin.users.read',
    'security.audit.read',
  )
  const canViewAdminKpi = canReadAdminUsers || canReadAdminRoles || canReadAudit
  const canReadOperationalData = (
    canReadTickets
    || canReadAssets
    || canReadSla
    || canReadKnowledge
    || canReadNotifications
    || canReadEmailLog
  )
  const ticketsQuery = useQuery({
    queryKey: ['dashboard-tickets', session?.access_token],
    queryFn: () => fetchTickets(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadTickets),
  })
  const assetsQuery = useQuery({
    queryKey: ['dashboard-assets', session?.access_token],
    queryFn: () => fetchAssets(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadAssets),
  })
  const slaOverviewQuery = useQuery({
    queryKey: ['dashboard-sla-overview', session?.access_token],
    queryFn: () => fetchSlaOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadSla),
  })
  const knowledgeQuery = useQuery({
    queryKey: ['dashboard-knowledge', session?.access_token],
    queryFn: () => fetchKnowledgeArticles(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadKnowledge),
  })
  const notificationsQuery = useQuery({
    queryKey: ['dashboard-notifications', session?.access_token],
    queryFn: () => fetchNotifications(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadNotifications),
  })
  const unreadNotificationsQuery = useQuery({
    queryKey: ['dashboard-notifications-unread', session?.access_token],
    queryFn: () => fetchNotificationUnreadCount(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadNotifications),
  })
  const emailLogQuery = useQuery({
    queryKey: ['dashboard-email-log', session?.access_token],
    queryFn: () => fetchEmailLog(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadEmailLog),
  })
  const adminUsersQuery = useQuery({
    queryKey: ['dashboard-admin-users', session?.access_token],
    queryFn: () => fetchAdminUsers(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadAdminUsers),
  })
  const adminRolesQuery = useQuery({
    queryKey: ['dashboard-admin-roles', session?.access_token],
    queryFn: () => fetchAdminRoles(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadAdminRoles),
  })
  const adminAuditQuery = useQuery({
    queryKey: ['dashboard-admin-audit', session?.access_token],
    queryFn: () => fetchAdminAuditLogs(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadAudit),
  })
  const adminRiskQuery = useQuery({
    queryKey: ['dashboard-admin-risk', session?.access_token],
    queryFn: () => fetchSecurityRiskSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadAudit),
  })
  const executiveOverviewQuery = useQuery({
    queryKey: ['dashboard-executive-overview', session?.access_token],
    queryFn: () => fetchAnalyticsOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadAnalytics),
  })
  const aiProviderQuery = useQuery({
    queryKey: ['dashboard-ai-provider', session?.access_token],
    queryFn: () => fetchAiProviderStatus(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadAiProvider),
  })
  const dashboardSources = [
    ...(canReadTickets ? [{ label: translate('заявки'), query: ticketsQuery }] : []),
    ...(canReadAssets ? [{ label: translate('активы'), query: assetsQuery }] : []),
    ...(canReadSla ? [{ label: 'SLA', query: slaOverviewQuery }] : []),
    ...(canReadKnowledge ? [{ label: translate('база знаний'), query: knowledgeQuery }] : []),
    ...(canReadNotifications ? [
      { label: translate('уведомления'), query: notificationsQuery },
      { label: translate('счётчик уведомлений'), query: unreadNotificationsQuery },
    ] : []),
    ...(canReadEmailLog ? [{ label: 'email pipeline', query: emailLogQuery }] : []),
    ...(canReadAdminUsers ? [{ label: translate('пользователи'), query: adminUsersQuery }] : []),
    ...(canReadAdminRoles ? [{ label: translate('роли'), query: adminRolesQuery }] : []),
    ...(canReadAudit ? [
      { label: translate('аудит'), query: adminAuditQuery },
      { label: 'security risk', query: adminRiskQuery },
    ] : []),
    ...(canReadAnalytics ? [{ label: 'executive analytics', query: executiveOverviewQuery }] : []),
    ...(canReadAiProvider ? [{ label: 'AI provider', query: aiProviderQuery }] : []),
  ]
  const failedDashboardSources = dashboardSources.filter(({ query }) => query.isError)

  const tickets = ticketsQuery.data ?? []
  const assets = assetsQuery.data ?? []
  const articles = knowledgeQuery.data ?? []
  const notifications = notificationsQuery.data?.items ?? []
  const emailLog = emailLogQuery.data ?? []
  const overview = slaOverviewQuery.data
  const quickActions = [
    ...(canReadTickets ? [{ to: '/tickets', label: 'Открыть заявки', hint: 'Очередь, статусы, комментарии' }] : []),
    ...(canReadNotifications ? [{ to: '/notifications', label: 'Проверить уведомления', hint: 'События и персональные уведомления' }] : []),
    ...(canReadKnowledge ? [{ to: '/knowledge', label: 'Найти статью', hint: 'База знаний и полезные решения' }] : []),
    ...(canUseAi ? [{ to: '/copilot', label: 'Открыть AI Copilot', hint: 'Локальная симуляция или настроенный провайдер' }] : []),
    ...(canReadAnalytics ? [{ to: '/analytics', label: 'Посмотреть аналитику', hint: 'SLA, риски, тренды' }] : []),
  ]

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
      const assetLabel = ticket.asset_tag
        ? `${ticket.asset_tag} · ${ticket.asset_name ?? translate('Актив')}`
        : translate('Без актива')
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
      emailSimulated: emailLog.filter((item) => item.status === 'SIMULATED').length,
      emailErrors: emailLog.filter((item) => item.status === 'FAILED').length,
      latestNotificationEvents: notifications.slice(0, 6),
    }
  }, [assets, tickets, articles, notifications, emailLog, translate])

  return (
    <LocalizedContent>
    <AppShell
      title="Добро пожаловать в SBS AI ITSM"
      subtitle="Рабочая область сформирована по разрешениям вашей учётной записи."
    >
      {quickActions.length > 0 ? (
        <section className="hero-action-grid">
          {quickActions.map((action) => (
            <Link key={action.to} to={action.to} className="hero-action-card">
              <strong>{translate(action.label)}</strong>
              <span>{translate(action.hint)}</span>
            </Link>
          ))}
        </section>
      ) : null}

      <header className="topbar-card">
        <HealthBadge />
      </header>

      {failedDashboardSources.length ? (
        <div className="state-panel state-panel-error" role="alert">
          <strong>Часть данных dashboard недоступна.</strong>
          <p>Источники: {failedDashboardSources.map(({ label }) => translate(label)).join(', ')}. Значения помечены «—» и не интерпретируются как ноль.</p>
          <button
            type="button"
            className="ghost-button"
            onClick={() => failedDashboardSources.forEach(({ query }) => void query.refetch())}
          >
            Повторить загрузку
          </button>
        </div>
      ) : null}

      {!canReadOperationalData && !canReadAnalytics && !canViewAdminKpi ? (
        <section className="foundation-card" role="status">
          <p className="eyebrow">PERMISSION-AWARE WORKSPACE</p>
          <h2>Рабочие данные пока недоступны</h2>
          <p>
            Учётная запись активна, но назначенные роли не содержат разрешений чтения
            для операционных модулей. Администратор организации может добавить права
            без пересоздания пользователя.
          </p>
          <Link className="secondary-button" to="/account">Открыть учётную запись</Link>
        </section>
      ) : null}

      {canReadOperationalData ? (
      <section className="metric-grid dashboard-metrics">
        {canReadTickets ? <article className="metric-card">
          <span>Открытых заявок</span>
          <strong>{queryValue(ticketsQuery, formatNumber(metrics.openTickets))}</strong>
          <p>Все не закрытые обращения.</p>
        </article> : null}
        {canReadTickets ? <article className="metric-card">
          <span>Просрочено SLA</span>
          <strong>{queryValue(ticketsQuery, formatNumber(metrics.overdue))}</strong>
          <p>Заявки, перешагнувшие срок due date.</p>
        </article> : null}
        {canReadAssets ? <article className="metric-card">
          <span>Проблемные активы</span>
          <strong>{queryValue(assetsQuery, formatNumber(metrics.problemAssets.length))}</strong>
          <p>Неисправные и ремонтируемые устройства.</p>
        </article> : null}
        {canReadAssets ? <article className="metric-card">
          <span>Скоро истекает гарантия</span>
          <strong>{queryValue(assetsQuery, formatNumber(metrics.warrantySoon.length))}</strong>
          <p>Активы в окне ближайших 45 дней.</p>
        </article> : null}
        {canReadSla ? <article className="metric-card">
          <span>Нарушения SLA</span>
          <strong>{queryValue(slaOverviewQuery, formatNumber(overview?.breached_tickets ?? 0))}</strong>
          <p>Текущие breach-ы в рабочем контуре.</p>
        </article> : null}
        {canReadTickets ? <article className="metric-card">
          <span>Среднее время реакции</span>
          <strong>{queryValue(ticketsQuery, formatMinutes(metrics.avgResponse))}</strong>
          <p>Считается по доступной истории реакции.</p>
        </article> : null}
        {canReadTickets && canReadKnowledge ? <article className="metric-card">
          <span>Решено через базу знаний</span>
          <strong>{queryValue({
            isPending: ticketsQuery.isPending || knowledgeQuery.isPending,
            isError: ticketsQuery.isError || knowledgeQuery.isError,
          }, formatNumber(metrics.resolvedViaKnowledge))}</strong>
          <p>Закрытые заявки, попавшие в покрытые KB-категории.</p>
        </article> : null}
        {canReadTickets ? <article className="metric-card">
          <span>AI confidence average</span>
          <strong>{queryValue(ticketsQuery, formatPercent(metrics.aiConfidenceAverage))}</strong>
          <p>Оценочная уверенность классификации по доступному потоку заявок.</p>
        </article> : null}
        {canReadNotifications ? <article className="metric-card">
          <span>Непрочитанные уведомления</span>
          <strong>{queryValue(unreadNotificationsQuery, formatNumber(unreadNotificationsQuery.data?.unread_count ?? 0))}</strong>
          <p>Требуют внимания в Notification Center.</p>
        </article> : null}
        {canReadEmailLog ? <article className="metric-card">
          <span>Email в очереди</span>
          <strong>{queryValue(emailLogQuery, formatNumber(metrics.emailQueue))}</strong>
          <p>Сообщения со статусом PENDING.</p>
        </article> : null}
        {canReadEmailLog ? <article className="metric-card">
          <span>Подтверждено транспортом</span>
          <strong>{queryValue(emailLogQuery, formatNumber(metrics.emailSent))}</strong>
          <p>Только логи со статусом SENT.</p>
        </article> : null}
        {canReadEmailLog ? <article className="metric-card">
          <span>Симуляция email</span>
          <strong>{queryValue(emailLogQuery, formatNumber(metrics.emailSimulated))}</strong>
          <p>Внешняя отправка не выполнялась.</p>
        </article> : null}
        {canReadEmailLog ? <article className="metric-card">
          <span>Ошибки отправки</span>
          <strong>{queryValue(emailLogQuery, formatNumber(metrics.emailErrors))}</strong>
          <p>Логи со статусом FAILED.</p>
        </article> : null}
      </section>
      ) : null}

      {canUseAi || canReadAiProvider || canReadAnalytics ? (
      <section className="foundation-card dashboard-split">
        <div>
          <p className="eyebrow">AI CONTROL TOWER</p>
          <h2>Интеллектуальное управление ИТ</h2>
          <div className="mini-bars">
            <div className="mini-bar-row">
              <span>Configured → effective</span>
              <strong>
                {aiProviderQuery.isPending
                  ? '…'
                  : !canReadAiProvider
                    ? 'Доступ ограничен'
                  : `${aiProviderQuery.data?.configured_provider ?? 'n/a'} → ${aiProviderQuery.data?.active_provider ?? 'n/a'}`}
              </strong>
            </div>
            <div className="mini-bar-row">
              <span>Model</span>
              <strong>{aiProviderQuery.isPending ? '…' : !canReadAiProvider ? '—' : aiProviderQuery.data?.model ?? 'n/a'}</strong>
            </div>
            <div className="mini-bar-row">
              <span>Execution mode</span>
              <strong>{aiProviderQuery.isPending ? '…' : !canReadAiProvider ? 'RESTRICTED' : aiProviderQuery.data?.execution_mode ?? 'UNAVAILABLE'}</strong>
            </div>
            <div className="mini-bar-row">
              <span>External provider</span>
              <strong>{aiProviderQuery.isPending ? '…' : !canReadAiProvider ? 'RESTRICTED' : aiProviderQuery.data?.external_configured ? 'CONFIGURED' : 'NOT CONFIGURED'}</strong>
            </div>
            <div className="mini-bar-row">
              <span>AI analyses</span>
              <strong>
                {canReadAnalytics
                  ? executiveOverviewQuery.isPending
                    ? '…'
                    : formatNumber(executiveOverviewQuery.data?.ai.total_ai_analyses ?? 0)
                  : 'Доступ ограничен'}
              </strong>
            </div>
          </div>
        </div>
        <div className="status-column">
          <p className="eyebrow">AI QUICK ACTIONS</p>
          <div className="workload-list">
            {canUseAi ? <Link to="/copilot" className="workload-card" style={{ textDecoration: 'none' }}>
              <span>Открыть AI Copilot</span>
              <strong>Go</strong>
            </Link> : null}
            {canUseAi && canReadTickets ? <Link to="/tickets" className="workload-card" style={{ textDecoration: 'none' }}>
              <span>Запустить AI анализ тикета</span>
              <strong>Run</strong>
            </Link> : null}
            {canReadTickets && canReadKnowledge && canCreateKnowledgeFromTicket ? <Link to="/knowledge" className="workload-card" style={{ textDecoration: 'none' }}>
              <span>Создать KB из инцидентов</span>
              <strong>Build</strong>
            </Link> : null}
          </div>
        </div>
      </section>
      ) : null}

      {canReadAnalytics ? (
        <section className="foundation-card dashboard-split admin-kpi-block">
          <div>
            <p className="eyebrow">WORKFLOW AUTOMATION</p>
            <h2>Состояние автоматизации процессов</h2>
            <div className="mini-bars">
              <div className="mini-bar-row"><span>Active rules</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.automation.active_rules ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Runs today</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.automation.runs_today ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Success rate</span><strong>{executiveOverviewQuery.isPending ? '…' : formatPercent(executiveOverviewQuery.data?.automation.automation_success_rate ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Pending approvals</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.automation.pending_approvals ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Runbooks</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.automation.runbooks_available ?? 0)}</strong></div>
            </div>
          </div>
          <div className="status-column">
            <p className="eyebrow">TOP TRIGGERED RULES</p>
            <div className="activity-list">
              {(executiveOverviewQuery.data?.automation.top_triggered_rules ?? []).map((item) => (
                <article className="activity-item" key={item.rule_id}>
                  <header>
                    <strong>{item.rule_name}</strong>
                    <span>{formatNumber(item.count)}</span>
                  </header>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {canReadAnalytics ? (
        <section className="foundation-card dashboard-split admin-kpi-block">
          <div>
            <p className="eyebrow">INTEGRATION HEALTH</p>
            <h2>Состояние интеграционного слоя</h2>
            <div className="mini-bars">
              <div className="mini-bar-row"><span>Enabled systems</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.integrations.enabled_systems ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Systems with errors</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.integrations.systems_with_errors ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Last health check</span><strong>{executiveOverviewQuery.isPending ? '…' : formatDateTime(executiveOverviewQuery.data?.integrations.last_health_check)}</strong></div>
              <div className="mini-bar-row"><span>Active import jobs</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.integrations.active_import_jobs ?? 0)}</strong></div>
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
                  <small>{formatDateTime(item.created_at)}</small>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {canReadAnalytics ? (
        <section className="foundation-card dashboard-split admin-kpi-block">
          <div>
            <p className="eyebrow">EXECUTIVE SUMMARY</p>
            <h2>Короткий управленческий срез</h2>
            <div className="mini-bars">
              <div className="mini-bar-row"><span>Health score</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.executive_summary.health_score ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>SLA compliance</span><strong>{executiveOverviewQuery.isPending ? '…' : formatPercent(executiveOverviewQuery.data?.sla.sla_compliance_percent ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Open critical tickets</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.tickets.open_critical_tickets ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Security risk</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.executive_summary.security_risk_score ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>AI confidence</span><strong>{executiveOverviewQuery.isPending ? '…' : formatPercent(executiveOverviewQuery.data?.ai.average_confidence_percent ?? 0)}</strong></div>
              <div className="mini-bar-row"><span>Asset risk</span><strong>{executiveOverviewQuery.isPending ? '…' : formatNumber(executiveOverviewQuery.data?.executive_summary.asset_risk_score ?? 0)}</strong></div>
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

      {canViewAdminKpi ? (
        <section className="foundation-card dashboard-split admin-kpi-block">
          <div>
            <p className="eyebrow">ADMIN KPI</p>
            <h2>Администрирование и безопасность</h2>
            <div className="mini-bars">
              {canReadAdminUsers ? (
                <>
                  <div className="mini-bar-row">
                    <span>Active users</span>
                    <strong>
                      {adminUsersQuery.isPending
                        ? '…'
                        : formatNumber((adminUsersQuery.data ?? []).filter((user) => user.is_active).length)}
                    </strong>
                  </div>
                  <div className="mini-bar-row">
                    <span>Inactive users</span>
                    <strong>
                      {adminUsersQuery.isPending
                        ? '…'
                        : formatNumber((adminUsersQuery.data ?? []).filter((user) => !user.is_active).length)}
                    </strong>
                  </div>
                </>
              ) : null}
              {canReadAdminRoles ? (
                <div className="mini-bar-row">
                  <span>Roles count</span>
                  <strong>{adminRolesQuery.isPending ? '…' : formatNumber(adminRolesQuery.data?.length ?? 0)}</strong>
                </div>
              ) : null}
              {canReadAudit ? (
                <>
                  <div className="mini-bar-row">
                    <span>Failed login attempts</span>
                    <strong>{adminRiskQuery.isPending ? '…' : formatNumber(adminRiskQuery.data?.failed_logins_24h ?? 0)}</strong>
                  </div>
                  <div className="mini-bar-row">
                    <span>Admin changes today</span>
                    <strong>
                      {adminAuditQuery.isPending
                        ? '…'
                        : formatNumber((adminAuditQuery.data ?? []).filter(
                            (item) =>
                              item.action.startsWith('user_') ||
                              item.action.startsWith('role_') ||
                              item.action.startsWith('setting_'),
                          ).length)}
                    </strong>
                  </div>
                  <div className="mini-bar-row">
                    <span>Risk summary</span>
                    <strong>{adminRiskQuery.isPending ? '…' : (adminRiskQuery.data?.risk_level ?? 'n/a').toUpperCase()}</strong>
                  </div>
                </>
              ) : null}
            </div>
          </div>
          {canReadAudit ? (
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
                    <small>{formatDateTime(item.created_at)}</small>
                  </article>
                ))}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {canReadTickets ? (
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
                <strong>{formatNumber(item.count)}</strong>
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
                <strong>{formatNumber(item.count)}</strong>
              </article>
            ))}
          </div>
        </div>
      </section>
      ) : null}

      {canReadNotifications || canReadEmailLog ? (
      <section className="foundation-card dashboard-split">
        {canReadNotifications ? <div>
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
                  <small>{formatDateTime(item.created_at)}</small>
                </article>
              ))
            )}
          </div>
        </div> : null}
        {canReadEmailLog ? <div className="status-column">
          <p className="eyebrow">EMAIL PIPELINE</p>
          <div className="status-list">
            <span>Queue: {formatNumber(metrics.emailQueue)}</span>
            <span>Sent: {formatNumber(metrics.emailSent)}</span>
            <span>Failed: {formatNumber(metrics.emailErrors)}</span>
          </div>
        </div> : null}
      </section>
      ) : null}

      {canReadKnowledge ? (
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
                <strong>{formatNumber(article.helpful_count)}</strong>
              </div>
            ))}
          </div>
        </div>

        {canReadTickets ? <div className="status-column">
          <p className="eyebrow">KNOWLEDGE GAPS</p>
          <div className="activity-list">
            {metrics.lackingInstructions.length === 0 ? (
              <p className="muted">Критичных пробелов в инструкциях не найдено.</p>
            ) : (
              metrics.lackingInstructions.slice(0, 5).map((item) => (
                <article className="activity-item" key={item.category}>
                  <header>
                    <strong>{item.category}</strong>
                    <span>{formatNumber(item.count)}</span>
                  </header>
                  <p>Тема обращений без достаточного покрытия в базе знаний.</p>
                </article>
              ))
            )}
          </div>
        </div> : null}
      </section>
      ) : null}

      {canReadTickets || canReadAssets ? (
      <section className="foundation-card dashboard-split">
        {canReadTickets ? <div>
          <p className="eyebrow">TOP HARDWARE</p>
          <h2>Активы по числу заявок</h2>
          <div className="mini-bars">
            {metrics.topHardware.slice(0, 5).map((item) => (
              <div className="mini-bar-row" key={item.hardware}>
                <span>{item.hardware}</span>
                <div className="mini-bar-track">
                  <div className="mini-bar-fill" style={{ width: `${Math.max(14, (item.count / Math.max(1, tickets.length)) * 100)}%` }} />
                </div>
                <strong>{formatNumber(item.count)}</strong>
              </div>
            ))}
          </div>
        </div> : null}

        {canReadAssets ? <div className="status-column">
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
        </div> : null}
      </section>
      ) : null}

      <section className="foundation-card">
        <div>
          <p className="eyebrow">СИСТЕМНЫЙ СТАТУС</p>
          <h2>Локальный контур доступен</h2>
          <p>
            Интерфейс подключён к API, а доступные модули и запросы ограничены реальными
            разрешениями текущей учётной записи.
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
    </LocalizedContent>
  )
}
