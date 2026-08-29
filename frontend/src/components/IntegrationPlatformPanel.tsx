import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createIntegrationServiceAccount,
  createOutboundWebhookSubscription,
  fetchIntegrationApiRequestLogs,
  fetchIntegrationApiTokens,
  fetchIntegrationConnectorContract,
  fetchIntegrationPlatformDashboard,
  fetchIntegrationPlatformScopes,
  fetchIntegrationServiceAccounts,
  fetchOutboundWebhookDeliveries,
  fetchOutboundWebhookSubscriptions,
  fetchTenants,
  issueIntegrationApiToken,
  replayOutboundWebhookDelivery,
  revokeIntegrationApiToken,
  rotateIntegrationApiToken,
  rotateOutboundWebhookSecret,
  testOutboundWebhookSubscription,
  updateIntegrationServiceAccount,
  updateOutboundWebhookSubscription,
  type IntegrationApiToken,
  type IntegrationServiceAccount,
  type OutboundWebhookSubscription,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import QueryFailureNotice from './QueryFailureNotice'

type View = 'overview' | 'accounts' | 'webhooks' | 'deliveries' | 'audit' | 'sdk'

const views: Array<{ key: View; label: string }> = [
  { key: 'overview', label: 'Обзор' },
  { key: 'accounts', label: 'Сервисные аккаунты' },
  { key: 'webhooks', label: 'Исходящие webhooks' },
  { key: 'deliveries', label: 'Доставка и DLQ' },
  { key: 'audit', label: 'API-аудит' },
  { key: 'sdk', label: 'SDK-контракт' },
]

const defaultEvents = [
  'ticket_created',
  'ticket_status_changed',
  'sla_breached',
  'major_incident.declared',
  'approval.requested',
  'security_high_risk',
].join(', ')

function splitValues(value: string, lowercase = false) {
  return Array.from(new Set(
    value
      .split(/[\n,;]+/)
      .map((item) => (lowercase ? item.trim().toLowerCase() : item.trim()))
      .filter(Boolean),
  ))
}

function statusClass(value: string) {
  const normalized = value.toUpperCase()
  if (['ACTIVE', 'SUCCEEDED', 'ALLOWED'].includes(normalized)) {
    return 'badge badge-positive'
  }
  if (['DRAFT', 'PAUSED', 'PENDING', 'PROCESSING', 'RETRY'].includes(normalized)) {
    return 'badge badge-warning'
  }
  return 'badge badge-danger'
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

export default function IntegrationPlatformPanel() {
  const { session } = useAuth()
  const { translate, formatDateTime } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const user = session?.user
  const isRoot = user?.role === 'saas_root'
  const has = (permission: string) => Boolean(isRoot || user?.permissions.includes(permission))
  const canReadAccounts = has('integration.platform.accounts.read')
  const canManageAccounts = has('integration.platform.accounts.manage')
  const canReadTokens = has('integration.platform.tokens.read')
  const canIssueTokens = has('integration.platform.tokens.issue')
  const canRevokeTokens = has('integration.platform.tokens.revoke')
  const canReadWebhooks = has('integration.platform.webhooks.read')
  const canManageWebhooks = has('integration.platform.webhooks.manage')
  const canReplay = has('integration.platform.webhooks.replay')
  const canObserve = has('integration.platform.observability.read')

  const [view, setView] = useState<View>('overview')
  const [tenantId, setTenantId] = useState(user?.tenant_id ?? '')
  const [selectedAccountId, setSelectedAccountId] = useState('')
  const [selectedWebhookId, setSelectedWebhookId] = useState('')
  const [deliveryStatus, setDeliveryStatus] = useState('ALL')
  const [auditOutcome, setAuditOutcome] = useState<'ALL' | 'ALLOWED' | 'DENIED'>('ALL')
  const [busy, setBusy] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [revealed, setRevealed] = useState<{ title: string; value: string } | null>(null)
  const [accountDraft, setAccountDraft] = useState({
    name: '',
    description: '',
    scopes: ['integration.events.write'],
    cidrs: '',
    rate: '120',
    ttl: '90',
  })
  const [accountEdit, setAccountEdit] = useState({
    name: '',
    description: '',
    scopes: [] as string[],
    cidrs: '',
    rate: '120',
    ttl: '90',
    reason: 'Плановое изменение конфигурации',
  })
  const [tokenDraft, setTokenDraft] = useState({
    name: 'Основной токен',
    scopes: [] as string[],
    ttl: '30',
  })
  const [webhookDraft, setWebhookDraft] = useState({
    name: '',
    description: '',
    target: '',
    events: defaultEvents,
    timeout: '15',
    attempts: '6',
  })
  const [webhookEdit, setWebhookEdit] = useState({
    name: '',
    description: '',
    target: '',
    events: '',
    timeout: '15',
    attempts: '6',
    reason: 'Плановое изменение конфигурации',
  })

  const tenantsQuery = useQuery({
    queryKey: ['integration-platform', 'tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot),
  })
  useEffect(() => {
    if (isRoot && !tenantId && tenantsQuery.data?.length) {
      setTenantId(tenantsQuery.data[0].id)
    }
  }, [isRoot, tenantId, tenantsQuery.data])
  const scopedTenant = isRoot ? tenantId || null : user?.tenant_id ?? null

  const scopesQuery = useQuery({
    queryKey: ['integration-platform', 'scopes', token],
    queryFn: () => fetchIntegrationPlatformScopes(token),
    enabled: Boolean(token && canReadAccounts),
  })
  const dashboardQuery = useQuery({
    queryKey: ['integration-platform', 'dashboard', token, scopedTenant],
    queryFn: () => fetchIntegrationPlatformDashboard(token, scopedTenant),
    enabled: Boolean(token && scopedTenant && canObserve),
    refetchInterval: 15_000,
  })
  const accountsQuery = useQuery({
    queryKey: ['integration-platform', 'accounts', token, scopedTenant],
    queryFn: () => fetchIntegrationServiceAccounts(token, scopedTenant),
    enabled: Boolean(token && scopedTenant && canReadAccounts),
    refetchInterval: 15_000,
  })
  const webhooksQuery = useQuery({
    queryKey: ['integration-platform', 'webhooks', token, scopedTenant],
    queryFn: () => fetchOutboundWebhookSubscriptions(token, scopedTenant),
    enabled: Boolean(token && scopedTenant && canReadWebhooks),
    refetchInterval: 10_000,
  })
  const deliveriesQuery = useQuery({
    queryKey: [
      'integration-platform',
      'deliveries',
      token,
      scopedTenant,
      selectedWebhookId,
      deliveryStatus,
    ],
    queryFn: () => fetchOutboundWebhookDeliveries(token, {
      tenant_id: scopedTenant,
      subscription_id: selectedWebhookId || undefined,
      status: deliveryStatus,
      limit: 250,
    }),
    enabled: Boolean(token && scopedTenant && canReadWebhooks),
    refetchInterval: 5_000,
  })
  const auditQuery = useQuery({
    queryKey: [
      'integration-platform',
      'audit',
      token,
      scopedTenant,
      selectedAccountId,
      auditOutcome,
    ],
    queryFn: () => fetchIntegrationApiRequestLogs(token, {
      tenant_id: scopedTenant,
      account_id: selectedAccountId || undefined,
      outcome: auditOutcome === 'ALL' ? undefined : auditOutcome,
      limit: 250,
    }),
    enabled: Boolean(token && scopedTenant && canObserve),
    refetchInterval: 15_000,
  })
  const contractQuery = useQuery({
    queryKey: ['integration-platform', 'contract', token],
    queryFn: () => fetchIntegrationConnectorContract(token),
    enabled: Boolean(token && canReadAccounts),
  })

  const accounts = accountsQuery.data ?? []
  const webhooks = webhooksQuery.data ?? []
  const selectedAccount = useMemo(
    () => accounts.find((item) => item.id === selectedAccountId) ?? null,
    [accounts, selectedAccountId],
  )
  const selectedWebhook = useMemo(
    () => webhooks.find((item) => item.id === selectedWebhookId) ?? null,
    [webhooks, selectedWebhookId],
  )
  const tokensQuery = useQuery({
    queryKey: ['integration-platform', 'tokens', token, selectedAccountId],
    queryFn: () => fetchIntegrationApiTokens(token, selectedAccountId),
    enabled: Boolean(token && selectedAccountId && canReadTokens),
    refetchInterval: 15_000,
  })

  useEffect(() => {
    if (!selectedAccountId && accounts.length) setSelectedAccountId(accounts[0].id)
    if (selectedAccountId && !accounts.some((item) => item.id === selectedAccountId)) {
      setSelectedAccountId(accounts[0]?.id ?? '')
    }
  }, [accounts, selectedAccountId])
  useEffect(() => {
    if (!selectedWebhookId && webhooks.length) setSelectedWebhookId(webhooks[0].id)
    if (selectedWebhookId && !webhooks.some((item) => item.id === selectedWebhookId)) {
      setSelectedWebhookId(webhooks[0]?.id ?? '')
    }
  }, [webhooks, selectedWebhookId])
  useEffect(() => {
    if (!selectedAccount) return
    setAccountEdit({
      name: selectedAccount.name,
      description: selectedAccount.description ?? '',
      scopes: selectedAccount.allowed_scopes,
      cidrs: selectedAccount.allowed_ip_cidrs.join(', '),
      rate: String(selectedAccount.rate_limit_per_minute),
      ttl: String(selectedAccount.max_token_ttl_days),
      reason: 'Плановое изменение конфигурации',
    })
    setTokenDraft((current) => ({
      ...current,
      scopes: selectedAccount.allowed_scopes,
    }))
  }, [selectedAccount])
  useEffect(() => {
    if (!selectedWebhook) return
    setWebhookEdit({
      name: selectedWebhook.name,
      description: selectedWebhook.description ?? '',
      target: '',
      events: selectedWebhook.event_types.join(', '),
      timeout: String(selectedWebhook.timeout_seconds),
      attempts: String(selectedWebhook.max_attempts),
      reason: 'Плановое изменение конфигурации',
    })
  }, [selectedWebhook])
  useEffect(() => {
    setRevealed(null)
    setSelectedAccountId('')
    setSelectedWebhookId('')
  }, [scopedTenant])

  async function refresh() {
    await queryClient.invalidateQueries({ queryKey: ['integration-platform'] })
  }

  async function runAction<T>(
    key: string,
    operation: () => Promise<T>,
    success: string,
  ): Promise<T | null> {
    setBusy(key)
    setError('')
    setNotice('')
    try {
      const result = await operation()
      setNotice(success)
      await refresh()
      return result
    } catch (caught) {
      setError(errorText(caught))
      return null
    } finally {
      setBusy('')
    }
  }

  function toggleScope(
    current: string[],
    scope: string,
    update: (next: string[]) => void,
  ) {
    update(
      current.includes(scope)
        ? current.filter((item) => item !== scope)
        : [...current, scope],
    )
  }

  async function copyRevealed() {
    if (!revealed) return
    try {
      await navigator.clipboard.writeText(revealed.value)
      setNotice('Секрет скопирован в буфер обмена.')
    } catch {
      setError('Браузер запретил доступ к буферу обмена.')
    }
  }

  const dashboard = dashboardQuery.data
  const activeAccounts = dashboard?.service_accounts.ACTIVE ?? 0
  const activeWebhooks = dashboard?.webhook_subscriptions.ACTIVE ?? 0
  const failedDeliveries =
    (dashboard?.deliveries.FAILED ?? 0) + (dashboard?.deliveries.DEAD_LETTER ?? 0)
  const testPassed = Boolean(
    selectedWebhook
    && selectedWebhook.last_tested_target_version === selectedWebhook.target_version
    && selectedWebhook.last_tested_secret_version === selectedWebhook.signing_secret_version,
  )

  if (!canReadAccounts && !canReadWebhooks && !canObserve) {
    return (
      <LocalizedContent>
        <section className="section-card">
          <p className="state-panel state-panel-empty">
            Для production-платформы интеграций вашей роли не назначены права доступа.
          </p>
        </section>
      </LocalizedContent>
    )
  }

  return (
    <LocalizedContent>
      <div className="integration-platform">
      <section className="section-card integration-platform-hero">
        <div className="section-header">
          <div>
            <p className="eyebrow">PRODUCTION INTEGRATION CONTROL PLANE</p>
            <h2 className="section-title">Защищённая платформа интеграций</h2>
            <p className="section-subtitle">
              Scoped API-токены, IP-ограничения, подписанные CloudEvents webhooks,
              автоматические повторы, dead-letter и аудит каждого обращения.
            </p>
          </div>
          {isRoot ? (
            <label className="inline-field">
              <span>Организация</span>
              <select value={tenantId} onChange={(event) => setTenantId(event.target.value)}>
                <option value="">Выберите организацию</option>
                {(tenantsQuery.data ?? []).map((tenant) => (
                  <option value={tenant.id} key={tenant.id}>{tenant.name}</option>
                ))}
              </select>
            </label>
          ) : null}
        </div>
      </section>

      <nav className="module-subnav" aria-label="Integration platform navigation">
        {views.map((item) => (
          <button
            type="button"
            className={`module-subnav-tab ${view === item.key ? 'active' : ''}`}
            onClick={() => setView(item.key)}
            key={item.key}
          >
            {translate(item.label)}
          </button>
        ))}
      </nav>

      <QueryFailureNotice
        title="Часть данных Integration Platform недоступна."
        sources={[
          { label: 'организации', query: tenantsQuery },
          { label: 'scopes', query: scopesQuery },
          { label: 'оперативная сводка', query: dashboardQuery },
          { label: 'accounts', query: accountsQuery },
          { label: 'webhooks', query: webhooksQuery },
          { label: 'deliveries', query: deliveriesQuery },
          { label: 'аудит', query: auditQuery },
          { label: 'contract', query: contractQuery },
          { label: 'tokens', query: tokensQuery },
        ]}
      />
      {error ? <div className="alert alert-danger" role="alert">{error}</div> : null}
      {notice ? <div className="alert alert-success">{notice}</div> : null}
      {revealed ? (
        <section className="event-secret-box" aria-live="polite">
          <div>
            <span>{revealed.title} — показывается только сейчас</span>
            <code>{revealed.value}</code>
          </div>
          <div className="analytics-actions">
            <button type="button" onClick={() => void copyRevealed()}>Копировать</button>
            <button type="button" className="ghost-button" onClick={() => setRevealed(null)}>
              Я сохранил
            </button>
          </div>
        </section>
      ) : null}

      {view === 'overview' ? (
        <>
          <section className="module-overview-grid">
            <article className="metric-card">
              <span>Активные сервисные аккаунты</span>
              <strong>{dashboardQuery.isPending ? '…' : activeAccounts}</strong>
              <p>Машинные клиенты с ограниченными scope.</p>
            </article>
            <article className="metric-card">
              <span>Активные webhooks</span>
              <strong>{dashboardQuery.isPending ? '…' : activeWebhooks}</strong>
              <p>Проверенные подписки с HMAC-подписью.</p>
            </article>
            <article className="metric-card">
              <span>Ошибки и DLQ</span>
              <strong>{dashboardQuery.isPending ? '…' : failedDeliveries}</strong>
              <p>Доставки, требующие анализа или replay.</p>
            </article>
            <article className="metric-card">
              <span>Средняя доставка</span>
              <strong>{dashboardQuery.isPending ? '…' : `${dashboard?.average_delivery_latency_ms ?? 0} ms`}</strong>
              <p>Средняя задержка успешных webhook-вызовов.</p>
            </article>
          </section>
          <section className="section-card dashboard-split">
            <div>
              <p className="eyebrow">API SECURITY</p>
              <h2>Доступ сервисов</h2>
              <div className="activity-list">
                <article className="activity-item">
                  <header><strong>Разрешено</strong><span className="badge badge-positive">{dashboard?.api_requests.allowed ?? 0}</span></header>
                  <p>Запросы с валидным токеном, scope, CIDR и лимитом.</p>
                </article>
                <article className="activity-item">
                  <header><strong>Отклонено</strong><span className="badge badge-danger">{dashboard?.api_requests.denied ?? 0}</span></header>
                  <p>Отказы видны в API-аудите с безопасной причиной.</p>
                </article>
              </div>
            </div>
            <div>
              <p className="eyebrow">OUTBOUND SAFETY</p>
              <h2>Allowlist получателей</h2>
              <p className="section-subtitle">
                Redirect запрещён, URL и signing secret зашифрованы, ответ ограничен по размеру.
              </p>
              <p className={`alert ${dashboard?.outbound_allowed_hosts_configured ? 'alert-success' : 'alert-warning'}`}>
                {dashboard?.outbound_allowed_hosts_configured
                  ? 'Allowlist исходящих webhook-хостов настроен.'
                  : 'Исходящие webhooks отключены: задайте INTEGRATION_OUTBOUND_WEBHOOK_ALLOWED_HOSTS.'}
              </p>
            </div>
          </section>
        </>
      ) : null}

      {view === 'accounts' ? (
        <>
          {canManageAccounts ? (
            <section className="section-card">
              <div className="section-header">
                <div>
                  <h2 className="section-title">Новый сервисный аккаунт</h2>
                  <p className="section-subtitle">Сначала задайте максимально узкие scope и CIDR, затем выпустите токен.</p>
                </div>
              </div>
              <div className="form-grid">
                <label><span>Название</span><input value={accountDraft.name} onChange={(event) => setAccountDraft({ ...accountDraft, name: event.target.value })} placeholder="Monitoring gateway" /></label>
                <label><span>Rate limit / мин.</span><input type="number" min="1" max="10000" value={accountDraft.rate} onChange={(event) => setAccountDraft({ ...accountDraft, rate: event.target.value })} /></label>
                <label><span>Макс. TTL токена, дней</span><input type="number" min="1" max="365" value={accountDraft.ttl} onChange={(event) => setAccountDraft({ ...accountDraft, ttl: event.target.value })} /></label>
                <label><span>Описание</span><input value={accountDraft.description} onChange={(event) => setAccountDraft({ ...accountDraft, description: event.target.value })} /></label>
                <label><span>Разрешённые CIDR (пусто = любые)</span><input value={accountDraft.cidrs} onChange={(event) => setAccountDraft({ ...accountDraft, cidrs: event.target.value })} placeholder="10.10.0.0/16, 203.0.113.8/32" /></label>
              </div>
              <div className="integration-scope-grid">
                {(scopesQuery.data ?? []).map((scope) => (
                  <label className="integration-scope-option" key={scope.scope}>
                    <input
                      type="checkbox"
                      checked={accountDraft.scopes.includes(scope.scope)}
                      onChange={() => toggleScope(
                        accountDraft.scopes,
                        scope.scope,
                        (next) => setAccountDraft({ ...accountDraft, scopes: next }),
                      )}
                    />
                    <span><strong>{scope.scope}</strong><small>{scope.description}</small></span>
                  </label>
                ))}
              </div>
              <div className="analytics-actions">
                <button
                  type="button"
                  disabled={Boolean(busy) || !scopedTenant || !accountDraft.name.trim() || !accountDraft.scopes.length}
                  onClick={() => void runAction(
                    'create-account',
                    () => createIntegrationServiceAccount(token, {
                      tenant_id: isRoot ? scopedTenant : undefined,
                      name: accountDraft.name,
                      description: accountDraft.description,
                      allowed_scopes: accountDraft.scopes,
                      allowed_ip_cidrs: splitValues(accountDraft.cidrs),
                      rate_limit_per_minute: Number(accountDraft.rate),
                      max_token_ttl_days: Number(accountDraft.ttl),
                    }),
                    'Сервисный аккаунт создан.',
                  ).then((created) => {
                    if (!created) return
                    setSelectedAccountId(created.id)
                    setAccountDraft({ name: '', description: '', scopes: ['integration.events.write'], cidrs: '', rate: '120', ttl: '90' })
                  })}
                >
                  Создать аккаунт
                </button>
              </div>
            </section>
          ) : null}

          <section className="section-card">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead><tr><th>Аккаунт</th><th>Статус</th><th>Scope</th><th>Токены</th><th>Запросы</th><th>Последнее использование</th></tr></thead>
                <tbody>
                  {accountsQuery.isPending ? <tr><td colSpan={6}><p className="state-panel state-panel-loading">Загрузка сервисных аккаунтов…</p></td></tr> : null}
                  {!accountsQuery.isPending && !accounts.length ? <tr><td colSpan={6}><p className="state-panel state-panel-empty">Сервисные аккаунты ещё не созданы.</p></td></tr> : null}
                  {accounts.map((item) => (
                    <tr
                      key={item.id}
                      className={selectedAccountId === item.id ? 'selected-row' : ''}
                      onClick={() => setSelectedAccountId(item.id)}
                    >
                      <td><strong>{item.name}</strong><p className="table-subtext">{item.client_id}</p></td>
                      <td><span className={statusClass(item.status)}>{item.status}</span></td>
                      <td>{item.allowed_scopes.join(', ')}</td>
                      <td>{item.active_tokens}</td>
                      <td>{item.total_requests}<p className="table-subtext">отказов: {item.failed_auth_count}</p></td>
                      <td>{formatDateTime(item.last_used_at)}<p className="table-subtext">{item.last_used_ip ?? '—'}</p></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {selectedAccount ? (
            <section className="section-card dashboard-split">
              <div>
                <p className="eyebrow">ACCOUNT POLICY</p>
                <h2>{selectedAccount.name}</h2>
                <div className="form-grid">
                  <label><span>Название</span><input value={accountEdit.name} disabled={!canManageAccounts || selectedAccount.status === 'REVOKED'} onChange={(event) => setAccountEdit({ ...accountEdit, name: event.target.value })} /></label>
                  <label><span>Rate limit / мин.</span><input type="number" min="1" max="10000" value={accountEdit.rate} disabled={!canManageAccounts || selectedAccount.status === 'REVOKED'} onChange={(event) => setAccountEdit({ ...accountEdit, rate: event.target.value })} /></label>
                  <label><span>Макс. TTL, дней</span><input type="number" min="1" max="365" value={accountEdit.ttl} disabled={!canManageAccounts || selectedAccount.status === 'REVOKED'} onChange={(event) => setAccountEdit({ ...accountEdit, ttl: event.target.value })} /></label>
                  <label><span>Описание</span><input value={accountEdit.description} disabled={!canManageAccounts || selectedAccount.status === 'REVOKED'} onChange={(event) => setAccountEdit({ ...accountEdit, description: event.target.value })} /></label>
                  <label><span>CIDR</span><input value={accountEdit.cidrs} disabled={!canManageAccounts || selectedAccount.status === 'REVOKED'} onChange={(event) => setAccountEdit({ ...accountEdit, cidrs: event.target.value })} /></label>
                  <label><span>Причина</span><input value={accountEdit.reason} disabled={!canManageAccounts || selectedAccount.status === 'REVOKED'} onChange={(event) => setAccountEdit({ ...accountEdit, reason: event.target.value })} /></label>
                </div>
                <div className="integration-scope-grid">
                  {(scopesQuery.data ?? []).map((scope) => (
                    <label className="integration-scope-option" key={scope.scope}>
                      <input
                        type="checkbox"
                        checked={accountEdit.scopes.includes(scope.scope)}
                        disabled={!canManageAccounts || selectedAccount.status === 'REVOKED'}
                        onChange={() => toggleScope(
                          accountEdit.scopes,
                          scope.scope,
                          (next) => setAccountEdit({ ...accountEdit, scopes: next }),
                        )}
                      />
                      <span><strong>{scope.scope}</strong><small>{scope.description}</small></span>
                    </label>
                  ))}
                </div>
                {canManageAccounts && selectedAccount.status !== 'REVOKED' ? (
                  <div className="analytics-actions">
                    <button
                      type="button"
                      disabled={Boolean(busy) || accountEdit.reason.trim().length < 3 || !accountEdit.scopes.length}
                      onClick={() => void runAction(
                        'save-account',
                        () => updateIntegrationServiceAccount(token, selectedAccount.id, {
                          expected_version: selectedAccount.version,
                          name: accountEdit.name,
                          description: accountEdit.description,
                          allowed_scopes: accountEdit.scopes,
                          allowed_ip_cidrs: splitValues(accountEdit.cidrs),
                          rate_limit_per_minute: Number(accountEdit.rate),
                          max_token_ttl_days: Number(accountEdit.ttl),
                          reason: accountEdit.reason,
                        }),
                        'Политика аккаунта сохранена.',
                      )}
                    >
                      Сохранить
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      disabled={Boolean(busy)}
                      onClick={() => void runAction(
                        'toggle-account',
                        () => updateIntegrationServiceAccount(token, selectedAccount.id, {
                          expected_version: selectedAccount.version,
                          status: selectedAccount.status === 'ACTIVE' ? 'SUSPENDED' : 'ACTIVE',
                          reason: selectedAccount.status === 'ACTIVE' ? 'Ручная приостановка доступа' : 'Ручное восстановление доступа',
                        }),
                        selectedAccount.status === 'ACTIVE' ? 'Аккаунт приостановлен.' : 'Аккаунт активирован.',
                      )}
                    >
                      {selectedAccount.status === 'ACTIVE' ? 'Приостановить' : 'Активировать'}
                    </button>
                    <button
                      type="button"
                      className="danger-button"
                      disabled={Boolean(busy)}
                      onClick={() => {
                        if (!window.confirm(translate('Безвозвратно отозвать аккаунт и все активные токены?'))) return
                        void runAction(
                          'revoke-account',
                          () => updateIntegrationServiceAccount(token, selectedAccount.id, {
                            expected_version: selectedAccount.version,
                            status: 'REVOKED',
                            reason: 'Администратор отозвал сервисный аккаунт',
                          }),
                          'Аккаунт и его токены отозваны.',
                        )
                      }}
                    >
                      Отозвать аккаунт
                    </button>
                  </div>
                ) : null}
              </div>

              <div>
                <p className="eyebrow">API TOKENS</p>
                <h2>Токены доступа</h2>
                {canIssueTokens && selectedAccount.status === 'ACTIVE' ? (
                  <div className="integration-token-form">
                    <label><span>Название токена</span><input value={tokenDraft.name} onChange={(event) => setTokenDraft({ ...tokenDraft, name: event.target.value })} /></label>
                    <label><span>TTL, дней</span><input type="number" min="1" max={selectedAccount.max_token_ttl_days} value={tokenDraft.ttl} onChange={(event) => setTokenDraft({ ...tokenDraft, ttl: event.target.value })} /></label>
                    <div className="integration-scope-grid">
                      {selectedAccount.allowed_scopes.map((scope) => (
                        <label className="integration-scope-option" key={scope}>
                          <input
                            type="checkbox"
                            checked={tokenDraft.scopes.includes(scope)}
                            onChange={() => toggleScope(
                              tokenDraft.scopes,
                              scope,
                              (next) => setTokenDraft({ ...tokenDraft, scopes: next }),
                            )}
                          />
                          <span><strong>{scope}</strong></span>
                        </label>
                      ))}
                    </div>
                    <button
                      type="button"
                      disabled={Boolean(busy) || !tokenDraft.name.trim() || !tokenDraft.scopes.length}
                      onClick={() => void runAction(
                        'issue-token',
                        () => issueIntegrationApiToken(token, selectedAccount.id, {
                          name: tokenDraft.name,
                          scopes: tokenDraft.scopes,
                          ttl_days: Number(tokenDraft.ttl),
                        }),
                        'Токен выпущен. Сохраните его сейчас.',
                      ).then((created) => {
                        if (created?.access_token) {
                          setRevealed({
                            title: `${translate('API-токен')} «${created.name}»`,
                            value: created.access_token,
                          })
                        }
                      })}
                    >
                      Выпустить токен
                    </button>
                  </div>
                ) : null}
                <div className="activity-list integration-token-list">
                  {tokensQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка токенов…</p> : null}
                  {!tokensQuery.isPending && !(tokensQuery.data ?? []).length ? <p className="state-panel state-panel-empty">Токенов нет.</p> : null}
                  {(tokensQuery.data ?? []).map((item: IntegrationApiToken) => (
                    <article className="activity-item" key={item.id}>
                      <header><strong>{item.name}</strong><span className={statusClass(item.status)}>{item.status}</span></header>
                      <code>{item.token_hint}</code>
                      <p>{item.scopes.join(', ')}</p>
                      <small>Истекает {formatDateTime(item.expires_at)} · использован {formatDateTime(item.last_used_at)}</small>
                      {item.status === 'ACTIVE' ? (
                        <div className="analytics-actions">
                          {canIssueTokens ? (
                            <button
                              type="button"
                              className="ghost-button"
                              disabled={Boolean(busy)}
                              onClick={() => void runAction(
                                `rotate-token-${item.id}`,
                                () => rotateIntegrationApiToken(token, item.id, {
                                  expected_version: item.version,
                                  reason: 'Плановая ротация токена',
                                }),
                                'Токен заменён. Сохраните новый секрет.',
                              ).then((created) => {
                                if (created?.access_token) {
                                  setRevealed({
                                    title: `${translate('Новый API-токен')} «${created.name}»`,
                                    value: created.access_token,
                                  })
                                }
                              })}
                            >
                              Ротировать
                            </button>
                          ) : null}
                          {canRevokeTokens ? (
                            <button
                              type="button"
                              className="danger-button"
                              disabled={Boolean(busy)}
                              onClick={() => {
                                if (!window.confirm(`${translate('Отозвать токен')} ${item.name}?`)) return
                                void runAction(
                                  `revoke-token-${item.id}`,
                                  () => revokeIntegrationApiToken(token, item.id, {
                                    expected_version: item.version,
                                    reason: 'Ручной отзыв токена',
                                  }),
                                  'Токен отозван.',
                                )
                              }}
                            >
                              Отозвать
                            </button>
                          ) : null}
                        </div>
                      ) : null}
                    </article>
                  ))}
                </div>
              </div>
            </section>
          ) : null}
        </>
      ) : null}

      {view === 'webhooks' ? (
        <>
          {canManageWebhooks ? (
            <section className="section-card">
              <div className="section-header">
                <div>
                  <h2 className="section-title">Новая webhook-подписка</h2>
                  <p className="section-subtitle">HTTPS-хост должен быть заранее добавлен в серверный allowlist.</p>
                </div>
              </div>
              <div className="form-grid">
                <label><span>Название</span><input value={webhookDraft.name} onChange={(event) => setWebhookDraft({ ...webhookDraft, name: event.target.value })} /></label>
                <label><span>HTTPS URL</span><input value={webhookDraft.target} onChange={(event) => setWebhookDraft({ ...webhookDraft, target: event.target.value })} placeholder="https://automation.example.com/itsm/events" /></label>
                <label><span>Описание</span><input value={webhookDraft.description} onChange={(event) => setWebhookDraft({ ...webhookDraft, description: event.target.value })} /></label>
                <label><span>Timeout, сек.</span><input type="number" min="1" max="60" value={webhookDraft.timeout} onChange={(event) => setWebhookDraft({ ...webhookDraft, timeout: event.target.value })} /></label>
                <label><span>Макс. попыток</span><input type="number" min="1" max="20" value={webhookDraft.attempts} onChange={(event) => setWebhookDraft({ ...webhookDraft, attempts: event.target.value })} /></label>
                <label><span>Типы событий</span><textarea value={webhookDraft.events} onChange={(event) => setWebhookDraft({ ...webhookDraft, events: event.target.value })} /></label>
              </div>
              <button
                type="button"
                disabled={Boolean(busy) || !scopedTenant || !webhookDraft.name.trim() || !webhookDraft.target.trim()}
                onClick={() => void runAction(
                  'create-webhook',
                  () => createOutboundWebhookSubscription(token, {
                    tenant_id: isRoot ? scopedTenant : undefined,
                    name: webhookDraft.name,
                    description: webhookDraft.description,
                    target_url: webhookDraft.target,
                    event_types: splitValues(webhookDraft.events, true),
                    timeout_seconds: Number(webhookDraft.timeout),
                    max_attempts: Number(webhookDraft.attempts),
                  }),
                  'Webhook создан в DRAFT. Сохраните signing secret и выполните тест.',
                ).then((created) => {
                  if (!created) return
                  setSelectedWebhookId(created.id)
                  if (created.signing_secret) {
                    setRevealed({ title: `Signing secret «${created.name}»`, value: created.signing_secret })
                  }
                  setWebhookDraft({ name: '', description: '', target: '', events: defaultEvents, timeout: '15', attempts: '6' })
                })}
              >
                Создать webhook
              </button>
            </section>
          ) : null}

          <section className="section-card">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead><tr><th>Подписка</th><th>Статус</th><th>Назначение</th><th>События</th><th>Успех / ошибки / DLQ</th><th>Последний результат</th></tr></thead>
                <tbody>
                  {webhooksQuery.isPending ? <tr><td colSpan={6}><p className="state-panel state-panel-loading">Загрузка webhook-подписок…</p></td></tr> : null}
                  {!webhooksQuery.isPending && !webhooks.length ? <tr><td colSpan={6}><p className="state-panel state-panel-empty">Исходящие webhooks ещё не созданы.</p></td></tr> : null}
                  {webhooks.map((item) => (
                    <tr
                      key={item.id}
                      className={selectedWebhookId === item.id ? 'selected-row' : ''}
                      onClick={() => setSelectedWebhookId(item.id)}
                    >
                      <td><strong>{item.name}</strong><p className="table-subtext">{item.signing_secret_hint ?? 'secret removed'}</p></td>
                      <td><span className={statusClass(item.status)}>{item.status}</span></td>
                      <td>{item.target_hint ?? '—'}</td>
                      <td>{item.event_types.join(', ')}</td>
                      <td>{item.success_count} / {item.failure_count} / {item.dead_letter_count}</td>
                      <td>{formatDateTime(item.last_success_at ?? item.last_failure_at)}<p className="table-subtext">{item.last_error ?? '—'}</p></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          {selectedWebhook ? (
            <section className="section-card">
              <div className="section-header">
                <div>
                  <p className="eyebrow">WEBHOOK POLICY</p>
                  <h2 className="section-title">{selectedWebhook.name}</h2>
                  <p className="section-subtitle">
                    Проверка текущих версий: {testPassed ? 'успешна' : 'не выполнена'}.
                    Новый URL или secret автоматически требует повторного теста.
                  </p>
                </div>
                <span className={statusClass(selectedWebhook.status)}>{selectedWebhook.status}</span>
              </div>
              <div className="form-grid">
                <label><span>Название</span><input value={webhookEdit.name} disabled={!canManageWebhooks || selectedWebhook.status === 'REVOKED'} onChange={(event) => setWebhookEdit({ ...webhookEdit, name: event.target.value })} /></label>
                <label><span>Новый URL (пусто = без изменения)</span><input value={webhookEdit.target} disabled={!canManageWebhooks || selectedWebhook.status === 'REVOKED'} onChange={(event) => setWebhookEdit({ ...webhookEdit, target: event.target.value })} placeholder={selectedWebhook.target_hint ?? ''} /></label>
                <label><span>Описание</span><input value={webhookEdit.description} disabled={!canManageWebhooks || selectedWebhook.status === 'REVOKED'} onChange={(event) => setWebhookEdit({ ...webhookEdit, description: event.target.value })} /></label>
                <label><span>Timeout, сек.</span><input type="number" min="1" max="60" value={webhookEdit.timeout} disabled={!canManageWebhooks || selectedWebhook.status === 'REVOKED'} onChange={(event) => setWebhookEdit({ ...webhookEdit, timeout: event.target.value })} /></label>
                <label><span>Макс. попыток</span><input type="number" min="1" max="20" value={webhookEdit.attempts} disabled={!canManageWebhooks || selectedWebhook.status === 'REVOKED'} onChange={(event) => setWebhookEdit({ ...webhookEdit, attempts: event.target.value })} /></label>
                <label><span>Причина</span><input value={webhookEdit.reason} disabled={!canManageWebhooks || selectedWebhook.status === 'REVOKED'} onChange={(event) => setWebhookEdit({ ...webhookEdit, reason: event.target.value })} /></label>
                <label><span>Типы событий</span><textarea value={webhookEdit.events} disabled={!canManageWebhooks || selectedWebhook.status === 'REVOKED'} onChange={(event) => setWebhookEdit({ ...webhookEdit, events: event.target.value })} /></label>
              </div>
              {canManageWebhooks && selectedWebhook.status !== 'REVOKED' ? (
                <div className="analytics-actions">
                  <button
                    type="button"
                    disabled={Boolean(busy) || webhookEdit.reason.trim().length < 3}
                    onClick={() => void runAction(
                      'save-webhook',
                      () => updateOutboundWebhookSubscription(token, selectedWebhook.id, {
                        expected_version: selectedWebhook.version,
                        name: webhookEdit.name,
                        description: webhookEdit.description,
                        ...(webhookEdit.target.trim() ? { target_url: webhookEdit.target.trim() } : {}),
                        event_types: splitValues(webhookEdit.events, true),
                        timeout_seconds: Number(webhookEdit.timeout),
                        max_attempts: Number(webhookEdit.attempts),
                        reason: webhookEdit.reason,
                      }),
                      'Webhook-конфигурация сохранена.',
                    ).then((updated) => {
                      if (updated) setWebhookEdit((current) => ({ ...current, target: '' }))
                    })}
                  >
                    Сохранить
                  </button>
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={Boolean(busy)}
                    onClick={() => void runAction(
                      'test-webhook',
                      () => testOutboundWebhookSubscription(token, selectedWebhook.id),
                      'Тест поставлен в очередь. После успешной доставки появится разрешение на активацию.',
                    )}
                  >
                    Тестировать
                  </button>
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={Boolean(busy)}
                    onClick={() => void runAction(
                      'rotate-webhook',
                      () => rotateOutboundWebhookSecret(token, selectedWebhook.id, 'Плановая ротация signing secret'),
                      'Signing secret заменён. Сохраните его и повторите тест.',
                    ).then((updated) => {
                      if (updated?.signing_secret) {
                        setRevealed({
                          title: `${translate('Новый signing secret')} «${updated.name}»`,
                          value: updated.signing_secret,
                        })
                      }
                    })}
                  >
                    Ротировать secret
                  </button>
                  {selectedWebhook.status !== 'ACTIVE' ? (
                    <button
                      type="button"
                      disabled={Boolean(busy) || !testPassed}
                      title={testPassed ? '' : 'Сначала дождитесь успешного теста текущего URL и secret'}
                      onClick={() => void runAction(
                        'activate-webhook',
                        () => updateOutboundWebhookSubscription(token, selectedWebhook.id, {
                          expected_version: selectedWebhook.version,
                          status: 'ACTIVE',
                          reason: 'Активация после успешного теста',
                        }),
                        'Webhook активирован.',
                      )}
                    >
                      Активировать
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="ghost-button"
                      disabled={Boolean(busy)}
                      onClick={() => void runAction(
                        'pause-webhook',
                        () => updateOutboundWebhookSubscription(token, selectedWebhook.id, {
                          expected_version: selectedWebhook.version,
                          status: 'PAUSED',
                          reason: 'Ручная приостановка доставки',
                        }),
                        'Webhook приостановлен.',
                      )}
                    >
                      Приостановить
                    </button>
                  )}
                  <button
                    type="button"
                    className="danger-button"
                    disabled={Boolean(busy)}
                    onClick={() => {
                      if (!window.confirm(translate('Безвозвратно отозвать webhook и удалить его секреты?'))) return
                      void runAction(
                        'revoke-webhook',
                        () => updateOutboundWebhookSubscription(token, selectedWebhook.id, {
                          expected_version: selectedWebhook.version,
                          status: 'REVOKED',
                          reason: 'Администратор отозвал webhook',
                        }),
                        'Webhook отозван, ожидающие доставки отменены.',
                      )
                    }}
                  >
                    Отозвать
                  </button>
                </div>
              ) : null}
            </section>
          ) : null}
        </>
      ) : null}

      {view === 'deliveries' ? (
        <section className="section-card">
          <div className="section-header">
            <div>
              <h2 className="section-title">Очередь доставки и dead-letter</h2>
              <p className="section-subtitle">Постоянные ошибки отделены от исчерпанных повторов; replay создаёт новую отслеживаемую доставку.</p>
            </div>
            <div className="tickets-toolbar-group">
              <label className="inline-field"><span>Webhook</span><select value={selectedWebhookId} onChange={(event) => setSelectedWebhookId(event.target.value)}><option value="">Все</option>{webhooks.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
              <label className="inline-field"><span>Статус</span><select value={deliveryStatus} onChange={(event) => setDeliveryStatus(event.target.value)}>{['ALL', 'PENDING', 'PROCESSING', 'RETRY', 'SUCCEEDED', 'FAILED', 'DEAD_LETTER', 'CANCELLED'].map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
            </div>
          </div>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Создано</th><th>Событие</th><th>Статус</th><th>Попытки</th><th>HTTP / latency</th><th>Следующая попытка</th><th>Ошибка</th><th /></tr></thead>
              <tbody>
                {deliveriesQuery.isPending ? <tr><td colSpan={8}><p className="state-panel state-panel-loading">Загрузка доставок…</p></td></tr> : null}
                {!deliveriesQuery.isPending && !(deliveriesQuery.data ?? []).length ? <tr><td colSpan={8}><p className="state-panel state-panel-empty">Доставок по фильтру нет.</p></td></tr> : null}
                {(deliveriesQuery.data ?? []).map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}<p className="table-subtext">{item.id.slice(0, 8)}</p></td>
                    <td>{item.event_type}<p className="table-subtext">{item.entity_type ?? '—'} {item.entity_id ?? ''}</p></td>
                    <td><span className={statusClass(item.status)}>{item.status}</span>{item.is_test ? <p className="table-subtext">TEST</p> : null}</td>
                    <td>{item.attempts} / {item.max_attempts}</td>
                    <td>{item.response_status ?? '—'} / {item.response_time_ms ?? '—'} ms</td>
                    <td>{formatDateTime(item.next_attempt_at)}</td>
                    <td>{item.last_error ?? '—'}</td>
                    <td>
                      {canReplay && ['FAILED', 'DEAD_LETTER', 'CANCELLED'].includes(item.status) ? (
                        <button
                          type="button"
                          className="ghost-button"
                          disabled={Boolean(busy)}
                          onClick={() => void runAction(
                            `replay-${item.id}`,
                            () => replayOutboundWebhookDelivery(token, item.id, 'Ручной replay после анализа ошибки'),
                            'Новая replay-доставка поставлена в очередь.',
                          )}
                        >
                          Replay
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

      {view === 'audit' ? (
        <section className="section-card">
          <div className="section-header">
            <div>
              <h2 className="section-title">Аудит машинного API</h2>
              <p className="section-subtitle">Токены и секреты не журналируются; фиксируются client, scope, IP, outcome и request ID.</p>
            </div>
            <div className="tickets-toolbar-group">
              <label className="inline-field"><span>Аккаунт</span><select value={selectedAccountId} onChange={(event) => setSelectedAccountId(event.target.value)}><option value="">Все</option>{accounts.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}</select></label>
              <label className="inline-field"><span>Результат</span><select value={auditOutcome} onChange={(event) => setAuditOutcome(event.target.value as typeof auditOutcome)}>{['ALL', 'ALLOWED', 'DENIED'].map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
            </div>
          </div>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Дата</th><th>Результат</th><th>Метод / path</th><th>Scope</th><th>IP</th><th>Request ID</th><th>Причина</th></tr></thead>
              <tbody>
                {auditQuery.isPending ? <tr><td colSpan={7}><p className="state-panel state-panel-loading">Загрузка API-аудита…</p></td></tr> : null}
                {!auditQuery.isPending && !(auditQuery.data ?? []).length ? <tr><td colSpan={7}><p className="state-panel state-panel-empty">API-запросов по фильтру пока нет.</p></td></tr> : null}
                {(auditQuery.data ?? []).map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td><span className={statusClass(item.outcome)}>{item.outcome}</span></td>
                    <td>{item.method} {item.path}</td>
                    <td>{item.required_scope ?? 'identity only'}</td>
                    <td>{item.source_ip ?? '—'}</td>
                    <td>{item.request_id}</td>
                    <td>{item.reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {view === 'sdk' ? (
        <section className="section-card dashboard-split">
          <div>
            <p className="eyebrow">CONNECTOR SDK</p>
            <h2>Версия {contractQuery.data?.contract_version ?? '—'}</h2>
            <p className="section-subtitle">{contractQuery.data?.event_format ?? 'CloudEvents 1.0 structured JSON'}</p>
            <pre className="analytics-export-preview">{`curl -X POST "$BASE_URL/api/v1/integration-platform/sdk/v1/events" \\
  -H "Authorization: Bearer $SBS_SERVICE_TOKEN" \\
  -H "Content-Type: application/json" \\
  -d '{
    "event_type": "monitoring.alert",
    "entity_type": "asset",
    "entity_id": "asset-id",
    "idempotency_key": "source-alert-unique-id",
    "data": {"severity": "critical"}
  }'`}</pre>
          </div>
          <div>
            <p className="eyebrow">SIGNATURE VERIFICATION</p>
            <h2>Проверка исходящего webhook</h2>
            <pre className="analytics-export-preview">{`expected = HMAC_SHA256(
  signing_secret,
  X_SBS_TIMESTAMP + "." + raw_request_body
)

constant_time_compare(
  "v1=" + hex(expected),
  X_SBS_SIGNATURE
)`}</pre>
            <div className="activity-list">
              {Object.entries(contractQuery.data?.sdk_endpoints ?? {}).map(([name, path]) => (
                <article className="activity-item" key={name}><header><strong>{name}</strong></header><code>{path}</code></article>
              ))}
            </div>
          </div>
        </section>
      ) : null}
      </div>
    </LocalizedContent>
  )
}
