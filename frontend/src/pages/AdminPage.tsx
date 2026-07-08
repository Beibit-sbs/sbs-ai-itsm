import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'
import {
  activateAdminUser,
  assignUserRoles,
  createAdminUser,
  deactivateAdminUser,
  fetchAdminAuditLogById,
  fetchAdminAuditLogs,
  fetchAdminPermissions,
  fetchAdminRoleById,
  fetchAdminRoles,
  fetchAdminUserById,
  fetchAdminSettings,
  fetchCurrentTenant,
  fetchUserRoles,
  fetchLoginEvents,
  fetchRiskSummary,
  fetchSecurityOverview,
  fetchTenants,
  updateAdminSetting,
  fetchAdminUsers,
  updateAdminUser,
  type AdminRole,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'

const tabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'users', label: 'Пользователи' },
  { key: 'roles', label: 'Роли и права' },
  { key: 'audit', label: 'Аудит' },
  { key: 'settings', label: 'Настройки' },
  { key: 'security', label: 'Security' },
  { key: 'tenants', label: 'Организация' },
] as const

type TabKey = (typeof tabs)[number]['key']

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function riskBadgeClass(level: string | null | undefined) {
  const normalized = String(level ?? '').toLowerCase()
  if (normalized === 'high') return 'badge badge-danger'
  if (normalized === 'medium') return 'badge badge-warning'
  return 'badge badge-positive'
}

function includesText(value: string | null | undefined, query: string) {
  if (!query) return true
  return String(value ?? '').toLowerCase().includes(query)
}

function matchesDateRange(value: string | null, fromDate: string, toDate: string) {
  if (!value) return false
  const ts = new Date(value).getTime()
  if (Number.isNaN(ts)) return false
  if (fromDate) {
    const fromTs = new Date(`${fromDate}T00:00:00`).getTime()
    if (ts < fromTs) return false
  }
  if (toDate) {
    const toTs = new Date(`${toDate}T23:59:59`).getTime()
    if (ts > toTs) return false
  }
  return true
}

export default function AdminPage() {
  const { session } = useAuth()
  const canReadTenants = session?.user.role === 'saas_root' || (session?.user.permissions ?? []).includes('tenant.read')
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabKey>('overview')
  const [search, setSearch] = useState('')
  const [roleFilter, setRoleFilter] = useState('ALL')
  const [activeFilter, setActiveFilter] = useState<'ALL' | 'ACTIVE' | 'INACTIVE'>('ALL')
  const [auditActionFilter, setAuditActionFilter] = useState('')
  const [auditActorFilter, setAuditActorFilter] = useState('')
  const [auditEntityFilter, setAuditEntityFilter] = useState('')
  const [auditSearch, setAuditSearch] = useState('')
  const [auditFromDate, setAuditFromDate] = useState('')
  const [auditToDate, setAuditToDate] = useState('')
  const [selectedRoleId, setSelectedRoleId] = useState<string>('')
  const [selectedUserId, setSelectedUserId] = useState<string>('')
  const [selectedAuditId, setSelectedAuditId] = useState<string>('')
  const [roleAssignUserId, setRoleAssignUserId] = useState<string>('')
  const [roleAssignRoleId, setRoleAssignRoleId] = useState<string>('')
  const [isCreateUserModalOpen, setIsCreateUserModalOpen] = useState(false)
  const [settingsEditValue, setSettingsEditValue] = useState<Record<string, string>>({})
  const [actionMessage, setActionMessage] = useState<string>('')
  const [actionError, setActionError] = useState<string>('')
  const [newUser, setNewUser] = useState({
    email: '',
    full_name: '',
    position: '',
    department: '',
    phone: '',
    password: 'Sbs!2026',
    role_id: '',
    active: true,
  })

  const closeAllModals = () => {
    setIsCreateUserModalOpen(false)
    setSelectedUserId('')
    setSelectedAuditId('')
    setRoleAssignUserId('')
    setRoleAssignRoleId('')
  }

  useEffect(() => {
    if (!isCreateUserModalOpen && !selectedUserId && !selectedAuditId && !roleAssignUserId) return
    const onKeydown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeAllModals()
    }
    window.addEventListener('keydown', onKeydown)
    return () => window.removeEventListener('keydown', onKeydown)
  }, [isCreateUserModalOpen, selectedAuditId, selectedUserId, roleAssignUserId])

  const usersQuery = useQuery({
    queryKey: ['admin-users', session?.access_token, roleFilter, activeFilter],
    queryFn: () =>
      fetchAdminUsers(session?.access_token ?? '', {
        role_id: roleFilter,
        active: activeFilter === 'ALL' ? 'ALL' : activeFilter === 'ACTIVE',
      }),
    enabled: Boolean(session?.access_token),
  })

  const tenantsQuery = useQuery({
    queryKey: ['tenants', session?.access_token],
    queryFn: () => fetchTenants(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadTenants),
    retry: false,
  })

  const currentTenantQuery = useQuery({
    queryKey: ['tenant-current', session?.access_token],
    queryFn: () => fetchCurrentTenant(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadTenants),
    retry: false,
  })

  const rolesQuery = useQuery({
    queryKey: ['admin-roles', session?.access_token],
    queryFn: () => fetchAdminRoles(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const selectedRoleQuery = useQuery({
    queryKey: ['admin-role-by-id', session?.access_token, selectedRoleId],
    queryFn: () => fetchAdminRoleById(session?.access_token ?? '', selectedRoleId),
    enabled: Boolean(session?.access_token && selectedRoleId),
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

  const selectedAuditQuery = useQuery({
    queryKey: ['admin-audit-by-id', session?.access_token, selectedAuditId],
    queryFn: () => fetchAdminAuditLogById(session?.access_token ?? '', selectedAuditId),
    enabled: Boolean(session?.access_token && selectedAuditId),
  })

  const settingsQuery = useQuery({
    queryKey: ['admin-settings', session?.access_token],
    queryFn: () => fetchAdminSettings(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const loginEventsQuery = useQuery({
    queryKey: ['security-login-events', session?.access_token],
    queryFn: () => fetchLoginEvents(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const sessionOverviewQuery = useQuery({
    queryKey: ['security-session-overview', session?.access_token],
    queryFn: () => fetchSecurityOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const riskSummaryQuery = useQuery({
    queryKey: ['security-risk-summary', session?.access_token],
    queryFn: () => fetchRiskSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const selectedUserQuery = useQuery({
    queryKey: ['admin-user-by-id', session?.access_token, selectedUserId],
    queryFn: () => fetchAdminUserById(session?.access_token ?? '', selectedUserId),
    enabled: Boolean(session?.access_token && selectedUserId),
  })

  const userRolesQuery = useQuery({
    queryKey: ['admin-user-role-map', session?.access_token, usersQuery.data?.length, auditQuery.data?.length],
    queryFn: async () => {
      if (!session?.access_token) return new Map<string, AdminRole[]>()
      const map = new Map<string, AdminRole[]>()
      const rows = usersQuery.data ?? []
      await Promise.all(
        rows.map(async (item) => {
          try {
            const roles = await fetchUserRoles(session.access_token, item.id)
            map.set(item.id, roles)
          } catch {
            map.set(item.id, [])
          }
        }),
      )
      return map
    },
    enabled: Boolean(session?.access_token && (usersQuery.data ?? []).length > 0),
    staleTime: 30000,
  })

  const detailsUserRolesQuery = useQuery({
    queryKey: ['admin-user-roles-detail', session?.access_token, selectedUserId],
    queryFn: async () => {
      if (!session?.access_token || !selectedUserId) return [] as AdminRole[]
      return fetchUserRoles(session.access_token, selectedUserId)
    },
    enabled: Boolean(session?.access_token && selectedUserId),
  })

  const createUserMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      const createdUser = await createAdminUser(session.access_token, {
        email: newUser.email,
        full_name: newUser.full_name,
        password: newUser.password,
        position: newUser.position || null,
        department: newUser.department || null,
        phone: newUser.phone || null,
        role_id: newUser.role_id || null,
      })
      if (!newUser.active) {
        await deactivateAdminUser(session.access_token, createdUser.id)
      }
      return createdUser
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Пользователь успешно создан.')
      setIsCreateUserModalOpen(false)
      setNewUser({ email: '', full_name: '', position: '', department: '', phone: '', password: 'Sbs!2026', role_id: '', active: true })
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['security-session-overview'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось создать пользователя'),
  })

  const toggleUserMutation = useMutation({
    mutationFn: async (payload: { userId: string; active: boolean }) => {
      if (!session?.access_token) throw new Error('No session')
      return payload.active ? activateAdminUser(session.access_token, payload.userId) : deactivateAdminUser(session.access_token, payload.userId)
    },
    onSuccess: async () => {
      setActionError('')
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['security-session-overview'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось изменить статус пользователя'),
  })

  const assignRoleMutation = useMutation({
    mutationFn: async (payload: { userId: string; roleId: string }) => {
      if (!session?.access_token) throw new Error('No session')
      return assignUserRoles(session.access_token, payload.userId, [payload.roleId])
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Роль пользователя обновлена.')
      setRoleAssignUserId('')
      setRoleAssignRoleId('')
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-user-role-map'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-user-roles-detail'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось назначить роль'),
  })

  const settingMutation = useMutation({
    mutationFn: async (payload: { key: string; value: string }) => {
      if (!session?.access_token) throw new Error('No session')
      return updateAdminSetting(session.access_token, payload.key, payload.value)
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Настройка обновлена.')
      await queryClient.invalidateQueries({ queryKey: ['admin-settings'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось изменить настройку'),
  })

  const userPatchMutation = useMutation({
    mutationFn: async (payload: { userId: string; data: { full_name: string; position: string | null; department: string | null; phone: string | null } }) => {
      if (!session?.access_token) throw new Error('No session')
      return updateAdminUser(session.access_token, payload.userId, payload.data)
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Данные пользователя обновлены.')
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-user-by-id'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось обновить пользователя'),
  })

  const users = usersQuery.data ?? []
  const roles = rolesQuery.data ?? []
  const permissions = permissionsQuery.data ?? []
  const auditLogs = auditQuery.data ?? []
  const settings = settingsQuery.data ?? []
  const userRoleMap = userRolesQuery.data ?? new Map<string, AdminRole[]>()

  useEffect(() => {
    if (!selectedRoleId && roles.length > 0) {
      const preferred = roles.find((item) => item.code === 'saas_root') ?? roles[0]
      setSelectedRoleId(preferred.id)
    }
  }, [roles, selectedRoleId])

  const filteredUsers = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return users
    return users.filter((item) => [item.email, item.full_name, item.position, item.department].filter(Boolean).some((value) => String(value).toLowerCase().includes(query)))
  }, [users, search])

  const rolePermissions = useMemo(() => {
    const selectedRole = selectedRoleQuery.data
    if (!selectedRole) return {} as Record<string, typeof permissions>
    const roleCode = selectedRole.code
    let allowed = permissions
    if (roleCode !== 'saas_root') {
      const scopes: Record<string, string[]> = {
        organization_admin: ['tickets', 'assets', 'sla', 'knowledge', 'ai', 'notifications', 'admin', 'security', 'analytics', 'reports', 'integrations', 'automation'],
        it_manager: ['tickets', 'assets', 'sla', 'knowledge', 'ai', 'notifications', 'analytics', 'reports', 'integrations', 'automation'],
        it_agent: ['tickets', 'assets', 'knowledge', 'notifications', 'automation'],
        requester: ['tickets', 'knowledge', 'notifications'],
        security_officer: ['security', 'analytics', 'reports', 'notifications', 'integrations', 'automation', 'tickets', 'knowledge'],
        knowledge_manager: ['knowledge', 'notifications'],
      }
      const modules = scopes[roleCode] ?? ['tickets', 'admin']
      allowed = permissions.filter((item) => modules.includes(item.module))
    }
    return allowed.reduce<Record<string, typeof permissions>>((acc, item) => {
      acc[item.module] = acc[item.module] ? [...acc[item.module], item] : [item]
      return acc
    }, {})
  }, [permissions, selectedRoleQuery.data])

  const filteredAuditLogs = useMemo(() => {
    const query = auditSearch.trim().toLowerCase()
    return auditLogs.filter((item) => {
      const searchMatched =
        !query ||
        includesText(item.actor_email, query) ||
        includesText(item.action, query) ||
        includesText(item.entity_type, query) ||
        includesText(item.entity_id, query) ||
        includesText(item.ip_address, query) ||
        includesText(JSON.stringify(item.metadata), query)
      const dateMatched = (!auditFromDate && !auditToDate) || matchesDateRange(item.created_at, auditFromDate, auditToDate)
      return searchMatched && dateMatched
    })
  }, [auditFromDate, auditLogs, auditSearch, auditToDate])

  const latestAuditEvents = useMemo(() => auditLogs.slice(0, 8), [auditLogs])
  const latestLogins = useMemo(() => (loginEventsQuery.data ?? []).slice(0, 8), [loginEventsQuery.data])

  const security = riskSummaryQuery.data
  const sessionOverview = sessionOverviewQuery.data

  const totalUsers = users.length
  const activeUsers = users.filter((item) => item.is_active).length
  const inactiveUsers = users.filter((item) => !item.is_active).length
  const permissionsCount = permissions.length
  const failedLogins = security?.failed_logins_24h ?? 0
  const riskLevel = String(security?.risk_level ?? 'low').toLowerCase()
  const riskyEventsCount = (security?.recent_security_events ?? []).length
  const adminChangesToday = auditLogs.filter((item) => item.action.startsWith('user_') || item.action.startsWith('role_') || item.action === 'setting_changed').length

  const selectedUser = selectedUserQuery.data
  const selectedUserRoles = detailsUserRolesQuery.data ?? []
  const selectedUserPermissionSummary = useMemo(() => {
    const roleCodes = new Set(selectedUserRoles.map((item) => item.code))
    if (roleCodes.has('saas_root')) {
      return permissions.reduce<Record<string, number>>((acc, item) => {
        acc[item.module] = (acc[item.module] ?? 0) + 1
        return acc
      }, {})
    }
    const scopes: Record<string, string[]> = {
      organization_admin: ['tickets', 'assets', 'sla', 'knowledge', 'ai', 'notifications', 'admin', 'security', 'analytics', 'reports', 'integrations', 'automation'],
      it_manager: ['tickets', 'assets', 'sla', 'knowledge', 'ai', 'notifications', 'analytics', 'reports', 'integrations', 'automation'],
      it_agent: ['tickets', 'assets', 'knowledge', 'notifications', 'automation'],
      requester: ['tickets', 'knowledge', 'notifications'],
      security_officer: ['security', 'analytics', 'reports', 'notifications', 'integrations', 'automation', 'tickets', 'knowledge'],
      knowledge_manager: ['knowledge', 'notifications'],
    }
    const modules = new Set<string>()
    roleCodes.forEach((code) => (scopes[code] ?? []).forEach((moduleName) => modules.add(moduleName)))
    return permissions
      .filter((item) => modules.has(item.module))
      .reduce<Record<string, number>>((acc, item) => {
        acc[item.module] = (acc[item.module] ?? 0) + 1
        return acc
      }, {})
  }, [permissions, selectedUserRoles])

  const selectedUserAuditHistory = useMemo(() => {
    if (!selectedUserId) return []
    return auditLogs.filter((item) => item.entity_type === 'user' && item.entity_id === selectedUserId).slice(0, 12)
  }, [auditLogs, selectedUserId])

  const settingsMap = useMemo(() => {
    return settings.reduce<Record<string, string>>((acc, item) => {
      acc[item.key] = item.value ?? ''
      return acc
    }, {})
  }, [settings])

  useEffect(() => {
    setSettingsEditValue(settingsMap)
  }, [settingsMap])

  const isLoading = usersQuery.isPending || rolesQuery.isPending
  const securityAuditRows = auditLogs.filter((item) => item.entity_type === 'security' || String(item.action).startsWith('security.') || String(item.action).startsWith('login_')).slice(0, 12)

  const canShowTenants = canReadTenants && !(tenantsQuery.isError && !currentTenantQuery.data)

  return (
    <AppShell title="Администрирование" subtitle="Управление пользователями, ролями, правами, аудитом, настройками и безопасностью">
      <section className="admin-section-header">
        <div>
          <p className="eyebrow">ADMIN CONSOLE</p>
          <p className="admin-page-subtitle">Внутренние разделы администрирования с единым контекстом управления.</p>
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

      <section className="admin-subnav" aria-label="Admin subsection navigation">
        {tabs.map((tab) => (
          <button
            type="button"
            className={`admin-subnav-tab ${activeTab === tab.key ? 'active' : ''}`}
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </section>

      {actionError ? <p className="error-message">{actionError}</p> : null}
      {actionMessage ? <p className="state-panel state-panel-loading">{actionMessage}</p> : null}

      <section className="admin-content-area">
      {activeTab === 'overview' ? (
        <>
          <section className="metric-grid dashboard-metrics admin-panel">
            <article className="metric-card">
              <span>Всего пользователей</span>
              <strong>{isLoading ? '…' : totalUsers}</strong>
              <p>Все аккаунты в текущем scope.</p>
            </article>
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
              <span>Permissions</span>
              <strong>{permissionsQuery.isPending ? '…' : permissionsCount}</strong>
              <p>Права, сгруппированные по модулям.</p>
            </article>
            <article className="metric-card">
              <span>Audit events today</span>
              <strong>{auditQuery.isPending ? '…' : latestAuditEvents.length}</strong>
              <p>Последние события административного аудита.</p>
            </article>
            <article className="metric-card">
              <span>Admin changes today</span>
              <strong>{auditQuery.isPending ? '…' : adminChangesToday}</strong>
              <p>Изменения пользователей, ролей и настроек.</p>
            </article>
            <article className="metric-card">
              <span>Failed login attempts</span>
              <strong>{riskSummaryQuery.isPending ? '…' : failedLogins}</strong>
              <p>Неуспешные входы за 24 часа.</p>
            </article>
            <article className="metric-card">
              <span>Security risk summary</span>
              <strong>{riskSummaryQuery.isPending ? '…' : riskLevel.toUpperCase()}</strong>
              <p>Оценка риска на базе audit/login событий.</p>
            </article>
          </section>

          <section className="foundation-card dashboard-split admin-panel">
            <div>
              <p className="eyebrow">QUICK ACTIONS</p>
              <h2>Быстрые действия администратора</h2>
              <div className="analytics-actions">
                <button type="button" onClick={() => setIsCreateUserModalOpen(true)}>
                  Создать пользователя
                </button>
                <button type="button" className="ghost-button" onClick={() => setActiveTab('roles')}>
                  Открыть роли
                </button>
                <button type="button" className="ghost-button" onClick={() => setActiveTab('audit')}>
                  Открыть аудит
                </button>
                <button type="button" className="ghost-button" onClick={() => setActiveTab('security')}>
                  Настройки безопасности
                </button>
              </div>
              <p className="muted">
                Security summary:{' '}
                <span className={riskBadgeClass(riskLevel)}>{riskLevel.toUpperCase()}</span>
              </p>
            </div>
            <div>
              <p className="eyebrow">LATEST LOGINS</p>
              <h2>Последние входы</h2>
              <div className="activity-list">
                {loginEventsQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка последних входов…</p> : null}
                {loginEventsQuery.isError ? (
                  <div className="state-panel state-panel-error">
                    <p>Не удалось загрузить события входа.</p>
                    <button type="button" className="ghost-button" onClick={() => loginEventsQuery.refetch()}>
                      Retry
                    </button>
                  </div>
                ) : null}
                {!loginEventsQuery.isPending && !loginEventsQuery.isError && latestLogins.length === 0 ? (
                  <p className="state-panel state-panel-empty">Логины пока не зафиксированы.</p>
                ) : null}
                {latestLogins.map((event) => (
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
          </section>

          <section className="foundation-card dashboard-split admin-panel">
            <div>
              <p className="eyebrow">LATEST AUDIT EVENTS</p>
              <h2>Недавние audit events</h2>
              <div className="activity-list">
                {auditQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка аудита…</p> : null}
                {auditQuery.isError ? (
                  <div className="state-panel state-panel-error">
                    <p>Не удалось загрузить аудит.</p>
                    <button type="button" className="ghost-button" onClick={() => auditQuery.refetch()}>
                      Retry
                    </button>
                  </div>
                ) : null}
                {!auditQuery.isPending && !auditQuery.isError && latestAuditEvents.length === 0 ? <p className="state-panel state-panel-empty">Событий пока нет.</p> : null}
                {latestAuditEvents.map((event) => (
                  <article className="activity-item" key={event.id}>
                    <header>
                      <strong>{event.action}</strong>
                      <span>{event.actor_email}</span>
                    </header>
                    <p>
                      {event.entity_type} / {event.entity_id ?? '—'}
                    </p>
                    <small>{formatDateTime(event.created_at)}</small>
                  </article>
                ))}
              </div>
            </div>
            <div>
              <p className="eyebrow">SECURITY SUMMARY</p>
              <h2>Security overview</h2>
              <div className="detail-fields">
                <div>
                  <span>Risk level</span>
                  <strong className={riskBadgeClass(riskLevel)}>{riskLevel.toUpperCase()}</strong>
                </div>
                <div>
                  <span>Failed logins</span>
                  <strong>{failedLogins}</strong>
                </div>
                <div>
                  <span>Successful logins</span>
                  <strong>{security?.success_logins_24h ?? 0}</strong>
                </div>
                <div>
                  <span>Risky events</span>
                  <strong>{riskyEventsCount}</strong>
                </div>
              </div>
            </div>
          </section>
        </>
      ) : null}

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
              <button type="button" className="tickets-create-button" onClick={() => setIsCreateUserModalOpen(true)}>
                Создать пользователя
              </button>
            </div>
          </section>

          <section className="foundation-card admin-panel">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>ФИО</th>
                    <th>Email</th>
                    <th>Должность</th>
                    <th>Подразделение</th>
                    <th>Роли</th>
                    <th>Статус</th>
                    <th>Last login</th>
                    <th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {usersQuery.isPending ? (
                    <tr>
                      <td colSpan={8}>
                        <p className="state-panel state-panel-loading">Загрузка пользователей…</p>
                      </td>
                    </tr>
                  ) : null}
                  {usersQuery.isError ? (
                    <tr>
                      <td colSpan={8}>
                        <div className="state-panel state-panel-error">
                          <p>Не удалось загрузить пользователей.</p>
                          <button type="button" className="ghost-button" onClick={() => usersQuery.refetch()}>
                            Retry
                          </button>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                  {!usersQuery.isPending && filteredUsers.length === 0 ? (
                    <tr>
                      <td colSpan={8}>
                        <p className="state-panel state-panel-empty">Пользователи не найдены по текущим фильтрам.</p>
                      </td>
                    </tr>
                  ) : null}
                  {filteredUsers.map((user) => {
                    const roleNames = userRoleMap.get(user.id)?.map((item) => item.name).join(', ') || '—'
                    return (
                      <tr key={user.id}>
                        <td>{user.full_name}</td>
                        <td>{user.email}</td>
                        <td>{user.position ?? '—'}</td>
                        <td>{user.department ?? '—'}</td>
                        <td>{roleNames}</td>
                        <td>{user.is_active ? 'active' : 'inactive'}</td>
                        <td>{formatDateTime(user.last_login_at)}</td>
                        <td>
                          <div className="analytics-actions">
                            <button type="button" className="ghost-button" onClick={() => setSelectedUserId(user.id)}>
                              Детали
                            </button>
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() => {
                                const nextActive = !user.is_active
                                const confirmed = window.confirm(nextActive ? 'Активировать пользователя?' : 'Деактивировать пользователя?')
                                if (!confirmed) return
                                toggleUserMutation.mutate({ userId: user.id, active: nextActive })
                              }}
                              disabled={toggleUserMutation.isPending || assignRoleMutation.isPending}
                            >
                              {user.is_active ? 'Деактивировать' : 'Активировать'}
                            </button>
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() => {
                                setRoleAssignUserId(user.id)
                                setRoleAssignRoleId('')
                              }}
                            >
                              Назначить роли
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === 'roles' ? (
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">ROLES</p>
            <h2>Системные и tenant роли</h2>
            <div className="activity-list">
              {rolesQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка ролей…</p> : null}
              {rolesQuery.isError ? (
                <div className="state-panel state-panel-error">
                  <p>Не удалось загрузить роли.</p>
                  <button type="button" className="ghost-button" onClick={() => rolesQuery.refetch()}>
                    Retry
                  </button>
                </div>
              ) : null}
              {!rolesQuery.isPending && roles.length === 0 ? <p className="state-panel state-panel-empty">Роли не найдены.</p> : null}
              {roles.map((role) => (
                <button type="button" className={`activity-item admin-role-button ${selectedRoleId === role.id ? 'admin-role-active' : ''}`} key={role.id} onClick={() => setSelectedRoleId(role.id)}>
                  <header>
                    <strong>{role.name}</strong>
                    <span>{role.code}</span>
                  </header>
                  <p>{role.description ?? '—'}</p>
                  <small>{role.is_system ? 'System role' : 'Custom role'}</small>
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="eyebrow">ROLE DETAILS</p>
            <h2>{selectedRoleQuery.data?.name ?? 'Выберите роль'}</h2>
            <p>{selectedRoleQuery.data?.description ?? 'Описание роли недоступно.'}</p>
            <p className="muted">Пользователей с ролью: {users.filter((user) => (userRoleMap.get(user.id) ?? []).some((role) => role.id === selectedRoleId)).length}</p>
            <h3>Permissions by module</h3>
            <div className="activity-list">
              {permissionsQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка прав…</p> : null}
              {permissionsQuery.isError ? (
                <div className="state-panel state-panel-error">
                  <p>Не удалось загрузить права.</p>
                  <button type="button" className="ghost-button" onClick={() => permissionsQuery.refetch()}>
                    Retry
                  </button>
                </div>
              ) : null}
              {!permissionsQuery.isPending && Object.entries(rolePermissions).length === 0 ? <p className="state-panel state-panel-empty">Права доступа не найдены.</p> : null}
              <div className="admin-scroll-block">
                {Object.entries(rolePermissions).map(([module, items]) => (
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
              <label className="inline-field">
                <span>Date from</span>
                <input type="date" value={auditFromDate} onChange={(event) => setAuditFromDate(event.target.value)} />
              </label>
              <label className="inline-field">
                <span>Date to</span>
                <input type="date" value={auditToDate} onChange={(event) => setAuditToDate(event.target.value)} />
              </label>
              <label className="inline-field">
                <span>Search</span>
                <input value={auditSearch} onChange={(event) => setAuditSearch(event.target.value)} placeholder="actor, action, ip, metadata" />
              </label>
            </div>
          </section>

          <section className="foundation-card admin-panel">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Дата/время</th>
                    <th>Actor</th>
                    <th>Action</th>
                    <th>Entity type</th>
                    <th>Entity id</th>
                    <th>IP</th>
                    <th>Result / metadata</th>
                    <th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {auditQuery.isPending ? (
                    <tr>
                      <td colSpan={8}>
                        <p className="state-panel state-panel-loading">Загрузка аудита…</p>
                      </td>
                    </tr>
                  ) : null}
                  {auditQuery.isError ? (
                    <tr>
                      <td colSpan={8}>
                        <div className="state-panel state-panel-error">
                          <p>Ошибка загрузки аудита.</p>
                          <button type="button" className="ghost-button" onClick={() => auditQuery.refetch()}>
                            Retry
                          </button>
                        </div>
                      </td>
                    </tr>
                  ) : null}
                  {!auditQuery.isPending && filteredAuditLogs.length === 0 ? (
                    <tr>
                      <td colSpan={8}>
                        <p className="state-panel state-panel-empty">Записи аудита не найдены.</p>
                      </td>
                    </tr>
                  ) : null}
                  {filteredAuditLogs.map((log) => (
                    <tr key={log.id}>
                      <td>{formatDateTime(log.created_at)}</td>
                      <td>{log.actor_email}</td>
                      <td>{log.action}</td>
                      <td>{log.entity_type}</td>
                      <td>{log.entity_id ?? '—'}</td>
                      <td>{log.ip_address ?? '—'}</td>
                      <td>{Object.keys(log.metadata).slice(0, 2).join(', ') || '—'}</td>
                      <td>
                        <button type="button" className="ghost-button" onClick={() => setSelectedAuditId(log.id)}>
                          Детали
                        </button>
                      </td>
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
                  <th>Sensitive</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {settingsQuery.isPending ? (
                  <tr>
                    <td colSpan={6}>
                      <p className="state-panel state-panel-loading">Загрузка настроек…</p>
                    </td>
                  </tr>
                ) : null}
                {settingsQuery.isError ? (
                  <tr>
                    <td colSpan={6}>
                      <div className="state-panel state-panel-error">
                        <p>Не удалось загрузить настройки.</p>
                        <button type="button" className="ghost-button" onClick={() => settingsQuery.refetch()}>
                          Retry
                        </button>
                      </div>
                    </td>
                  </tr>
                ) : null}
                {!settingsQuery.isPending && settings.length === 0 ? (
                  <tr>
                    <td colSpan={6}>
                      <p className="state-panel state-panel-empty">Настройки не найдены.</p>
                    </td>
                  </tr>
                ) : null}
                {settings.map((item) => (
                  <tr key={item.id}>
                    <td>{item.key}</td>
                    <td>{item.is_sensitive ? '***' : settingsEditValue[item.key] ?? item.value ?? '—'}</td>
                    <td>{item.description ?? '—'}</td>
                    <td>{item.is_sensitive ? 'yes' : 'no'}</td>
                    <td>{formatDateTime(item.updated_at)}</td>
                    <td>
                      {!item.is_sensitive ? (
                        <div className="admin-setting-actions">
                          <input
                            value={settingsEditValue[item.key] ?? item.value ?? ''}
                            onChange={(event) => setSettingsEditValue((prev) => ({ ...prev, [item.key]: event.target.value }))}
                            disabled={settingMutation.isPending}
                          />
                          <button
                            type="button"
                            className="ghost-button"
                            disabled={settingMutation.isPending}
                            onClick={() => {
                              const confirmed = window.confirm(`Сохранить новое значение для ${item.key}?`)
                              if (!confirmed) return
                              settingMutation.mutate({ key: item.key, value: settingsEditValue[item.key] ?? '' })
                            }}
                          >
                            Сохранить
                          </button>
                        </div>
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
              <span>Locked/inactive users</span>
              <strong>{sessionOverviewQuery.isPending ? '…' : sessionOverview?.inactive_users ?? 0}</strong>
              <p>Неактивные или заблокированные пользователи.</p>
            </article>
            <article className="metric-card">
              <span>Risky events</span>
              <strong>{riskSummaryQuery.isPending ? '…' : riskyEventsCount}</strong>
              <p>Последние сигналы security.</p>
            </article>
            <article className="metric-card">
              <span>Admin changes today</span>
              <strong>{auditQuery.isPending ? '…' : adminChangesToday}</strong>
              <p>Изменения в users, roles и settings.</p>
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
                {loginEventsQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка login-событий…</p> : null}
                {!loginEventsQuery.isPending && (loginEventsQuery.data ?? []).length === 0 ? <p className="state-panel state-panel-empty">Событий входа не найдено.</p> : null}
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
              <h2>Latest security audit events</h2>
              <div className="activity-list">
                {auditQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка security событий…</p> : null}
                {!auditQuery.isPending && securityAuditRows.length === 0 ? <p className="state-panel state-panel-empty">Событий безопасности не найдено.</p> : null}
                {securityAuditRows.map((event) => (
                  <article className="activity-item" key={event.id}>
                    <header>
                      <strong>{String(event.action)}</strong>
                      <span>{String(event.actor_email)}</span>
                    </header>
                    <p>{formatDateTime(String(event.created_at))}</p>
                    <small>{event.ip_address ?? 'n/a'}</small>
                  </article>
                ))}
              </div>
              <div className="foundation-card analytics-inline-card admin-panel">
                <div>
                  <p className="eyebrow">RISK SUMMARY</p>
                  <h3>Рекомендации</h3>
                  <div className="activity-list">
                    <article className="activity-item">
                      <header>
                        <strong>MFA demo</strong>
                        <span className={riskBadgeClass('medium')}>MEDIUM</span>
                      </header>
                      <p>Включить MFA demo для privileged ролей.</p>
                    </article>
                    <article className="activity-item">
                      <header>
                        <strong>Inactive users</strong>
                        <span className={riskBadgeClass('low')}>LOW</span>
                      </header>
                      <p>Проверить и очистить stale аккаунты.</p>
                    </article>
                    <article className="activity-item">
                      <header>
                        <strong>Failed logins</strong>
                        <span className={riskBadgeClass(failedLogins > 5 ? 'high' : 'medium')}>{failedLogins > 5 ? 'HIGH' : 'MEDIUM'}</span>
                      </header>
                      <p>Проверить рост неуспешных входов за 24 часа.</p>
                    </article>
                    <article className="activity-item">
                      <header>
                        <strong>Admin changes</strong>
                        <span className={riskBadgeClass(adminChangesToday > 8 ? 'high' : 'low')}>{adminChangesToday > 8 ? 'HIGH' : 'LOW'}</span>
                      </header>
                      <p>Сверить массовые изменения с изменениями регламента.</p>
                    </article>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === 'tenants' ? (
        <section className="foundation-card admin-panel">
          <div>
            <p className="eyebrow">TENANTS / ORGANIZATION</p>
            <h2>Организационный контур</h2>
          </div>
          <div className="activity-list">
            {canShowTenants && tenantsQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка tenants…</p> : null}
            {canShowTenants && tenantsQuery.isError ? (
              <div className="state-panel state-panel-error">
                <p>Доступ к полному списку tenants ограничен текущей ролью.</p>
                <button type="button" className="ghost-button" onClick={() => tenantsQuery.refetch()}>
                  Retry
                </button>
              </div>
            ) : null}
            {!canShowTenants || (!tenantsQuery.isPending && (tenantsQuery.data ?? []).length === 0) ? (
              <div className="detail-fields">
                <div>
                  <span>Current organization</span>
                  <strong>{currentTenantQuery.data?.name ?? 'SBS Demo University'}</strong>
                </div>
                <div>
                  <span>SaaS mode</span>
                  <strong>Enabled</strong>
                </div>
                <div>
                  <span>Tenant isolation enabled</span>
                  <strong>True</strong>
                </div>
                <div>
                  <span>Demo tenant</span>
                  <strong>SBS Demo University</strong>
                </div>
              </div>
            ) : null}
            {(tenantsQuery.data ?? []).length > 0 ? (
              <div className="ticket-table-wrap">
                <table className="ticket-table">
                  <thead>
                    <tr>
                      <th>Организация</th>
                      <th>Tenant code</th>
                      <th>Status</th>
                      <th>Users count</th>
                      <th>Modules enabled</th>
                      <th>Created at</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(tenantsQuery.data ?? []).map((tenant) => (
                      <tr key={tenant.id}>
                        <td>{tenant.name}</td>
                        <td>{tenant.slug}</td>
                        <td>{tenant.status}</td>
                        <td>{users.filter((user) => user.tenant_id === tenant.id).length}</td>
                        <td>tickets, assets, knowledge, ai, notifications</td>
                        <td>—</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}
      </section>

      {isCreateUserModalOpen ? (
        <div className="modal-backdrop" onClick={closeAllModals}>
          <section className="modal-card modal-card-xl" onClick={(event) => event.stopPropagation()}>
            <header className="modal-header">
              <div>
                <p className="eyebrow">CREATE USER</p>
                <h2>Новый пользователь</h2>
              </div>
              <button type="button" className="ghost-button" onClick={closeAllModals}>
                Закрыть
              </button>
            </header>
            <div className="modal-body">
              <form
                className="modal-form"
                onSubmit={(event) => {
                  event.preventDefault()
                  setActionError('')
                  setActionMessage('')
                  createUserMutation.mutate()
                }}
              >
                <div className="form-grid">
                  <label>
                    <span>full_name</span>
                    <input required value={newUser.full_name} onChange={(event) => setNewUser((prev) => ({ ...prev, full_name: event.target.value }))} />
                  </label>
                  <label>
                    <span>email</span>
                    <input required type="email" value={newUser.email} onChange={(event) => setNewUser((prev) => ({ ...prev, email: event.target.value }))} />
                  </label>
                  <label>
                    <span>password</span>
                    <input required type="text" value={newUser.password} onChange={(event) => setNewUser((prev) => ({ ...prev, password: event.target.value }))} />
                  </label>
                  <label>
                    <span>position</span>
                    <input value={newUser.position} onChange={(event) => setNewUser((prev) => ({ ...prev, position: event.target.value }))} />
                  </label>
                  <label>
                    <span>department</span>
                    <input value={newUser.department} onChange={(event) => setNewUser((prev) => ({ ...prev, department: event.target.value }))} />
                  </label>
                  <label>
                    <span>phone</span>
                    <input value={newUser.phone} onChange={(event) => setNewUser((prev) => ({ ...prev, phone: event.target.value }))} />
                  </label>
                  <label>
                    <span>role</span>
                    <select value={newUser.role_id} onChange={(event) => setNewUser((prev) => ({ ...prev, role_id: event.target.value }))}>
                      <option value="">Без роли</option>
                      {roles.map((role) => (
                        <option key={role.id} value={role.id}>
                          {role.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>active</span>
                    <select value={newUser.active ? 'true' : 'false'} onChange={(event) => setNewUser((prev) => ({ ...prev, active: event.target.value === 'true' }))}>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  </label>
                </div>
                <footer className="modal-footer">
                  <button type="button" className="ghost-button" onClick={closeAllModals} disabled={createUserMutation.isPending}>
                    Отмена
                  </button>
                  <button type="submit" disabled={createUserMutation.isPending}>
                    {createUserMutation.isPending ? 'Создание…' : 'Создать пользователя'}
                  </button>
                </footer>
              </form>
            </div>
          </section>
        </div>
      ) : null}

      {selectedUserId ? (
        <div className="modal-backdrop" onClick={closeAllModals}>
          <section className="modal-card modal-card-xl" onClick={(event) => event.stopPropagation()}>
            <header className="modal-header">
              <div>
                <p className="eyebrow">USER DETAILS</p>
                <h2>{selectedUser?.full_name ?? 'Пользователь'}</h2>
              </div>
              <button type="button" className="ghost-button" onClick={closeAllModals}>
                Закрыть
              </button>
            </header>
            <div className="modal-body">
              {selectedUserQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка профиля пользователя…</p> : null}
              {selectedUserQuery.isError ? (
                <div className="state-panel state-panel-error">
                  <p>Не удалось загрузить детали пользователя.</p>
                  <button type="button" className="ghost-button" onClick={() => selectedUserQuery.refetch()}>
                    Retry
                  </button>
                </div>
              ) : null}
              {selectedUser ? (
                <>
                  <div className="detail-fields">
                    <div>
                      <span>ФИО</span>
                      <strong>{selectedUser.full_name}</strong>
                    </div>
                    <div>
                      <span>email</span>
                      <strong>{selectedUser.email}</strong>
                    </div>
                    <div>
                      <span>department</span>
                      <strong>{selectedUser.department ?? '—'}</strong>
                    </div>
                    <div>
                      <span>position</span>
                      <strong>{selectedUser.position ?? '—'}</strong>
                    </div>
                    <div>
                      <span>phone</span>
                      <strong>{selectedUser.phone ?? '—'}</strong>
                    </div>
                    <div>
                      <span>roles</span>
                      <strong>{selectedUserRoles.map((item) => item.name).join(', ') || '—'}</strong>
                    </div>
                    <div>
                      <span>is_active</span>
                      <strong>{String(selectedUser.is_active)}</strong>
                    </div>
                    <div>
                      <span>is_superuser</span>
                      <strong>{String(selectedUser.is_superuser)}</strong>
                    </div>
                    <div>
                      <span>last_login_at</span>
                      <strong>{formatDateTime(selectedUser.last_login_at)}</strong>
                    </div>
                    <div>
                      <span>created_at</span>
                      <strong>{formatDateTime(selectedUser.created_at)}</strong>
                    </div>
                  </div>
                  <section className="admin-panel">
                    <p className="eyebrow">PERMISSIONS SUMMARY</p>
                    <div className="activity-list">
                      {Object.entries(selectedUserPermissionSummary).map(([moduleName, count]) => (
                        <article className="activity-item" key={moduleName}>
                          <header>
                            <strong>{moduleName}</strong>
                            <span>{count}</span>
                          </header>
                        </article>
                      ))}
                      {Object.entries(selectedUserPermissionSummary).length === 0 ? <p className="state-panel state-panel-empty">Сводка прав недоступна.</p> : null}
                    </div>
                  </section>
                  <section className="admin-panel">
                    <p className="eyebrow">AUDIT HISTORY</p>
                    <div className="activity-list">
                      {selectedUserAuditHistory.length === 0 ? <p className="state-panel state-panel-empty">История аудита пользователя недоступна.</p> : null}
                      {selectedUserAuditHistory.map((item) => (
                        <article className="activity-item" key={item.id}>
                          <header>
                            <strong>{item.action}</strong>
                            <span>{formatDateTime(item.created_at)}</span>
                          </header>
                          <p>{JSON.stringify(item.metadata)}</p>
                        </article>
                      ))}
                    </div>
                  </section>
                  <section className="admin-panel">
                    <p className="eyebrow">EDIT PROFILE</p>
                    <form
                      className="modal-form"
                      onSubmit={(event) => {
                        event.preventDefault()
                        const form = event.currentTarget
                        const data = new FormData(form)
                        userPatchMutation.mutate({
                          userId: selectedUser.id,
                          data: {
                            full_name: String(data.get('full_name') ?? selectedUser.full_name),
                            position: String(data.get('position') ?? selectedUser.position ?? '') || null,
                            department: String(data.get('department') ?? selectedUser.department ?? '') || null,
                            phone: String(data.get('phone') ?? selectedUser.phone ?? '') || null,
                          },
                        })
                      }}
                    >
                      <div className="form-grid">
                        <label>
                          <span>full_name</span>
                          <input name="full_name" defaultValue={selectedUser.full_name} />
                        </label>
                        <label>
                          <span>position</span>
                          <input name="position" defaultValue={selectedUser.position ?? ''} />
                        </label>
                        <label>
                          <span>department</span>
                          <input name="department" defaultValue={selectedUser.department ?? ''} />
                        </label>
                        <label>
                          <span>phone</span>
                          <input name="phone" defaultValue={selectedUser.phone ?? ''} />
                        </label>
                      </div>
                      <footer className="modal-footer">
                        <button type="submit" disabled={userPatchMutation.isPending}>
                          {userPatchMutation.isPending ? 'Сохранение…' : 'Сохранить'}
                        </button>
                      </footer>
                    </form>
                  </section>
                </>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {roleAssignUserId ? (
        <div className="modal-backdrop" onClick={closeAllModals}>
          <section className="modal-card" onClick={(event) => event.stopPropagation()}>
            <header className="modal-header">
              <div>
                <p className="eyebrow">ASSIGN USER ROLES</p>
                <h2>Назначение роли пользователю</h2>
              </div>
              <button type="button" className="ghost-button" onClick={closeAllModals}>
                Закрыть
              </button>
            </header>
            <div className="modal-body">
              <label>
                <span>role</span>
                <select value={roleAssignRoleId} onChange={(event) => setRoleAssignRoleId(event.target.value)}>
                  <option value="">Выберите роль</option>
                  {roles.map((role: AdminRole) => (
                    <option key={role.id} value={role.id}>
                      {role.code}
                    </option>
                  ))}
                </select>
              </label>
              <footer className="modal-footer">
                <button type="button" className="ghost-button" onClick={closeAllModals}>
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={!roleAssignRoleId || assignRoleMutation.isPending}
                  onClick={() => {
                    if (!roleAssignRoleId) return
                    assignRoleMutation.mutate({ userId: roleAssignUserId, roleId: roleAssignRoleId })
                  }}
                >
                  {assignRoleMutation.isPending ? 'Назначение…' : 'Назначить роль'}
                </button>
              </footer>
            </div>
          </section>
        </div>
      ) : null}

      {selectedAuditId ? (
        <div className="modal-backdrop" onClick={closeAllModals}>
          <section className="modal-card modal-card-xl" onClick={(event) => event.stopPropagation()}>
            <header className="modal-header">
              <div>
                <p className="eyebrow">AUDIT LOG DETAILS</p>
                <h2>{selectedAuditQuery.data?.action ?? 'Событие аудита'}</h2>
              </div>
              <button type="button" className="ghost-button" onClick={closeAllModals}>
                Закрыть
              </button>
            </header>
            <div className="modal-body">
              {selectedAuditQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка деталей аудита…</p> : null}
              {selectedAuditQuery.isError ? (
                <div className="state-panel state-panel-error">
                  <p>Не удалось загрузить событие аудита.</p>
                  <button type="button" className="ghost-button" onClick={() => selectedAuditQuery.refetch()}>
                    Retry
                  </button>
                </div>
              ) : null}
              {selectedAuditQuery.data ? (
                <>
                  <div className="detail-fields">
                    <div>
                      <span>Actor</span>
                      <strong>{selectedAuditQuery.data.actor_email}</strong>
                    </div>
                    <div>
                      <span>Entity</span>
                      <strong>{selectedAuditQuery.data.entity_type}</strong>
                    </div>
                    <div>
                      <span>Entity id</span>
                      <strong>{selectedAuditQuery.data.entity_id ?? '—'}</strong>
                    </div>
                    <div>
                      <span>user_agent</span>
                      <strong>{selectedAuditQuery.data.user_agent ?? '—'}</strong>
                    </div>
                    <div>
                      <span>ip_address</span>
                      <strong>{selectedAuditQuery.data.ip_address ?? '—'}</strong>
                    </div>
                    <div>
                      <span>created_at</span>
                      <strong>{formatDateTime(selectedAuditQuery.data.created_at)}</strong>
                    </div>
                  </div>
                  <p className="eyebrow">metadata JSON</p>
                  <pre className="analytics-export-preview">{JSON.stringify(selectedAuditQuery.data.metadata, null, 2)}</pre>
                </>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}
    </AppShell>
  )
}