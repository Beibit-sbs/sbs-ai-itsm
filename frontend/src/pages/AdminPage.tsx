import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'
import {
  activateAdminUser,
  assignUserRoles,
  createAdminUser,
  deactivateAdminUser,
  fetchAdminAuditLogs,
  fetchAdminPermissions,
  fetchAdminRoles,
  fetchAdminSettings,
  fetchAdminUsers,
  fetchSecurityLoginEvents,
  fetchSecurityRiskSummary,
  fetchSecuritySessionOverview,
  patchAdminSetting,
  type AdminRole,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'

const tabs = [
  { key: 'users', label: 'Пользователи' },
  { key: 'roles', label: 'Роли и права' },
  { key: 'audit', label: 'Аудит' },
  { key: 'settings', label: 'Настройки' },
  { key: 'security', label: 'Security Overview' },
] as const

type TabKey = (typeof tabs)[number]['key']

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export default function AdminPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabKey>('users')
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('ALL')
  const [activeFilter, setActiveFilter] = useState<'ALL' | 'ACTIVE' | 'INACTIVE'>('ALL')
  const [auditActionFilter, setAuditActionFilter] = useState('')
  const [auditActorFilter, setAuditActorFilter] = useState('')
  const [auditEntityFilter, setAuditEntityFilter] = useState('')
  const [newUser, setNewUser] = useState({
    email: '',
    full_name: '',
    position: '',
    department: '',
    phone: '',
    password: 'Sbs!2026',
    role_id: '',
  })

  const usersQuery = useQuery({
    queryKey: ['admin-users', session?.access_token, roleFilter, activeFilter],
    queryFn: () =>
      fetchAdminUsers(session?.access_token ?? '', {
        role_id: roleFilter,
        active: activeFilter === 'ALL' ? 'ALL' : activeFilter === 'ACTIVE',
      }),
    enabled: Boolean(session?.access_token),
  })

  const rolesQuery = useQuery({
    queryKey: ['admin-roles', session?.access_token],
    queryFn: () => fetchAdminRoles(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const permissionsQuery = useQuery({
    queryKey: ['admin-permissions', session?.access_token],
    queryFn: () => fetchAdminPermissions(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const auditQuery = useQuery({
    queryKey: ['admin-audit', session?.access_token, auditActionFilter, auditActorFilter, auditEntityFilter],
    queryFn: () =>
      fetchAdminAuditLogs(session?.access_token ?? '', {
        action: auditActionFilter || undefined,
        actor_email: auditActorFilter || undefined,
        entity_type: auditEntityFilter || undefined,
      }),
    enabled: Boolean(session?.access_token),
  })

  const settingsQuery = useQuery({
    queryKey: ['admin-settings', session?.access_token],
    queryFn: () => fetchAdminSettings(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const loginEventsQuery = useQuery({
    queryKey: ['security-login-events', session?.access_token],
    queryFn: () => fetchSecurityLoginEvents(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const sessionOverviewQuery = useQuery({
    queryKey: ['security-session-overview', session?.access_token],
    queryFn: () => fetchSecuritySessionOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const riskSummaryQuery = useQuery({
    queryKey: ['security-risk-summary', session?.access_token],
    queryFn: () => fetchSecurityRiskSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const createUserMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      return createAdminUser(session.access_token, {
        email: newUser.email,
        full_name: newUser.full_name,
        password: newUser.password,
        position: newUser.position || null,
        department: newUser.department || null,
        phone: newUser.phone || null,
        role_id: newUser.role_id || null,
      })
    },
    onSuccess: async () => {
      setNewUser({ email: '', full_name: '', position: '', department: '', phone: '', password: 'Sbs!2026', role_id: '' })
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
  })

  const toggleUserMutation = useMutation({
    mutationFn: async (payload: { userId: string; active: boolean }) => {
      if (!session?.access_token) throw new Error('No session')
      return payload.active ? activateAdminUser(session.access_token, payload.userId) : deactivateAdminUser(session.access_token, payload.userId)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['security-session-overview'] })
    },
  })

  const assignRoleMutation = useMutation({
    mutationFn: async (payload: { userId: string; roleId: string }) => {
      if (!session?.access_token) throw new Error('No session')
      return assignUserRoles(session.access_token, payload.userId, [payload.roleId])
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
  })

  const settingMutation = useMutation({
    mutationFn: async (payload: { key: string; value: string }) => {
      if (!session?.access_token) throw new Error('No session')
      return patchAdminSetting(session.access_token, payload.key, payload.value)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['admin-settings'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
  })

  const users = usersQuery.data ?? []
  const roles = rolesQuery.data ?? []
  const permissions = permissionsQuery.data ?? []
  const auditLogs = auditQuery.data ?? []
  const settings = settingsQuery.data ?? []

  const filteredUsers = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return users
    return users.filter((item) => [item.email, item.full_name, item.position, item.department].filter(Boolean).some((value) => String(value).toLowerCase().includes(query)))
  }, [users, search])

  const groupedPermissions = useMemo(() => {
    return permissions.reduce<Record<string, typeof permissions>>((acc, item) => {
      acc[item.module] = acc[item.module] ? [...acc[item.module], item] : [item]
      return acc
    }, {})
  }, [permissions])

  const security = riskSummaryQuery.data
  const sessionOverview = sessionOverviewQuery.data

  const activeUsers = users.filter((item) => item.is_active).length
  const inactiveUsers = users.filter((item) => !item.is_active).length
  const adminChangesToday = auditLogs.filter((item) => item.action.startsWith('user_') || item.action.startsWith('role_') || item.action === 'setting_changed').length

  const isLoading = usersQuery.isPending || rolesQuery.isPending

  return (
    <AppShell title="Администрирование" subtitle="Пользователи, роли, права, аудит и безопасность в единой консоли управления.">
      <section className="foundation-card">
        <div>
          <p className="eyebrow">ADMIN & SECURITY</p>
          <h2>Контур управления платформой</h2>
          <p>Раздел поддерживает multi-role контроль доступа, аудит операций и security monitoring.</p>
        </div>
        <div className="status-column">
          <HealthBadge />
          <div className="status-list">
            <span>✓ RBAC permissions</span>
            <span>✓ Tenant isolation</span>
            <span>✓ Audit trail</span>
          </div>
        </div>
      </section>

      <section className="metric-grid dashboard-metrics">
        <article className="metric-card">
          <span>Активные пользователи</span>
          <strong>{isLoading ? '…' : activeUsers}</strong>
          <p>Учетные записи со статусом active.</p>
        </article>
        <article className="metric-card">
          <span>Неактивные пользователи</span>
          <strong>{isLoading ? '…' : inactiveUsers}</strong>
          <p>Учетные записи со статусом inactive.</p>
        </article>
        <article className="metric-card">
          <span>Ролей в системе</span>
          <strong>{rolesQuery.isPending ? '…' : roles.length}</strong>
          <p>Системные и tenant-роли.</p>
        </article>
        <article className="metric-card">
          <span>Admin changes today</span>
          <strong>{auditQuery.isPending ? '…' : adminChangesToday}</strong>
          <p>Изменения пользователей, ролей и настроек.</p>
        </article>
        <article className="metric-card">
          <span>Failed login attempts</span>
          <strong>{riskSummaryQuery.isPending ? '…' : security?.failed_logins_24h ?? 0}</strong>
          <p>Неуспешные входы за 24 часа.</p>
        </article>
        <article className="metric-card">
          <span>Security risk summary</span>
          <strong>{riskSummaryQuery.isPending ? '…' : (security?.risk_level ?? 'n/a').toUpperCase()}</strong>
          <p>Оценка риска на базе audit/login событий.</p>
        </article>
      </section>

      <section className="foundation-card admin-panel">
        <div>
          <p className="eyebrow">ADMIN TABS</p>
          <h2>Управление</h2>
        </div>
        <div className="notification-tabs">
          {tabs.map((tab) => (
            <button type="button" className={activeTab === tab.key ? 'admin-tab-active' : 'ghost-button'} key={tab.key} onClick={() => setActiveTab(tab.key)}>
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      {activeTab === 'users' ? (
        <>
          <section className="foundation-card tickets-toolbar">
            <div className="tickets-toolbar-group">
              <label className="inline-field">
                <span>Поиск</span>
                <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="email, имя, отдел" />
              </label>
              <label className="inline-field">
                <span>Роль</span>
                <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                  <option value="ALL">Все роли</option>
                  {roles.map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="inline-field">
                <span>Статус</span>
                <select value={activeFilter} onChange={(event) => setActiveFilter(event.target.value as 'ALL' | 'ACTIVE' | 'INACTIVE')}>
                  <option value="ALL">Все</option>
                  <option value="ACTIVE">Active</option>
                  <option value="INACTIVE">Inactive</option>
                </select>
              </label>
            </div>
          </section>

          <section className="foundation-card admin-panel">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Пользователь</th>
                    <th>Отдел</th>
                    <th>Позиция</th>
                    <th>Last login</th>
                    <th>Статус</th>
                    <th>Роль</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredUsers.map((user) => {
                    return (
                      <tr key={user.id}>
                        <td>
                          <strong>{user.full_name}</strong>
                          <p className="table-subtext">{user.email}</p>
                        </td>
                        <td>{user.department ?? '—'}</td>
                        <td>{user.position ?? '—'}</td>
                        <td>{formatDateTime(user.last_login_at)}</td>
                        <td>{user.is_active ? 'active' : 'inactive'}</td>
                        <td>
                          <select onChange={(event) => assignRoleMutation.mutate({ userId: user.id, roleId: event.target.value })} defaultValue="">
                            <option value="">Назначить роль</option>
                            {roles.map((role: AdminRole) => (
                              <option key={role.id} value={role.id}>
                                {role.code}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={() => toggleUserMutation.mutate({ userId: user.id, active: !user.is_active })}
                          >
                            {user.is_active ? 'Деактивировать' : 'Активировать'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="foundation-card admin-panel">
            <div>
              <p className="eyebrow">CREATE USER</p>
              <h2>Новый пользователь</h2>
            </div>
            <form
              className="modal-form"
              onSubmit={(event) => {
                event.preventDefault()
                createUserMutation.mutate()
              }}
            >
              <div className="form-grid">
                <label>
                  <span>Email</span>
                  <input value={newUser.email} onChange={(event) => setNewUser((prev) => ({ ...prev, email: event.target.value }))} />
                </label>
                <label>
                  <span>ФИО</span>
                  <input value={newUser.full_name} onChange={(event) => setNewUser((prev) => ({ ...prev, full_name: event.target.value }))} />
                </label>
                <label>
                  <span>Роль</span>
                  <select value={newUser.role_id} onChange={(event) => setNewUser((prev) => ({ ...prev, role_id: event.target.value }))}>
                    <option value="">Без роли</option>
                    {roles.map((role) => (
                      <option key={role.id} value={role.id}>
                        {role.code}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Отдел</span>
                  <input value={newUser.department} onChange={(event) => setNewUser((prev) => ({ ...prev, department: event.target.value }))} />
                </label>
                <label>
                  <span>Должность</span>
                  <input value={newUser.position} onChange={(event) => setNewUser((prev) => ({ ...prev, position: event.target.value }))} />
                </label>
                <label>
                  <span>Телефон</span>
                  <input value={newUser.phone} onChange={(event) => setNewUser((prev) => ({ ...prev, phone: event.target.value }))} />
                </label>
              </div>
              <button type="submit" disabled={createUserMutation.isPending}>
                {createUserMutation.isPending ? 'Создание…' : 'Создать пользователя'}
              </button>
            </form>
          </section>
        </>
      ) : null}

      {activeTab === 'roles' ? (
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">ROLES</p>
            <h2>Системные и tenant роли</h2>
            <div className="activity-list">
              {roles.map((role) => (
                <article className="activity-item" key={role.id}>
                  <header>
                    <strong>{role.name}</strong>
                    <span>{role.code}</span>
                  </header>
                  <p>{role.description ?? '—'}</p>
                  <small>{role.is_system ? 'System role' : 'Custom role'}</small>
                </article>
              ))}
            </div>
          </div>
          <div>
            <p className="eyebrow">PERMISSIONS</p>
            <h2>Права по модулям</h2>
            <div className="activity-list">
              {Object.entries(groupedPermissions).map(([module, items]) => (
                <article className="activity-item" key={module}>
                  <header>
                    <strong>{module}</strong>
                    <span>{items.length}</span>
                  </header>
                  <p>{items.map((item) => item.code).join(', ')}</p>
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {activeTab === 'audit' ? (
        <>
          <section className="foundation-card tickets-toolbar">
            <div className="tickets-toolbar-group">
              <label className="inline-field">
                <span>Action</span>
                <input value={auditActionFilter} onChange={(event) => setAuditActionFilter(event.target.value)} placeholder="user_updated" />
              </label>
              <label className="inline-field">
                <span>Actor</span>
                <input value={auditActorFilter} onChange={(event) => setAuditActorFilter(event.target.value)} placeholder="admin@sbs.local" />
              </label>
              <label className="inline-field">
                <span>Entity</span>
                <input value={auditEntityFilter} onChange={(event) => setAuditEntityFilter(event.target.value)} placeholder="user" />
              </label>
            </div>
          </section>

          <section className="foundation-card admin-panel">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Дата</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Entity</th>
                    <th>Entity ID</th>
                  </tr>
                </thead>
                <tbody>
                  {auditLogs.map((log) => (
                    <tr key={log.id}>
                      <td>{formatDateTime(log.created_at)}</td>
                      <td>{log.actor_email}</td>
                      <td>{log.action}</td>
                      <td>{log.entity_type}</td>
                      <td>{log.entity_id ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === 'settings' ? (
        <section className="foundation-card admin-panel">
          <div>
            <p className="eyebrow">SYSTEM SETTINGS</p>
            <h2>Конфигурация платформы</h2>
            <p className="muted">Sensitive settings не отображаются и не редактируются через UI.</p>
          </div>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead>
                <tr>
                  <th>Ключ</th>
                  <th>Значение</th>
                  <th>Описание</th>
                  <th>Updated</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {settings.map((item) => (
                  <tr key={item.id}>
                    <td>{item.key}</td>
                    <td>{item.is_sensitive ? '***' : item.value ?? '—'}</td>
                    <td>{item.description ?? '—'}</td>
                    <td>{formatDateTime(item.updated_at)}</td>
                    <td>
                      {!item.is_sensitive ? (
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => {
                            const nextValue = window.prompt(`Новое значение для ${item.key}`, item.value ?? '')
                            if (nextValue == null) return
                            settingMutation.mutate({ key: item.key, value: nextValue })
                          }}
                        >
                          Изменить
                        </button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeTab === 'security' ? (
        <>
          <section className="metric-grid dashboard-metrics">
            <article className="metric-card">
              <span>Успешные входы (24ч)</span>
              <strong>{riskSummaryQuery.isPending ? '…' : security?.success_logins_24h ?? 0}</strong>
              <p>Login success events</p>
            </article>
            <article className="metric-card">
              <span>Неуспешные входы (24ч)</span>
              <strong>{riskSummaryQuery.isPending ? '…' : security?.failed_logins_24h ?? 0}</strong>
              <p>Login failed events</p>
            </article>
            <article className="metric-card">
              <span>Активные пользователи</span>
              <strong>{sessionOverviewQuery.isPending ? '…' : sessionOverview?.active_users ?? 0}</strong>
              <p>По текущему tenant scope</p>
            </article>
            <article className="metric-card">
              <span>Risk level</span>
              <strong>{riskSummaryQuery.isPending ? '…' : (security?.risk_level ?? 'n/a').toUpperCase()}</strong>
              <p>Расчет по security сигналам</p>
            </article>
          </section>

          <section className="foundation-card dashboard-split admin-panel">
            <div>
              <p className="eyebrow">LOGIN EVENTS</p>
              <h2>Последние события входа</h2>
              <div className="activity-list">
                {(loginEventsQuery.data ?? []).slice(0, 10).map((event) => (
                  <article className="activity-item" key={event.id}>
                    <header>
                      <strong>{event.actor_email}</strong>
                      <span>{event.action}</span>
                    </header>
                    <p>{formatDateTime(event.created_at)}</p>
                    <small>{event.ip_address ?? 'n/a'}</small>
                  </article>
                ))}
              </div>
            </div>
            <div>
              <p className="eyebrow">RISK DETAILS</p>
              <h2>Последние события безопасности</h2>
              <div className="activity-list">
                {(security?.recent_security_events ?? []).slice(0, 10).map((event, index) => (
                  <article className="activity-item" key={String(event.id ?? index)}>
                    <header>
                      <strong>{String(event.action ?? 'security.event')}</strong>
                      <span>{String(event.actor_email ?? 'n/a')}</span>
                    </header>
                    <p>{formatDateTime(String(event.created_at ?? null))}</p>
                  </article>
                ))}
              </div>
            </div>
          </section>
        </>
      ) : null}
    </AppShell>
  )
}