import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'
import MfaEnrollmentPanel from '../components/MfaEnrollmentPanel'
import ConfigurationCenterPanel from '../components/ConfigurationCenterPanel'
import TenantExperiencePanel from '../components/TenantExperiencePanel'
import LocalizedContentPanel from '../components/LocalizedContentPanel'
import {
  activateAdminUser,
  adminResetUserMfa,
  assignUserRoles,
  createAdminRole,
  createAdminUser,
  createTenant,
  deactivateAdminUser,
  fetchAdminAuditLogById,
  fetchAdminAuditLogs,
  fetchAdminAiProviderConfig,
  fetchAdminPermissions,
  fetchAdminRoleById,
  fetchAdminRolePermissions,
  fetchAdminRoles,
  fetchAdminUserById,
  fetchAdminUserExternalIdentities,
  fetchAdminSettings,
  fetchCurrentTenant,
  fetchIdentityProviderStatus,
  fetchUserRoles,
  fetchLoginEvents,
  fetchMfaOverview,
  fetchRiskSummary,
  fetchSecurityOverview,
  fetchSecuritySessions,
  fetchTenants,
  patchAdminRole,
  patchAdminAiProviderConfig,
  patchCurrentTenant,
  replaceAdminRolePermissions,
  resetAdminUserPassword,
  revokeSecuritySession,
  revokeUserSessions,
  testAdminAiProviderConfig,
  testIdentityProvider,
  linkAdminUserExternalIdentity,
  unlinkAdminUserExternalIdentity,
  fetchAdminUsers,
  updateAdminUser,
  type AdminAiProviderConfigPatch,
  type AdminAiProviderConfigTestResult,
  type AdminPermission,
  type AdminRole,
  type IdentityProviderTestResult,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import LocalizedContent from '../experience/LocalizedContent'

const tabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'users', label: 'Пользователи' },
  { key: 'roles', label: 'Роли и права' },
  { key: 'audit', label: 'Аудит' },
  { key: 'settings', label: 'Настройки' },
  { key: 'identity', label: 'Identity & SSO' },
  { key: 'security', label: 'Security' },
  { key: 'tenants', label: 'Организация' },
] as const

const permissionGuidance: Record<string, string> = {
  'tickets.scope.all': 'Видимость всех заявок организации.',
  'tickets.scope.assigned': 'Видимость назначенных на пользователя и пока не назначенных заявок.',
  'tickets.scope.requester': 'Видимость только собственных заявок пользователя.',
  'tickets.self_assign': 'Разрешает взять неназначенную заявку на себя и включает assigned-видимость.',
  'requests.scope.all': 'Видимость всех сервисных запросов организации.',
  'requests.scope.requester': 'Видимость только собственных сервисных запросов.',
  'monitoring.events.read': 'Чтение tenant-wide событий мониторинга и correlation groups.',
  'monitoring.events.manage': 'Acknowledge и escalation событий мониторинга.',
  'major_incidents.read': 'Чтение Major Incident Command Center.',
  'major_incidents.manage': 'Объявление и управление Major Incidents, действиями и PIR.',
}

const permissionModuleLabels: Record<string, string> = {
  admin: 'Администрирование',
  ai: 'AI и Copilot',
  analytics: 'Аналитика',
  assets: 'Активы и CMDB',
  automation: 'Автоматизация',
  catalog: 'Каталог услуг',
  changes: 'Изменения',
  configuration: 'Конфигурация платформы',
  data: 'Управление данными',
  email: 'Email Operations',
  integrations: 'Интеграции',
  knowledge: 'База знаний',
  monitoring: 'Мониторинг событий',
  notifications: 'Уведомления',
  problems: 'Проблемы и KEDB',
  reports: 'Отчётность',
  requests: 'Сервисные запросы',
  search: 'Глобальный поиск',
  security: 'Безопасность и аудит',
  sla: 'SLA и обязательства',
  teams: 'Teams Collaboration',
  tenant: 'Организация',
  tickets: 'Заявки Service Desk',
}

type TabKey = (typeof tabs)[number]['key']
type AiProviderKey = 'mock' | 'openai' | 'gemini'

const defaultAiConfigDraft = {
  provider: 'mock' as AiProviderKey,
  openai_model: 'gpt-4o-mini',
  openai_base_url: 'https://api.openai.com/v1',
  gemini_model: 'gemini-2.0-flash-exp',
  pii_redaction_enabled: true,
  request_timeout_seconds: '15',
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
  const { formatDateTime, translate } = useTenantExperience()
  const [searchParams, setSearchParams] = useSearchParams()
  const isRoot = session?.user.role === 'saas_root'
  const effectivePermissions = new Set(session?.user.permissions ?? [])
  const hasPermission = (...codes: string[]) => (
    isRoot || codes.some((code) => effectivePermissions.has(code))
  )
  const canReadUsers = hasPermission('admin.users.read')
  const canCreateUsers = hasPermission('admin.users.create')
  const canManageUsers = hasPermission('admin.users.update')
  const canReadRoles = hasPermission('admin.roles.read')
  const canProvisionUsers = canCreateUsers && canReadRoles
  const canManageRoles = hasPermission('admin.roles.manage')
  const canReadPermissions = hasPermission('admin.permissions.read')
  const canReadAudit = hasPermission('security.audit.read')
  const canReadSettings = hasPermission('admin.settings.read')
  const canManageSettings = hasPermission('admin.settings.update')
  const canReadConfiguration = hasPermission('admin.configuration.read')
  const canReadLoginEvents = hasPermission('security.login_events.read')
  const canReadSessions = hasPermission('security.sessions.read')
  const canManageSessions = hasPermission('security.sessions.manage')
  const canReadMfa = hasPermission('security.mfa.read')
  const canManageMfa = hasPermission('security.mfa.manage')
  const canReadTenants = isRoot
  const canReadTenantProfile = hasPermission('tenant.profile.read')
  const canManageTenantProfile =
    !isRoot && effectivePermissions.has('tenant.profile.manage')
  const canManageGlobalAiProvider = isRoot
  const canViewSecurity = (
    canReadLoginEvents
    || canReadSessions
    || canReadAudit
    || canReadMfa
  )
  const availableTabs = useMemo(
    () => tabs.filter((tab) => ({
      overview: true,
      users: canReadUsers,
      roles: canReadRoles,
      audit: canReadAudit,
      settings: canReadSettings || canReadConfiguration,
      identity: canReadSettings,
      security: canViewSecurity,
      tenants: canReadTenants || canReadTenantProfile,
    })[tab.key]),
    [
      canReadAudit,
      canReadRoles,
      canReadConfiguration,
      canReadSettings,
      canReadTenants,
      canReadTenantProfile,
      canReadUsers,
      canViewSecurity,
    ],
  )
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
  const [roleAssignRoleIds, setRoleAssignRoleIds] = useState<string[]>([])
  const [isCreateUserModalOpen, setIsCreateUserModalOpen] = useState(false)
  const [isCreateRoleModalOpen, setIsCreateRoleModalOpen] = useState(false)
  const [rolePermissionDraft, setRolePermissionDraft] = useState<string[]>([])
  const [permissionSearch, setPermissionSearch] = useState('')
  const [newPasswordDraft, setNewPasswordDraft] = useState('')
  const [aiConfigDraft, setAiConfigDraft] = useState(defaultAiConfigDraft)
  const [openaiApiKeyDraft, setOpenaiApiKeyDraft] = useState('')
  const [geminiApiKeyDraft, setGeminiApiKeyDraft] = useState('')
  const [aiTestResult, setAiTestResult] = useState<AdminAiProviderConfigTestResult | null>(null)
  const [identityTestResult, setIdentityTestResult] = useState<IdentityProviderTestResult | null>(null)
  const [externalIdentitySubject, setExternalIdentitySubject] = useState('')
  const [externalIdentityEmail, setExternalIdentityEmail] = useState('')
  const [actionMessage, setActionMessage] = useState<string>('')
  const [actionError, setActionError] = useState<string>('')
  const [newUser, setNewUser] = useState({
    tenant_id: '',
    email: '',
    full_name: '',
    position: '',
    department: '',
    location: '',
    cost_center: '',
    phone: '',
    password: '',
    role_ids: [] as string[],
    active: true,
  })
  const [newRole, setNewRole] = useState({
    code: '',
    name: '',
    description: '',
  })

  useEffect(() => {
    const linkedTab = searchParams.get('tab')
    if (linkedTab && availableTabs.some((tab) => tab.key === linkedTab)) {
      setActiveTab(linkedTab as TabKey)
      const next = new URLSearchParams(searchParams)
      next.delete('tab')
      setSearchParams(next, { replace: true })
      return
    }
    const linkedUserId = searchParams.get('user')
    if (!linkedUserId) return
    setActiveTab('users')
    setSelectedUserId(linkedUserId)
    const next = new URLSearchParams(searchParams)
    next.delete('user')
    setSearchParams(next, { replace: true })
  }, [availableTabs, searchParams, setSearchParams])

  useEffect(() => {
    if (!availableTabs.some((tab) => tab.key === activeTab)) {
      setActiveTab(availableTabs[0]?.key ?? 'overview')
    }
  }, [activeTab, availableTabs])

  const closeAllModals = () => {
    setIsCreateUserModalOpen(false)
    setIsCreateRoleModalOpen(false)
    setSelectedUserId('')
    setSelectedAuditId('')
    setRoleAssignUserId('')
    setRoleAssignRoleIds([])
    setNewPasswordDraft('')
    setExternalIdentitySubject('')
    setExternalIdentityEmail('')
  }

  const createRoleDialogRef = useDialogFocusTrap<HTMLElement>(
    isCreateRoleModalOpen,
    closeAllModals,
  )
  const createUserDialogRef = useDialogFocusTrap<HTMLElement>(
    isCreateUserModalOpen,
    closeAllModals,
  )
  const userDetailDialogRef = useDialogFocusTrap<HTMLElement>(
    Boolean(selectedUserId),
    closeAllModals,
  )
  const roleAssignDialogRef = useDialogFocusTrap<HTMLElement>(
    Boolean(roleAssignUserId),
    closeAllModals,
  )
  const auditDetailDialogRef = useDialogFocusTrap<HTMLElement>(
    Boolean(selectedAuditId),
    closeAllModals,
  )

  const usersQuery = useQuery({
    queryKey: ['admin-users', session?.access_token, roleFilter, activeFilter],
    queryFn: () =>
      fetchAdminUsers(session?.access_token ?? '', {
        role_id: roleFilter,
        active: activeFilter === 'ALL' ? 'ALL' : activeFilter === 'ACTIVE',
      }),
    enabled: Boolean(session?.access_token && canReadUsers),
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
    enabled: Boolean(session?.access_token && canReadTenantProfile),
    retry: false,
  })

  const rolesQuery = useQuery({
    queryKey: ['admin-roles', session?.access_token],
    queryFn: () => fetchAdminRoles(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadRoles),
  })

  const selectedRoleQuery = useQuery({
    queryKey: ['admin-role-by-id', session?.access_token, selectedRoleId],
    queryFn: () => fetchAdminRoleById(session?.access_token ?? '', selectedRoleId),
    enabled: Boolean(session?.access_token && canReadRoles && selectedRoleId),
  })

  const selectedRolePermissionsQuery = useQuery({
    queryKey: ['admin-role-permissions', session?.access_token, selectedRoleId],
    queryFn: () => fetchAdminRolePermissions(session?.access_token ?? '', selectedRoleId),
    enabled: Boolean(session?.access_token && canReadRoles && selectedRoleId),
  })

  const permissionsQuery = useQuery({
    queryKey: ['admin-permissions', session?.access_token],
    queryFn: () => fetchAdminPermissions(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadPermissions),
  })

  const auditQuery = useQuery({
    queryKey: ['admin-audit', session?.access_token, auditActionFilter, auditActorFilter, auditEntityFilter],
    queryFn: () =>
      fetchAdminAuditLogs(session?.access_token ?? '', {
        action: auditActionFilter || undefined,
        actor_email: auditActorFilter || undefined,
        entity_type: auditEntityFilter || undefined,
      }),
    enabled: Boolean(session?.access_token && canReadAudit),
  })

  const selectedAuditQuery = useQuery({
    queryKey: ['admin-audit-by-id', session?.access_token, selectedAuditId],
    queryFn: () => fetchAdminAuditLogById(session?.access_token ?? '', selectedAuditId),
    enabled: Boolean(session?.access_token && canReadAudit && selectedAuditId),
  })

  const settingsQuery = useQuery({
    queryKey: ['admin-settings', session?.access_token],
    queryFn: () => fetchAdminSettings(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadSettings),
  })

  const aiProviderConfigQuery = useQuery({
    queryKey: ['admin-ai-provider-config', session?.access_token],
    queryFn: () => fetchAdminAiProviderConfig(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadSettings),
  })

  const identityProviderQuery = useQuery({
    queryKey: ['admin-identity-provider', session?.access_token],
    queryFn: () => fetchIdentityProviderStatus(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadSettings),
    retry: false,
  })

  const loginEventsQuery = useQuery({
    queryKey: ['security-login-events', session?.access_token],
    queryFn: () => fetchLoginEvents(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadLoginEvents),
  })

  const sessionOverviewQuery = useQuery({
    queryKey: ['security-session-overview', session?.access_token],
    queryFn: () => fetchSecurityOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadSessions),
  })

  const securitySessionsQuery = useQuery({
    queryKey: ['security-sessions', session?.access_token],
    queryFn: () => fetchSecuritySessions(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadSessions),
  })

  const riskSummaryQuery = useQuery({
    queryKey: ['security-risk-summary', session?.access_token],
    queryFn: () => fetchRiskSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadAudit),
  })

  const mfaOverviewQuery = useQuery({
    queryKey: ['security-mfa-overview', session?.access_token],
    queryFn: () => fetchMfaOverview(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadMfa),
  })

  const selectedUserQuery = useQuery({
    queryKey: ['admin-user-by-id', session?.access_token, selectedUserId],
    queryFn: () => fetchAdminUserById(session?.access_token ?? '', selectedUserId),
    enabled: Boolean(session?.access_token && canReadUsers && selectedUserId),
  })

  const selectedUserExternalIdentitiesQuery = useQuery({
    queryKey: ['admin-user-external-identities', session?.access_token, selectedUserId],
    queryFn: () => fetchAdminUserExternalIdentities(session?.access_token ?? '', selectedUserId),
    enabled: Boolean(session?.access_token && canReadUsers && selectedUserId),
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
    enabled: Boolean(
      session?.access_token
      && canReadRoles
      && (usersQuery.data ?? []).length > 0
    ),
    staleTime: 30000,
  })

  const detailsUserRolesQuery = useQuery({
    queryKey: ['admin-user-roles-detail', session?.access_token, selectedUserId],
    queryFn: async () => {
      if (!session?.access_token || !selectedUserId) return [] as AdminRole[]
      return fetchUserRoles(session.access_token, selectedUserId)
    },
    enabled: Boolean(session?.access_token && canReadRoles && selectedUserId),
  })

  const detailsUserRolePermissionsQuery = useQuery({
    queryKey: [
      'admin-user-role-permissions',
      session?.access_token,
      selectedUserId,
      (detailsUserRolesQuery.data ?? []).map((role) => role.id).join(','),
    ],
    queryFn: async () => {
      if (!session?.access_token) return [] as AdminPermission[]
      const rolePermissions = await Promise.all(
        (detailsUserRolesQuery.data ?? []).map((role) =>
          fetchAdminRolePermissions(session.access_token, role.id),
        ),
      )
      return Array.from(
        new Map(rolePermissions.flat().map((permission) => [permission.id, permission])).values(),
      )
    },
    enabled: Boolean(
      session?.access_token
      && canReadRoles
      && selectedUserId
      && detailsUserRolesQuery.isSuccess
    ),
  })

  const roleAssignCurrentRolesQuery = useQuery({
    queryKey: ['admin-user-roles-assignment', session?.access_token, roleAssignUserId],
    queryFn: async () => {
      if (!session?.access_token || !roleAssignUserId) return [] as AdminRole[]
      return fetchUserRoles(session.access_token, roleAssignUserId)
    },
    enabled: Boolean(
      session?.access_token
      && canManageRoles
      && roleAssignUserId
    ),
  })

  const roleAssignPermissionsQuery = useQuery({
    queryKey: [
      'admin-role-assignment-permissions',
      session?.access_token,
      [...roleAssignRoleIds].sort().join(','),
    ],
    queryFn: async () => {
      if (!session?.access_token) return [] as AdminPermission[]
      const rolePermissions = await Promise.all(
        roleAssignRoleIds.map((roleId) =>
          fetchAdminRolePermissions(session.access_token, roleId),
        ),
      )
      return Array.from(
        new Map(
          rolePermissions
            .flat()
            .map((permission) => [permission.id, permission]),
        ).values(),
      ).sort((left, right) => left.code.localeCompare(right.code))
    },
    enabled: Boolean(
      session?.access_token
      && canManageRoles
      && roleAssignUserId
      && roleAssignRoleIds.length > 0
    ),
  })

  const createUserRolePermissionsQuery = useQuery({
    queryKey: [
      'admin-create-user-role-permissions',
      session?.access_token,
      [...newUser.role_ids].sort().join(','),
    ],
    queryFn: async () => {
      if (!session?.access_token) return [] as AdminPermission[]
      const rolePermissions = await Promise.all(
        newUser.role_ids.map((roleId) =>
          fetchAdminRolePermissions(session.access_token, roleId),
        ),
      )
      return Array.from(
        new Map(
          rolePermissions
            .flat()
            .map((permission) => [permission.id, permission]),
        ).values(),
      ).sort((left, right) => left.code.localeCompare(right.code))
    },
    enabled: Boolean(
      session?.access_token
      && canProvisionUsers
      && canReadRoles
      && newUser.role_ids.length > 0
    ),
  })

  const createUserMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      if (!canCreateUsers) throw new Error('Недостаточно прав для создания пользователя')
      const createdUser = await createAdminUser(session.access_token, {
        email: newUser.email,
        full_name: newUser.full_name,
        password: newUser.password,
        position: newUser.position || null,
        department: newUser.department || null,
        location: newUser.location || null,
        cost_center: newUser.cost_center || null,
        phone: newUser.phone || null,
        tenant_id: session.user.role === 'saas_root' ? newUser.tenant_id || null : undefined,
        role_ids: newUser.role_ids,
      })
      if (!newUser.active && canManageUsers) {
        await deactivateAdminUser(session.access_token, createdUser.id)
      }
      return createdUser
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Пользователь успешно создан.')
      setIsCreateUserModalOpen(false)
      setNewUser({ tenant_id: '', email: '', full_name: '', position: '', department: '', location: '', cost_center: '', phone: '', password: '', role_ids: [], active: true })
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['security-session-overview'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось создать пользователя'),
  })

  const toggleUserMutation = useMutation({
    mutationFn: async (payload: { userId: string; active: boolean }) => {
      if (!session?.access_token) throw new Error('No session')
      if (!canManageUsers) throw new Error('Недостаточно прав для изменения пользователя')
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
    mutationFn: async (payload: { userId: string; roleIds: string[] }) => {
      if (!session?.access_token) throw new Error('No session')
      if (!canManageRoles) throw new Error('Недостаточно прав для назначения ролей')
      return assignUserRoles(session.access_token, payload.userId, payload.roleIds)
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Набор ролей пользователя обновлён.')
      setRoleAssignUserId('')
      setRoleAssignRoleIds([])
      await queryClient.invalidateQueries({ queryKey: ['admin-users'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-user-role-map'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-user-roles-detail'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось назначить роль'),
  })

  const aiProviderSaveMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      const timeout = Number(aiConfigDraft.request_timeout_seconds)
      if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('Timeout должен быть положительным числом')
      const payload: AdminAiProviderConfigPatch = {
        provider: aiConfigDraft.provider,
        openai_model: aiConfigDraft.openai_model.trim(),
        openai_base_url: aiConfigDraft.openai_base_url.trim(),
        gemini_model: aiConfigDraft.gemini_model.trim(),
        pii_redaction_enabled: aiConfigDraft.pii_redaction_enabled,
        request_timeout_seconds: timeout,
      }
      if (openaiApiKeyDraft.trim()) payload.openai_api_key = openaiApiKeyDraft.trim()
      if (geminiApiKeyDraft.trim()) payload.gemini_api_key = geminiApiKeyDraft.trim()
      return patchAdminAiProviderConfig(session.access_token, payload)
    },
    onSuccess: async (config) => {
      setActionError('')
      setActionMessage(
        config.provider === 'mock'
          ? 'Выбрана локальная AI-симуляция; внешний provider не активирован.'
          : `${translate('Конфигурация')} ${config.provider} ${translate('сохранена и выбрана для внешних AI-вызовов.')}`,
      )
      setOpenaiApiKeyDraft('')
      setGeminiApiKeyDraft('')
      setAiTestResult(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-ai-provider-config'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-settings'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['ai-provider-status'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось сохранить AI provider'),
  })

  const aiProviderTestMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      const timeout = Number(aiConfigDraft.request_timeout_seconds)
      if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('Timeout должен быть положительным числом')
      return testAdminAiProviderConfig(session.access_token, {
        provider: aiConfigDraft.provider,
        openai_model: aiConfigDraft.openai_model.trim(),
        openai_base_url: aiConfigDraft.openai_base_url.trim(),
        gemini_model: aiConfigDraft.gemini_model.trim(),
        request_timeout_seconds: timeout,
        ...(openaiApiKeyDraft.trim() ? { openai_api_key: openaiApiKeyDraft.trim() } : {}),
        ...(geminiApiKeyDraft.trim() ? { gemini_api_key: geminiApiKeyDraft.trim() } : {}),
      })
    },
    onSuccess: (result) => {
      setActionError('')
      setAiTestResult(result)
      setActionMessage(
        result.simulation
          ? 'Проверена локальная симуляция; внешнее AI-соединение не выполнялось.'
          : result.success
            ? 'Подключение к AI provider успешно проверено.'
            : '',
      )
    },
    onError: (error) => {
      setAiTestResult(null)
      setActionError(error instanceof Error ? error.message : 'Не удалось проверить AI provider')
    },
  })

  const aiProviderClearKeyMutation = useMutation({
    mutationFn: async (provider: Exclude<AiProviderKey, 'mock'>) => {
      if (!session?.access_token) throw new Error('No session')
      return patchAdminAiProviderConfig(session.access_token, {
        provider: aiConfigDraft.provider === provider ? 'mock' : aiConfigDraft.provider,
        clear_openai_api_key: provider === 'openai',
        clear_gemini_api_key: provider === 'gemini',
      })
    },
    onSuccess: async (config) => {
      setActionError('')
      setActionMessage('Сохранённый API-ключ удалён. Активный provider при необходимости переключён на Mock.')
      setAiConfigDraft((previous) => ({ ...previous, provider: config.provider }))
      setOpenaiApiKeyDraft('')
      setGeminiApiKeyDraft('')
      setAiTestResult(null)
      await queryClient.invalidateQueries({ queryKey: ['admin-ai-provider-config'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-settings'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось удалить API-ключ'),
  })

  const tenantProfileMutation = useMutation({
    mutationFn: async (payload: { name: string; description: string | null }) => {
      if (!session?.access_token) throw new Error('No session')
      return patchCurrentTenant(session.access_token, payload)
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Профиль организации обновлён.')
      await queryClient.invalidateQueries({ queryKey: ['tenant-current'] })
      await queryClient.invalidateQueries({ queryKey: ['tenants'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось обновить организацию'),
  })

  const tenantCreateMutation = useMutation({
    mutationFn: async (payload: { name: string; slug: string; description: string | null }) => {
      if (!session?.access_token) throw new Error('No session')
      return createTenant(session.access_token, payload)
    },
    onSuccess: async (tenant) => {
      setActionError('')
      setActionMessage(`${translate('Организация «')}${tenant.name}${translate('» создана вместе со стандартными ITSM-ролями.')}`)
      await queryClient.invalidateQueries({ queryKey: ['tenants'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-roles'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось создать организацию'),
  })

  const identityProviderTestMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      return testIdentityProvider(session.access_token)
    },
    onSuccess: async (result) => {
      setActionError('')
      setIdentityTestResult(result)
      setActionMessage(result.success ? 'OIDC discovery и доверенные endpoints успешно проверены.' : '')
      await queryClient.invalidateQueries({ queryKey: ['admin-identity-provider'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => {
      setIdentityTestResult(null)
      setActionError(error instanceof Error ? error.message : 'Не удалось проверить Identity Provider')
    },
  })

  const linkExternalIdentityMutation = useMutation({
    mutationFn: async (userId: string) => {
      if (!session?.access_token) throw new Error('No session')
      const subject = externalIdentitySubject.trim()
      if (!subject) throw new Error('Введите immutable subject из Identity Provider')
      return linkAdminUserExternalIdentity(session.access_token, userId, {
        subject,
        email_at_link: externalIdentityEmail.trim() || null,
      })
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Корпоративная identity привязана к пользователю.')
      setExternalIdentitySubject('')
      setExternalIdentityEmail('')
      await queryClient.invalidateQueries({ queryKey: ['admin-user-external-identities'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-identity-provider'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось привязать identity'),
  })

  const unlinkExternalIdentityMutation = useMutation({
    mutationFn: async (payload: { userId: string; identityId: string }) => {
      if (!session?.access_token) throw new Error('No session')
      await unlinkAdminUserExternalIdentity(session.access_token, payload.userId, payload.identityId)
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Корпоративная identity отвязана.')
      await queryClient.invalidateQueries({ queryKey: ['admin-user-external-identities'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-identity-provider'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось отвязать identity'),
  })

  const userPatchMutation = useMutation({
    mutationFn: async (payload: { userId: string; data: { full_name: string; position: string | null; department: string | null; location: string | null; cost_center: string | null; phone: string | null } }) => {
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

  const createRoleMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      return createAdminRole(session.access_token, {
        code: newRole.code.trim().toLowerCase(),
        name: newRole.name.trim(),
        description: newRole.description.trim() || null,
      })
    },
    onSuccess: async (role) => {
      setActionError('')
      setActionMessage(`${translate('Роль')} ${role.name} ${translate('создана. Теперь назначьте ей права.')}`)
      setNewRole({ code: '', name: '', description: '' })
      setIsCreateRoleModalOpen(false)
      setSelectedRoleId(role.id)
      await queryClient.invalidateQueries({ queryKey: ['admin-roles'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось создать роль'),
  })

  const updateRoleMutation = useMutation({
    mutationFn: async (payload: { roleId: string; name: string; description: string | null }) => {
      if (!session?.access_token) throw new Error('No session')
      return patchAdminRole(session.access_token, payload.roleId, {
        name: payload.name,
        description: payload.description,
      })
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Описание роли обновлено.')
      await queryClient.invalidateQueries({ queryKey: ['admin-roles'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-role-by-id'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось обновить роль'),
  })

  const replaceRolePermissionsMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token || !selectedRoleId) throw new Error('Роль не выбрана')
      return replaceAdminRolePermissions(session.access_token, selectedRoleId, rolePermissionDraft)
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Права роли сохранены и применяются к новым API-запросам.')
      await queryClient.invalidateQueries({ queryKey: ['admin-role-permissions'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-user-role-map'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось сохранить права роли'),
  })

  const resetPasswordMutation = useMutation({
    mutationFn: async (userId: string) => {
      if (!session?.access_token) throw new Error('No session')
      if (!newPasswordDraft) throw new Error('Введите новый пароль')
      return resetAdminUserPassword(session.access_token, userId, newPasswordDraft, true)
    },
    onSuccess: async (result) => {
      setActionError('')
      setActionMessage(`${translate('Временный пароль установлен. Отозвано сессий:')} ${result.sessions_revoked}${translate('. При следующем входе пользователь обязан сменить пароль.')}`)
      setNewPasswordDraft('')
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
      await queryClient.invalidateQueries({ queryKey: ['security-sessions'] })
      await queryClient.invalidateQueries({ queryKey: ['security-session-overview'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось изменить пароль'),
  })

  const revokeSessionMutation = useMutation({
    mutationFn: async (sessionId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return revokeSecuritySession(session.access_token, sessionId)
    },
    onSuccess: async () => {
      setActionError('')
      setActionMessage('Сессия отозвана.')
      await queryClient.invalidateQueries({ queryKey: ['security-sessions'] })
      await queryClient.invalidateQueries({ queryKey: ['security-session-overview'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось отозвать сессию'),
  })

  const revokeUserSessionsMutation = useMutation({
    mutationFn: async (userId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return revokeUserSessions(session.access_token, userId)
    },
    onSuccess: async (result) => {
      setActionError('')
      setActionMessage(`${translate('Отозвано сессий пользователя:')} ${result.sessions_revoked}.`)
      await queryClient.invalidateQueries({ queryKey: ['security-sessions'] })
      await queryClient.invalidateQueries({ queryKey: ['security-session-overview'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось отозвать сессии пользователя'),
  })

  const resetUserMfaMutation = useMutation({
    mutationFn: async (userId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return adminResetUserMfa(session.access_token, userId)
    },
    onSuccess: async (result) => {
      setActionError('')
      setActionMessage(
        result.reset
          ? `${translate('MFA сброшена. Отозвано сессий:')} ${result.sessions_revoked}.`
          : 'У пользователя MFA не была включена.',
      )
      await queryClient.invalidateQueries({ queryKey: ['security-mfa-overview'] })
      await queryClient.invalidateQueries({ queryKey: ['security-sessions'] })
      await queryClient.invalidateQueries({ queryKey: ['security-session-overview'] })
      await queryClient.invalidateQueries({ queryKey: ['admin-audit'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Не удалось сбросить MFA пользователя'),
  })

  const users = usersQuery.data ?? []
  const roles = rolesQuery.data ?? []
  const tenants = tenantsQuery.data ?? []
  const createUserTenantId = session?.user.role === 'saas_root'
    ? newUser.tenant_id
    : session?.user.tenant_id ?? ''
  const createUserRoles = roles.filter((role) => role.tenant_id === createUserTenantId)
  const roleAssignUser = users.find((user) => user.id === roleAssignUserId)
  const roleAssignmentOptions = roles.filter(
    (role) => role.tenant_id !== null && role.tenant_id === roleAssignUser?.tenant_id,
  )
  const roleAssignEffectivePermissions = roleAssignPermissionsQuery.data ?? []
  const tenantNameMap = useMemo(() => {
    const entries = tenants.map((tenant) => [tenant.id, tenant.name] as const)
    if (currentTenantQuery.data) {
      entries.push([currentTenantQuery.data.id, currentTenantQuery.data.name])
    }
    return new Map(entries)
  }, [currentTenantQuery.data, tenants])
  const permissions = permissionsQuery.data ?? []
  const auditLogs = auditQuery.data ?? []
  const settings = settingsQuery.data ?? []
  const userRoleMap = userRolesQuery.data ?? new Map<string, AdminRole[]>()
  const selectedRole = selectedRoleQuery.data
  const selectedRoleIsReadOnly =
    !selectedRole ||
    !canManageRoles ||
    (session?.user.role !== 'saas_root' &&
      (selectedRole.tenant_id === null || selectedRole.is_system))
  const securitySessions = securitySessionsQuery.data ?? []
  const mfaOverview = mfaOverviewQuery.data

  useEffect(() => {
    if (!selectedRoleId && roles.length > 0) {
      const preferred = roles.find((item) => item.code === 'saas_root') ?? roles[0]
      setSelectedRoleId(preferred.id)
    }
  }, [roles, selectedRoleId])

  useEffect(() => {
    if (!isCreateUserModalOpen || session?.user.role !== 'saas_root') return
    if (!newUser.tenant_id && tenants.length === 1) {
      setNewUser((previous) => ({ ...previous, tenant_id: tenants[0].id, role_ids: [] }))
    }
  }, [isCreateUserModalOpen, newUser.tenant_id, session?.user.role, tenants])

  useEffect(() => {
    setRolePermissionDraft((selectedRolePermissionsQuery.data ?? []).map((item) => item.id))
  }, [selectedRoleId, selectedRolePermissionsQuery.data])

  useEffect(() => {
    if (!roleAssignUserId || !roleAssignCurrentRolesQuery.isSuccess) return
    setRoleAssignRoleIds(
      (roleAssignCurrentRolesQuery.data ?? []).map((role) => role.id),
    )
  }, [
    roleAssignCurrentRolesQuery.data,
    roleAssignCurrentRolesQuery.isSuccess,
    roleAssignUserId,
  ])

  const filteredUsers = useMemo(() => {
    const query = search.trim().toLowerCase()
    if (!query) return users
    return users.filter((item) => [item.email, item.full_name, item.position, item.department].filter(Boolean).some((value) => String(value).toLowerCase().includes(query)))
  }, [users, search])

  const permissionsByModule = useMemo(() => {
    return permissions.reduce<Record<string, AdminPermission[]>>((acc, item) => {
      acc[item.module] = acc[item.module] ? [...acc[item.module], item] : [item]
      return acc
    }, {})
  }, [permissions])
  const filteredPermissionsByModule = useMemo(() => {
    const query = permissionSearch.trim().toLowerCase()
    if (!query) return permissionsByModule
    return Object.fromEntries(
      Object.entries(permissionsByModule)
        .map(([module, items]) => [
          module,
          items.filter((item) => [
            item.code,
            item.name,
            item.description,
            permissionGuidance[item.code],
            module,
          ].filter(Boolean).some((value) => String(value).toLowerCase().includes(query))),
        ] as const)
        .filter(([, items]) => items.length > 0),
    )
  }, [permissionSearch, permissionsByModule])
  const rolePermissionWarnings = useMemo(() => {
    const codeById = new Map(permissions.map((item) => [item.id, item.code]))
    const codes = new Set(rolePermissionDraft.map((id) => codeById.get(id)).filter(Boolean))
    const warnings: string[] = []
    const hasAny = (...values: string[]) => values.some((value) => codes.has(value))
    if (
      codes.has('tickets.read')
      && !hasAny(
        'tickets.scope.all',
        'tickets.scope.assigned',
        'tickets.scope.requester',
        'tickets.assign',
        'tickets.self_assign',
      )
    ) {
      warnings.push('Для tickets.read выберите хотя бы одну область видимости заявок.')
    }
    if (
      codes.has('requests.read')
      && !hasAny(
        'requests.scope.all',
        'requests.scope.requester',
        'requests.manage',
        'requests.fulfill',
        'requests.approve',
      )
    ) {
      warnings.push('Для requests.read выберите хотя бы одну область видимости сервисных запросов.')
    }
    return warnings
  }, [permissions, rolePermissionDraft])
  const updatePermissionGroup = (items: AdminPermission[], checked: boolean) => {
    const itemIds = new Set(items.map((item) => item.id))
    setRolePermissionDraft((previous) => checked
      ? Array.from(new Set([...previous, ...itemIds]))
      : previous.filter((id) => !itemIds.has(id)))
  }

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
  const selectedUserMfa = mfaOverview?.users.find((item) => item.user_id === selectedUserId)
  const selectedUserRoles = detailsUserRolesQuery.data ?? []
  const selectedUserPermissionSummary = useMemo(() => {
    return (detailsUserRolePermissionsQuery.data ?? [])
      .reduce<Record<string, number>>((acc, item) => {
        acc[item.module] = (acc[item.module] ?? 0) + 1
        return acc
      }, {})
  }, [detailsUserRolePermissionsQuery.data])

  const selectedUserAuditHistory = useMemo(() => {
    if (!selectedUserId) return []
    return auditLogs.filter((item) => item.entity_type === 'user' && item.entity_id === selectedUserId).slice(0, 12)
  }, [auditLogs, selectedUserId])

  useEffect(() => {
    const config = aiProviderConfigQuery.data
    if (!config) return
    setAiConfigDraft({
      provider: config.provider,
      openai_model: config.openai_model,
      openai_base_url: config.openai_base_url,
      gemini_model: config.gemini_model,
      pii_redaction_enabled: config.pii_redaction_enabled,
      request_timeout_seconds: String(config.request_timeout_seconds),
    })
  }, [aiProviderConfigQuery.data])

  const isLoading = (
    (canReadUsers && usersQuery.isPending)
    || (canReadRoles && rolesQuery.isPending)
  )
  const securityAuditRows = auditLogs.filter((item) => item.entity_type === 'security' || String(item.action).startsWith('security.') || String(item.action).startsWith('login_')).slice(0, 12)

  return (
    <LocalizedContent>
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
        {availableTabs.map((tab) => (
          <button
            type="button"
            className={`admin-subnav-tab ${activeTab === tab.key ? 'active' : ''}`}
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
          >
            {translate(tab.label)}
          </button>
        ))}
      </section>

      {actionError ? <p className="error-message">{actionError}</p> : null}
      {actionMessage ? <p className="state-panel state-panel-loading">{actionMessage}</p> : null}

      <section className="admin-content-area">
      {activeTab === 'overview' ? (
        <>
          <section className="metric-grid dashboard-metrics admin-panel">
            {canReadUsers ? <article className="metric-card">
              <span>Всего пользователей</span>
              <strong>{isLoading ? '…' : totalUsers}</strong>
              <p>Все аккаунты в текущем scope.</p>
            </article> : null}
            {canReadUsers ? <article className="metric-card">
              <span>Активные пользователи</span>
              <strong>{isLoading ? '…' : activeUsers}</strong>
              <p>Учетные записи со статусом active.</p>
            </article> : null}
            {canReadUsers ? <article className="metric-card">
              <span>Неактивные пользователи</span>
              <strong>{isLoading ? '…' : inactiveUsers}</strong>
              <p>Учетные записи со статусом inactive.</p>
            </article> : null}
            {canReadRoles ? <article className="metric-card">
              <span>Ролей в системе</span>
              <strong>{rolesQuery.isPending ? '…' : roles.length}</strong>
              <p>Системные и tenant-роли.</p>
            </article> : null}
            {canReadPermissions ? <article className="metric-card">
              <span>Permissions</span>
              <strong>{permissionsQuery.isPending ? '…' : permissionsCount}</strong>
              <p>Права, сгруппированные по модулям.</p>
            </article> : null}
            {canReadAudit ? <article className="metric-card">
              <span>Audit events today</span>
              <strong>{auditQuery.isPending ? '…' : latestAuditEvents.length}</strong>
              <p>Последние события административного аудита.</p>
            </article> : null}
            {canReadAudit ? <article className="metric-card">
              <span>Admin changes today</span>
              <strong>{auditQuery.isPending ? '…' : adminChangesToday}</strong>
              <p>Изменения пользователей, ролей и настроек.</p>
            </article> : null}
            {canReadAudit ? <article className="metric-card">
              <span>Failed login attempts</span>
              <strong>{riskSummaryQuery.isPending ? '…' : failedLogins}</strong>
              <p>Неуспешные входы за 24 часа.</p>
            </article> : null}
            {canReadAudit ? <article className="metric-card">
              <span>Security risk summary</span>
              <strong>{riskSummaryQuery.isPending ? '…' : riskLevel.toUpperCase()}</strong>
              <p>Оценка риска на базе audit/login событий.</p>
            </article> : null}
          </section>

          <section className="foundation-card dashboard-split admin-panel">
            <div>
              <p className="eyebrow">QUICK ACTIONS</p>
              <h2>Быстрые действия администратора</h2>
              <div className="analytics-actions">
                {canReadUsers ? <button type="button" className="ghost-button" onClick={() => setActiveTab('users')}>
                  Открыть пользователей
                </button> : null}
                {canProvisionUsers ? <button type="button" onClick={() => setIsCreateUserModalOpen(true)}>
                  Создать пользователя
                </button> : null}
                {canReadRoles ? <button type="button" className="ghost-button" onClick={() => setActiveTab('roles')}>
                  Открыть роли
                </button> : null}
                {canReadAudit ? <button type="button" className="ghost-button" onClick={() => setActiveTab('audit')}>
                  Открыть аудит
                </button> : null}
                {canViewSecurity ? <button type="button" className="ghost-button" onClick={() => setActiveTab('security')}>
                  Настройки безопасности
                </button> : null}
                {canReadSettings ? <button type="button" className="ghost-button" onClick={() => setActiveTab('settings')}>
                  Открыть настройки
                </button> : null}
                {canReadTenants || canReadTenantProfile ? <button type="button" className="ghost-button" onClick={() => setActiveTab('tenants')}>
                  Открыть организацию
                </button> : null}
              </div>
              {canReadAudit ? <p className="muted">
                Security summary:{' '}
                <span className={riskBadgeClass(riskLevel)}>{riskLevel.toUpperCase()}</span>
              </p> : null}
            </div>
            {canReadLoginEvents ? <div>
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
            </div> : null}
          </section>

          {canReadAudit ? <section className="foundation-card dashboard-split admin-panel">
            <div>
              <p className="eyebrow">LATEST AUDIT EVENTS</p>
              <h2>Недавние события аудита</h2>
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
          </section> : null}
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
              {canReadRoles ? <label className="inline-field">
                <span>Роль</span>
                <select value={roleFilter} onChange={(event) => setRoleFilter(event.target.value)}>
                  <option value="ALL">Все роли</option>
                  {roles.map((role) => (
                    <option key={role.id} value={role.id}>
                      {role.name}
                      {session?.user.role === 'saas_root'
                        ? ` · ${role.tenant_id ? tenantNameMap.get(role.tenant_id) ?? 'Unknown tenant' : 'Global'}`
                        : ''}
                    </option>
                  ))}
                </select>
              </label> : null}
              <label className="inline-field">
                <span>Статус</span>
                <select value={activeFilter} onChange={(event) => setActiveFilter(event.target.value as 'ALL' | 'ACTIVE' | 'INACTIVE')}>
                  <option value="ALL">Все</option>
                  <option value="ACTIVE">Active</option>
                  <option value="INACTIVE">Inactive</option>
                </select>
              </label>
              {canProvisionUsers ? <button type="button" className="tickets-create-button" onClick={() => setIsCreateUserModalOpen(true)}>
                Создать пользователя
              </button> : null}
            </div>
          </section>

          <section className="foundation-card admin-panel">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>ФИО</th>
                    <th>Email</th>
                    <th>Организация</th>
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
                      <td colSpan={9}>
                        <p className="state-panel state-panel-loading">Загрузка пользователей…</p>
                      </td>
                    </tr>
                  ) : null}
                  {usersQuery.isError ? (
                    <tr>
                      <td colSpan={9}>
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
                      <td colSpan={9}>
                        <p className="state-panel state-panel-empty">Пользователи не найдены по текущим фильтрам.</p>
                      </td>
                    </tr>
                  ) : null}
                  {filteredUsers.map((user) => {
                    const roleNames = canReadRoles
                      ? userRoleMap.get(user.id)?.map((item) => item.name).join(', ') || '—'
                      : 'Доступ ограничен'
                    return (
                      <tr key={user.id}>
                        <td>{user.full_name}</td>
                        <td>{user.email}</td>
                        <td>{user.tenant_id ? tenantNameMap.get(user.tenant_id) ?? user.tenant_id : 'Global'}</td>
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
                            {canManageUsers ? <button
                              type="button"
                              className="ghost-button"
                              onClick={() => {
                                const nextActive = !user.is_active
                                const confirmed = window.confirm(nextActive
                                  ? translate('Активировать пользователя?')
                                  : translate('Деактивировать пользователя?'))
                                if (!confirmed) return
                                toggleUserMutation.mutate({ userId: user.id, active: nextActive })
                              }}
                              disabled={toggleUserMutation.isPending || assignRoleMutation.isPending}
                            >
                              {user.is_active ? 'Деактивировать' : 'Активировать'}
                            </button> : null}
                            {canManageRoles ? <button
                              type="button"
                              className="ghost-button"
                              onClick={() => {
                                setRoleAssignUserId(user.id)
                                setRoleAssignRoleIds([])
                              }}
                            >
                              Назначить роли
                            </button> : null}
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
            <div className="admin-section-heading">
              <div>
                <h2>Системные и tenant-роли</h2>
                <p className="muted">Глобальные роли наследуются и доступны администратору организации только для чтения.</p>
              </div>
              {canManageRoles ? (
                <button type="button" onClick={() => setIsCreateRoleModalOpen(true)}>
                  Создать роль
                </button>
              ) : null}
            </div>
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
              {!rolesQuery.isPending && !rolesQuery.isError && roles.length === 0 ? <p className="state-panel state-panel-empty">Роли не найдены.</p> : null}
              {roles.map((role) => (
                <button type="button" className={`activity-item admin-role-button ${selectedRoleId === role.id ? 'admin-role-active' : ''}`} key={role.id} onClick={() => setSelectedRoleId(role.id)}>
                  <header>
                    <strong>{role.name}</strong>
                    <span>{role.code}</span>
                  </header>
                  <p>{role.description ?? '—'}</p>
                  <small>
                    {role.tenant_id === null
                      ? 'Глобальная роль · только чтение'
                      : role.is_system && session?.user.role !== 'saas_root'
                        ? 'Системная роль организации · только чтение'
                        : role.is_system
                          ? 'Системная роль организации'
                          : 'Пользовательская роль'}
                  </small>
                </button>
              ))}
            </div>
          </div>
          <div>
            <p className="eyebrow">ROLE DETAILS</p>
            <h2>{selectedRole?.name ?? 'Выберите роль'}</h2>
            <p>{selectedRole?.description ?? 'Описание роли недоступно.'}</p>
            {canReadUsers ? <p className="muted">Пользователей с ролью: {users.filter((user) => (userRoleMap.get(user.id) ?? []).some((role) => role.id === selectedRoleId)).length}</p> : null}
            {selectedRole ? (
              <form
                className="admin-role-editor"
                onSubmit={(event) => {
                  event.preventDefault()
                  const data = new FormData(event.currentTarget)
                  updateRoleMutation.mutate({
                    roleId: selectedRole.id,
                    name: String(data.get('role_name') ?? selectedRole.name).trim(),
                    description: String(data.get('role_description') ?? '').trim() || null,
                  })
                }}
              >
                <label>
                  <span>Название</span>
                  <input name="role_name" defaultValue={selectedRole.name} disabled={selectedRoleIsReadOnly} key={`${selectedRole.id}-name`} />
                </label>
                <label>
                  <span>Описание</span>
                  <textarea name="role_description" defaultValue={selectedRole.description ?? ''} disabled={selectedRoleIsReadOnly} key={`${selectedRole.id}-description`} />
                </label>
                {!selectedRoleIsReadOnly ? (
                  <button type="submit" className="ghost-button" disabled={updateRoleMutation.isPending}>
                    {updateRoleMutation.isPending ? 'Сохранение…' : 'Сохранить описание'}
                  </button>
                ) : (
                  <p className="state-panel state-panel-empty">Эта роль наследуется из глобального контура. Создайте tenant-роль, чтобы настроить собственный набор прав.</p>
                )}
              </form>
            ) : null}
            <div className="admin-permissions-header">
              <div>
                <h3>Фактические права по модулям</h3>
                <p className="muted">Отмечены права, реально связанные с ролью в RBAC.</p>
              </div>
              {!selectedRoleIsReadOnly && canReadPermissions ? (
                <button
                  type="button"
                  onClick={() => replaceRolePermissionsMutation.mutate()}
                  disabled={replaceRolePermissionsMutation.isPending || rolePermissionWarnings.length > 0}
                  title={rolePermissionWarnings.length ? 'Сначала устраните конфликт области видимости.' : undefined}
                >
                  {replaceRolePermissionsMutation.isPending ? 'Применение…' : 'Применить права'}
                </button>
              ) : null}
            </div>
            <div className="activity-list admin-permission-groups">
              {(canReadPermissions && permissionsQuery.isPending) || selectedRolePermissionsQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка прав…</p> : null}
              {canReadPermissions && permissionsQuery.isError ? (
                <div className="state-panel state-panel-error">
                  <p>Не удалось загрузить права.</p>
                  <button type="button" className="ghost-button" onClick={() => permissionsQuery.refetch()}>
                    Retry
                  </button>
                </div>
              ) : null}
              {selectedRolePermissionsQuery.isError ? (
                <div className="state-panel state-panel-error">
                  <p>Не удалось загрузить фактические права роли.</p>
                  <button type="button" className="ghost-button" onClick={() => selectedRolePermissionsQuery.refetch()}>
                    Retry
                  </button>
                </div>
              ) : null}
              {!canReadPermissions ? <p className="state-panel state-panel-empty">Каталог разрешений скрыт: требуется admin.permissions.read.</p> : null}
              {canReadPermissions ? (
                <div className="admin-permission-tools">
                  <label>
                    <span>Поиск разрешений</span>
                    <input
                      type="search"
                      value={permissionSearch}
                      onChange={(event) => setPermissionSearch(event.target.value)}
                      placeholder="Например: заявки, scope, аудит или tickets.read"
                    />
                  </label>
                  <span>{rolePermissionDraft.length} из {permissions.length} выбрано</span>
                </div>
              ) : null}
              {rolePermissionWarnings.map((warning) => (
                <p className="state-panel state-panel-warning" role="alert" key={warning}>{warning}</p>
              ))}
              {canReadPermissions && !permissionsQuery.isPending && !permissionsQuery.isError && Object.entries(filteredPermissionsByModule).length === 0 ? <p className="state-panel state-panel-empty">Разрешения по текущему поиску не найдены.</p> : null}
              <div className="admin-scroll-block admin-permission-scroll">
                {Object.entries(filteredPermissionsByModule).map(([module, items]) => {
                  const selectedCount = items.filter((item) => rolePermissionDraft.includes(item.id)).length
                  return (
                  <article className="activity-item admin-permission-group" key={module}>
                  <header>
                    <div>
                      <strong>{permissionModuleLabels[module] ? translate(permissionModuleLabels[module]) : module}</strong>
                      <small><code>{module}</code></small>
                    </div>
                    <div className="admin-permission-group-actions">
                      <span>{selectedCount}/{items.length}</span>
                      {!selectedRoleIsReadOnly ? (
                        <>
                          <button type="button" className="ghost-button" onClick={() => updatePermissionGroup(items, true)}>Все</button>
                          <button type="button" className="ghost-button" onClick={() => updatePermissionGroup(items, false)}>Снять</button>
                        </>
                      ) : null}
                    </div>
                  </header>
                  <div className="admin-permission-checklist">
                    {items.map((item) => (
                      <label key={item.id} title={item.description ?? item.name}>
                        <input
                          type="checkbox"
                          checked={rolePermissionDraft.includes(item.id)}
                          disabled={selectedRoleIsReadOnly}
                          onChange={(event) =>
                            setRolePermissionDraft((previous) =>
                              event.target.checked
                                ? [...previous, item.id]
                                : previous.filter((permissionId) => permissionId !== item.id),
                            )
                          }
                        />
                        <span>
                          <strong>{item.name}</strong>
                          <small><code>{item.code}</code></small>
                          <small>{permissionGuidance[item.code] ?? item.description ?? 'Дополнительное описание не задано.'}</small>
                        </span>
                      </label>
                    ))}
                  </div>
                </article>
                  )
                })}
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
                <input value={auditActorFilter} onChange={(event) => setAuditActorFilter(event.target.value)} placeholder="user@example.com" />
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
            <p className="muted">Подключение AI настраивается отдельно; сохранённые ключи никогда не возвращаются в браузер.</p>
          </div>

          <ConfigurationCenterPanel />

          {canReadSettings ? <><section className="ai-provider-console" aria-label="Настройка AI provider">
            <header className="ai-provider-console-header">
              <div>
                <p className="eyebrow">AI PROVIDER</p>
                <h3>OpenAI / Gemini</h3>
                <p>Выберите движок, добавьте серверный API-ключ, проверьте соединение и только затем активируйте конфигурацию.</p>
              </div>
              <div className="ai-provider-current">
                <span>Активный provider</span>
                <strong>{aiProviderConfigQuery.isPending ? 'Загрузка…' : aiProviderConfigQuery.data?.provider.toUpperCase() ?? 'N/A'}</strong>
                <small>{aiProviderConfigQuery.data?.updated_at ? `${translate('Обновлено')} ${formatDateTime(aiProviderConfigQuery.data.updated_at)}` : 'Используются runtime defaults'}</small>
              </div>
            </header>

            {aiProviderConfigQuery.isError ? (
              <div className="state-panel state-panel-error">
                <p>Не удалось загрузить конфигурацию AI provider.</p>
                <button type="button" className="ghost-button" onClick={() => aiProviderConfigQuery.refetch()}>Повторить</button>
              </div>
            ) : null}

            {!canManageGlobalAiProvider ? (
              <div className="state-panel state-panel-warning">
                <strong>Глобальная конфигурация — только SaaS Root</strong>
                <p>
                  Tenant-администратор управляет data policy и бюджетом в AI
                  Copilot, но не видит и не изменяет общие API-ключи платформы.
                </p>
              </div>
            ) : null}

            <fieldset
              className="ai-provider-configuration-fields"
              disabled={!canManageGlobalAiProvider}
            >
            <div className="ai-provider-choice" role="group" aria-label="Выбор AI provider">
              {([
                ['mock', 'Mock', 'Локальные правила без внешнего API'],
                ['openai', 'OpenAI', 'ChatGPT API для классификации и рекомендаций'],
                ['gemini', 'Gemini', 'Google Gemini API для AI-функций'],
              ] as const).map(([key, title, description]) => (
                <button
                  key={key}
                  type="button"
                  className={`ai-provider-option ${aiConfigDraft.provider === key ? 'active' : ''}`}
                  aria-pressed={aiConfigDraft.provider === key}
                  onClick={() => {
                    setAiConfigDraft((previous) => ({ ...previous, provider: key }))
                    setAiTestResult(null)
                  }}
                >
                  <span className={`provider-dot provider-dot-${key}`} />
                  <strong>{title}</strong>
                  <small>{description}</small>
                </button>
              ))}
            </div>

            {aiConfigDraft.provider === 'mock' ? (
              <div className="ai-provider-form ai-provider-mock-note">
                <strong>Локальная AI-симуляция</strong>
                <p>Только для демонстрации и тестов: внешний AI не вызывается, данные не покидают платформу, API-ключ и интернет не требуются.</p>
              </div>
            ) : null}

            {aiConfigDraft.provider === 'openai' ? (
              <div className="ai-provider-form">
                <div className="ai-provider-form-heading">
                  <div>
                    <h4>OpenAI API</h4>
                    <p>Нужен API-ключ OpenAI Platform. Подписка ChatGPT сама по себе API-ключ не создаёт.</p>
                  </div>
                  <span className={aiProviderConfigQuery.data?.openai_api_key_configured ? 'badge badge-positive' : 'badge badge-warning'}>
                    {aiProviderConfigQuery.data?.openai_api_key_configured ? 'Ключ настроен' : 'Ключ не задан'}
                  </span>
                </div>
                <div className="ai-provider-fields">
                  <label>
                    <span>API key</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={openaiApiKeyDraft}
                      onChange={(event) => setOpenaiApiKeyDraft(event.target.value)}
                      placeholder={aiProviderConfigQuery.data?.openai_api_key_configured ? 'Введите новый ключ только для замены' : 'sk-…'}
                    />
                    <small>После сохранения ключ маскируется и больше не загружается в интерфейс.</small>
                  </label>
                  <label>
                    <span>Model</span>
                    <input value={aiConfigDraft.openai_model} onChange={(event) => setAiConfigDraft((previous) => ({ ...previous, openai_model: event.target.value }))} />
                  </label>
                  <label className="ai-provider-wide-field">
                    <span>Base URL</span>
                    <input type="url" value={aiConfigDraft.openai_base_url} onChange={(event) => setAiConfigDraft((previous) => ({ ...previous, openai_base_url: event.target.value }))} />
                  </label>
                </div>
                <div className="ai-provider-secret-actions">
                  <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer">Создать ключ OpenAI ↗</a>
                  {aiProviderConfigQuery.data?.openai_api_key_configured ? (
                    <button
                      type="button"
                      className="ghost-button danger-button"
                      disabled={aiProviderClearKeyMutation.isPending}
                      onClick={() => {
                        if (window.confirm(translate('Удалить сохранённый OpenAI API-ключ?'))) aiProviderClearKeyMutation.mutate('openai')
                      }}
                    >
                      Удалить сохранённый ключ
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}

            {aiConfigDraft.provider === 'gemini' ? (
              <div className="ai-provider-form">
                <div className="ai-provider-form-heading">
                  <div>
                    <h4>Google Gemini API</h4>
                    <p>Используйте ключ Google AI Studio, ограниченный только Gemini API.</p>
                  </div>
                  <span className={aiProviderConfigQuery.data?.gemini_api_key_configured ? 'badge badge-positive' : 'badge badge-warning'}>
                    {aiProviderConfigQuery.data?.gemini_api_key_configured ? 'Ключ настроен' : 'Ключ не задан'}
                  </span>
                </div>
                <div className="ai-provider-fields">
                  <label>
                    <span>API key</span>
                    <input
                      type="password"
                      autoComplete="new-password"
                      value={geminiApiKeyDraft}
                      onChange={(event) => setGeminiApiKeyDraft(event.target.value)}
                      placeholder={aiProviderConfigQuery.data?.gemini_api_key_configured ? 'Введите новый ключ только для замены' : 'AIza…'}
                    />
                    <small>Ключ хранится только на backend и не возвращается через API.</small>
                  </label>
                  <label>
                    <span>Model</span>
                    <input value={aiConfigDraft.gemini_model} onChange={(event) => setAiConfigDraft((previous) => ({ ...previous, gemini_model: event.target.value }))} />
                  </label>
                </div>
                <div className="ai-provider-secret-actions">
                  <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer">Создать ключ Gemini ↗</a>
                  {aiProviderConfigQuery.data?.gemini_api_key_configured ? (
                    <button
                      type="button"
                      className="ghost-button danger-button"
                      disabled={aiProviderClearKeyMutation.isPending}
                      onClick={() => {
                        if (window.confirm(translate('Удалить сохранённый Gemini API-ключ?'))) aiProviderClearKeyMutation.mutate('gemini')
                      }}
                    >
                      Удалить сохранённый ключ
                    </button>
                  ) : null}
                </div>
              </div>
            ) : null}

            <div className="ai-provider-runtime-settings">
              <label>
                <span>Timeout, секунд</span>
                <input type="number" min="1" max="120" value={aiConfigDraft.request_timeout_seconds} onChange={(event) => setAiConfigDraft((previous) => ({ ...previous, request_timeout_seconds: event.target.value }))} />
              </label>
              <label className="ai-provider-switch">
                <input type="checkbox" checked={aiConfigDraft.pii_redaction_enabled} onChange={(event) => setAiConfigDraft((previous) => ({ ...previous, pii_redaction_enabled: event.target.checked }))} />
                <span>
                  <strong>PII redaction</strong>
                  <small>Скрывать email, телефоны и другие персональные данные перед внешним AI-вызовом.</small>
                </span>
              </label>
            </div>
            </fieldset>

            {aiTestResult ? (
              <div className={`state-panel ${aiTestResult.simulation ? 'state-panel-warning' : aiTestResult.success ? 'state-panel-success' : 'state-panel-error'}`} role="status">
                <strong>{aiTestResult.simulation ? 'Только локальная симуляция' : aiTestResult.success ? 'Соединение работает' : 'Проверка не пройдена'}</strong>
                <p>
                  Provider: {aiTestResult.effective_provider} · Model: {aiTestResult.model}
                  {aiTestResult.response_status ? ` · HTTP ${aiTestResult.response_status}` : ''}
                </p>
                {aiTestResult.summary ? <p>Ответ: {aiTestResult.summary}</p> : null}
                {aiTestResult.reason ? <p>Причина: {aiTestResult.reason}</p> : null}
              </div>
            ) : null}

            <footer className="ai-provider-actions">
              <button
                type="button"
                className="ghost-button"
                disabled={!canManageGlobalAiProvider || aiProviderTestMutation.isPending || aiProviderConfigQuery.isPending}
                onClick={() => aiProviderTestMutation.mutate()}
              >
                {aiProviderTestMutation.isPending ? 'Проверка…' : 'Проверить подключение'}
              </button>
              <button
                type="button"
                disabled={!canManageGlobalAiProvider || aiProviderSaveMutation.isPending || aiProviderConfigQuery.isPending}
                onClick={() => aiProviderSaveMutation.mutate()}
              >
                {aiProviderSaveMutation.isPending ? 'Сохранение…' : 'Сохранить и активировать'}
              </button>
            </footer>
          </section>

          <details className="legacy-settings-diagnostic">
            <summary>Технический read-only список параметров</summary>
          <div className="admin-settings-heading">
            <div>
              <p className="eyebrow">ADVANCED FLAGS</p>
              <h3>Системные параметры</h3>
            </div>
            <p className="muted">Технические флаги текущей организации. Sensitive-поля доступны только через специализированные панели.</p>
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
                </tr>
              </thead>
              <tbody>
                {settingsQuery.isPending ? (
                  <tr>
                    <td colSpan={5}>
                      <p className="state-panel state-panel-loading">Загрузка настроек…</p>
                    </td>
                  </tr>
                ) : null}
                {settingsQuery.isError ? (
                  <tr>
                    <td colSpan={5}>
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
                    <td colSpan={5}>
                      <p className="state-panel state-panel-empty">Настройки не найдены.</p>
                    </td>
                  </tr>
                ) : null}
                {settings.map((item) => (
                  <tr key={item.id}>
                    <td>{item.key}</td>
                    <td>{item.is_sensitive ? '***' : item.value ?? '—'}</td>
                    <td>{item.description ?? '—'}</td>
                    <td>{item.is_sensitive ? 'yes' : 'no'}</td>
                    <td>{formatDateTime(item.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          </details></> : null}
        </section>
      ) : null}

      {activeTab === 'identity' ? (
        <>
          <section className="metric-grid dashboard-metrics admin-panel">
            <article className="metric-card">
              <span>Identity Provider</span>
              <strong>{identityProviderQuery.isPending ? '…' : identityProviderQuery.data?.enabled ? 'ENABLED' : 'DISABLED'}</strong>
              <p>{identityProviderQuery.data?.provider_name ?? 'OIDC'} · Authorization Code + PKCE</p>
            </article>
            <article className="metric-card">
              <span>Production readiness</span>
              <strong>{identityProviderQuery.isPending ? '…' : identityProviderQuery.data?.ready ? 'READY' : 'ACTION'}</strong>
              <p>Проверка обязательных runtime-параметров.</p>
            </article>
            <article className="metric-card">
              <span>Linked users</span>
              <strong>{identityProviderQuery.isPending ? '…' : identityProviderQuery.data?.linked_users ?? 0}</strong>
              <p>{identityProviderQuery.data?.linked_identities ?? 0} внешних identities в текущем scope.</p>
            </article>
            <article className="metric-card">
              <span>OIDC logins / 24h</span>
              <strong>{identityProviderQuery.isPending ? '…' : identityProviderQuery.data?.successful_logins_24h ?? 0}</strong>
              <p>Ошибок: {identityProviderQuery.data?.failed_logins_24h ?? 0}</p>
            </article>
          </section>

          <section className="foundation-card admin-panel identity-provider-console">
            <header className="identity-provider-header">
              <div>
                <p className="eyebrow">ENTERPRISE IDENTITY</p>
                <h2>Single Sign-On / OpenID Connect</h2>
                <p className="muted">
                  Пароли и client secret не вводятся в браузере. Они задаются через переменные окружения или Secret Manager,
                  а консоль показывает безопасный статус и позволяет проверить OIDC discovery.
                </p>
              </div>
              <span className={identityProviderQuery.data?.ready ? 'badge badge-positive' : 'badge badge-warning'}>
                {identityProviderQuery.data?.ready ? 'Готово к production' : 'Требуется настройка'}
              </span>
            </header>

            {identityProviderQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка Identity Provider…</p> : null}
            {identityProviderQuery.isError ? (
              <div className="state-panel state-panel-error">
                <p>Не удалось получить безопасный статус Identity Provider.</p>
                <button type="button" className="ghost-button" onClick={() => identityProviderQuery.refetch()}>
                  Повторить
                </button>
              </div>
            ) : null}

            {identityProviderQuery.data ? (
              <>
                <div className="detail-fields identity-provider-details">
                  <div>
                    <span>Provider</span>
                    <strong>{identityProviderQuery.data.provider_name}</strong>
                  </div>
                  <div>
                    <span>Кнопка входа</span>
                    <strong>{identityProviderQuery.data.button_label}</strong>
                  </div>
                  <div>
                    <span>Issuer URL</span>
                    <strong>{identityProviderQuery.data.issuer_url ?? '—'}</strong>
                  </div>
                  <div>
                    <span>Redirect URI</span>
                    <strong>{identityProviderQuery.data.redirect_uri ?? '—'}</strong>
                  </div>
                  <div>
                    <span>Client ID</span>
                    <strong>{identityProviderQuery.data.client_id_configured ? 'Настроен' : 'Не настроен'}</strong>
                  </div>
                  <div>
                    <span>Client secret</span>
                    <strong>{identityProviderQuery.data.client_secret_configured ? 'Настроен в Secret Manager' : 'Не настроен'}</strong>
                  </div>
                  <div>
                    <span>Client auth</span>
                    <strong>{identityProviderQuery.data.client_auth_method}</strong>
                  </div>
                  <div>
                    <span>Scopes</span>
                    <strong>{identityProviderQuery.data.scopes.join(', ') || '—'}</strong>
                  </div>
                  <div>
                    <span>Allowed algorithms</span>
                    <strong>{identityProviderQuery.data.allowed_algorithms.join(', ') || '—'}</strong>
                  </div>
                  <div>
                    <span>Allowed email domains</span>
                    <strong>{identityProviderQuery.data.allowed_email_domains.join(', ') || 'Не заданы'}</strong>
                  </div>
                  <div>
                    <span>Auto-provision</span>
                    <strong>{identityProviderQuery.data.auto_provision ? 'Enabled' : 'Disabled'}</strong>
                  </div>
                  <div>
                    <span>Email linking</span>
                    <strong>{identityProviderQuery.data.allow_email_linking ? 'Allowed' : 'Disabled'}</strong>
                  </div>
                  <div>
                    <span>Default role</span>
                    <strong>{identityProviderQuery.data.default_role_code}</strong>
                  </div>
                  <div>
                    <span>Configuration source</span>
                    <strong>{identityProviderQuery.data.configuration_source}</strong>
                  </div>
                </div>

                {identityProviderQuery.data.readiness_issues.length > 0 ? (
                  <section className="identity-readiness">
                    <p className="eyebrow">READINESS CHECKLIST</p>
                    <ul>
                      {identityProviderQuery.data.readiness_issues.map((issue) => <li key={issue}>{issue}</li>)}
                    </ul>
                    <p className="muted">
                      Настройте OIDC_ENABLED, OIDC_ISSUER_URL, OIDC_CLIENT_ID, OIDC_CLIENT_SECRET,
                      OIDC_REDIRECT_URI и OIDC_ALLOWED_EMAIL_DOMAINS на backend, затем перезапустите сервис.
                    </p>
                  </section>
                ) : (
                  <p className="state-panel state-panel-success">Все обязательные параметры Identity Provider настроены.</p>
                )}

                {identityTestResult ? (
                  <div className={`state-panel ${identityTestResult.success ? 'state-panel-success' : 'state-panel-error'}`} role="status">
                    <strong>{identityTestResult.success ? 'OIDC discovery успешно проверен' : 'Проверка не пройдена'}</strong>
                    {identityTestResult.reason ? <p>{identityTestResult.reason}</p> : null}
                    {identityTestResult.issuer ? <p>Issuer: {identityTestResult.issuer}</p> : null}
                    {identityTestResult.success ? (
                      <p>
                        Hosts: authorization={identityTestResult.authorization_endpoint_host ?? '—'} ·
                        token={identityTestResult.token_endpoint_host ?? '—'} · JWKS={identityTestResult.jwks_host ?? '—'}
                      </p>
                    ) : null}
                  </div>
                ) : null}

                <footer className="identity-provider-actions">
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={!canManageSettings || identityProviderTestMutation.isPending}
                    onClick={() => identityProviderTestMutation.mutate()}
                  >
                    {identityProviderTestMutation.isPending ? 'Проверка discovery…' : 'Проверить OIDC discovery'}
                  </button>
                  <small>Результат и инициатор проверки записываются в audit trail.</small>
                </footer>
              </>
            ) : null}
          </section>
        </>
      ) : null}

      {activeTab === 'security' ? (
        <>
          {canReadSessions && sessionOverviewQuery.isError ? (
            <div className="state-panel state-panel-error admin-panel">
              <p>Не удалось получить сводку сессий. Значения сессий скрыты, чтобы не показывать ложные нули.</p>
              <button type="button" className="ghost-button" onClick={() => sessionOverviewQuery.refetch()}>
                Повторить
              </button>
            </div>
          ) : null}
          {canReadAudit && riskSummaryQuery.isError ? (
            <div className="state-panel state-panel-error admin-panel">
              <p>Не удалось получить security risk summary.</p>
              <button type="button" className="ghost-button" onClick={() => riskSummaryQuery.refetch()}>
                Повторить
              </button>
            </div>
          ) : null}
          {canReadSessions || canReadAudit ? <section className="metric-grid dashboard-metrics">
            {canReadAudit ? <article className="metric-card">
              <span>Успешные входы (24ч)</span>
              <strong>{riskSummaryQuery.isPending ? '…' : security?.success_logins_24h ?? 0}</strong>
              <p>Login success events</p>
            </article> : null}
            {canReadAudit ? <article className="metric-card">
              <span>Неуспешные входы (24ч)</span>
              <strong>{riskSummaryQuery.isPending ? '…' : security?.failed_logins_24h ?? 0}</strong>
              <p>Login failed events</p>
            </article> : null}
            {canReadSessions ? <article className="metric-card">
              <span>Активные сессии</span>
              <strong>{sessionOverviewQuery.isPending ? '…' : sessionOverviewQuery.isError ? '—' : sessionOverview?.active_sessions ?? 0}</strong>
              <p>Действующие refresh-сессии текущего tenant</p>
            </article> : null}
            {canReadSessions ? <article className="metric-card">
              <span>Входили за 24 часа</span>
              <strong>{sessionOverviewQuery.isPending ? '…' : sessionOverviewQuery.isError ? '—' : sessionOverview?.logged_in_last_24h ?? 0}</strong>
              <p>Уникальные пользователи</p>
            </article> : null}
            {canReadSessions ? <article className="metric-card">
              <span>Locked/inactive users</span>
              <strong>{sessionOverviewQuery.isPending ? '…' : sessionOverviewQuery.isError ? '—' : sessionOverview?.inactive_users ?? 0}</strong>
              <p>Неактивные или заблокированные пользователи.</p>
            </article> : null}
            {canReadAudit ? <article className="metric-card">
              <span>Risky events</span>
              <strong>{riskSummaryQuery.isPending ? '…' : riskyEventsCount}</strong>
              <p>Последние сигналы security.</p>
            </article> : null}
            {canReadAudit ? <article className="metric-card">
              <span>Admin changes today</span>
              <strong>{auditQuery.isPending ? '…' : adminChangesToday}</strong>
              <p>Изменения в users, roles и settings.</p>
            </article> : null}
            {canReadAudit ? <article className="metric-card">
              <span>Risk level</span>
              <strong>{riskSummaryQuery.isPending ? '…' : (security?.risk_level ?? 'n/a').toUpperCase()}</strong>
              <p>Расчет по security сигналам</p>
            </article> : null}
          </section> : null}

          <MfaEnrollmentPanel />

          {canReadMfa ? (
            <section className="foundation-card admin-panel">
              <div className="admin-section-heading">
                <div>
                  <p className="eyebrow">PRIVILEGED ACCESS</p>
                  <h2>Покрытие MFA</h2>
                  <p className="muted">
                    Состояние регистрации TOTP и recovery-кодов в текущем tenant. Сброс чужой MFA требует права управления и MFA-подтверждённой сессии администратора.
                  </p>
                </div>
                <button type="button" className="ghost-button" onClick={() => mfaOverviewQuery.refetch()} disabled={mfaOverviewQuery.isFetching}>
                  {mfaOverviewQuery.isFetching ? 'Обновление…' : 'Обновить'}
                </button>
              </div>
              {mfaOverviewQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка статуса MFA…</p> : null}
              {mfaOverviewQuery.isError ? (
                <div className="state-panel state-panel-error">
                  <p>Не удалось получить сводку MFA.</p>
                  <button type="button" className="ghost-button" onClick={() => mfaOverviewQuery.refetch()}>Повторить</button>
                </div>
              ) : null}
              {mfaOverview ? (
                <>
                  <div className="mfa-admin-metrics">
                    <article>
                      <span>Политика</span>
                      <strong>{mfaOverview.enforcement_enabled ? 'ENFORCED' : 'MONITOR ONLY'}</strong>
                      <small>Роли: {mfaOverview.required_role_codes.join(', ')}</small>
                    </article>
                    <article>
                      <span>Зарегистрировано</span>
                      <strong>{mfaOverview.enrolled_users} / {mfaOverview.total_users}</strong>
                      <small>Активные и неактивные пользователи</small>
                    </article>
                    <article className={mfaOverview.required_users_without_mfa > 0 ? 'mfa-metric-risk' : ''}>
                      <span>Privileged gap</span>
                      <strong>{mfaOverview.required_users_without_mfa}</strong>
                      <small>Обязательных пользователей без MFA</small>
                    </article>
                    <article className={!mfaOverview.current_session_verified ? 'mfa-metric-risk' : ''}>
                      <span>Моя сессия</span>
                      <strong>{mfaOverview.current_session_verified ? 'VERIFIED' : 'NOT VERIFIED'}</strong>
                      <small>Step-up для критичных действий</small>
                    </article>
                  </div>
                  <div className="ticket-table-wrap">
                    <table className="ticket-table">
                      <thead>
                        <tr>
                          <th>Пользователь</th>
                          <th>Роль</th>
                          <th>Требование</th>
                          <th>MFA</th>
                          <th>Recovery</th>
                          <th>Действия</th>
                        </tr>
                      </thead>
                      <tbody>
                        {mfaOverview.users.map((userMfa) => (
                          <tr key={userMfa.user_id}>
                            <td>
                              <strong>{userMfa.full_name}</strong>
                              <small className="admin-table-subline">{userMfa.email}</small>
                            </td>
                            <td>{userMfa.role}</td>
                            <td><span className={userMfa.required ? 'badge badge-warning' : 'badge'}>{userMfa.required ? 'REQUIRED' : 'OPTIONAL'}</span></td>
                            <td>
                              <span className={userMfa.enabled ? 'badge badge-positive' : userMfa.required ? 'badge badge-danger' : 'badge'}>
                                {userMfa.locked ? 'LOCKED' : userMfa.enabled ? 'ENABLED' : 'DISABLED'}
                              </span>
                            </td>
                            <td>{userMfa.enabled ? userMfa.recovery_codes_remaining : '—'}</td>
                            <td>
                              {userMfa.enabled && userMfa.user_id !== session?.user.id && canManageMfa ? (
                                <button
                                  type="button"
                                  className="ghost-button danger-button"
                                  disabled={resetUserMfaMutation.isPending || !session?.user.mfa_verified}
                                  title={!session?.user.mfa_verified ? 'Войдите через MFA, чтобы выполнить защищённый сброс' : undefined}
                                  onClick={() => {
                                    if (window.confirm(`${translate('Сбросить MFA пользователя')} ${userMfa.email} ${translate('и отозвать все его сессии?')}`)) {
                                      resetUserMfaMutation.mutate(userMfa.user_id)
                                    }
                                  }}
                                >
                                  Сбросить MFA
                                </button>
                              ) : '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : null}
            </section>
          ) : null}

          {canReadSessions ? <section className="foundation-card admin-panel">
            <div className="admin-section-heading">
              <div>
                <p className="eyebrow">SESSION CONTROL</p>
                <h2>Активные пользовательские сессии</h2>
                <p className="muted">
                  Отзыв действует сразу для API-запросов и refresh-токена. Текущая сессия отмечена отдельно.
                </p>
              </div>
              <button type="button" className="ghost-button" onClick={() => securitySessionsQuery.refetch()} disabled={securitySessionsQuery.isFetching}>
                {securitySessionsQuery.isFetching ? 'Обновление…' : 'Обновить'}
              </button>
            </div>
            {securitySessionsQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка сессий…</p> : null}
            {securitySessionsQuery.isError ? (
              <div className="state-panel state-panel-error">
                <p>Не удалось загрузить список сессий.</p>
                <button type="button" className="ghost-button" onClick={() => securitySessionsQuery.refetch()}>
                  Retry
                </button>
              </div>
            ) : null}
            {!securitySessionsQuery.isPending && securitySessions.length === 0 ? <p className="state-panel state-panel-empty">Сессии не найдены.</p> : null}
            {securitySessions.length > 0 ? (
              <div className="ticket-table-wrap">
                <table className="ticket-table">
                  <thead>
                    <tr>
                      <th>Пользователь</th>
                      <th>Создана</th>
                      <th>Refresh истекает</th>
                      <th>Статус</th>
                      <th>Действия</th>
                    </tr>
                  </thead>
                  <tbody>
                    {securitySessions.map((authSession) => (
                      <tr key={authSession.id}>
                        <td>
                          <strong>{authSession.user_name}</strong>
                          <small className="admin-table-subline">{authSession.user_email}</small>
                        </td>
                        <td>
                          {formatDateTime(authSession.created_at)}
                          <small className="admin-table-subline">
                            {authSession.ip_address ?? '—'} · {authSession.auth_method ?? '—'}
                          </small>
                          <small className="admin-table-subline" title={authSession.user_agent ?? undefined}>
                            {authSession.user_agent ?? '—'}
                          </small>
                        </td>
                        <td>{formatDateTime(authSession.refresh_expires_at)}</td>
                        <td>
                          <span className={authSession.is_active ? 'badge badge-positive' : 'badge'}>
                            {authSession.is_current ? 'CURRENT · ' : ''}
                            {authSession.is_active ? 'ACTIVE' : authSession.revoked_at ? 'REVOKED' : 'EXPIRED'}
                          </span>
                        </td>
                        <td>
                          {authSession.is_active && canManageSessions ? (
                            <button
                              type="button"
                              className="ghost-button"
                              disabled={revokeSessionMutation.isPending}
                              onClick={() => {
                                const confirmed = window.confirm(
                                  authSession.is_current
                                    ? translate('Отозвать текущую сессию? Вы потеряете доступ к консоли.')
                                    : `${translate('Отозвать сессию')} ${authSession.user_email}?`,
                                )
                                if (confirmed) revokeSessionMutation.mutate(authSession.id)
                              }}
                            >
                              Отозвать
                            </button>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}
          </section> : null}

          {canReadLoginEvents || canReadAudit ? <section className="foundation-card dashboard-split admin-panel">
            {canReadLoginEvents ? <div>
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
            </div> : null}
            {canReadAudit ? <div>
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
                        <strong>Privileged MFA coverage</strong>
                        <span className={riskBadgeClass((mfaOverview?.required_users_without_mfa ?? 0) > 0 ? 'high' : 'low')}>
                          {(mfaOverview?.required_users_without_mfa ?? 0) > 0 ? 'HIGH' : 'LOW'}
                        </span>
                      </header>
                      <p>
                        {mfaOverview
                          ? `${mfaOverview.required_users_without_mfa} ${translate('обязательных пользователей без MFA; политика')} ${mfaOverview.enforcement_enabled ? translate('включена') : translate('работает в режиме мониторинга')}.`
                          : 'Получить актуальное состояние MFA для привилегированных ролей.'}
                      </p>
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
            </div> : null}
          </section> : null}
        </>
      ) : null}

      {activeTab === 'tenants' ? (
        <>
          <section className="foundation-card admin-panel organization-console">
            <header className="identity-provider-header">
              <div>
                <p className="eyebrow">ORGANIZATION PROFILE</p>
                <h2>Организационный контур</h2>
                <p className="muted">Профиль и граница изоляции текущей организации. Slug и tenant ID неизменяемы из консоли.</p>
              </div>
              {currentTenantQuery.data ? <span className="badge badge-positive">{currentTenantQuery.data.status.toUpperCase()}</span> : null}
            </header>

            {currentTenantQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка организации…</p> : null}
            {currentTenantQuery.isError ? (
              <div className="state-panel state-panel-error">
                <p>Не удалось получить профиль текущей организации.</p>
                <button type="button" className="ghost-button" onClick={() => currentTenantQuery.refetch()}>Повторить</button>
              </div>
            ) : null}

            {currentTenantQuery.data ? (
              <>
                <div className="detail-fields">
                  <div>
                    <span>Tenant ID</span>
                    <strong>{currentTenantQuery.data.id}</strong>
                  </div>
                  <div>
                    <span>Slug</span>
                    <strong>{currentTenantQuery.data.slug}</strong>
                  </div>
                    <div>
                      <span>Users in scope</span>
                      <strong>{canReadUsers ? users.filter((user) => user.tenant_id === currentTenantQuery.data?.id).length : 'Доступ ограничен'}</strong>
                  </div>
                  <div>
                    <span>Tenant isolation</span>
                    <strong>Enforced</strong>
                  </div>
                  <div>
                    <span>Created</span>
                    <strong>{formatDateTime(currentTenantQuery.data.created_at)}</strong>
                  </div>
                  <div>
                    <span>Updated</span>
                    <strong>{formatDateTime(currentTenantQuery.data.updated_at)}</strong>
                  </div>
                </div>
                <form
                  key={`${currentTenantQuery.data.id}:${currentTenantQuery.data.updated_at}`}
                  className="organization-profile-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    const data = new FormData(event.currentTarget)
                    tenantProfileMutation.mutate({
                      name: String(data.get('organization_name') ?? '').trim(),
                      description: String(data.get('organization_description') ?? '').trim() || null,
                    })
                  }}
                >
                  <label>
                    <span>Название организации</span>
                    <input
                      name="organization_name"
                      required
                      maxLength={200}
                      defaultValue={currentTenantQuery.data.name}
                      disabled={!canManageTenantProfile}
                    />
                  </label>
                  <label>
                    <span>Описание</span>
                    <textarea
                      name="organization_description"
                      maxLength={4000}
                      defaultValue={currentTenantQuery.data.description ?? ''}
                      disabled={!canManageTenantProfile}
                    />
                  </label>
                  <footer className="identity-provider-actions">
                    <button type="submit" disabled={!canManageTenantProfile || tenantProfileMutation.isPending}>
                      {tenantProfileMutation.isPending ? 'Сохранение…' : 'Сохранить профиль'}
                    </button>
                    <small>
                      {canManageTenantProfile
                        ? 'Изменение фиксируется в audit trail.'
                        : 'Профиль доступен только для чтения в текущей роли.'}
                    </small>
                  </footer>
                </form>
              </>
            ) : null}

            {!currentTenantQuery.isPending && !currentTenantQuery.isError && !currentTenantQuery.data && session?.user.role === 'saas_root' ? (
              <p className="state-panel state-panel-empty">Root-сессия не привязана к одной организации. Используйте fleet view ниже.</p>
            ) : null}
          </section>

          <TenantExperiencePanel />
          <LocalizedContentPanel />

          {canReadTenants ? (
            <section className="foundation-card admin-panel">
              <div>
                <p className="eyebrow">SAAS ROOT / TENANT FLEET</p>
                <h2>Организации платформы</h2>
              </div>
              {session?.user.role === 'saas_root' ? (
                <form
                  className="organization-profile-form"
                  onSubmit={(event) => {
                    event.preventDefault()
                    const form = event.currentTarget
                    const data = new FormData(form)
                    tenantCreateMutation.mutate(
                      {
                        name: String(data.get('tenant_name') ?? '').trim(),
                        slug: String(data.get('tenant_slug') ?? '').trim().toLowerCase(),
                        description: String(data.get('tenant_description') ?? '').trim() || null,
                      },
                      { onSuccess: () => form.reset() },
                    )
                  }}
                >
                  <header>
                    <h3>Новая организация</h3>
                    <p className="muted">Создаёт изолированный tenant и стандартные роли: администратор, IT-менеджер, агент, заявитель, безопасность и база знаний.</p>
                  </header>
                  <label>
                    <span>Название</span>
                    <input name="tenant_name" required minLength={2} maxLength={200} placeholder="SBS Production" />
                  </label>
                  <label>
                    <span>Slug</span>
                    <input name="tenant_slug" required minLength={3} maxLength={120} pattern="[a-z0-9]+(?:-[a-z0-9]+)*" placeholder="sbs-production" />
                  </label>
                  <label>
                    <span>Описание</span>
                    <textarea name="tenant_description" maxLength={4000} placeholder="Назначение и границы организации" />
                  </label>
                  <footer className="identity-provider-actions">
                    <button type="submit" disabled={tenantCreateMutation.isPending}>
                      {tenantCreateMutation.isPending ? 'Создание…' : 'Создать организацию'}
                    </button>
                    <small>Операция фиксируется в audit trail.</small>
                  </footer>
                </form>
              ) : null}
              {tenantsQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка tenant fleet…</p> : null}
              {tenantsQuery.isError ? (
                <div className="state-panel state-panel-error">
                  <p>Не удалось получить глобальный список организаций.</p>
                  <button type="button" className="ghost-button" onClick={() => tenantsQuery.refetch()}>Повторить</button>
                </div>
              ) : null}
              {(tenantsQuery.data ?? []).length > 0 ? (
                <div className="ticket-table-wrap">
                  <table className="ticket-table">
                    <thead>
                      <tr>
                        <th>Организация</th>
                        <th>Slug</th>
                        <th>Status</th>
                        <th>Users</th>
                        <th>Description</th>
                        <th>Created</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(tenantsQuery.data ?? []).map((tenant) => (
                        <tr key={tenant.id}>
                          <td>{tenant.name}</td>
                          <td>{tenant.slug}</td>
                          <td>{tenant.status}</td>
                          <td>{users.filter((user) => user.tenant_id === tenant.id).length}</td>
                          <td>{tenant.description ?? '—'}</td>
                          <td>{formatDateTime(tenant.created_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </section>
          ) : null}
        </>
      ) : null}
      </section>

      {isCreateRoleModalOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeAllModals}>
          <section
            ref={createRoleDialogRef}
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-create-role-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="modal-header">
              <div>
                <p className="eyebrow">CREATE TENANT ROLE</p>
                <h2 id="admin-create-role-title">Новая роль организации</h2>
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
                  createRoleMutation.mutate()
                }}
              >
                <label>
                  <span>Код роли</span>
                  <input
                    required
                    pattern="[a-z0-9_]+"
                    value={newRole.code}
                    onChange={(event) => setNewRole((previous) => ({ ...previous, code: event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, '_') }))}
                    placeholder="service_desk_lead"
                  />
                  <small>Только латинские буквы, цифры и подчёркивание. Код нельзя изменить после создания.</small>
                </label>
                <label>
                  <span>Название</span>
                  <input required value={newRole.name} onChange={(event) => setNewRole((previous) => ({ ...previous, name: event.target.value }))} />
                </label>
                <label>
                  <span>Описание</span>
                  <textarea value={newRole.description} onChange={(event) => setNewRole((previous) => ({ ...previous, description: event.target.value }))} />
                </label>
                <footer className="modal-footer">
                  <button type="button" className="ghost-button" onClick={closeAllModals}>
                    Отмена
                  </button>
                  <button type="submit" disabled={createRoleMutation.isPending}>
                    {createRoleMutation.isPending ? 'Создание…' : 'Создать роль'}
                  </button>
                </footer>
              </form>
            </div>
          </section>
        </div>
      ) : null}

      {isCreateUserModalOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={closeAllModals}>
          <section
            ref={createUserDialogRef}
            className="modal-card modal-card-xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-create-user-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="modal-header">
              <div>
                <p className="eyebrow">CREATE USER</p>
                <h2 id="admin-create-user-title">Новый пользователь</h2>
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
                <div className="state-panel">
                  <strong>Порядок настройки</strong>
                  <p>Выберите организацию, затем роль. Права пользователя определяются выбранной ролью и не выходят за границы tenant.</p>
                </div>
                <div className="form-grid">
                  {session?.user.role === 'saas_root' ? (
                    <label>
                      <span>Организация</span>
                      <select
                        required
                        value={newUser.tenant_id}
                        onChange={(event) => setNewUser((previous) => ({
                          ...previous,
                          tenant_id: event.target.value,
                          role_ids: [],
                        }))}
                      >
                        <option value="">Выберите организацию</option>
                        {tenants.map((tenant) => (
                          <option key={tenant.id} value={tenant.id}>
                            {tenant.name} · {tenant.slug}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  <label>
                    <span>ФИО</span>
                    <input required value={newUser.full_name} onChange={(event) => setNewUser((prev) => ({ ...prev, full_name: event.target.value }))} />
                  </label>
                  <label>
                    <span>Корпоративная почта</span>
                    <input required type="email" value={newUser.email} onChange={(event) => setNewUser((prev) => ({ ...prev, email: event.target.value }))} />
                  </label>
                  <label>
                    <span>Временный пароль</span>
                    <input required type="password" autoComplete="new-password" value={newUser.password} onChange={(event) => setNewUser((prev) => ({ ...prev, password: event.target.value }))} />
                    <small>Не менее установленной политикой длины, с буквами, цифрами и спецсимволом. При первом входе пользователь обязан заменить его.</small>
                  </label>
                  <label>
                    <span>Должность</span>
                    <input value={newUser.position} onChange={(event) => setNewUser((prev) => ({ ...prev, position: event.target.value }))} />
                  </label>
                  <label>
                    <span>Подразделение</span>
                    <input value={newUser.department} onChange={(event) => setNewUser((prev) => ({ ...prev, department: event.target.value }))} />
                  </label>
                  <label>
                    <span>Локация</span>
                    <input value={newUser.location} onChange={(event) => setNewUser((prev) => ({ ...prev, location: event.target.value }))} placeholder="HQ, Branch-1" />
                  </label>
                  <label>
                    <span>Cost center</span>
                    <input value={newUser.cost_center} onChange={(event) => setNewUser((prev) => ({ ...prev, cost_center: event.target.value }))} placeholder="CC-100" />
                  </label>
                  <label>
                    <span>Телефон</span>
                    <input value={newUser.phone} onChange={(event) => setNewUser((prev) => ({ ...prev, phone: event.target.value }))} />
                  </label>
                  <fieldset className="admin-role-assignment-fieldset admin-create-user-roles">
                    <legend>Роли и права</legend>
                    {!createUserTenantId ? (
                      <p className="state-panel state-panel-empty">
                        Сначала выберите организацию.
                      </p>
                    ) : (
                      <div className="admin-permission-checklist admin-role-assignment-options">
                        {createUserRoles.map((role) => (
                          <label key={role.id}>
                            <input
                              type="checkbox"
                              checked={newUser.role_ids.includes(role.id)}
                              onChange={(event) =>
                                setNewUser((previous) => ({
                                  ...previous,
                                  role_ids: event.target.checked
                                    ? [...previous.role_ids, role.id]
                                    : previous.role_ids.filter((roleId) => roleId !== role.id),
                                }))
                              }
                            />
                            <span>
                              <strong>{role.name} · {role.code}</strong>
                              <small>
                                {role.is_system ? 'Системная роль' : 'Пользовательская роль'}
                                {role.description ? ` · ${role.description}` : ''}
                              </small>
                            </span>
                          </label>
                        ))}
                      </div>
                    )}
                    <small>
                      Первая выбранная роль будет основной. Итоговые права:
                      {' '}
                      {createUserRolePermissionsQuery.isPending
                        ? 'расчёт…'
                        : createUserRolePermissionsQuery.data?.length ?? 0}
                    </small>
                  </fieldset>
                  <label>
                    <span>Статус учётной записи</span>
                    <select
                      value={newUser.active ? 'true' : 'false'}
                      disabled={!canManageUsers}
                      onChange={(event) => setNewUser((prev) => ({ ...prev, active: event.target.value === 'true' }))}
                    >
                      <option value="true">Активна</option>
                      <option value="false">Отключена</option>
                    </select>
                  </label>
                </div>
                <footer className="modal-footer">
                  <button type="button" className="ghost-button" onClick={closeAllModals} disabled={createUserMutation.isPending}>
                    Отмена
                  </button>
                  <button
                    type="submit"
                    disabled={
                      createUserMutation.isPending ||
                      newUser.role_ids.length === 0 ||
                      (session?.user.role === 'saas_root' && !newUser.tenant_id)
                    }
                  >
                    {createUserMutation.isPending ? 'Создание…' : 'Создать пользователя'}
                  </button>
                </footer>
              </form>
            </div>
          </section>
        </div>
      ) : null}

      {selectedUserId ? (
        <div className="modal-backdrop" role="presentation" onClick={closeAllModals}>
          <section
            ref={userDetailDialogRef}
            className="modal-card modal-card-xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-user-detail-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="modal-header">
              <div>
                <p className="eyebrow">USER DETAILS</p>
                <h2 id="admin-user-detail-title">{selectedUser?.full_name ?? 'Пользователь'}</h2>
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
                      <span>location</span>
                      <strong>{selectedUser.location ?? '—'}</strong>
                    </div>
                    <div>
                      <span>cost_center</span>
                      <strong>{selectedUser.cost_center ?? '—'}</strong>
                    </div>
                    <div>
                      <span>phone</span>
                      <strong>{selectedUser.phone ?? '—'}</strong>
                    </div>
                    <div>
                      <span>roles</span>
                      <strong>{canReadRoles ? selectedUserRoles.map((item) => item.name).join(', ') || '—' : 'Доступ ограничен'}</strong>
                    </div>
                    <div>
                      <span>is_active</span>
                      <strong>{String(selectedUser.is_active)}</strong>
                    </div>
                    <div>
                      <span>must_change_password</span>
                      <strong>{String(selectedUser.must_change_password)}</strong>
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
                  {selectedUserMfa ? (
                    <section className="admin-panel identity-user-panel">
                      <div className="identity-user-heading">
                        <div>
                          <p className="eyebrow">MULTI-FACTOR AUTHENTICATION</p>
                          <h3>Защита учётной записи</h3>
                        </div>
                        <span className={selectedUserMfa.enabled ? 'badge badge-positive' : selectedUserMfa.required ? 'badge badge-danger' : 'badge badge-warning'}>
                          {selectedUserMfa.enabled ? 'ENABLED' : selectedUserMfa.required ? 'REQUIRED · MISSING' : 'DISABLED'}
                        </span>
                      </div>
                      <div className="mfa-status-grid">
                        <div><span>Роль</span><strong>{selectedUserMfa.role}</strong></div>
                        <div><span>Подтверждена</span><strong>{formatDateTime(selectedUserMfa.verified_at)}</strong></div>
                        <div><span>Recovery-коды</span><strong>{selectedUserMfa.enabled ? selectedUserMfa.recovery_codes_remaining : '—'}</strong></div>
                        <div><span>Блокировка</span><strong>{selectedUserMfa.locked ? 'Временно заблокирована' : 'Нет'}</strong></div>
                      </div>
                      {selectedUserMfa.enabled && selectedUser.id !== session?.user.id && canManageMfa ? (
                        <div>
                          <button
                            type="button"
                            className="ghost-button danger-button"
                            disabled={resetUserMfaMutation.isPending || !session?.user.mfa_verified}
                            onClick={() => {
                              if (window.confirm(`${translate('Сбросить MFA пользователя')} ${selectedUser.email} ${translate('и отозвать все активные сессии?')}`)) {
                                resetUserMfaMutation.mutate(selectedUser.id)
                              }
                            }}
                          >
                            {resetUserMfaMutation.isPending ? 'Сбрасываем…' : 'Сбросить MFA и сессии'}
                          </button>
                          {!session?.user.mfa_verified ? (
                            <p className="muted">Для защищённого сброса войдите в текущую сессию через MFA.</p>
                          ) : null}
                        </div>
                      ) : null}
                    </section>
                  ) : null}
                  {canReadRoles ? <section className="admin-panel">
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
                  </section> : null}
                  {canReadAudit ? <section className="admin-panel">
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
                  </section> : null}
                  <section className="admin-panel identity-user-panel">
                    <div className="identity-user-heading">
                      <div>
                        <p className="eyebrow">ENTERPRISE IDENTITY</p>
                        <h3>Корпоративная учётная запись</h3>
                      </div>
                      <span className={(selectedUserExternalIdentitiesQuery.data ?? []).length > 0 ? 'badge badge-positive' : 'badge badge-warning'}>
                        {(selectedUserExternalIdentitiesQuery.data ?? []).length > 0 ? 'Привязана' : 'Не привязана'}
                      </span>
                    </div>
                    {selectedUserExternalIdentitiesQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка identities…</p> : null}
                    {selectedUserExternalIdentitiesQuery.isError ? (
                      <div className="state-panel state-panel-error">
                        <p>Не удалось получить корпоративные identities пользователя.</p>
                        <button type="button" className="ghost-button" onClick={() => selectedUserExternalIdentitiesQuery.refetch()}>Повторить</button>
                      </div>
                    ) : null}
                    <div className="activity-list">
                      {(selectedUserExternalIdentitiesQuery.data ?? []).map((identity) => (
                        <article className="activity-item" key={identity.id}>
                          <header>
                            <strong>{identity.provider_name}</strong>
                            <span>{formatDateTime(identity.last_login_at)}</span>
                          </header>
                          <p>{identity.email_at_link}</p>
                          <small>Issuer: {identity.issuer} · Subject: {identity.subject}</small>
                          {canManageUsers ? (
                            <button
                              type="button"
                              className="ghost-button danger-button"
                              disabled={unlinkExternalIdentityMutation.isPending}
                              onClick={() => {
                                const confirmed = window.confirm(`${translate('Отвязать')} ${identity.provider_name} ${translate('identity от')} ${selectedUser.email}?`)
                                if (confirmed) unlinkExternalIdentityMutation.mutate({ userId: selectedUser.id, identityId: identity.id })
                              }}
                            >
                              Отвязать identity
                            </button>
                          ) : null}
                        </article>
                      ))}
                    </div>
                    {!selectedUserExternalIdentitiesQuery.isPending && (selectedUserExternalIdentitiesQuery.data ?? []).length === 0 ? (
                      <p className="state-panel state-panel-empty">У пользователя пока нет привязки к корпоративному Identity Provider.</p>
                    ) : null}
                    {canManageUsers && identityProviderQuery.data?.enabled && (selectedUserExternalIdentitiesQuery.data ?? []).length === 0 ? (
                      <div className="identity-link-form">
                        <label>
                          <span>Immutable subject (sub)</span>
                          <input
                            value={externalIdentitySubject}
                            maxLength={255}
                            onChange={(event) => setExternalIdentitySubject(event.target.value)}
                            placeholder="OIDC subject пользователя"
                          />
                        </label>
                        <label>
                          <span>Email at link</span>
                          <input
                            type="email"
                            value={externalIdentityEmail}
                            onChange={(event) => setExternalIdentityEmail(event.target.value)}
                            placeholder={selectedUser.email}
                          />
                        </label>
                        <button
                          type="button"
                          disabled={!externalIdentitySubject.trim() || linkExternalIdentityMutation.isPending}
                          onClick={() => linkExternalIdentityMutation.mutate(selectedUser.id)}
                        >
                          {linkExternalIdentityMutation.isPending ? 'Привязка…' : 'Привязать identity'}
                        </button>
                      </div>
                    ) : null}
                    {canReadSettings && identityProviderQuery.data && !identityProviderQuery.data.enabled ? (
                      <p className="muted">Сначала настройте и включите OIDC в разделе Identity &amp; SSO.</p>
                    ) : null}
                  </section>
                  {canManageUsers ? <section className="admin-panel">
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
                            location: String(data.get('location') ?? selectedUser.location ?? '') || null,
                            cost_center: String(data.get('cost_center') ?? selectedUser.cost_center ?? '') || null,
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
                          <span>location</span>
                          <input name="location" defaultValue={selectedUser.location ?? ''} />
                        </label>
                        <label>
                          <span>cost_center</span>
                          <input name="cost_center" defaultValue={selectedUser.cost_center ?? ''} />
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
                  </section> : null}
                  {canManageUsers || canManageSessions ? <section className="admin-panel admin-danger-zone">
                    <p className="eyebrow">ACCOUNT SECURITY</p>
                    <h3>Пароль и активные сессии</h3>
                    {canManageUsers ? <p className="muted">Новый пароль не попадает в аудит. Все сессии отзываются обязательно, а при следующем входе пользователь должен заменить временный пароль.</p> : null}
                    {canManageUsers ? <div className="form-grid">
                      <label>
                        <span>Новый временный пароль</span>
                        <input
                          type="password"
                          autoComplete="new-password"
                          value={newPasswordDraft}
                          onChange={(event) => setNewPasswordDraft(event.target.value)}
                          placeholder="Минимум по политике организации"
                        />
                      </label>
                      <label className="admin-checkbox-row">
                        <input
                          type="checkbox"
                          checked
                          disabled
                          readOnly
                        />
                        <span>Отозвать все сессии (обязательное требование безопасности)</span>
                      </label>
                    </div> : null}
                    <div className="analytics-actions">
                      {canManageUsers ? <button
                        type="button"
                        disabled={!newPasswordDraft || resetPasswordMutation.isPending}
                        onClick={() => {
                          const confirmed = window.confirm(`${translate('Сбросить пароль пользователя')} ${selectedUser.email}?`)
                          if (confirmed) resetPasswordMutation.mutate(selectedUser.id)
                        }}
                      >
                        {resetPasswordMutation.isPending ? 'Смена пароля…' : 'Сбросить пароль'}
                      </button> : null}
                      {canManageSessions ? (
                        <button
                          type="button"
                          className="ghost-button"
                          disabled={revokeUserSessionsMutation.isPending}
                          onClick={() => {
                            const confirmed = window.confirm(`${translate('Отозвать все активные сессии')} ${selectedUser.email}?`)
                            if (confirmed) revokeUserSessionsMutation.mutate(selectedUser.id)
                          }}
                        >
                          {revokeUserSessionsMutation.isPending ? 'Отзыв…' : 'Отозвать все сессии'}
                        </button>
                      ) : null}
                    </div>
                  </section> : null}
                </>
              ) : null}
            </div>
          </section>
        </div>
      ) : null}

      {roleAssignUserId ? (
        <div className="modal-backdrop" role="presentation" onClick={closeAllModals}>
          <section
            ref={roleAssignDialogRef}
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-role-assign-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="modal-header">
              <div>
                <p className="eyebrow">ASSIGN USER ROLES</p>
                <h2 id="admin-role-assign-title">Назначение роли пользователю</h2>
              </div>
              <button type="button" className="ghost-button" onClick={closeAllModals}>
                Закрыть
              </button>
            </header>
            <div className="modal-body">
              <div className="state-panel">
                <strong>{roleAssignUser?.full_name ?? 'Пользователь'}</strong>
                <p>
                  Организация: {roleAssignUser?.tenant_id
                    ? tenantNameMap.get(roleAssignUser.tenant_id) ?? roleAssignUser.tenant_id
                    : 'Global'}. Показаны только роли этой организации.
                </p>
              </div>
              <fieldset className="admin-role-assignment-fieldset">
                <legend>Роли пользователя</legend>
                <p className="muted">
                  Отмеченный набор полностью заменит текущие роли. Права объединяются без дубликатов.
                </p>
                {roleAssignCurrentRolesQuery.isPending ? (
                  <p className="state-panel state-panel-loading">Загрузка текущих ролей…</p>
                ) : null}
                {roleAssignCurrentRolesQuery.isError ? (
                  <div className="state-panel state-panel-error">
                    <p>Не удалось загрузить текущие роли пользователя.</p>
                    <button type="button" className="ghost-button" onClick={() => roleAssignCurrentRolesQuery.refetch()}>
                      Повторить
                    </button>
                  </div>
                ) : null}
                <div className="admin-permission-checklist admin-role-assignment-options">
                  {roleAssignmentOptions.map((role: AdminRole) => (
                    <label key={role.id}>
                      <input
                        type="checkbox"
                        checked={roleAssignRoleIds.includes(role.id)}
                        disabled={roleAssignCurrentRolesQuery.isPending}
                        onChange={(event) =>
                          setRoleAssignRoleIds((previous) =>
                            event.target.checked
                              ? [...previous, role.id]
                              : previous.filter((roleId) => roleId !== role.id),
                          )
                        }
                      />
                      <span>
                        <strong>{role.name} · {role.code}</strong>
                        <small>
                          {role.is_system ? 'Системная роль' : 'Пользовательская роль'}
                          {role.description ? ` · ${role.description}` : ''}
                        </small>
                      </span>
                    </label>
                  ))}
                </div>
                <p className="muted">
                  Роль organization_admin нельзя снять с последнего активного администратора: сначала назначьте замену.
                </p>
              </fieldset>
              <section className="state-panel" aria-live="polite">
                <strong>
                  Итоговые права: {roleAssignPermissionsQuery.isPending ? 'расчёт…' : roleAssignEffectivePermissions.length}
                </strong>
                {roleAssignEffectivePermissions.length > 0 ? (
                  <p>
                    {roleAssignEffectivePermissions.slice(0, 12).map((permission) => permission.code).join(', ')}
                    {roleAssignEffectivePermissions.length > 12
                      ? ` ${translate('и ещё')} ${roleAssignEffectivePermissions.length - 12}`
                      : ''}
                  </p>
                ) : (
                  <p>Выберите хотя бы одну роль, чтобы пользователь получил рабочие права.</p>
                )}
              </section>
              <footer className="modal-footer">
                <button type="button" className="ghost-button" onClick={closeAllModals}>
                  Отмена
                </button>
                <button
                  type="button"
                  disabled={
                    roleAssignRoleIds.length === 0 ||
                    roleAssignCurrentRolesQuery.isPending ||
                    assignRoleMutation.isPending
                  }
                  onClick={() => {
                    if (roleAssignRoleIds.length === 0) return
                    assignRoleMutation.mutate({
                      userId: roleAssignUserId,
                      roleIds: roleAssignRoleIds,
                    })
                  }}
                >
                  {assignRoleMutation.isPending ? 'Назначение…' : 'Сохранить роли'}
                </button>
              </footer>
            </div>
          </section>
        </div>
      ) : null}

      {selectedAuditId ? (
        <div className="modal-backdrop" role="presentation" onClick={closeAllModals}>
          <section
            ref={auditDetailDialogRef}
            className="modal-card modal-card-xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-audit-detail-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <header className="modal-header">
              <div>
                <p className="eyebrow">AUDIT LOG DETAILS</p>
                <h2 id="admin-audit-detail-title">{selectedAuditQuery.data?.action ?? 'Событие аудита'}</h2>
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
    </LocalizedContent>
  )
}
