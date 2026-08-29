import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createAssetDiscoveryConnector,
  createCMDBSource,
  decideAssetDiscoveryStaleCandidate,
  fetchAssetDiscoveryConnectors,
  fetchAssetDiscoveryDashboard,
  fetchAssetDiscoveryRuns,
  fetchAssetDiscoveryStaleCandidates,
  fetchCMDBSources,
  retryAssetDiscoveryRun,
  rotateAssetDiscoveryCredential,
  startAssetDiscoveryRun,
  testAssetDiscoveryConnector,
  updateAssetDiscoveryConnector,
  type AssetDiscoveryConnector,
  type AssetDiscoveryProvider,
  type AssetDiscoveryRun,
  type AssetDiscoveryStaleCandidate,
  type CIClass,
  type Tenant,
} from '../api/client'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import QueryFailureNotice from './QueryFailureNotice'

type Props = {
  accessToken: string
  tenantId: string
  isRoot: boolean
  canManage: boolean
  canRun: boolean
  canReview: boolean
  tenants: Tenant[]
  classes: CIClass[]
  onTenantChange: (tenantId: string) => void
}

type CredentialDraft = {
  directory_tenant_id: string
  client_id: string
  client_secret: string
  username: string
  password: string
  token: string
}

const emptyCredential = (): CredentialDraft => ({
  directory_tenant_id: '',
  client_id: '',
  client_secret: '',
  username: '',
  password: '',
  token: '',
})

const providerLabels: Record<AssetDiscoveryProvider, string> = {
  INTUNE: 'Microsoft Intune',
  AZURE_RESOURCE_GRAPH: 'Azure Resource Graph',
  SCCM_ADMIN_SERVICE: 'Microsoft Configuration Manager',
  LANSWEEPER_DATA_API: 'Lansweeper Data API',
}

const runStatusLabels: Record<AssetDiscoveryRun['status'], string> = {
  QUEUED: 'В очереди',
  RUNNING: 'Выполняется',
  RETRY: 'Повтор',
  COMPLETED: 'Завершён',
  COMPLETED_WITH_ERRORS: 'Требует проверки',
  FAILED: 'Ошибка',
  DEAD_LETTER: 'Dead letter',
  CANCELLED: 'Отменён',
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

function authForProvider(provider: AssetDiscoveryProvider): AssetDiscoveryConnector['auth_type'] {
  if (provider === 'INTUNE' || provider === 'AZURE_RESOURCE_GRAPH') {
    return 'OAUTH_CLIENT_CREDENTIALS'
  }
  if (provider === 'LANSWEEPER_DATA_API') return 'API_TOKEN'
  return 'BEARER'
}

function credentialPayload(
  authType: AssetDiscoveryConnector['auth_type'],
  draft: CredentialDraft,
): Record<string, string> {
  if (authType === 'OAUTH_CLIENT_CREDENTIALS') {
    return {
      directory_tenant_id: draft.directory_tenant_id,
      client_id: draft.client_id,
      client_secret: draft.client_secret,
    }
  }
  if (authType === 'BASIC') {
    return { username: draft.username, password: draft.password }
  }
  return { token: draft.token }
}

function providerConfiguration(
  provider: AssetDiscoveryProvider,
  form: {
    subscription_ids: string
    azure_query: string
    sccm_endpoint_path: string
    lansweeper_site_id: string
    lansweeper_page_size: string
  },
): Record<string, unknown> {
  if (provider === 'AZURE_RESOURCE_GRAPH') {
    return {
      subscription_ids: form.subscription_ids
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean),
      query: form.azure_query,
    }
  }
  if (provider === 'SCCM_ADMIN_SERVICE') {
    return { endpoint_path: form.sccm_endpoint_path }
  }
  if (provider === 'LANSWEEPER_DATA_API') {
    return {
      site_id: form.lansweeper_site_id,
      page_size: Number(form.lansweeper_page_size),
    }
  }
  return {}
}

function makeSourceCode(provider: AssetDiscoveryProvider) {
  return `DISC_${provider}_${Date.now().toString().slice(-6)}`.slice(0, 64)
}

export default function AssetDiscoveryPanel({
  accessToken,
  tenantId,
  isRoot,
  canManage,
  canRun,
  canReview,
  tenants,
  classes,
  onTenantChange,
}: Props) {
  const { translate, formatDateTime } = useTenantExperience()
  const queryClient = useQueryClient()
  const scopeReady = !isRoot || Boolean(tenantId)
  const publishedClasses = classes.filter((item) => item.published_version)
  const [selectedConnectorId, setSelectedConnectorId] = useState('')
  const [notice, setNotice] = useState('')
  const [staleReasons, setStaleReasons] = useState<Record<string, string>>({})
  const [rotationDrafts, setRotationDrafts] = useState<Record<string, CredentialDraft>>({})
  const [policyDrafts, setPolicyDrafts] = useState<Record<string, {
    schedule_minutes: string
    max_records: string
    missing_threshold_runs: string
    auto_apply: boolean
  }>>({})
  const [form, setForm] = useState({
    source_id: 'NEW',
    source_name: '',
    default_class_id: '',
    name: '',
    provider: 'INTUNE' as AssetDiscoveryProvider,
    auth_type: 'OAUTH_CLIENT_CREDENTIALS' as AssetDiscoveryConnector['auth_type'],
    base_url: '',
    schedule_minutes: '60',
    max_records: '5000',
    missing_threshold_runs: '3',
    auto_apply: false,
    subscription_ids: '',
    azure_query: 'Resources | project id, name, type, location, tags, resourceGroup, subscriptionId',
    sccm_endpoint_path: '/AdminService/v1.0/Device',
    lansweeper_site_id: '',
    lansweeper_page_size: '100',
    credential: emptyCredential(),
  })

  const sourcesQuery = useQuery({
    queryKey: ['cmdb-sources', accessToken, tenantId],
    queryFn: () => fetchCMDBSources(accessToken, tenantId || undefined),
    enabled: Boolean(accessToken && scopeReady),
  })
  const connectorsQuery = useQuery({
    queryKey: ['asset-discovery-connectors', accessToken, tenantId],
    queryFn: () => fetchAssetDiscoveryConnectors(accessToken, tenantId || undefined),
    enabled: Boolean(accessToken && scopeReady),
    refetchInterval: 5000,
  })
  const runsQuery = useQuery({
    queryKey: ['asset-discovery-runs', accessToken, tenantId, selectedConnectorId],
    queryFn: () => fetchAssetDiscoveryRuns(
      accessToken,
      tenantId || undefined,
      selectedConnectorId || undefined,
    ),
    enabled: Boolean(accessToken && scopeReady),
    refetchInterval: 5000,
  })
  const staleQuery = useQuery({
    queryKey: ['asset-discovery-stale', accessToken, tenantId, selectedConnectorId],
    queryFn: () => fetchAssetDiscoveryStaleCandidates(
      accessToken,
      tenantId || undefined,
      selectedConnectorId || undefined,
    ),
    enabled: Boolean(accessToken && scopeReady),
    refetchInterval: 5000,
  })
  const dashboardQuery = useQuery({
    queryKey: ['asset-discovery-dashboard', accessToken, tenantId],
    queryFn: () => fetchAssetDiscoveryDashboard(accessToken, tenantId || undefined),
    enabled: Boolean(accessToken && scopeReady),
    refetchInterval: 5000,
  })

  const discoverySources = (sourcesQuery.data ?? []).filter(
    (item) => item.source_type === 'DISCOVERY' && item.status === 'ACTIVE',
  )
  const boundSourceIds = useMemo(
    () => new Set((connectorsQuery.data ?? []).map((item) => item.cmdb_source_id)),
    [connectorsQuery.data],
  )
  const availableSources = discoverySources.filter((item) => !boundSourceIds.has(item.id))
  const connectors = connectorsQuery.data ?? []
  const runs = runsQuery.data ?? []
  const staleCandidates = staleQuery.data ?? []
  const dashboard = dashboardQuery.data

  useEffect(() => {
    if (!form.default_class_id && publishedClasses.length) {
      setForm((current) => ({
        ...current,
        default_class_id: publishedClasses[0].id,
      }))
    }
  }, [form.default_class_id, publishedClasses])

  useEffect(() => {
    setPolicyDrafts((current) => {
      const next = { ...current }
      for (const item of connectors) {
        next[item.id] ??= {
          schedule_minutes: String(item.schedule_minutes),
          max_records: String(item.max_records),
          missing_threshold_runs: String(item.missing_threshold_runs),
          auto_apply: item.auto_apply,
        }
      }
      return next
    })
    setRotationDrafts((current) => {
      const next = { ...current }
      for (const item of connectors) next[item.id] ??= emptyCredential()
      return next
    })
  }, [connectors])

  useEffect(() => setSelectedConnectorId(''), [tenantId])

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['asset-discovery-connectors'] }),
      queryClient.invalidateQueries({ queryKey: ['asset-discovery-runs'] }),
      queryClient.invalidateQueries({ queryKey: ['asset-discovery-stale'] }),
      queryClient.invalidateQueries({ queryKey: ['asset-discovery-dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['cmdb-sources'] }),
      queryClient.invalidateQueries({ queryKey: ['cmdb-reconciliation-runs'] }),
      queryClient.invalidateQueries({ queryKey: ['assets'] }),
    ])
  }

  const createMutation = useMutation({
    mutationFn: async () => {
      let sourceId = form.source_id
      if (sourceId === 'NEW') {
        const source = await createCMDBSource(accessToken, {
          tenant_id: isRoot ? tenantId : undefined,
          default_class_id: form.default_class_id,
          code: makeSourceCode(form.provider),
          name: form.source_name || `${providerLabels[form.provider]} discovery`,
          description: `Governed ${providerLabels[form.provider]} asset discovery source`,
          source_type: 'DISCOVERY',
          priority: 100,
          identification_rules: ['serial_number', 'asset_tag', 'name'],
          authoritative_fields: [
            'name',
            'serial_number',
            'manufacturer',
            'model',
            'original_type',
            'lifecycle_status',
            'condition',
            'assigned_to_name',
            'verification_status',
            'environment',
            'location',
            'attributes.*',
          ],
          claim_unowned_fields: true,
          stale_after_hours: Math.max(
            24,
            Math.ceil(Number(form.schedule_minutes) * 3 / 60),
          ),
        })
        sourceId = source.id
      }
      return createAssetDiscoveryConnector(accessToken, {
        tenant_id: isRoot ? tenantId : undefined,
        cmdb_source_id: sourceId,
        name: form.name || `${providerLabels[form.provider]} connector`,
        provider: form.provider,
        auth_type: form.auth_type,
        base_url: form.base_url || null,
        credential: credentialPayload(form.auth_type, form.credential),
        configuration: providerConfiguration(form.provider, form),
        schedule_minutes: Number(form.schedule_minutes),
        auto_apply: form.auto_apply,
        missing_threshold_runs: Number(form.missing_threshold_runs),
        max_records: Number(form.max_records),
      })
    },
    onSuccess: async (item) => {
      setSelectedConnectorId(item.id)
      setNotice('Коннектор создан в статусе DRAFT. Проверьте соединение и активируйте его.')
      setForm((current) => ({
        ...current,
        source_name: '',
        name: '',
        credential: emptyCredential(),
      }))
      await invalidate()
    },
  })

  const statusMutation = useMutation({
    mutationFn: ({
      connector,
      nextStatus,
    }: {
      connector: AssetDiscoveryConnector
      nextStatus: AssetDiscoveryConnector['status']
    }) => updateAssetDiscoveryConnector(accessToken, connector, {
      status: nextStatus,
      reason: `Статус изменён администратором на ${nextStatus}`,
    }),
    onSuccess: async (item) => {
      setNotice(`${translate('Статус')} ${item.name}: ${item.status}`)
      await invalidate()
    },
  })

  const policyMutation = useMutation({
    mutationFn: (connector: AssetDiscoveryConnector) => {
      const draft = policyDrafts[connector.id] ?? {
        schedule_minutes: String(connector.schedule_minutes),
        max_records: String(connector.max_records),
        missing_threshold_runs: String(connector.missing_threshold_runs),
        auto_apply: connector.auto_apply,
      }
      return updateAssetDiscoveryConnector(accessToken, connector, {
        schedule_minutes: Number(draft.schedule_minutes),
        max_records: Number(draft.max_records),
        missing_threshold_runs: Number(draft.missing_threshold_runs),
        auto_apply: draft.auto_apply,
        reason: 'Политика discovery обновлена администратором',
      })
    },
    onSuccess: invalidate,
  })

  const testMutation = useMutation({
    mutationFn: (connector: AssetDiscoveryConnector) => (
      testAssetDiscoveryConnector(accessToken, connector.id)
    ),
    onSuccess: async (result) => {
      setNotice(
        result.sample
          ? `${translate('Соединение работает. Пример:')} ${result.sample.name} (${result.sample.external_id}).`
          : 'Соединение работает, но источник вернул пустой набор.',
      )
      await invalidate()
    },
  })

  const runMutation = useMutation({
    mutationFn: (connector: AssetDiscoveryConnector) => (
      startAssetDiscoveryRun(accessToken, connector.id)
    ),
    onSuccess: async (run) => {
      setSelectedConnectorId(run.connector_id)
      setNotice('Discovery-запуск поставлен в очередь worker.')
      await invalidate()
    },
  })

  const retryMutation = useMutation({
    mutationFn: (run: AssetDiscoveryRun) => retryAssetDiscoveryRun(
      accessToken,
      run.id,
      'Повтор после исправления конфигурации коннектора',
    ),
    onSuccess: invalidate,
  })

  const rotateMutation = useMutation({
    mutationFn: (connector: AssetDiscoveryConnector) => (
      rotateAssetDiscoveryCredential(
        accessToken,
        connector.id,
        credentialPayload(connector.auth_type, rotationDrafts[connector.id] ?? emptyCredential()),
        'Плановая ротация credential через Asset Discovery',
      )
    ),
    onSuccess: async (item) => {
      setRotationDrafts((current) => ({
        ...current,
        [item.id]: emptyCredential(),
      }))
      setNotice(
        `Credential ${item.name} ${translate('обновлён и коннектор поставлен на паузу.')} `
        + translate('Проверьте новое подключение и снова активируйте коннектор.'),
      )
      await invalidate()
    },
  })

  const staleMutation = useMutation({
    mutationFn: ({
      candidate,
      decision,
    }: {
      candidate: AssetDiscoveryStaleCandidate
      decision: 'RETIRE' | 'DISMISS'
    }) => decideAssetDiscoveryStaleCandidate(
      accessToken,
      candidate,
      decision,
      staleReasons[candidate.id]
        || (decision === 'RETIRE'
          ? 'Актив подтверждён как отсутствующий и выведен из эксплуатации'
          : 'Отсутствие проверено и не требует вывода из эксплуатации'),
    ),
    onSuccess: invalidate,
  })

  const setProvider = (provider: AssetDiscoveryProvider) => {
    setForm((current) => ({
      ...current,
      provider,
      auth_type: authForProvider(provider),
      credential: emptyCredential(),
    }))
  }

  const credentialFields = (
    authType: AssetDiscoveryConnector['auth_type'],
    credential: CredentialDraft,
    onChange: (credential: CredentialDraft) => void,
  ) => {
    if (authType === 'OAUTH_CLIENT_CREDENTIALS') {
      return (
        <>
          <label>Entra tenant ID<input value={credential.directory_tenant_id} onChange={(event) => onChange({ ...credential, directory_tenant_id: event.target.value })} required /></label>
          <label>Application client ID<input value={credential.client_id} onChange={(event) => onChange({ ...credential, client_id: event.target.value })} required /></label>
          <label>Client secret<input type="password" autoComplete="new-password" value={credential.client_secret} onChange={(event) => onChange({ ...credential, client_secret: event.target.value })} required /></label>
        </>
      )
    }
    if (authType === 'BASIC') {
      return (
        <>
          <label>Username<input value={credential.username} onChange={(event) => onChange({ ...credential, username: event.target.value })} required /></label>
          <label>Password<input type="password" autoComplete="new-password" value={credential.password} onChange={(event) => onChange({ ...credential, password: event.target.value })} required /></label>
        </>
      )
    }
    return (
      <label>{authType === 'API_TOKEN' ? 'Personal access token' : 'Bearer token'}<input type="password" autoComplete="new-password" value={credential.token} onChange={(event) => onChange({ ...credential, token: event.target.value })} required /></label>
    )
  }

  if (!scopeReady) {
    return (
      <LocalizedContent>
        <section className="section-card">
          <h2>Asset Discovery</h2>
          <p className="empty-state">Выберите организацию, чтобы управлять discovery-коннекторами.</p>
        </section>
      </LocalizedContent>
    )
  }

  const mutationError = createMutation.error
    || statusMutation.error
    || policyMutation.error
    || testMutation.error
    || runMutation.error
    || retryMutation.error
    || rotateMutation.error
    || staleMutation.error

  return (
    <LocalizedContent>
      <>
      {isRoot ? (
        <section className="section-card cmdb-tenant-selector">
          <label>
            Организация
            <select value={tenantId} onChange={(event) => onTenantChange(event.target.value)}>
              <option value="">Выберите организацию</option>
              {tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
            </select>
          </label>
        </section>
      ) : null}

      <section className="module-overview-grid">
        <article className="metric-card"><span>Активные коннекторы</span><strong>{dashboard?.connectors.ACTIVE ?? 0}</strong></article>
        <article className="metric-card"><span>В очереди / retry</span><strong>{(dashboard?.runs.QUEUED ?? 0) + (dashboard?.runs.RETRY ?? 0)}</strong></article>
        <article className="metric-card"><span>Нездоровые</span><strong>{dashboard?.unhealthy_connectors ?? 0}</strong></article>
        <article className="metric-card"><span>Stale на проверке</span><strong>{dashboard?.open_stale_candidates ?? 0}</strong></article>
      </section>

      {notice ? <p className="success-banner">{notice}</p> : null}
      <QueryFailureNotice
        title="Часть данных Asset Discovery недоступна."
        sources={[
          { label: 'источники', query: sourcesQuery },
          { label: 'коннекторы', query: connectorsQuery },
          { label: 'запуски', query: runsQuery },
          { label: 'stale candidates', query: staleQuery },
          { label: 'оперативная сводка', query: dashboardQuery },
        ]}
      />
      {mutationError ? <p className="error-banner" role="alert">{errorText(mutationError)}</p> : null}

      {canManage ? (
        <section className="section-card">
          <div className="section-heading">
            <div>
              <p className="eyebrow">DISCOVERY SETUP</p>
              <h2>Подключить источник активов</h2>
              <p>Credential шифруется и никогда не возвращается API. Новый CMDB-источник можно создать вместе с коннектором.</p>
            </div>
          </div>
          <form className="settings-grid" onSubmit={(event) => { event.preventDefault(); createMutation.mutate() }}>
            <label>Провайдер<select value={form.provider} onChange={(event) => setProvider(event.target.value as AssetDiscoveryProvider)}><option value="INTUNE">Microsoft Intune</option><option value="AZURE_RESOURCE_GRAPH">Azure Resource Graph</option><option value="SCCM_ADMIN_SERVICE">Microsoft Configuration Manager</option><option value="LANSWEEPER_DATA_API">Lansweeper Data API</option></select></label>
            <label>CMDB-источник<select value={form.source_id} onChange={(event) => setForm({ ...form, source_id: event.target.value })}><option value="NEW">Создать новый governed source</option>{availableSources.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.code}</option>)}</select></label>
            {form.source_id === 'NEW' ? (
              <>
                <label>Название CMDB-источника<input value={form.source_name} onChange={(event) => setForm({ ...form, source_name: event.target.value })} placeholder={`${providerLabels[form.provider]} discovery`} /></label>
                <label>Класс CI<select value={form.default_class_id} onChange={(event) => setForm({ ...form, default_class_id: event.target.value })} required><option value="">Выберите опубликованный класс</option>{publishedClasses.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.code}</option>)}</select></label>
              </>
            ) : null}
            <label>Название коннектора<input value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder={`${providerLabels[form.provider]} connector`} /></label>
            {form.provider === 'SCCM_ADMIN_SERVICE' ? (
              <>
                <label>AdminService HTTPS URL<input value={form.base_url} onChange={(event) => setForm({ ...form, base_url: event.target.value })} placeholder="https://sccm-admin.example.internal" required /></label>
                <label>Авторизация<select value={form.auth_type} onChange={(event) => setForm({ ...form, auth_type: event.target.value as AssetDiscoveryConnector['auth_type'], credential: emptyCredential() })}><option value="BEARER">Bearer через trusted gateway</option><option value="BASIC">Basic</option></select></label>
                <label>Endpoint path<input value={form.sccm_endpoint_path} onChange={(event) => setForm({ ...form, sccm_endpoint_path: event.target.value })} /></label>
              </>
            ) : null}
            {form.provider === 'LANSWEEPER_DATA_API' ? (
              <>
                <label>Авторизация<select value={form.auth_type} onChange={(event) => setForm({ ...form, auth_type: event.target.value as AssetDiscoveryConnector['auth_type'], credential: emptyCredential() })}><option value="API_TOKEN">PAT · Authorization Token</option><option value="BEARER">OAuth access token</option></select></label>
                <label>Site ID<input value={form.lansweeper_site_id} onChange={(event) => setForm({ ...form, lansweeper_site_id: event.target.value })} required /></label>
                <label>Page size<input type="number" min={1} max={500} value={form.lansweeper_page_size} onChange={(event) => setForm({ ...form, lansweeper_page_size: event.target.value })} /></label>
              </>
            ) : null}
            {form.provider === 'AZURE_RESOURCE_GRAPH' ? (
              <>
                <label>Subscription IDs<input value={form.subscription_ids} onChange={(event) => setForm({ ...form, subscription_ids: event.target.value })} placeholder="UUID, UUID; пусто = tenant scope" /></label>
                <label className="span-2">Resource Graph KQL<textarea rows={3} value={form.azure_query} onChange={(event) => setForm({ ...form, azure_query: event.target.value })} /></label>
              </>
            ) : null}
            {credentialFields(form.auth_type, form.credential, (credential) => setForm({ ...form, credential }))}
            <label>Расписание, минут<input type="number" min={5} max={43200} value={form.schedule_minutes} onChange={(event) => setForm({ ...form, schedule_minutes: event.target.value })} /></label>
            <label>Максимум CI за запуск<input type="number" min={1} max={50000} value={form.max_records} onChange={(event) => setForm({ ...form, max_records: event.target.value })} /></label>
            <label>Missing scans до stale<input type="number" min={1} max={100} value={form.missing_threshold_runs} onChange={(event) => setForm({ ...form, missing_threshold_runs: event.target.value })} /></label>
            <label className="checkbox-field"><input type="checkbox" checked={form.auto_apply} onChange={(event) => setForm({ ...form, auto_apply: event.target.checked })} /><span>Автоматически применять однозначные валидные пакеты</span></label>
            <div className="analytics-actions"><button type="submit" disabled={createMutation.isPending || (form.source_id === 'NEW' && !form.default_class_id)}>{createMutation.isPending ? 'Создание…' : 'Создать DRAFT-коннектор'}</button></div>
          </form>
        </section>
      ) : null}

      <section className="section-card">
        <div className="section-heading">
          <div><p className="eyebrow">CONNECTOR HEALTH</p><h2>Коннекторы</h2></div>
          <label className="inline-field"><span>История</span><select value={selectedConnectorId} onChange={(event) => setSelectedConnectorId(event.target.value)}><option value="">Все коннекторы</option>{connectors.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
        </div>
        <div className="admin-card-grid">
          {connectors.map((item) => {
            const policy = policyDrafts[item.id]
            const rotation = rotationDrafts[item.id] ?? emptyCredential()
            return (
              <article className="foundation-card" key={item.id}>
                <div className="section-heading">
                  <div><span className={`status-pill status-${item.status.toLowerCase()}`}>{item.status}</span><h3>{item.name}</h3><p>{providerLabels[item.provider]} · {item.cmdb_source_name}</p></div>
                  <strong>{item.credential_hint ?? 'credential отсутствует'}</strong>
                </div>
                <dl className="detail-grid">
                  <div><dt>Последний успех</dt><dd>{formatDateTime(item.last_success_at)}</dd></div>
                  <div><dt>Следующий запуск</dt><dd>{formatDateTime(item.next_run_at)}</dd></div>
                  <div><dt>Успех / ошибки</dt><dd>{item.successful_runs} / {item.failed_runs}</dd></div>
                  <div><dt>Обнаружено</dt><dd>{item.discovered_records}</dd></div>
                  <div>
                    <dt>Credential version</dt>
                    <dd>
                      {item.credential_version}
                      <small>
                        {item.last_tested_credential_version === item.credential_version
                          ? 'проверен'
                          : 'нужна проверка'}
                      </small>
                    </dd>
                  </div>
                  <div><dt>Режим</dt><dd>{item.auto_apply ? 'AUTO APPLY' : 'PREVIEW'}</dd></div>
                </dl>
                {item.last_error ? <p className="error-banner">{item.last_error}</p> : null}
                <div className="analytics-actions">
                  {canManage && item.status !== 'REVOKED' ? <button type="button" className="ghost-button" onClick={() => testMutation.mutate(item)} disabled={testMutation.isPending}>Проверить</button> : null}
                  {canManage && item.status !== 'ACTIVE' && item.status !== 'REVOKED' ? <button type="button" onClick={() => statusMutation.mutate({ connector: item, nextStatus: 'ACTIVE' })} disabled={item.last_tested_credential_version !== item.credential_version}>Активировать</button> : null}
                  {canManage && item.status === 'ACTIVE' ? <button type="button" className="ghost-button" onClick={() => statusMutation.mutate({ connector: item, nextStatus: 'PAUSED' })}>Пауза</button> : null}
                  {canRun && item.status === 'ACTIVE' ? <button type="button" onClick={() => runMutation.mutate(item)} disabled={runMutation.isPending}>Запустить сейчас</button> : null}
                </div>
                {canManage && item.status !== 'REVOKED' && policy ? (
                  <details>
                    <summary>Политика, credential и отзыв</summary>
                    <div className="settings-grid">
                      <label>Расписание, минут<input type="number" min={5} value={policy.schedule_minutes} onChange={(event) => setPolicyDrafts({ ...policyDrafts, [item.id]: { ...policy, schedule_minutes: event.target.value } })} /></label>
                      <label>Максимум CI<input type="number" min={1} max={50000} value={policy.max_records} onChange={(event) => setPolicyDrafts({ ...policyDrafts, [item.id]: { ...policy, max_records: event.target.value } })} /></label>
                      <label>Missing scans<input type="number" min={1} max={100} value={policy.missing_threshold_runs} onChange={(event) => setPolicyDrafts({ ...policyDrafts, [item.id]: { ...policy, missing_threshold_runs: event.target.value } })} /></label>
                      <label className="checkbox-field"><input type="checkbox" checked={policy.auto_apply} onChange={(event) => setPolicyDrafts({ ...policyDrafts, [item.id]: { ...policy, auto_apply: event.target.checked } })} /><span>Auto apply</span></label>
                      <button type="button" onClick={() => policyMutation.mutate(item)}>Сохранить политику</button>
                      {credentialFields(item.auth_type, rotation, (credential) => setRotationDrafts({ ...rotationDrafts, [item.id]: credential }))}
                      <button type="button" onClick={() => rotateMutation.mutate(item)}>Rotate credential</button>
                      <button type="button" className="danger-button" onClick={() => statusMutation.mutate({ connector: item, nextStatus: 'REVOKED' })}>Отозвать навсегда</button>
                    </div>
                  </details>
                ) : null}
              </article>
            )
          })}
          {!connectorsQuery.isPending && connectors.length === 0 ? <p className="empty-state">Discovery-коннекторы ещё не созданы.</p> : null}
        </div>
      </section>

      <section className="section-card">
        <div className="section-heading"><div><p className="eyebrow">EXECUTION HISTORY</p><h2>Запуски и reconciliation</h2></div></div>
        <div className="ticket-table-wrap">
          <table className="ticket-table">
            <thead><tr><th>Создан</th><th>Коннектор</th><th>Статус</th><th>Записей</th><th>Создать / обновить / без изменений</th><th>Ошибки</th><th>Missing / stale</th><th>Снимок</th><th>Действие</th></tr></thead>
            <tbody>
              {runs.map((item) => (
                <tr key={item.id}>
                  <td>{formatDateTime(item.created_at)}</td>
                  <td>{item.connector_name}<small>{item.provider}</small></td>
                  <td>{translate(runStatusLabels[item.status])}<small>attempt {item.attempts}/{item.max_attempts}</small></td>
                  <td>{item.records_fetched}<small>{item.pages_fetched} pages</small></td>
                  <td>{item.created_count} / {item.updated_count} / {item.unchanged_count}</td>
                  <td>{item.invalid_count + item.ambiguous_count}{item.last_error ? <small>{item.last_error}</small> : null}</td>
                  <td>{item.missing_count} / {item.stale_count}</td>
                  <td>{item.complete_snapshot ? 'полный' : 'ограничен лимитом'}</td>
                  <td>{canRun && ['FAILED', 'DEAD_LETTER', 'CANCELLED'].includes(item.status) ? <button type="button" className="ghost-button" onClick={() => retryMutation.mutate(item)}>Повторить</button> : '—'}</td>
                </tr>
              ))}
              {!runsQuery.isPending && runs.length === 0 ? <tr><td colSpan={9}><p className="empty-state">Запусков пока нет.</p></td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>

      <section className="section-card">
        <div className="section-heading"><div><p className="eyebrow">STALE REVIEW</p><h2>Активы, исчезнувшие из полного снимка</h2><p>Система никогда не удаляет CI автоматически. Вывод из эксплуатации требует явного решения и попадает в аудит.</p></div></div>
        <div className="ticket-table-wrap">
          <table className="ticket-table">
            <thead><tr><th>Актив</th><th>Коннектор</th><th>External ID</th><th>Пропущено запусков</th><th>Впервые / последний раз</th><th>Обоснование</th><th>Решение</th></tr></thead>
            <tbody>
              {staleCandidates.map((item) => (
                <tr key={item.id}>
                  <td><strong>{item.asset_tag}</strong><small>{item.asset_name}</small></td>
                  <td>{item.connector_name}</td>
                  <td>{item.external_id}</td>
                  <td>{item.missing_run_count}</td>
                  <td>{formatDateTime(item.first_missing_at)}<small>{formatDateTime(item.last_missing_at)}</small></td>
                  <td><input value={staleReasons[item.id] ?? ''} onChange={(event) => setStaleReasons({ ...staleReasons, [item.id]: event.target.value })} placeholder="Результат проверки" /></td>
                  <td>{canReview ? <div className="analytics-actions"><button type="button" className="ghost-button" onClick={() => staleMutation.mutate({ candidate: item, decision: 'DISMISS' })}>Оставить</button><button type="button" className="danger-button" onClick={() => staleMutation.mutate({ candidate: item, decision: 'RETIRE' })}>Retire CI</button></div> : 'Только просмотр'}</td>
                </tr>
              ))}
              {!staleQuery.isPending && staleCandidates.length === 0 ? <tr><td colSpan={7}><p className="empty-state">Открытых stale-кандидатов нет.</p></td></tr> : null}
            </tbody>
          </table>
        </div>
      </section>
      </>
    </LocalizedContent>
  )
}
