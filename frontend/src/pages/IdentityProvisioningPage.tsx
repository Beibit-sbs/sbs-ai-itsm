import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  changeIdentityConnectorState,
  createIdentityConnector,
  deprovisionIdentity,
  fetchAdminRoles,
  fetchAdminUsers,
  fetchIdentityConnectors,
  fetchIdentityOwnership,
  fetchIdentityOwnershipTransfers,
  fetchIdentityProvisioningDashboard,
  fetchIdentityProvisioningEvents,
  fetchProvisionedGroups,
  fetchProvisionedIdentities,
  fetchTenants,
  mapProvisionedGroupRole,
  retryIdentityProvisioningEvent,
  rotateIdentityConnectorToken,
  updateIdentityConnector,
  type IdentityConnector,
  type ProvisionedGroup,
  type ProvisionedIdentity,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { useLocalizedDefaultState } from '../experience/useLocalizedDefaultState'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'

type View = 'overview' | 'connectors' | 'identities' | 'groups' | 'events' | 'transfers'

const views: Array<{ key: View; label: string }> = [
  { key: 'overview', label: 'Обзор' },
  { key: 'connectors', label: 'Подключения' },
  { key: 'identities', label: 'Сотрудники' },
  { key: 'groups', label: 'Группы и роли' },
  { key: 'events', label: 'Журнал синхронизации' },
  { key: 'transfers', label: 'Передача ответственности' },
]

function badgeClass(value: string) {
  const normalized = value.toLowerCase()
  if (['active', 'applied', 'completed'].includes(normalized)) return 'badge badge-positive'
  if (['draft', 'paused', 'retry_scheduled', 'received'].includes(normalized)) return 'badge badge-warning'
  return 'badge badge-danger'
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

export default function IdentityProvisioningPage() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const has = (permission: string) => isRoot || permissions.has(permission)
  const canRead = has('identity.provisioning.read')
  const canManage = has('identity.provisioning.manage')
  const canReadRoles = has('admin.roles.read')
  const canReadUsers = has('admin.users.read')
  const canConfigureConnector = canManage && canReadRoles && canReadUsers
  const [view, setView] = useState<View>('overview')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [selectedConnectorId, setSelectedConnectorId] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [oneTimeToken, setOneTimeToken] = useState<{
    token: string
    connectorName: string
  } | null>(null)
  const [identitySearch, setIdentitySearch] = useState('')
  const [identityState, setIdentityState] = useState('')
  const [eventState, setEventState] = useState('')
  const [offboardingIdentity, setOffboardingIdentity] = useState<ProvisionedIdentity | null>(null)
  const [offboardingOwnerId, setOffboardingOwnerId] = useState('')
  const [offboardingReason, setOffboardingReason] = useLocalizedDefaultState('Завершение работы сотрудника')
  const offboardingDialogRef = useDialogFocusTrap<HTMLElement>(
    Boolean(offboardingIdentity),
    () => setOffboardingIdentity(null),
  )
  const [connectorDraft, setConnectorDraft] = useState({
    name: 'Microsoft Entra ID',
    provider_type: 'ENTRA' as 'SCIM' | 'ENTRA',
    external_tenant_id: '',
    default_role_id: '',
    fallback_owner_id: '',
    allowed_ip_cidrs: '',
    retry_max_attempts: '5',
  })
  const [configurationDraft, setConfigurationDraft] = useState({
    default_role_id: '',
    fallback_owner_id: '',
    allowed_ip_cidrs: '',
    retry_max_attempts: '5',
  })

  const tenantsQuery = useQuery({
    queryKey: ['identity-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot),
  })
  useEffect(() => {
    if (isRoot && !tenantId && tenantsQuery.data?.length) {
      setTenantId(tenantsQuery.data[0].id)
    }
  }, [isRoot, tenantId, tenantsQuery.data])

  const scopedTenant = isRoot ? tenantId || null : session?.user.tenant_id ?? null
  const dashboardQuery = useQuery({
    queryKey: ['identity-dashboard', token, scopedTenant],
    queryFn: () => fetchIdentityProvisioningDashboard(token, scopedTenant),
    enabled: Boolean(token && scopedTenant && canRead),
    refetchInterval: 30_000,
  })
  const connectorsQuery = useQuery({
    queryKey: ['identity-connectors', token, scopedTenant],
    queryFn: () => fetchIdentityConnectors(token, scopedTenant),
    enabled: Boolean(token && scopedTenant && canRead),
    refetchInterval: 30_000,
  })
  const rolesQuery = useQuery({
    queryKey: ['identity-roles', token],
    queryFn: () => fetchAdminRoles(token),
    enabled: Boolean(token && canReadRoles),
  })
  const usersQuery = useQuery({
    queryKey: ['identity-users', token],
    queryFn: () => fetchAdminUsers(token),
    enabled: Boolean(token && canReadUsers),
  })
  const identitiesQuery = useQuery({
    queryKey: [
      'provisioned-identities',
      token,
      scopedTenant,
      selectedConnectorId,
      identityState,
      identitySearch,
    ],
    queryFn: () =>
      fetchProvisionedIdentities(token, {
        tenant_id: scopedTenant,
        connector_id: selectedConnectorId || null,
        lifecycle_state: identityState || null,
        search: identitySearch || null,
        page_size: 250,
      }),
    enabled: Boolean(token && scopedTenant && canRead),
  })
  const groupsQuery = useQuery({
    queryKey: ['provisioned-groups', token, scopedTenant, selectedConnectorId],
    queryFn: () =>
      fetchProvisionedGroups(token, {
        tenant_id: scopedTenant,
        connector_id: selectedConnectorId || null,
      }),
    enabled: Boolean(token && scopedTenant && canRead),
  })
  const eventsQuery = useQuery({
    queryKey: ['identity-events', token, scopedTenant, selectedConnectorId, eventState],
    queryFn: () =>
      fetchIdentityProvisioningEvents(token, {
        tenant_id: scopedTenant,
        connector_id: selectedConnectorId || null,
        status: eventState || null,
        page_size: 250,
      }),
    enabled: Boolean(token && scopedTenant && canRead),
    refetchInterval: 15_000,
  })
  const transfersQuery = useQuery({
    queryKey: ['identity-transfers', token, scopedTenant],
    queryFn: () =>
      fetchIdentityOwnershipTransfers(token, {
        tenant_id: scopedTenant,
        page_size: 250,
      }),
    enabled: Boolean(token && scopedTenant && canRead),
  })
  const ownershipQuery = useQuery({
    queryKey: ['identity-ownership', token, offboardingIdentity?.id],
    queryFn: () => fetchIdentityOwnership(token, offboardingIdentity?.id ?? ''),
    enabled: Boolean(token && offboardingIdentity?.id && canRead),
  })

  const tenantRoles = useMemo(
    () => (rolesQuery.data ?? []).filter((role) => role.tenant_id === scopedTenant && role.code !== 'saas_root'),
    [rolesQuery.data, scopedTenant],
  )
  const tenantUsers = useMemo(
    () => (usersQuery.data ?? []).filter((user) => user.tenant_id === scopedTenant && user.is_active),
    [usersQuery.data, scopedTenant],
  )
  const selectedConnector = useMemo(
    () => (connectorsQuery.data ?? []).find((item) => item.id === selectedConnectorId) ?? null,
    [connectorsQuery.data, selectedConnectorId],
  )

  useEffect(() => {
    if (!selectedConnectorId && connectorsQuery.data?.length) {
      setSelectedConnectorId(connectorsQuery.data[0].id)
    }
  }, [connectorsQuery.data, selectedConnectorId])
  useEffect(() => {
    if (!connectorDraft.default_role_id && tenantRoles.length) {
      setConnectorDraft((current) => ({ ...current, default_role_id: tenantRoles[0].id }))
    }
    if (!connectorDraft.fallback_owner_id && tenantUsers.length) {
      setConnectorDraft((current) => ({ ...current, fallback_owner_id: tenantUsers[0].id }))
    }
  }, [connectorDraft.default_role_id, connectorDraft.fallback_owner_id, tenantRoles, tenantUsers])
  useEffect(() => {
    if (!selectedConnector) return
    setConfigurationDraft({
      default_role_id: selectedConnector.default_role_id,
      fallback_owner_id: selectedConnector.fallback_owner_id,
      allowed_ip_cidrs: selectedConnector.allowed_ip_cidrs.join('\n'),
      retry_max_attempts: String(selectedConnector.retry_max_attempts),
    })
  }, [selectedConnector])

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['identity-dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['identity-connectors'] }),
      queryClient.invalidateQueries({ queryKey: ['provisioned-identities'] }),
      queryClient.invalidateQueries({ queryKey: ['provisioned-groups'] }),
      queryClient.invalidateQueries({ queryKey: ['identity-events'] }),
      queryClient.invalidateQueries({ queryKey: ['identity-transfers'] }),
      queryClient.invalidateQueries({ queryKey: ['identity-users'] }),
    ])
  }
  const mutationCallbacks = {
    onError: (mutationError: unknown) => {
      setNotice('')
      setError(errorText(mutationError))
    },
  }
  const createMutation = useMutation({
    mutationFn: () =>
      createIdentityConnector(token, {
        tenant_id: scopedTenant,
        name: connectorDraft.name,
        provider_type: connectorDraft.provider_type,
        external_tenant_id: connectorDraft.external_tenant_id || null,
        default_role_id: connectorDraft.default_role_id,
        fallback_owner_id: connectorDraft.fallback_owner_id,
        allowed_ip_cidrs: connectorDraft.allowed_ip_cidrs
          .split(/\s|,/)
          .map((item) => item.trim())
          .filter(Boolean),
        retry_max_attempts: Number(connectorDraft.retry_max_attempts),
      }),
    onSuccess: async (result) => {
      setError('')
      setOneTimeToken({ token: result.bearer_token, connectorName: result.connector.name })
      setSelectedConnectorId(result.connector.id)
      setNotice('Подключение создано. Скопируйте секрет до закрытия блока.')
      await invalidate()
    },
    ...mutationCallbacks,
  })
  const stateMutation = useMutation({
    mutationFn: ({ connector, action }: { connector: IdentityConnector; action: 'ACTIVATE' | 'PAUSE' | 'REVOKE' }) =>
      changeIdentityConnectorState(token, connector, action, translate('Изменение через Identity Provisioning Control Plane')),
    onSuccess: async (connector) => {
      setError('')
      setNotice(`${translate('Статус подключения:')} ${connector.status}`)
      await invalidate()
    },
    ...mutationCallbacks,
  })
  const rotateMutation = useMutation({
    mutationFn: (connector: IdentityConnector) => rotateIdentityConnectorToken(token, connector.id),
    onSuccess: async (result) => {
      setError('')
      setOneTimeToken({ token: result.bearer_token, connectorName: result.connector.name })
      setNotice('Токен обновлён. Предыдущий токен больше не работает.')
      await invalidate()
    },
    ...mutationCallbacks,
  })
  const configureMutation = useMutation({
    mutationFn: (connector: IdentityConnector) =>
      updateIdentityConnector(token, connector.id, {
        expected_version: connector.version,
        default_role_id: configurationDraft.default_role_id,
        fallback_owner_id: configurationDraft.fallback_owner_id,
        allowed_ip_cidrs: configurationDraft.allowed_ip_cidrs
          .split(/\s|,/)
          .map((item) => item.trim())
          .filter(Boolean),
        retry_max_attempts: Number(configurationDraft.retry_max_attempts),
      }),
    onSuccess: async () => {
      setError('')
      setNotice('Настройки подключения сохранены.')
      await invalidate()
    },
    ...mutationCallbacks,
  })
  const groupMutation = useMutation({
    mutationFn: ({ group, roleId }: { group: ProvisionedGroup; roleId: string | null }) =>
      mapProvisionedGroupRole(token, group, roleId),
    onSuccess: async () => {
      setError('')
      setNotice('Связь группы с ролью обновлена.')
      await invalidate()
    },
    ...mutationCallbacks,
  })
  const retryMutation = useMutation({
    mutationFn: (eventId: string) => retryIdentityProvisioningEvent(token, eventId),
    onSuccess: async () => {
      setError('')
      setNotice('Событие успешно обработано повторно.')
      await invalidate()
    },
    ...mutationCallbacks,
  })
  const deprovisionMutation = useMutation({
    mutationFn: () =>
      deprovisionIdentity(token, offboardingIdentity?.id ?? '', {
        fallback_owner_id: offboardingOwnerId,
        reason: offboardingReason,
      }),
    onSuccess: async () => {
      setError('')
      setNotice('Сотрудник отключён, активная работа и сессии безопасно переданы.')
      setOffboardingIdentity(null)
      setOffboardingOwnerId('')
      await invalidate()
    },
    ...mutationCallbacks,
  })

  const connectorUrl = `${window.location.origin}/api/v1/scim/v2`
  const busy =
    createMutation.isPending ||
    stateMutation.isPending ||
    rotateMutation.isPending ||
    configureMutation.isPending ||
    groupMutation.isPending ||
    retryMutation.isPending ||
    deprovisionMutation.isPending

  return (
    <LocalizedContent><AppShell
      title="Identity Provisioning"
      subtitle="Microsoft Entra ID / SCIM 2.0, группы, роли и безопасный жизненный цикл сотрудников"
    >
      <section className="identity-toolbar panel">
        <div className="segmented-control" aria-label="Раздел Identity Provisioning">
          {views.map((item) => (
            <button type="button" key={item.key} className={view === item.key ? 'active' : ''} onClick={() => setView(item.key)}>
              {translate(item.label)}
            </button>
          ))}
        </div>
        {isRoot ? (
          <label>Организация<select value={tenantId} onChange={(event) => {
            setTenantId(event.target.value)
            setSelectedConnectorId('')
          }}>
            {(tenantsQuery.data ?? []).map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
          </select></label>
        ) : null}
      </section>

      {notice ? <div className="alert alert-success" role="status" aria-live="polite">{notice}</div> : null}
      <QueryFailureNotice
        title="Часть данных Identity Provisioning недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: translate('оперативная сводка'), query: dashboardQuery },
          { label: translate('SCIM-коннекторы'), query: connectorsQuery },
          { label: translate('роли'), query: rolesQuery },
          { label: translate('пользователи'), query: usersQuery },
          { label: translate('внешние идентификаторы'), query: identitiesQuery },
          { label: translate('группы'), query: groupsQuery },
          { label: 'provisioning events', query: eventsQuery },
          { label: 'ownership transfers', query: transfersQuery },
          { label: 'ownership queue', query: ownershipQuery },
        ]}
      />
      {error ? <div className="alert alert-error" role="alert">{error}</div> : null}

      {oneTimeToken ? (
        <section className="panel identity-secret-panel">
          <div><p className="eyebrow">ОДНОРАЗОВЫЙ СЕКРЕТ · {oneTimeToken.connectorName}</p><h2>Скопируйте токен сейчас</h2><p>После закрытия он больше не показывается. В базе хранится только SHA-256 отпечаток.</p></div>
          <code>{oneTimeToken.token}</code>
          <div className="button-row">
            <button type="button" onClick={async () => {
              await navigator.clipboard.writeText(oneTimeToken.token)
              setNotice('Токен скопирован в буфер обмена.')
            }}>Скопировать токен</button>
            <button type="button" className="secondary" onClick={() => setOneTimeToken(null)}>Я сохранил токен</button>
          </div>
        </section>
      ) : null}

      {view === 'overview' ? (
        <>
          <section className="identity-metrics">
            <article><strong>{dashboardQuery.data?.active_connectors ?? 0}</strong><span>активных подключений</span></article>
            <article><strong>{dashboardQuery.data?.active_identities ?? 0}</strong><span>активных сотрудников</span></article>
            <article><strong>{dashboardQuery.data?.deprovisioned_identities ?? 0}</strong><span>отключено</span></article>
            <article><strong>{dashboardQuery.data?.retry_queue ?? 0}</strong><span>ожидают повтора</span></article>
            <article className={(dashboardQuery.data?.dead_letter ?? 0) > 0 ? 'metric-danger' : ''}><strong>{dashboardQuery.data?.dead_letter ?? 0}</strong><span>dead letter</span></article>
            <article><strong>{dashboardQuery.data?.ownership_transfers ?? 0}</strong><span>передач ответственности</span></article>
          </section>
          <section className="identity-overview-grid">
            <article className="panel">
              <p className="eyebrow">MICROSOFT ENTRA ID</p><h2>Как подключить provisioning</h2>
              <ol className="identity-steps">
                <li>Создайте подключение на вкладке «Подключения» и сохраните одноразовый токен.</li>
                <li>В Entra Enterprise Application откройте Provisioning → Automatic.</li>
                <li>Tenant URL: <code>{connectorUrl}</code></li>
                <li>Secret Token: токен из SBS AI ITSM. Нажмите Test Connection.</li>
                <li>Сопоставьте <code>externalId ← objectId</code>, <code>userName ← mail</code>, <code>active ← Switch([IsSoftDeleted])</code>.</li>
                <li>Включите пользователей и группы в Scope, затем запустите provisioning.</li>
              </ol>
            </article>
            <article className="panel">
              <p className="eyebrow">ЗАЩИТА JML</p><h2>Что происходит автоматически</h2>
              <ul className="identity-checklist">
                <li>✓ Joiner создаёт учётную запись без локального пароля.</li>
                <li>✓ Mover обновляет отдел, должность, руководителя и роли групп.</li>
                <li>✓ Leaver отзывает все сессии и права.</li>
                <li>✓ Заявки, проблемы, изменения, релизы, активы и approvals передаются fallback-владельцу.</li>
                <li>✓ Любая операция идемпотентна, версионируется и попадает в аудит.</li>
                <li>✓ Ошибки повторяются worker-ом с exponential backoff.</li>
              </ul>
            </article>
          </section>
        </>
      ) : null}

      {view === 'connectors' ? (
        <section className="identity-connectors-grid">
          <article className="panel">
            <div className="section-heading"><div><p className="eyebrow">CONTROL PLANE</p><h2>Подключения</h2></div><span className="badge">{connectorsQuery.data?.length ?? 0}</span></div>
            <div className="identity-connector-list">
              {(connectorsQuery.data ?? []).map((connector) => (
                <button type="button" key={connector.id} className={selectedConnectorId === connector.id ? 'identity-connector-card selected' : 'identity-connector-card'} onClick={() => setSelectedConnectorId(connector.id)}>
                  <span><strong>{connector.name}</strong><small>{connector.provider_type} · token …{connector.token_hint}</small></span>
                  <span className={badgeClass(connector.status)}>{connector.status}</span>
                  <span className="identity-card-stats">{connector.counts.active_identities} users · {connector.counts.groups} groups</span>
                </button>
              ))}
              {!connectorsQuery.isLoading && !connectorsQuery.data?.length ? <p className="empty-state">Подключений пока нет.</p> : null}
            </div>
            {selectedConnector ? (
              <div className="identity-connector-actions">
                <div className="key-value-list"><span>SCIM URL</span><code>{connectorUrl}</code><span>Последний успех</span><strong>{formatDateTime(selectedConnector.last_success_at)}</strong><span>Ошибки</span><strong>{selectedConnector.failure_count}</strong></div>
                {selectedConnector.last_error ? <p className="inline-error">{selectedConnector.last_error}</p> : null}
                {canManage ? (
                  <div className="button-row">
                    {['DRAFT', 'PAUSED'].includes(selectedConnector.status) ? <button type="button" disabled={busy} onClick={() => stateMutation.mutate({ connector: selectedConnector, action: 'ACTIVATE' })}>Активировать</button> : null}
                    {selectedConnector.status === 'ACTIVE' ? <button type="button" className="secondary" disabled={busy} onClick={() => stateMutation.mutate({ connector: selectedConnector, action: 'PAUSE' })}>Приостановить</button> : null}
                    {selectedConnector.status !== 'REVOKED' ? <button type="button" className="secondary" disabled={busy} onClick={() => rotateMutation.mutate(selectedConnector)}>Сменить токен</button> : null}
                    {selectedConnector.status !== 'REVOKED' ? <button type="button" className="danger" disabled={busy} onClick={() => {
                      if (window.confirm(translate('Отозвать подключение без возможности восстановления?'))) stateMutation.mutate({ connector: selectedConnector, action: 'REVOKE' })
                    }}>Отозвать</button> : null}
                  </div>
                ) : null}
                {canConfigureConnector && selectedConnector.status !== 'REVOKED' ? (
                  <form className="form-grid" onSubmit={(event) => {
                    event.preventDefault()
                    configureMutation.mutate(selectedConnector)
                  }}>
                    <label>Роль по умолчанию<select value={configurationDraft.default_role_id} onChange={(event) => setConfigurationDraft({ ...configurationDraft, default_role_id: event.target.value })}>{tenantRoles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label>
                    <label>Fallback-владелец<select value={configurationDraft.fallback_owner_id} onChange={(event) => setConfigurationDraft({ ...configurationDraft, fallback_owner_id: event.target.value })}>{tenantUsers.map((user) => <option key={user.id} value={user.id}>{user.full_name} · {user.email}</option>)}</select></label>
                    <label>Повторных попыток<input type="number" min="1" max="20" value={configurationDraft.retry_max_attempts} onChange={(event) => setConfigurationDraft({ ...configurationDraft, retry_max_attempts: event.target.value })} /></label>
                    <label className="span-2">IP allowlist (CIDR, по одному на строку)<textarea rows={3} placeholder="10.0.0.0/8" value={configurationDraft.allowed_ip_cidrs} onChange={(event) => setConfigurationDraft({ ...configurationDraft, allowed_ip_cidrs: event.target.value })} /></label>
                    <button type="submit" disabled={busy}>Сохранить настройки</button>
                  </form>
                ) : null}
              </div>
            ) : null}
          </article>
          {canConfigureConnector ? (
            <article className="panel">
              <p className="eyebrow">НОВОЕ ПОДКЛЮЧЕНИЕ</p><h2>Entra ID или SCIM 2.0</h2>
              <form className="form-grid" onSubmit={(event) => {
                event.preventDefault()
                setError('')
                createMutation.mutate()
              }}>
                <label>Название<input required minLength={3} value={connectorDraft.name} onChange={(event) => setConnectorDraft({ ...connectorDraft, name: event.target.value })} /></label>
                <label>Провайдер<select value={connectorDraft.provider_type} onChange={(event) => setConnectorDraft({ ...connectorDraft, provider_type: event.target.value as 'SCIM' | 'ENTRA' })}><option value="ENTRA">Microsoft Entra ID</option><option value="SCIM">Generic SCIM 2.0</option></select></label>
                <label className="span-2">Entra Tenant ID (необязательно)<input value={connectorDraft.external_tenant_id} onChange={(event) => setConnectorDraft({ ...connectorDraft, external_tenant_id: event.target.value })} /></label>
                <label>Роль по умолчанию<select required value={connectorDraft.default_role_id} onChange={(event) => setConnectorDraft({ ...connectorDraft, default_role_id: event.target.value })}>{tenantRoles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></label>
                <label>Fallback-владелец<select required value={connectorDraft.fallback_owner_id} onChange={(event) => setConnectorDraft({ ...connectorDraft, fallback_owner_id: event.target.value })}>{tenantUsers.map((user) => <option key={user.id} value={user.id}>{user.full_name} · {user.email}</option>)}</select></label>
                <label>Повторных попыток<input type="number" min="1" max="20" value={connectorDraft.retry_max_attempts} onChange={(event) => setConnectorDraft({ ...connectorDraft, retry_max_attempts: event.target.value })} /></label>
                <label className="span-2">IP allowlist (пусто = без ограничения)<textarea rows={3} value={connectorDraft.allowed_ip_cidrs} onChange={(event) => setConnectorDraft({ ...connectorDraft, allowed_ip_cidrs: event.target.value })} /></label>
                <button type="submit" disabled={busy || !scopedTenant || !connectorDraft.default_role_id || !connectorDraft.fallback_owner_id}>Создать и получить токен</button>
              </form>
            </article>
          ) : null}
        </section>
      ) : null}

      {view === 'identities' ? (
        <section className="panel">
          <div className="section-heading"><div><p className="eyebrow">JOINER · MOVER · LEAVER</p><h2>Сотрудники</h2></div><span className="badge">{identitiesQuery.data?.total ?? 0}</span></div>
          <div className="filter-row">
            <input placeholder="Поиск по имени, email или external ID" value={identitySearch} onChange={(event) => setIdentitySearch(event.target.value)} />
            <select value={selectedConnectorId} onChange={(event) => setSelectedConnectorId(event.target.value)}><option value="">Все подключения</option>{(connectorsQuery.data ?? []).map((connector) => <option key={connector.id} value={connector.id}>{connector.name}</option>)}</select>
            <select value={identityState} onChange={(event) => setIdentityState(event.target.value)}><option value="">Все состояния</option><option value="ACTIVE">ACTIVE</option><option value="DEPROVISIONED">DEPROVISIONED</option><option value="SUSPENDED">SUSPENDED</option></select>
          </div>
          <div className="table-scroll"><table>
            <thead><tr><th>Сотрудник</th><th>Источник</th><th>Отдел / должность</th><th>Группы</th><th>Состояние</th><th>Последняя синхронизация</th><th /></tr></thead>
            <tbody>{(identitiesQuery.data?.items ?? []).map((identity) => (
              <tr key={identity.id}>
                <td><strong>{identity.user?.full_name ?? identity.user_name}</strong><small>{identity.user_name}<br />ID: {identity.external_id}</small></td>
                <td>{(connectorsQuery.data ?? []).find((item) => item.id === identity.connector_id)?.name ?? identity.connector_id.slice(0, 8)}</td>
                <td>{identity.user?.department ?? '—'}<small>{identity.user?.position ?? '—'}</small></td>
                <td>{identity.groups.map((group) => group.display_name).join(', ') || 'Роль по умолчанию'}</td>
                <td><span className={badgeClass(identity.lifecycle_state)}>{identity.lifecycle_state}</span></td>
                <td>{formatDateTime(identity.last_synced_at)}</td>
                <td>{canManage && canReadUsers && identity.lifecycle_state === 'ACTIVE' ? <button type="button" className="danger compact" onClick={() => {
                  setOffboardingIdentity(identity)
                  const connector = (connectorsQuery.data ?? []).find((item) => item.id === identity.connector_id)
                  setOffboardingOwnerId(connector?.fallback_owner_id ?? '')
                }}>Offboard</button> : null}</td>
              </tr>
            ))}</tbody>
          </table></div>
        </section>
      ) : null}

      {offboardingIdentity ? (
        <div className="modal-backdrop" role="presentation">
          <section
            ref={offboardingDialogRef}
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-label="Безопасное отключение"
            tabIndex={-1}
          >
            <p className="eyebrow">SAFE OFFBOARDING</p><h2>{offboardingIdentity.user?.full_name ?? offboardingIdentity.user_name}</h2><p>Система отзовёт сессии и передаст активную ответственность выбранному сотруднику.</p>
            {ownershipQuery.isLoading ? <p>Проверяем владение…</p> : <div className="identity-ownership-preview"><strong>{ownershipQuery.data?.total ?? 0}</strong><span>объектов будет переназначено</span>{Object.entries(ownershipQuery.data?.counts ?? {}).filter(([, count]) => count > 0).map(([key, count]) => <small key={key}>{key}: {count}</small>)}</div>}
            <label>Новый владелец<select value={offboardingOwnerId} onChange={(event) => setOffboardingOwnerId(event.target.value)}>{tenantUsers.filter((user) => user.id !== offboardingIdentity.user_id).map((user) => <option key={user.id} value={user.id}>{user.full_name} · {user.email}</option>)}</select></label>
            <label>Причина<textarea rows={3} value={offboardingReason} onChange={(event) => setOffboardingReason(event.target.value)} /></label>
            <div className="button-row"><button type="button" className="danger" disabled={busy || !offboardingOwnerId || offboardingReason.length < 5} onClick={() => deprovisionMutation.mutate()}>Отключить и передать</button><button type="button" className="secondary" onClick={() => setOffboardingIdentity(null)}>Отмена</button></div>
          </section>
        </div>
      ) : null}

      {view === 'groups' ? (
        <section className="panel">
          <div className="section-heading"><div><p className="eyebrow">GROUP-BASED RBAC</p><h2>Группы и роли</h2></div><span className="badge">{groupsQuery.data?.length ?? 0}</span></div>
          <p>Группы приходят из Entra/SCIM. Здесь администратор задаёт роль платформы; роли участников пересчитываются автоматически.</p>
          <div className="table-scroll"><table>
            <thead><tr><th>Группа</th><th>External ID</th><th>Участники</th><th>Роль SBS AI ITSM</th><th>Синхронизация</th></tr></thead>
            <tbody>{(groupsQuery.data ?? []).map((group) => (
              <tr key={group.id}><td><strong>{group.display_name}</strong><small>{group.is_active ? 'ACTIVE' : 'INACTIVE'}</small></td><td><code>{group.external_id}</code></td><td>{group.member_count}</td><td><select disabled={!canManage || !canReadRoles || busy} value={group.mapped_role_id ?? ''} onChange={(event) => groupMutation.mutate({ group, roleId: event.target.value || null })}><option value="">Роль подключения по умолчанию</option>{tenantRoles.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}</select></td><td>{formatDateTime(group.last_synced_at)}</td></tr>
            ))}</tbody>
          </table></div>
        </section>
      ) : null}

      {view === 'events' ? (
        <section className="panel">
          <div className="section-heading"><div><p className="eyebrow">PROVISIONING AUDIT</p><h2>Журнал синхронизации</h2></div><span className="badge">{eventsQuery.data?.total ?? 0}</span></div>
          <div className="filter-row"><select value={eventState} onChange={(event) => setEventState(event.target.value)}><option value="">Все статусы</option><option value="APPLIED">APPLIED</option><option value="RETRY_SCHEDULED">RETRY_SCHEDULED</option><option value="DEAD_LETTER">DEAD_LETTER</option><option value="FAILED">FAILED</option></select></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Время</th><th>Ресурс</th><th>Операция</th><th>Статус</th><th>Попытки</th><th>Ошибка / следующий повтор</th><th /></tr></thead>
            <tbody>{(eventsQuery.data?.items ?? []).map((event) => (
              <tr key={event.id}><td>{formatDateTime(event.created_at)}</td><td>{event.resource_type}<small>{event.external_id ?? '—'}<br />request: {event.external_event_id}</small></td><td>{event.operation}</td><td><span className={badgeClass(event.status)}>{event.status}</span></td><td>{event.attempts}</td><td>{event.error_message ?? '—'}<small>{event.next_retry_at ? `${translate('Повтор:')} ${formatDateTime(event.next_retry_at)}` : ''}</small></td><td>{canManage && ['FAILED', 'RETRY_SCHEDULED', 'DEAD_LETTER'].includes(event.status) ? <button type="button" className="secondary compact" disabled={busy} onClick={() => retryMutation.mutate(event.id)}>Повторить</button> : null}</td></tr>
            ))}</tbody>
          </table></div>
        </section>
      ) : null}

      {view === 'transfers' ? (
        <section className="panel">
          <div className="section-heading"><div><p className="eyebrow">NO ORPHANED WORK</p><h2>Передача ответственности</h2></div><span className="badge">{transfersQuery.data?.total ?? 0}</span></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Время</th><th>От сотрудника</th><th>Новому владельцу</th><th>Передано</th><th>Сессии</th><th>Причина</th></tr></thead>
            <tbody>{(transfersQuery.data?.items ?? []).map((transfer) => {
              const from = (usersQuery.data ?? []).find((user) => user.id === transfer.from_user_id)
              const to = (usersQuery.data ?? []).find((user) => user.id === transfer.to_user_id)
              const total = Object.values(transfer.counts).reduce((sum, value) => sum + value, 0)
              return <tr key={transfer.id}><td>{formatDateTime(transfer.created_at)}</td><td>{from?.full_name ?? transfer.from_user_id}<small>{from?.email}</small></td><td>{to?.full_name ?? transfer.to_user_id}<small>{to?.email}</small></td><td>{total}<small>{Object.entries(transfer.counts).filter(([, count]) => count > 0).map(([key, count]) => `${key}: ${count}`).join(' · ') || 'Нет активных объектов'}</small></td><td>{transfer.sessions_revoked} отозвано</td><td>{transfer.reason}</td></tr>
            })}</tbody>
          </table></div>
        </section>
      ) : null}
    </AppShell></LocalizedContent>
  )
}
