import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  applyCMDBReconciliation,
  createCMDBSource,
  dismissCIDuplicateCandidate,
  fetchCIDuplicateCandidates,
  fetchCMDBReconciliationRun,
  fetchCMDBReconciliationRuns,
  fetchCMDBSourceHealth,
  fetchCMDBSources,
  mergeCIDuplicateCandidate,
  previewCMDBReconciliation,
  updateCMDBSource,
  type CIClass,
  type CIDuplicateCandidate,
  type CMDBInputRecord,
  type CMDBSource,
  type Tenant,
} from '../api/client'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'


type Props = {
  accessToken: string
  tenantId: string
  isRoot: boolean
  canManage: boolean
  tenants: Tenant[]
  classes: CIClass[]
  onTenantChange: (tenantId: string) => void
}

const defaultBatch = JSON.stringify([
  {
    external_id: 'discovery-node-001',
    asset_tag: 'CI-DISC-001',
    serial_number: 'SERIAL-001',
    name: 'app-node-001',
    lifecycle_status: 'ACTIVE',
    criticality: 'HIGH',
    environment: 'PRODUCTION',
    support_group: 'Platform Operations',
    location: 'DC-1',
    attributes: {},
  },
], null, 2)

function nextIdempotencyKey() {
  return globalThis.crypto?.randomUUID?.()
    ?? `cmdb-ui-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

function splitFields(value: string) {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

export default function CMDBReconciliationPanel({
  accessToken,
  tenantId,
  isRoot,
  canManage,
  tenants,
  classes,
  onTenantChange,
}: Props) {
  const { formatDateTime } = useTenantExperience()
  const queryClient = useQueryClient()
  const [selectedSourceId, setSelectedSourceId] = useState('')
  const [selectedRunId, setSelectedRunId] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState<string>(
    nextIdempotencyKey,
  )
  const [batchText, setBatchText] = useState(defaultBatch)
  const [batchParseError, setBatchParseError] = useState('')
  const [candidateReasons, setCandidateReasons] = useState<Record<string, string>>({})
  const [sourceDrafts, setSourceDrafts] = useState<Record<string, {
    priority: string
    stale_after_hours: string
    claim_unowned_fields: boolean
  }>>({})
  const [sourceForm, setSourceForm] = useState({
    code: '',
    name: '',
    description: '',
    source_type: 'API' as CMDBSource['source_type'],
    default_class_id: '',
    priority: '100',
    identification_rules: 'serial_number, inventory_number, asset_tag',
    authoritative_fields: 'name, lifecycle_status, location, criticality, environment, support_group, attributes.*',
    claim_unowned_fields: false,
    stale_after_hours: '24',
  })

  const scopeReady = !isRoot || Boolean(tenantId)
  const sourcesQuery = useQuery({
    queryKey: ['cmdb-sources', accessToken, tenantId],
    queryFn: () => fetchCMDBSources(accessToken, tenantId || undefined),
    enabled: Boolean(accessToken && scopeReady),
  })
  const runsQuery = useQuery({
    queryKey: ['cmdb-reconciliation-runs', accessToken, tenantId, selectedSourceId],
    queryFn: () => fetchCMDBReconciliationRuns(
      accessToken,
      tenantId || undefined,
      selectedSourceId || undefined,
    ),
    enabled: Boolean(accessToken && scopeReady),
  })
  const selectedRunQuery = useQuery({
    queryKey: ['cmdb-reconciliation-run', accessToken, selectedRunId],
    queryFn: () => fetchCMDBReconciliationRun(accessToken, selectedRunId),
    enabled: Boolean(accessToken && selectedRunId),
  })
  const candidatesQuery = useQuery({
    queryKey: ['cmdb-duplicate-candidates', accessToken, tenantId],
    queryFn: () => fetchCIDuplicateCandidates(
      accessToken,
      tenantId || undefined,
    ),
    enabled: Boolean(accessToken && scopeReady),
  })
  const healthQuery = useQuery({
    queryKey: ['cmdb-source-health', accessToken, tenantId],
    queryFn: () => fetchCMDBSourceHealth(accessToken, tenantId || undefined),
    enabled: Boolean(accessToken && scopeReady),
  })

  const sources = sourcesQuery.data ?? []
  const runs = runsQuery.data ?? []
  const selectedRun = selectedRunQuery.data
  const candidates = candidatesQuery.data ?? []
  const publishedClasses = classes.filter((item) => item.published_version)

  useEffect(() => {
    if (!selectedSourceId && sources.length) {
      setSelectedSourceId(sources[0].id)
    }
    setSourceDrafts((current) => {
      const next = { ...current }
      for (const source of sources) {
        next[source.id] ??= {
          priority: String(source.priority),
          stale_after_hours: String(source.stale_after_hours),
          claim_unowned_fields: source.claim_unowned_fields,
        }
      }
      return next
    })
  }, [selectedSourceId, sources])

  useEffect(() => {
    if (!sourceForm.default_class_id && publishedClasses.length) {
      setSourceForm((current) => ({
        ...current,
        default_class_id: publishedClasses[0].id,
      }))
    }
  }, [publishedClasses, sourceForm.default_class_id])

  useEffect(() => {
    if (!selectedRunId && runs.length) {
      setSelectedRunId(runs[0].id)
    }
  }, [runs, selectedRunId])

  useEffect(() => {
    setSelectedSourceId('')
    setSelectedRunId('')
  }, [tenantId])

  const invalidateGovernance = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['cmdb-sources'] }),
      queryClient.invalidateQueries({ queryKey: ['cmdb-source-health'] }),
      queryClient.invalidateQueries({ queryKey: ['cmdb-reconciliation-runs'] }),
      queryClient.invalidateQueries({ queryKey: ['cmdb-duplicate-candidates'] }),
      queryClient.invalidateQueries({ queryKey: ['cmdb-items'] }),
      queryClient.invalidateQueries({ queryKey: ['assets'] }),
    ])
  }

  const createSourceMutation = useMutation({
    mutationFn: () => createCMDBSource(accessToken, {
      tenant_id: isRoot ? tenantId : undefined,
      default_class_id: sourceForm.default_class_id || null,
      code: sourceForm.code,
      name: sourceForm.name,
      description: sourceForm.description || null,
      source_type: sourceForm.source_type,
      priority: Number(sourceForm.priority),
      identification_rules: splitFields(sourceForm.identification_rules),
      authoritative_fields: splitFields(sourceForm.authoritative_fields),
      claim_unowned_fields: sourceForm.claim_unowned_fields,
      stale_after_hours: Number(sourceForm.stale_after_hours),
    }),
    onSuccess: async (source) => {
      setSelectedSourceId(source.id)
      setSourceForm((current) => ({
        ...current,
        code: '',
        name: '',
        description: '',
      }))
      await invalidateGovernance()
    },
  })

  const updateSourceMutation = useMutation({
    mutationFn: ({
      source,
      status,
    }: {
      source: CMDBSource
      status?: CMDBSource['status']
    }) => {
      const draft = sourceDrafts[source.id]
      return updateCMDBSource(accessToken, source.id, {
        expected_version: source.version,
        status,
        priority: Number(draft?.priority ?? source.priority),
        stale_after_hours: Number(
          draft?.stale_after_hours ?? source.stale_after_hours,
        ),
        claim_unowned_fields: (
          draft?.claim_unowned_fields ?? source.claim_unowned_fields
        ),
        reason: status
          ? `Источник ${status === 'ACTIVE' ? 'активирован' : 'приостановлен'} владельцем CMDB`
          : 'Политика источника обновлена владельцем CMDB',
      })
    },
    onSuccess: invalidateGovernance,
  })

  const previewMutation = useMutation({
    mutationFn: () => {
      setBatchParseError('')
      let parsed: unknown
      try {
        parsed = JSON.parse(batchText)
      } catch {
        setBatchParseError('JSON не разобран. Проверьте кавычки и запятые.')
        throw new Error('Пакет содержит некорректный JSON')
      }
      if (!Array.isArray(parsed) || parsed.length === 0) {
        setBatchParseError('Нужен непустой JSON-массив записей.')
        throw new Error('Пакет должен быть непустым массивом')
      }
      return previewCMDBReconciliation(
        accessToken,
        selectedSourceId,
        idempotencyKey,
        parsed as CMDBInputRecord[],
      )
    },
    onSuccess: async (run) => {
      setSelectedRunId(run.id)
      setIdempotencyKey(nextIdempotencyKey())
      await invalidateGovernance()
      await queryClient.invalidateQueries({
        queryKey: ['cmdb-reconciliation-run', accessToken, run.id],
      })
    },
  })

  const applyMutation = useMutation({
    mutationFn: (runId: string) => applyCMDBReconciliation(accessToken, runId),
    onSuccess: async (run) => {
      setSelectedRunId(run.id)
      await invalidateGovernance()
      await queryClient.invalidateQueries({
        queryKey: ['cmdb-reconciliation-run', accessToken, run.id],
      })
    },
  })

  const dismissMutation = useMutation({
    mutationFn: (candidate: CIDuplicateCandidate) => (
      dismissCIDuplicateCandidate(
        accessToken,
        candidate.id,
        candidate.version,
        candidateReasons[candidate.id] || 'Совпадение проверено и не является дублем',
      )
    ),
    onSuccess: invalidateGovernance,
  })

  const mergeMutation = useMutation({
    mutationFn: (candidate: CIDuplicateCandidate) => (
      mergeCIDuplicateCandidate(
        accessToken,
        candidate,
        candidateReasons[candidate.id] || 'Дубль подтверждён владельцем CMDB',
      )
    ),
    onSuccess: invalidateGovernance,
  })

  const selectedSource = sources.find((source) => source.id === selectedSourceId)
  const previewCounts = useMemo(() => selectedRun ? [
    ['Создать', selectedRun.create_count],
    ['Обновить', selectedRun.update_count],
    ['Без изменений', selectedRun.unchanged_count],
    ['Конфликты', selectedRun.ambiguous_count],
    ['Ошибки', selectedRun.invalid_count],
    ['Защищено', selectedRun.skipped_count],
  ] : [], [selectedRun])

  if (!scopeReady) {
    return (
      <LocalizedContent>
        <section className="section-card">
          <p className="empty-state">
            Выберите организацию, чтобы управлять источниками CMDB.
          </p>
        </section>
      </LocalizedContent>
    )
  }

  return (
    <LocalizedContent>
      <div className="cmdb-reconciliation">
      {isRoot ? (
        <section className="foundation-card cmdb-tenant-context">
          <label className="inline-field">
            <span>Организация CMDB</span>
            <select
              value={tenantId}
              onChange={(event) => onTenantChange(event.target.value)}
            >
              {tenants.map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
          <p>Источники, прогоны и дубли изолированы в выбранной организации.</p>
        </section>
      ) : null}

      <section className="module-overview-grid">
        <article className="metric-card">
          <span>Источники</span>
          <strong>{healthQuery.data?.total_sources ?? sources.length}</strong>
        </article>
        <article className="metric-card">
          <span>Активные</span>
          <strong>{healthQuery.data?.active_sources ?? 0}</strong>
        </article>
        <article className="metric-card">
          <span>Просроченные</span>
          <strong>{healthQuery.data?.stale_sources ?? 0}</strong>
        </article>
        <article className="metric-card">
          <span>Дубли на разборе</span>
          <strong>{healthQuery.data?.open_duplicate_candidates ?? 0}</strong>
        </article>
      </section>

      <section className="section-card">
        <header className="section-header">
          <div>
            <h3 className="section-title">Источники истины и приоритет полей</h3>
            <p className="section-subtitle">
              Меньшее число приоритета сильнее. Поля более сильного источника
              защищены от перезаписи.
            </p>
          </div>
        </header>
        {sourcesQuery.isError ? (
          <p className="form-error">{errorMessage(sourcesQuery.error)}</p>
        ) : null}
        <div className="cmdb-source-grid">
          {sources.map((source) => {
            const draft = sourceDrafts[source.id] ?? {
              priority: String(source.priority),
              stale_after_hours: String(source.stale_after_hours),
              claim_unowned_fields: source.claim_unowned_fields,
            }
            return (
              <article
                className={`foundation-card cmdb-source-card ${
                  source.id === selectedSourceId ? 'selected' : ''
                }`}
                key={source.id}
              >
                <header>
                  <div>
                    <span className={`status-pill status-${source.status.toLowerCase()}`}>
                      {source.status}
                    </span>
                    {source.is_stale && source.status === 'ACTIVE' ? (
                      <span className="status-pill status-warning">STALE</span>
                    ) : null}
                  </div>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => setSelectedSourceId(source.id)}
                  >
                    Использовать
                  </button>
                </header>
                <h3>{source.name}</h3>
                <p>{source.code} · {source.source_type} · {source.default_class_name ?? 'класс задаётся записью'}</p>
                <dl>
                  <div><dt>Идентификация</dt><dd>{source.identification_rules.join(' → ')}</dd></div>
                  <div><dt>Авторитетные поля</dt><dd>{source.authoritative_fields.join(', ') || 'нет'}</dd></div>
                  <div><dt>Последний успех</dt><dd>{formatDateTime(source.last_success_at)}</dd></div>
                </dl>
                {canManage ? (
                  <div className="cmdb-source-policy">
                    <label>
                      <span>Приоритет</span>
                      <input
                        type="number"
                        min={1}
                        max={1000}
                        value={draft.priority}
                        onChange={(event) => setSourceDrafts((current) => ({
                          ...current,
                          [source.id]: { ...draft, priority: event.target.value },
                        }))}
                      />
                    </label>
                    <label>
                      <span>Stale, часов</span>
                      <input
                        type="number"
                        min={1}
                        value={draft.stale_after_hours}
                        onChange={(event) => setSourceDrafts((current) => ({
                          ...current,
                          [source.id]: {
                            ...draft,
                            stale_after_hours: event.target.value,
                          },
                        }))}
                      />
                    </label>
                    <label className="checkbox-row">
                      <input
                        type="checkbox"
                        checked={draft.claim_unowned_fields}
                        onChange={(event) => setSourceDrafts((current) => ({
                          ...current,
                          [source.id]: {
                            ...draft,
                            claim_unowned_fields: event.target.checked,
                          },
                        }))}
                      />
                      Забрать незакреплённые поля
                    </label>
                    <div className="cmdb-source-actions">
                      <button
                        type="button"
                        onClick={() => updateSourceMutation.mutate({ source })}
                        disabled={updateSourceMutation.isPending}
                      >
                        Сохранить политику
                      </button>
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => updateSourceMutation.mutate({
                          source,
                          status: source.status === 'ACTIVE' ? 'INACTIVE' : 'ACTIVE',
                        })}
                        disabled={updateSourceMutation.isPending}
                      >
                        {source.status === 'ACTIVE' ? 'Приостановить' : 'Активировать'}
                      </button>
                    </div>
                  </div>
                ) : null}
              </article>
            )
          })}
        </div>
        {updateSourceMutation.isError ? (
          <p className="form-error">{errorMessage(updateSourceMutation.error)}</p>
        ) : null}
      </section>

      {canManage ? (
        <div className="cmdb-admin-grid">
          <section className="section-card">
            <header className="section-header">
              <div>
                <h3 className="section-title">Новый источник CMDB</h3>
                <p className="section-subtitle">
                  Настройте идентификацию, владение полями и контроль свежести.
                </p>
              </div>
            </header>
            <form
              className="modal-form"
              onSubmit={(event) => {
                event.preventDefault()
                createSourceMutation.mutate()
              }}
            >
              <label><span>Код</span><input value={sourceForm.code} onChange={(event) => setSourceForm((current) => ({ ...current, code: event.target.value }))} placeholder="VMWARE_DISCOVERY" required /></label>
              <label><span>Название</span><input value={sourceForm.name} onChange={(event) => setSourceForm((current) => ({ ...current, name: event.target.value }))} placeholder="VMware Discovery" required /></label>
              <label><span>Описание</span><textarea value={sourceForm.description} onChange={(event) => setSourceForm((current) => ({ ...current, description: event.target.value }))} /></label>
              <label>
                <span>Тип источника</span>
                <select value={sourceForm.source_type} onChange={(event) => setSourceForm((current) => ({ ...current, source_type: event.target.value as CMDBSource['source_type'] }))}>
                  <option value="API">API</option>
                  <option value="DISCOVERY">Discovery</option>
                  <option value="FILE">Файл</option>
                  <option value="MANUAL">Ручной</option>
                </select>
              </label>
              <label>
                <span>Класс по умолчанию</span>
                <select value={sourceForm.default_class_id} onChange={(event) => setSourceForm((current) => ({ ...current, default_class_id: event.target.value }))}>
                  <option value="">Класс задаётся в записи</option>
                  {publishedClasses.map((ciClass) => (
                    <option key={ciClass.id} value={ciClass.id}>{ciClass.name}</option>
                  ))}
                </select>
              </label>
              <label><span>Приоритет</span><input type="number" min={1} max={1000} value={sourceForm.priority} onChange={(event) => setSourceForm((current) => ({ ...current, priority: event.target.value }))} required /></label>
              <label><span>Правила идентификации</span><input value={sourceForm.identification_rules} onChange={(event) => setSourceForm((current) => ({ ...current, identification_rules: event.target.value }))} required /><small>Через запятую, в порядке доверия.</small></label>
              <label><span>Авторитетные поля</span><textarea value={sourceForm.authoritative_fields} onChange={(event) => setSourceForm((current) => ({ ...current, authoritative_fields: event.target.value }))} /></label>
              <label><span>Stale после, часов</span><input type="number" min={1} value={sourceForm.stale_after_hours} onChange={(event) => setSourceForm((current) => ({ ...current, stale_after_hours: event.target.value }))} required /></label>
              <label className="checkbox-row">
                <input type="checkbox" checked={sourceForm.claim_unowned_fields} onChange={(event) => setSourceForm((current) => ({ ...current, claim_unowned_fields: event.target.checked }))} />
                Разрешить источнику забирать незакреплённые непустые поля
              </label>
              {createSourceMutation.isError ? (
                <p className="form-error">{errorMessage(createSourceMutation.error)}</p>
              ) : null}
              <button type="submit" disabled={createSourceMutation.isPending || !sourceForm.code.trim() || !sourceForm.name.trim()}>
                Создать источник
              </button>
            </form>
          </section>

          <section className="section-card">
            <header className="section-header">
              <div>
                <h3 className="section-title">Пакет сверки</h3>
                <p className="section-subtitle">
                  Preview ничего не меняет. Apply доступен после проверки результата.
                </p>
              </div>
            </header>
            <form
              className="modal-form"
              onSubmit={(event) => {
                event.preventDefault()
                previewMutation.mutate()
              }}
            >
              <label>
                <span>Источник</span>
                <select value={selectedSourceId} onChange={(event) => setSelectedSourceId(event.target.value)} required>
                  <option value="">Выберите источник</option>
                  {sources.filter((source) => source.status === 'ACTIVE').map((source) => (
                    <option key={source.id} value={source.id}>{source.name} · P{source.priority}</option>
                  ))}
                </select>
              </label>
              <label><span>Idempotency key</span><input value={idempotencyKey} onChange={(event) => setIdempotencyKey(event.target.value)} required /></label>
              <label>
                <span>JSON-массив записей</span>
                <textarea className="cmdb-json-editor" value={batchText} onChange={(event) => setBatchText(event.target.value)} spellCheck={false} required />
              </label>
              {batchParseError ? <p className="form-error">{batchParseError}</p> : null}
              {previewMutation.isError ? (
                <p className="form-error">{errorMessage(previewMutation.error)}</p>
              ) : null}
              <button type="submit" disabled={previewMutation.isPending || !selectedSourceId}>
                Выполнить безопасный preview
              </button>
            </form>
          </section>
        </div>
      ) : null}

      <section className="section-card">
        <header className="section-header">
          <div>
            <h3 className="section-title">Прогоны сверки</h3>
            <p className="section-subtitle">
              Каждый пакет неизменяем, имеет hash и идемпотентный ключ.
            </p>
          </div>
        </header>
        <div className="cmdb-run-layout">
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Дата</th><th>Источник</th><th>Статус</th><th>Вход</th><th>Действие</th></tr></thead>
              <tbody>
                {runs.map((run) => (
                  <tr key={run.id} className={run.id === selectedRunId ? 'selected-row' : ''}>
                    <td>{formatDateTime(run.created_at)}</td>
                    <td>{run.source_name}</td>
                    <td><span className={`status-pill status-${run.status.toLowerCase()}`}>{run.status}</span></td>
                    <td>{run.input_count}</td>
                    <td><button type="button" className="ghost-button" onClick={() => setSelectedRunId(run.id)}>Открыть</button></td>
                  </tr>
                ))}
                {!runs.length ? <tr><td colSpan={5}><p className="empty-state">Прогонов пока нет.</p></td></tr> : null}
              </tbody>
            </table>
          </div>
          <aside className="foundation-card cmdb-run-detail">
            {!selectedRun ? <p className="empty-state">Выберите прогон.</p> : (
              <>
                <header>
                  <div>
                    <span className={`status-pill status-${selectedRun.status.toLowerCase()}`}>{selectedRun.status}</span>
                    <h3>{selectedRun.source_name}</h3>
                  </div>
                  <code>{selectedRun.payload_hash.slice(0, 16)}</code>
                </header>
                <div className="cmdb-run-counts">
                  {previewCounts.map(([label, value]) => (
                    <div key={String(label)}><span>{label}</span><strong>{value}</strong></div>
                  ))}
                </div>
                {selectedRun.status === 'PREVIEWED' && canManage ? (
                  <button type="button" onClick={() => applyMutation.mutate(selectedRun.id)} disabled={applyMutation.isPending || selectedRun.invalid_count > 0 || selectedRun.ambiguous_count > 0}>
                    Применить подтверждённые изменения
                  </button>
                ) : null}
                {selectedRun.status === 'PREVIEWED' && (selectedRun.invalid_count > 0 || selectedRun.ambiguous_count > 0) ? (
                  <p className="form-warning">
                    Apply заблокирован до исправления ошибок и разбора неоднозначных совпадений.
                  </p>
                ) : null}
                {applyMutation.isError ? <p className="form-error">{errorMessage(applyMutation.error)}</p> : null}
              </>
            )}
          </aside>
        </div>
        {selectedRun ? (
          <div className="ticket-table-wrap cmdb-record-table">
            <table className="ticket-table">
              <thead><tr><th>#</th><th>External ID</th><th>Результат</th><th>CI</th><th>План</th><th>Защищено / ошибки</th></tr></thead>
              <tbody>
                {(selectedRun.records ?? []).map((record) => (
                  <tr key={record.id}>
                    <td>{record.row_number}</td>
                    <td><code>{record.external_id}</code></td>
                    <td><span className={`status-pill status-${record.outcome.toLowerCase()}`}>{record.outcome}</span></td>
                    <td>{record.matched_ci_id ?? (record.candidate_ids.join(', ') || 'новый CI')}</td>
                    <td>{Array.isArray(record.normalized._planned_fields) ? record.normalized._planned_fields.join(', ') : '—'}</td>
                    <td>
                      {record.errors.join(', ')
                        || (Array.isArray(record.normalized._blocked_fields) ? record.normalized._blocked_fields.join(', ') : '')
                        || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>

      <section className="section-card">
        <header className="section-header">
          <div>
            <h3 className="section-title">Очередь возможных дублей</h3>
            <p className="section-subtitle">
              Merge переносит зависимости на основной CI и архивирует дубль.
              Физического удаления нет.
            </p>
          </div>
        </header>
        <div className="cmdb-duplicate-list">
          {candidates.map((candidate) => (
            <article className="foundation-card cmdb-duplicate-card" key={candidate.id}>
              <header>
                <span className="status-pill status-warning">
                  {Math.round(candidate.confidence * 100)}% совпадения
                </span>
                <span>{candidate.reasons.join(' · ')}</span>
              </header>
              <div className="cmdb-duplicate-compare">
                <div>
                  <span>ОСНОВНОЙ CI</span>
                  <strong>{candidate.primary.name}</strong>
                  <p>{candidate.primary.asset_tag} · {candidate.primary.ci_class_name ?? 'без класса'} · v{candidate.primary.version}</p>
                </div>
                <b>↔</b>
                <div>
                  <span>ВОЗМОЖНЫЙ ДУБЛЬ</span>
                  <strong>{candidate.duplicate.name}</strong>
                  <p>{candidate.duplicate.asset_tag} · {candidate.duplicate.ci_class_name ?? 'без класса'} · v{candidate.duplicate.version}</p>
                </div>
              </div>
              {canManage ? (
                <div className="cmdb-duplicate-actions">
                  <input
                    value={candidateReasons[candidate.id] ?? ''}
                    onChange={(event) => setCandidateReasons((current) => ({
                      ...current,
                      [candidate.id]: event.target.value,
                    }))}
                    placeholder="Обоснование решения"
                  />
                  <button type="button" onClick={() => mergeMutation.mutate(candidate)} disabled={mergeMutation.isPending}>
                    Объединить безопасно
                  </button>
                  <button type="button" className="ghost-button" onClick={() => dismissMutation.mutate(candidate)} disabled={dismissMutation.isPending}>
                    Не является дублем
                  </button>
                </div>
              ) : null}
            </article>
          ))}
          {!candidates.length ? <p className="empty-state">Открытых кандидатов нет.</p> : null}
        </div>
        {mergeMutation.isError ? <p className="form-error">{errorMessage(mergeMutation.error)}</p> : null}
        {dismissMutation.isError ? <p className="form-error">{errorMessage(dismissMutation.error)}</p> : null}
      </section>

      {selectedSource ? (
        <p className="muted">
          Текущий источник: {selectedSource.name} · приоритет {selectedSource.priority}
          {' · '}последний запуск {formatDateTime(selectedSource.last_run_at)}
        </p>
      ) : null}
      </div>
    </LocalizedContent>
  )
}
