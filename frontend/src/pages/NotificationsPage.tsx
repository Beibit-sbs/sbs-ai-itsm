import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchNotificationUnreadCount,
  fetchNotifications,
  markAllNotificationsAsRead,
  markNotificationAsRead,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

const statusFilterOptions = [
  { value: 'ALL', label: 'Все' },
  { value: 'UNREAD', label: 'Непрочитанные' },
  { value: 'READ', label: 'Прочитанные' },
]

const typeFilterOptions = [
  { value: 'ALL', label: 'Все типы' },
  { value: 'ticket_created', label: 'Заявка создана' },
  { value: 'ticket_assigned', label: 'Назначение исполнителя' },
  { value: 'ticket_status_changed', label: 'Изменение статуса' },
  { value: 'ticket_comment_added', label: 'Комментарий' },
  { value: 'ticket_resolved', label: 'Решение заявки' },
  { value: 'sla_warning', label: 'SLA warning' },
  { value: 'sla_breached', label: 'SLA breached' },
  { value: 'ai_recommendation_ready', label: 'AI рекомендация' },
]

export default function NotificationsPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [activeNotificationId, setActiveNotificationId] = useState<string | null>(null)

  const notificationsQuery = useQuery({
    queryKey: ['notifications', session?.access_token, statusFilter, typeFilter],
    queryFn: () => fetchNotifications(session?.access_token ?? '', { status: statusFilter, type: typeFilter }),
    enabled: Boolean(session?.access_token),
  })

  const unreadQuery = useQuery({
    queryKey: ['notifications-unread-count', session?.access_token],
    queryFn: () => fetchNotificationUnreadCount(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const markReadMutation = useMutation({
    mutationFn: async (notificationId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return markNotificationAsRead(session.access_token, notificationId)
    },
    onSuccess: async () => {
      setActiveNotificationId(null)
      await queryClient.invalidateQueries({ queryKey: ['notifications'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: () => {
      setActiveNotificationId(null)
    },
  })

  const readAllMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      return markAllNotificationsAsRead(session.access_token)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['notifications'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
  })

  const notifications = notificationsQuery.data ?? []
  const unreadCount = unreadQuery.data?.unread_count ?? 0

  const grouped = useMemo(() => {
    const unread = notifications.filter((item) => item.status !== 'READ')
    const read = notifications.filter((item) => item.status === 'READ')
    return { unread, read }
  }, [notifications])

  return (
    <AppShell title="Уведомления" subtitle="Системные события, in-app уведомления и статус прочтения.">
      <section className="section-card">
        <div>
          <p className="eyebrow">NOTIFICATION CENTER</p>
          <h2>События и оповещения</h2>
          <p>В этом разделе доступны in-app уведомления по workflow заявок, SLA и AI.</p>
        </div>
        <div className="status-column">
          <span className="unread-pill">Непрочитано: {unreadCount}</span>
        </div>
      </section>

      <nav className="module-subnav" aria-label="Notifications navigation">
        <Link to="/notifications" className="module-subnav-tab active">Уведомления</Link>
        <Link to="/notifications/email-log" className="module-subnav-tab">Email Log</Link>
      </nav>

      <section className="foundation-card table-toolbar">
        <div className="table-filters">
          <label className="inline-field">
            <span>Статус</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              {statusFilterOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Тип события</span>
            <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
              {typeFilterOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          type="button"
          className="ghost-button tickets-create-button"
          onClick={() => {
            const confirmed = window.confirm('Отметить все текущие уведомления как прочитанные?')
            if (!confirmed) return
            readAllMutation.mutate()
          }}
          disabled={readAllMutation.isPending || notifications.length === 0}
        >
          {readAllMutation.isPending ? 'Обновление…' : 'Отметить все как прочитанные'}
        </button>
      </section>

      {markReadMutation.isError || readAllMutation.isError ? <p className="error-message">Не удалось обновить статус уведомлений.</p> : null}

      <section className="section-card notification-list-shell">
        {notificationsQuery.isPending ? (
          <p className="loading-state">Загрузка данных...</p>
        ) : notificationsQuery.isError ? (
          <div className="error-state">
            Не удалось загрузить уведомления.
            <div className="analytics-actions">
              <button type="button" className="ghost-button" onClick={() => notificationsQuery.refetch()}>Повторить</button>
            </div>
          </div>
        ) : notifications.length === 0 ? (
          <p className="empty-state">Данных пока нет. Измените фильтры или дождитесь новых событий.</p>
        ) : (
          <div className="notification-grid">
            {[...grouped.unread, ...grouped.read].map((notification) => (
              <article className={`notification-card ${notification.status !== 'READ' ? 'notification-card-unread' : ''}`} key={notification.id}>
                <header>
                  <strong>{notification.title}</strong>
                  <span>{notification.status}</span>
                </header>
                <p>{notification.message}</p>
                <small>
                  {formatDateTime(notification.created_at)} · {notification.channel} · {notification.type}
                </small>
                <small>
                  Получатель: {notification.recipient_name} ({notification.recipient_email})
                </small>
                {notification.related_ticket_id ? (
                  <small>
                    Связанная заявка: <Link to="/tickets">{notification.related_ticket_id.slice(0, 8)}</Link>
                  </small>
                ) : null}
                {notification.status !== 'READ' ? (
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => {
                      setActiveNotificationId(notification.id)
                      markReadMutation.mutate(notification.id)
                    }}
                    disabled={markReadMutation.isPending || readAllMutation.isPending}
                  >
                    {markReadMutation.isPending && activeNotificationId === notification.id ? 'Обновление…' : 'Отметить прочитанным'}
                  </button>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </section>
    </AppShell>
  )
}
