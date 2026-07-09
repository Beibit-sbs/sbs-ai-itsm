import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchNotificationPreferences,
  fetchNotifications,
  fetchNotificationTemplates,
  markAllNotificationsAsRead,
  markNotificationAsRead,
  patchNotificationPreferences,
  patchNotificationTemplate,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'

type NotificationTab = 'center' | 'unread' | 'settings' | 'templates' | 'email-log'

function formatDateTime(value: string) {
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

const statusFilterOptions = [
  { value: 'ALL', label: 'Все' },
  { value: 'UNREAD', label: 'Непрочитанные' },
  { value: 'READ', label: 'Прочитанные' },
]

const tabLabels: Record<NotificationTab, string> = {
  center: 'Центр',
  unread: 'Непрочитанные',
  settings: 'Настройки',
  templates: 'Шаблоны',
  'email-log': 'Email Log',
}

export default function NotificationsPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<NotificationTab>('center')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [activeNotificationId, setActiveNotificationId] = useState<string | null>(null)

  const notificationsQuery = useQuery({
    queryKey: ['notifications', session?.access_token, statusFilter, typeFilter],
    queryFn: () =>
      fetchNotifications(session?.access_token ?? '', {
        status: statusFilter,
        event_type: typeFilter,
        page: 1,
        page_size: 50,
      }),
    enabled: Boolean(session?.access_token),
  })

  const preferencesQuery = useQuery({
    queryKey: ['notification-preferences', session?.access_token],
    queryFn: () => fetchNotificationPreferences(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && activeTab === 'settings',
  })

  const templatesQuery = useQuery({
    queryKey: ['notification-templates', session?.access_token],
    queryFn: () => fetchNotificationTemplates(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && activeTab === 'templates',
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
    onError: () => setActiveNotificationId(null),
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

  const togglePreferenceMutation = useMutation({
    mutationFn: async (payload: { event_type: string; key: 'channel_in_app' | 'channel_email' | 'is_muted'; value: boolean }) => {
      if (!session?.access_token) throw new Error('No session')
      return patchNotificationPreferences(session.access_token, [{ event_type: payload.event_type, [payload.key]: payload.value }])
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['notification-preferences'] })
    },
  })

  const toggleTemplateMutation = useMutation({
    mutationFn: async (payload: { templateId: string; isActive: boolean }) => {
      if (!session?.access_token) throw new Error('No session')
      return patchNotificationTemplate(session.access_token, payload.templateId, { is_active: payload.isActive })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['notification-templates'] })
    },
  })

  const notificationsPage = notificationsQuery.data
  const notifications = notificationsPage?.items ?? []
  const unreadCount = notificationsPage?.unread_count ?? 0

  const grouped = useMemo(() => {
    const unread = notifications.filter((item) => item.status !== 'READ')
    const read = notifications.filter((item) => item.status === 'READ')
    return { unread, read }
  }, [notifications])

  const visibleNotifications = activeTab === 'unread' ? grouped.unread : [...grouped.unread, ...grouped.read]

  return (
    <AppShell title="Уведомления" subtitle="Центр событий, настройки коммуникаций и шаблоны уведомлений.">
      <section className="section-card">
        <div>
          <p className="eyebrow">NOTIFICATION CENTER</p>
          <h2>Уведомления и коммуникации</h2>
          <p>Production-ready центр событий с настройками, шаблонами и журналом email-отправок.</p>
        </div>
        <div className="status-column">
          <span className="unread-pill">Непрочитано: {unreadCount}</span>
        </div>
      </section>

      <nav className="module-subnav" aria-label="Notifications navigation">
        <button type="button" className={`module-subnav-tab ${activeTab === 'center' ? 'active' : ''}`} onClick={() => setActiveTab('center')}>{tabLabels.center}</button>
        <button type="button" className={`module-subnav-tab ${activeTab === 'unread' ? 'active' : ''}`} onClick={() => setActiveTab('unread')}>{tabLabels.unread}</button>
        <button type="button" className={`module-subnav-tab ${activeTab === 'settings' ? 'active' : ''}`} onClick={() => setActiveTab('settings')}>{tabLabels.settings}</button>
        <button type="button" className={`module-subnav-tab ${activeTab === 'templates' ? 'active' : ''}`} onClick={() => setActiveTab('templates')}>{tabLabels.templates}</button>
        <Link to="/notifications/email-log" className="module-subnav-tab">{tabLabels['email-log']}</Link>
      </nav>

      {(activeTab === 'center' || activeTab === 'unread') ? (
        <>
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
                <input
                  value={typeFilter === 'ALL' ? '' : typeFilter}
                  onChange={(event) => setTypeFilter(event.target.value.trim() || 'ALL')}
                  placeholder="Например: ticket_created"
                />
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
            ) : visibleNotifications.length === 0 ? (
              <p className="empty-state">Нет событий для выбранных фильтров.</p>
            ) : (
              <div className="notification-grid">
                {visibleNotifications.map((notification) => (
                  <article className={`notification-card ${notification.status !== 'READ' ? 'notification-card-unread' : ''}`} key={notification.id}>
                    <header>
                      <strong>{notification.title}</strong>
                      <span>{notification.status}</span>
                    </header>
                    <p>{notification.message}</p>
                    <small>
                      {formatDateTime(notification.created_at)} · {notification.channel} · {notification.event_type ?? notification.type}
                    </small>
                    <small>
                      Получатель: {notification.recipient_name} ({notification.recipient_email})
                    </small>
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
        </>
      ) : null}

      {activeTab === 'settings' ? (
        <section className="section-card notification-list-shell">
          {preferencesQuery.isPending ? (
            <p className="loading-state">Загрузка настроек...</p>
          ) : preferencesQuery.isError ? (
            <p className="error-message">Не удалось загрузить настройки уведомлений.</p>
          ) : (
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Событие</th>
                    <th>In-App</th>
                    <th>Email</th>
                    <th>Mute</th>
                  </tr>
                </thead>
                <tbody>
                  {(preferencesQuery.data ?? []).map((item) => (
                    <tr key={item.id}>
                      <td>{item.event_type}</td>
                      <td>
                        <input
                          type="checkbox"
                          checked={item.channel_in_app}
                          onChange={(event) => togglePreferenceMutation.mutate({ event_type: item.event_type, key: 'channel_in_app', value: event.target.checked })}
                        />
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={item.channel_email}
                          onChange={(event) => togglePreferenceMutation.mutate({ event_type: item.event_type, key: 'channel_email', value: event.target.checked })}
                        />
                      </td>
                      <td>
                        <input
                          type="checkbox"
                          checked={item.is_muted}
                          onChange={(event) => togglePreferenceMutation.mutate({ event_type: item.event_type, key: 'is_muted', value: event.target.checked })}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}

      {activeTab === 'templates' ? (
        <section className="section-card notification-list-shell">
          {templatesQuery.isPending ? (
            <p className="loading-state">Загрузка шаблонов...</p>
          ) : templatesQuery.isError ? (
            <p className="error-message">Не удалось загрузить шаблоны уведомлений.</p>
          ) : (
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Код</th>
                    <th>Канал</th>
                    <th>Активен</th>
                  </tr>
                </thead>
                <tbody>
                  {(templatesQuery.data ?? []).map((item) => (
                    <tr key={item.id}>
                      <td>{item.code}</td>
                      <td>{item.channel ?? 'in_app'}</td>
                      <td>
                        <input
                          type="checkbox"
                          checked={item.is_active}
                          onChange={(event) => toggleTemplateMutation.mutate({ templateId: item.id, isActive: event.target.checked })}
                        />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      ) : null}
    </AppShell>
  )
}
