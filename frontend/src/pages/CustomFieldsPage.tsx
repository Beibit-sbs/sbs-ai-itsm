import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createCustomFieldDraft,
  createCustomFieldSet,
  fetchCustomFieldCatalog,
  fetchCustomFieldDashboard,
  fetchCustomFieldSets,
  fetchCustomFieldVersions,
  fetchEntityCustomFieldSets,
  fetchTenants,
  publishCustomFieldVersion,
  saveCustomFieldDraft,
  saveEntityCustomFieldValues,
  searchCustomFieldValues,
  updateCustomFieldSet,
  type CustomFieldDefinition,
  type CustomFieldEntityType,
  type CustomFieldSchema,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { useLocalizedDefaultState } from '../experience/useLocalizedDefaultState'

type View = 'designer' | 'record-test' | 'search'
type EditorMode = 'visual' | 'json'

const views: Array<{ key: View; label: string }> = [
  { key: 'designer', label: 'Конструктор' },
  { key: 'record-test', label: 'Проверка на записи' },
  { key: 'search', label: 'Поиск по полям' },
]

const entityLabels: Record<CustomFieldEntityType, string> = {
  ticket: 'Инцидент',
  asset: 'Актив / CI',
  change: 'Изменение',
  problem: 'Проблема',
  request: 'Запрос услуги',
}

const applicabilityFields: Record<CustomFieldEntityType, string[]> = {
  ticket: ['status', 'priority', 'category', 'source', 'service_name'],
  asset: ['status', 'asset_type', 'category', 'location', 'department'],
  change: ['status', 'change_type', 'environment', 'risk_level', 'service_name'],
  problem: ['status', 'problem_type', 'priority', 'category', 'service_name'],
  request: ['status', 'source', 'service_name', 'cost_center'],
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

function parseObject(
  value: string,
  label: string,
  translate: (source: string) => string,
) {
  const parsed = JSON.parse(value) as unknown
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label} ${translate('должен быть JSON-объектом')}`)
  }
  return parsed as Record<string, unknown>
}

function emptySchema(
  entityType: CustomFieldEntityType,
  translate: (source: string) => string,
): CustomFieldSchema {
  return {
    schema_version: '1.0',
    title: `${translate('Дополнительные поля ·')} ${translate(entityLabels[entityType])}`,
    introduction: '',
    sections: [
      {
        id: 'additional_details',
        title: translate('Дополнительные сведения'),
        description: '',
        order: 10,
      },
    ],
    fields: [],
  }
}

function emptyField(
  index: number,
  translate: (source: string) => string,
): CustomFieldDefinition {
  return {
    key: `field_${index + 1}`,
    label: `${translate('Новое поле')} ${index + 1}`,
    type: 'text',
    section_id: 'additional_details',
    required: false,
    help_text: '',
    placeholder: '',
    options: [],
    validations: {},
    searchable: false,
    indexed: false,
    reportable: true,
    sensitive: false,
    immutable_after_set: false,
  }
}

function fieldOptionsText(field: CustomFieldDefinition) {
  return field.options
    .map((option) => `${option.value}=${option.label}`)
    .join('\n')
}

function parseOptions(value: string) {
  return value
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [rawValue, ...labelParts] = line.split('=')
      const optionValue = rawValue.trim()
      return {
        value: optionValue,
        label: labelParts.join('=').trim() || optionValue,
      }
    })
}

export default function CustomFieldsPage() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const can = (permission: string) => isRoot || permissions.has(permission)
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [view, setView] = useState<View>('designer')
  const [editorMode, setEditorMode] = useState<EditorMode>('visual')
  const [entityFilter, setEntityFilter] =
    useState<CustomFieldEntityType | 'ALL'>('ALL')
  const [selectedFieldSetId, setSelectedFieldSetId] = useState('')
  const [selectedVersionNumber, setSelectedVersionNumber] =
    useState<number | null>(null)
  const [schema, setSchema] = useLocalizedDefaultState<CustomFieldSchema>(
    (localize) => emptySchema('ticket', localize),
  )
  const [jsonEditor, setJsonEditor] = useState('')
  const [editorKey, setEditorKey] = useState('')
  const [dirty, setDirty] = useState(false)
  const [changeSummary, setChangeSummary] =
    useLocalizedDefaultState('Настройка дополнительных полей')
  const [allowBreaking, setAllowBreaking] = useState(false)
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState({
    code: '',
    name: '',
    description: '',
    entity_type: 'ticket' as CustomFieldEntityType,
  })
  const [applicabilityDraft, setApplicabilityDraft] = useState<
    Array<{ field: string; operator: 'eq' | 'neq' | 'in'; value: string }>
  >([])
  const [testEntityType, setTestEntityType] =
    useState<CustomFieldEntityType>('ticket')
  const [testEntityId, setTestEntityId] = useState('')
  const [loadedEntityId, setLoadedEntityId] = useState('')
  const [valueEditors, setValueEditors] = useState<Record<string, string>>({})
  const [searchTerm, setSearchTerm] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')

  const tenantsQuery = useQuery({
    queryKey: ['custom-fields-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot),
  })
  useEffect(() => {
    if (isRoot && !tenantId && tenantsQuery.data?.length) {
      setTenantId(tenantsQuery.data[0].id)
    }
  }, [isRoot, tenantId, tenantsQuery.data])
  const scopedTenant = isRoot ? tenantId || null : session?.user.tenant_id ?? null
  const scopeReady = Boolean(token && scopedTenant)

  const dashboardQuery = useQuery({
    queryKey: ['custom-fields-dashboard', token, scopedTenant],
    queryFn: () => fetchCustomFieldDashboard(token, scopedTenant),
    enabled: scopeReady && can('custom_fields.read'),
  })
  const catalogQuery = useQuery({
    queryKey: ['custom-fields-catalog', token],
    queryFn: () => fetchCustomFieldCatalog(token),
    enabled: Boolean(token) && can('custom_fields.read'),
    staleTime: 300_000,
  })
  const fieldSetsQuery = useQuery({
    queryKey: ['custom-field-sets', token, scopedTenant, entityFilter],
    queryFn: () =>
      fetchCustomFieldSets(
        token,
        scopedTenant,
        entityFilter === 'ALL' ? null : entityFilter,
      ),
    enabled: scopeReady && can('custom_fields.read'),
  })
  const fieldSets = fieldSetsQuery.data ?? []
  const selectedFieldSet = useMemo(
    () => fieldSets.find((item) => item.id === selectedFieldSetId) ?? null,
    [fieldSets, selectedFieldSetId],
  )
  const versionsQuery = useQuery({
    queryKey: ['custom-field-versions', token, selectedFieldSetId],
    queryFn: () => fetchCustomFieldVersions(token, selectedFieldSetId),
    enabled: Boolean(token && selectedFieldSetId),
  })
  const versions = versionsQuery.data ?? []
  const selectedVersion = useMemo(
    () =>
      versions.find((item) => item.version_number === selectedVersionNumber) ??
      null,
    [selectedVersionNumber, versions],
  )

  const entityFieldSetsQuery = useQuery({
    queryKey: [
      'entity-custom-fields',
      token,
      testEntityType,
      loadedEntityId,
    ],
    queryFn: () =>
      fetchEntityCustomFieldSets(
        token,
        testEntityType,
        loadedEntityId,
        scopedTenant,
      ),
    enabled:
      Boolean(token && loadedEntityId) &&
      can('custom_fields.values.read') &&
      view === 'record-test',
  })
  const searchQuery = useQuery({
    queryKey: [
      'custom-fields-search',
      token,
      scopedTenant,
      submittedSearch,
      entityFilter,
    ],
    queryFn: () =>
      searchCustomFieldValues(
        token,
        submittedSearch,
        scopedTenant,
        entityFilter === 'ALL' ? null : entityFilter,
      ),
    enabled:
      scopeReady &&
      submittedSearch.length >= 2 &&
      can('custom_fields.search') &&
      view === 'search',
  })

  useEffect(() => {
    if (!selectedFieldSetId && fieldSets.length) {
      setSelectedFieldSetId(fieldSets[0].id)
    } else if (
      selectedFieldSetId &&
      fieldSets.length &&
      !fieldSets.some((item) => item.id === selectedFieldSetId)
    ) {
      setSelectedFieldSetId(fieldSets[0].id)
    }
  }, [fieldSets, selectedFieldSetId])

  useEffect(() => {
    if (!selectedFieldSet) {
      setSelectedVersionNumber(null)
      return
    }
    setSelectedVersionNumber(
      selectedFieldSet.draft_version_number ??
        selectedFieldSet.published_version_number ??
        selectedFieldSet.latest_version_number,
    )
    setApplicabilityDraft(
      (selectedFieldSet.applicability.all ?? []).map((condition) => ({
        field: condition.field,
        operator: condition.operator,
        value: Array.isArray(condition.value)
          ? condition.value.join(', ')
          : String(condition.value ?? ''),
      })),
    )
  }, [selectedFieldSet])

  useEffect(() => {
    if (!selectedVersion?.schema_definition) return
    const nextKey = `${selectedVersion.id}:${selectedVersion.revision}`
    if (dirty && editorKey.startsWith(`${selectedVersion.id}:`)) return
    setSchema(structuredClone(selectedVersion.schema_definition))
    setJsonEditor(JSON.stringify(selectedVersion.schema_definition, null, 2))
    setEditorKey(nextKey)
    setDirty(false)
  }, [dirty, editorKey, selectedVersion])

  useEffect(() => {
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!dirty) return
      event.preventDefault()
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [dirty])

  useEffect(() => {
    const entries = entityFieldSetsQuery.data ?? []
    setValueEditors(
      Object.fromEntries(
        entries.map((entry) => [
          entry.field_set.id,
          JSON.stringify(entry.value_record?.values ?? {}, null, 2),
        ]),
      ),
    )
  }, [entityFieldSetsQuery.data])

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['custom-fields-dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['custom-field-sets'] }),
      queryClient.invalidateQueries({ queryKey: ['custom-field-versions'] }),
      queryClient.invalidateQueries({ queryKey: ['entity-custom-fields'] }),
      queryClient.invalidateQueries({ queryKey: ['custom-fields-search'] }),
    ])
  }

  const runAction = async (
    key: string,
    action: () => Promise<unknown>,
    successMessage: string,
  ) => {
    setBusy(key)
    setError('')
    setNotice('')
    try {
      await action()
      await invalidate()
      setNotice(translate(successMessage))
    } catch (actionError) {
      setError(errorText(actionError))
    } finally {
      setBusy('')
    }
  }

  const mutateSchema = (
    updater: (current: CustomFieldSchema) => CustomFieldSchema,
  ) => {
    setSchema((current) => updater(structuredClone(current)))
    setDirty(true)
  }

  const updateField = (
    index: number,
    updater: (field: CustomFieldDefinition) => CustomFieldDefinition,
  ) => {
    mutateSchema((current) => {
      current.fields[index] = updater({ ...current.fields[index] })
      return current
    })
  }

  const applyJson = () => {
    try {
      const parsed = parseObject(jsonEditor, translate('Схема'), translate) as CustomFieldSchema
      setSchema(parsed)
      setDirty(true)
      setError('')
      setNotice('JSON применён к рабочему черновику')
    } catch (parseError) {
      setError(errorText(parseError))
    }
  }

  const saveDraft = async () => {
    if (!selectedFieldSet || !selectedVersion) return
    await runAction(
      'save-draft',
      async () => {
        const result = await saveCustomFieldDraft(
          token,
          selectedFieldSet.id,
          selectedVersion,
          schema,
          changeSummary,
        )
        setSchema(result.version.schema_definition ?? schema)
        setJsonEditor(
          JSON.stringify(result.version.schema_definition ?? schema, null, 2),
        )
        setDirty(false)
      },
      'Черновик проверен и сохранён',
    )
  }

  const publishDraft = async () => {
    if (!selectedFieldSet || !selectedVersion) return
    await runAction(
      'publish',
      async () => {
        await publishCustomFieldVersion(token, selectedFieldSet, selectedVersion, {
          allow_breaking_changes: allowBreaking,
          reason: changeSummary,
        })
        setDirty(false)
        setAllowBreaking(false)
      },
      'Версия опубликована и стала активной',
    )
  }

  const createSet = async () => {
    await runAction(
      'create',
      async () => {
        const result = await createCustomFieldSet(token, {
          tenant_id: scopedTenant,
          code: createForm.code,
          name: createForm.name,
          description: createForm.description || null,
          entity_type: createForm.entity_type,
          applicability: { all: [] },
        })
        setSelectedFieldSetId(result.field_set.id)
        setSelectedVersionNumber(result.draft.version_number)
        setCreateOpen(false)
        setCreateForm({
          code: '',
          name: '',
          description: '',
          entity_type: 'ticket',
        })
      },
      'Набор полей создан с первым черновиком',
    )
  }

  const saveApplicability = async () => {
    if (!selectedFieldSet) return
    await runAction(
      'applicability',
      () =>
        updateCustomFieldSet(token, selectedFieldSet, {
          applicability: {
            all: applicabilityDraft.map((condition) => ({
              field: condition.field,
              operator: condition.operator,
              value:
                condition.operator === 'in'
                  ? condition.value
                      .split(',')
                      .map((item) => item.trim())
                      .filter(Boolean)
                  : condition.value,
            })),
          },
          reason: translate('Обновлена область применения набора полей'),
        }),
      'Область применения сохранена',
    )
  }

  const createNextDraft = async () => {
    if (!selectedFieldSet) return
    await runAction(
      'new-draft',
      async () => {
        const result = await createCustomFieldDraft(
          token,
          selectedFieldSet,
          changeSummary,
        )
        setSelectedVersionNumber(result.draft.version_number)
      },
      'Создан новый черновик из опубликованной версии',
    )
  }

  const changeStatus = async (
    nextStatus: 'ACTIVE' | 'PAUSED' | 'ARCHIVED',
  ) => {
    if (!selectedFieldSet) return
    if (
      nextStatus === 'ARCHIVED' &&
      !window.confirm(translate('Архивирование необратимо. Продолжить?'))
    ) {
      return
    }
    await runAction(
      `status-${nextStatus}`,
      () =>
        updateCustomFieldSet(token, selectedFieldSet, {
          status: nextStatus,
          reason: `${translate('Изменение статуса на')} ${nextStatus}`,
        }),
      `${translate('Статус изменён на')} ${nextStatus}`,
    )
  }

  const dashboard = dashboardQuery.data
  const selectedEditable = selectedVersion?.status === 'DRAFT'
  const validation = selectedVersion?.validation

  return (
    <LocalizedContent>
    <AppShell
      title="Настраиваемые поля"
      subtitle="Единый типизированный слой данных для инцидентов, активов, изменений, проблем и запросов"
    >
      <QueryFailureNotice
        title="Часть данных Custom Fields недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: translate('оперативная сводка'), query: dashboardQuery },
          { label: translate('каталог типов'), query: catalogQuery },
          { label: 'field sets', query: fieldSetsQuery },
          { label: translate('версии'), query: versionsQuery },
          { label: 'entity bindings', query: entityFieldSetsQuery },
          { label: translate('поиск'), query: searchQuery },
        ]}
      />
      <section className="custom-fields-page">
        <div className="custom-fields-hero">
          <div>
            <p className="eyebrow">CONFIGURATION MANAGEMENT · CFG-001</p>
            <h2>Custom Fields Control Plane</h2>
            <p>
              Проектируйте поля визуально, проверяйте совместимость схем,
              публикуйте неизменяемые версии и защищайте чувствительные значения.
            </p>
          </div>
          <div className="custom-fields-hero-actions">
            {isRoot ? (
              <label>
                <span>Организация</span>
                <select
                  value={tenantId}
                  onChange={(event) => setTenantId(event.target.value)}
                >
                  <option value="">Выберите tenant</option>
                  {(tenantsQuery.data ?? []).map((tenant) => (
                    <option key={tenant.id} value={tenant.id}>
                      {tenant.name}
                    </option>
                  ))}
                </select>
              </label>
            ) : null}
            {can('custom_fields.design') ? (
              <button
                type="button"
                className="primary-button"
                onClick={() => setCreateOpen((current) => !current)}
              >
                {createOpen ? 'Закрыть' : 'Создать набор полей'}
              </button>
            ) : null}
          </div>
        </div>

        {notice ? <div className="success-banner">{notice}</div> : null}
        {error ? <div className="error-state">{error}</div> : null}

        {createOpen ? (
          <form
            className="custom-fields-create"
            onSubmit={(event) => {
              event.preventDefault()
              void createSet()
            }}
          >
            <label>
              <span>Код</span>
              <input
                value={createForm.code}
                onChange={(event) =>
                  setCreateForm((current) => ({
                    ...current,
                    code: event.target.value,
                  }))
                }
                placeholder="ticket.security"
                required
              />
            </label>
            <label>
              <span>Название</span>
              <input
                value={createForm.name}
                onChange={(event) =>
                  setCreateForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                placeholder="Поля информационной безопасности"
                required
              />
            </label>
            <label>
              <span>Тип записи</span>
              <select
                value={createForm.entity_type}
                onChange={(event) =>
                  setCreateForm((current) => ({
                    ...current,
                    entity_type: event.target.value as CustomFieldEntityType,
                  }))
                }
              >
                {Object.entries(entityLabels).map(([value, label]) => (
                  <option key={value} value={value}>
                    {translate(label)}
                  </option>
                ))}
              </select>
            </label>
            <label className="custom-fields-wide">
              <span>Описание</span>
              <input
                value={createForm.description}
                onChange={(event) =>
                  setCreateForm((current) => ({
                    ...current,
                    description: event.target.value,
                  }))
                }
              />
            </label>
            <button
              type="submit"
              className="primary-button"
              disabled={busy === 'create'}
            >
              {busy === 'create' ? 'Создаём…' : 'Создать'}
            </button>
          </form>
        ) : null}

        <div className="custom-fields-metrics">
          <article>
            <span>Наборы полей</span>
            <strong>{dashboard?.field_sets.total ?? '—'}</strong>
            <small>{dashboard?.field_sets.by_status.ACTIVE ?? 0} активных</small>
          </article>
          <article>
            <span>Записи со значениями</span>
            <strong>{dashboard?.stored_value_records ?? '—'}</strong>
            <small>tenant-scoped</small>
          </article>
          <article>
            <span>Невалидные черновики</span>
            <strong>{dashboard?.invalid_drafts ?? '—'}</strong>
            <small>публикация закрыта fail-closed</small>
          </article>
          <article>
            <span>Типы полей</span>
            <strong>{catalogQuery.data?.field_types.length ?? '—'}</strong>
            <small>типизированный каталог</small>
          </article>
        </div>

        <div
          className="custom-fields-view-tabs"
          role="tablist"
          aria-label="Режим работы"
        >
          {views.map((item) => (
            <button
              key={item.key}
              type="button"
              role="tab"
              aria-selected={view === item.key}
              className={view === item.key ? 'active' : ''}
              onClick={() => setView(item.key)}
            >
              {translate(item.label)}
            </button>
          ))}
        </div>

        <div className="custom-fields-filterbar">
          <label>
            <span>Тип записи</span>
            <select
              value={entityFilter}
              onChange={(event) =>
                setEntityFilter(
                  event.target.value as CustomFieldEntityType | 'ALL',
                )
              }
            >
              <option value="ALL">Все типы</option>
              {Object.entries(entityLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {translate(label)}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Набор полей</span>
            <select
              value={selectedFieldSetId}
              onChange={(event) => {
                if (
                  dirty &&
                  !window.confirm(translate('Отменить несохранённые изменения?'))
                ) {
                  return
                }
                setDirty(false)
                setSelectedFieldSetId(event.target.value)
              }}
            >
              <option value="">Нет наборов</option>
              {fieldSets.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name} · {translate(entityLabels[item.entity_type])} · {item.status}
                </option>
              ))}
            </select>
          </label>
          {selectedFieldSet ? (
            <>
              <span
                className={`badge badge-${
                  selectedFieldSet.status === 'ACTIVE' ? 'positive' : 'warning'
                }`}
              >
                {selectedFieldSet.status}
              </span>
              <small>rev {selectedFieldSet.revision}</small>
            </>
          ) : null}
        </div>

        {view === 'designer' ? (
          !selectedFieldSet ? (
            <div className="empty-state">
              Создайте первый набор полей или выберите организацию с существующими
              настройками.
            </div>
          ) : (
            <div className="custom-fields-designer-grid">
              <aside className="custom-fields-sidebar-panel">
                <header>
                  <div>
                    <p className="eyebrow">{selectedFieldSet.code}</p>
                    <h3>{selectedFieldSet.name}</h3>
                  </div>
                </header>
                <dl className="custom-fields-meta">
                  <div>
                    <dt>Сущность</dt>
                    <dd>{translate(entityLabels[selectedFieldSet.entity_type])}</dd>
                  </div>
                  <div>
                    <dt>Опубликовано</dt>
                    <dd>v{selectedFieldSet.published_version_number ?? '—'}</dd>
                  </div>
                  <div>
                    <dt>Черновик</dt>
                    <dd>v{selectedFieldSet.draft_version_number ?? '—'}</dd>
                  </div>
                  <div>
                    <dt>Обновлено</dt>
                    <dd>{formatDateTime(selectedFieldSet.updated_at)}</dd>
                  </div>
                </dl>
                <div className="custom-fields-status-actions">
                  {can('custom_fields.design') &&
                  selectedFieldSet.status !== 'ARCHIVED' ? (
                    <>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busy !== ''}
                        onClick={() =>
                          void changeStatus(
                            selectedFieldSet.status === 'ACTIVE'
                              ? 'PAUSED'
                              : 'ACTIVE',
                          )
                        }
                      >
                        {selectedFieldSet.status === 'ACTIVE'
                          ? 'Приостановить'
                          : 'Активировать'}
                      </button>
                      <button
                        type="button"
                        className="ghost-button"
                        disabled={busy !== ''}
                        onClick={() => void changeStatus('ARCHIVED')}
                      >
                        Архивировать
                      </button>
                    </>
                  ) : null}
                </div>

                <section className="custom-fields-applicability">
                  <header>
                    <div>
                      <h4>Область применения</h4>
                      <p>Все условия должны выполняться.</p>
                    </div>
                    {can('custom_fields.design') ? (
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() =>
                          setApplicabilityDraft((current) => [
                            ...current,
                            {
                              field:
                                applicabilityFields[
                                  selectedFieldSet.entity_type
                                ][0],
                              operator: 'eq',
                              value: '',
                            },
                          ])
                        }
                      >
                        + Условие
                      </button>
                    ) : null}
                  </header>
                  {applicabilityDraft.length === 0 ? (
                    <p className="custom-fields-muted">
                      Применяется ко всем записям этого типа.
                    </p>
                  ) : (
                    applicabilityDraft.map((condition, index) => (
                      <div
                        className="custom-fields-condition"
                        key={`${condition.field}-${index}`}
                      >
                        <select
                          value={condition.field}
                          disabled={!can('custom_fields.design')}
                          onChange={(event) =>
                            setApplicabilityDraft((current) =>
                              current.map((item, itemIndex) =>
                                itemIndex === index
                                  ? { ...item, field: event.target.value }
                                  : item,
                              ),
                            )
                          }
                        >
                          {applicabilityFields[
                            selectedFieldSet.entity_type
                          ].map((field) => (
                            <option key={field} value={field}>
                              {field}
                            </option>
                          ))}
                        </select>
                        <select
                          value={condition.operator}
                          disabled={!can('custom_fields.design')}
                          onChange={(event) =>
                            setApplicabilityDraft((current) =>
                              current.map((item, itemIndex) =>
                                itemIndex === index
                                  ? {
                                      ...item,
                                      operator: event.target.value as
                                        | 'eq'
                                        | 'neq'
                                        | 'in',
                                    }
                                  : item,
                              ),
                            )
                          }
                        >
                          <option value="eq">равно</option>
                          <option value="neq">не равно</option>
                          <option value="in">одно из</option>
                        </select>
                        <input
                          value={condition.value}
                          disabled={!can('custom_fields.design')}
                          placeholder={
                            condition.operator === 'in'
                              ? 'high, critical'
                              : 'open'
                          }
                          onChange={(event) =>
                            setApplicabilityDraft((current) =>
                              current.map((item, itemIndex) =>
                                itemIndex === index
                                  ? { ...item, value: event.target.value }
                                  : item,
                              ),
                            )
                          }
                        />
                        {can('custom_fields.design') ? (
                          <button
                            type="button"
                            className="icon-button"
                            aria-label="Удалить условие"
                            onClick={() =>
                              setApplicabilityDraft((current) =>
                                current.filter(
                                  (_, itemIndex) => itemIndex !== index,
                                ),
                              )
                            }
                          >
                            ×
                          </button>
                        ) : null}
                      </div>
                    ))
                  )}
                  {can('custom_fields.design') ? (
                    <button
                      type="button"
                      className="secondary-button"
                      disabled={busy !== ''}
                      onClick={() => void saveApplicability()}
                    >
                      Сохранить область
                    </button>
                  ) : null}
                </section>

                <section className="custom-fields-versions">
                  <header>
                    <h4>Версии схемы</h4>
                    {!selectedFieldSet.draft_version_number &&
                    selectedFieldSet.status !== 'ARCHIVED' &&
                    can('custom_fields.design') ? (
                      <button
                        type="button"
                        className="ghost-button"
                        disabled={busy !== ''}
                        onClick={() => void createNextDraft()}
                      >
                        Новый черновик
                      </button>
                    ) : null}
                  </header>
                  {versions.map((version) => (
                    <button
                      type="button"
                      key={version.id}
                      className={
                        version.version_number === selectedVersionNumber
                          ? 'selected'
                          : ''
                      }
                      onClick={() => {
                        if (
                          dirty &&
                          !window.confirm(translate('Отменить несохранённые изменения?'))
                        ) {
                          return
                        }
                        setDirty(false)
                        setSelectedVersionNumber(version.version_number)
                      }}
                    >
                      <span>
                        <strong>v{version.version_number}</strong>
                        <small>{version.status}</small>
                      </span>
                      <span>
                        {version.integrity_valid ? '✓ integrity' : '⚠ integrity'}
                        <small>{formatDateTime(version.updated_at)}</small>
                      </span>
                    </button>
                  ))}
                </section>
              </aside>

              <section className="custom-fields-editor-panel">
                {!selectedVersion ? (
                  <div className="empty-state">Версия схемы недоступна.</div>
                ) : (
                  <>
                    <header className="custom-fields-editor-header">
                      <div>
                        <p className="eyebrow">
                          VERSION {selectedVersion.version_number} ·{' '}
                          {selectedVersion.status}
                        </p>
                        <h3>{schema.title}</h3>
                        <p>
                          SHA-256 {selectedVersion.schema_sha256.slice(0, 12)}… ·
                          rev {selectedVersion.revision}
                          {dirty ? ' · есть несохранённые изменения' : ''}
                        </p>
                      </div>
                      <div className="custom-fields-editor-modes">
                        <button
                          type="button"
                          className={editorMode === 'visual' ? 'active' : ''}
                          onClick={() => setEditorMode('visual')}
                        >
                          Визуально
                        </button>
                        <button
                          type="button"
                          className={editorMode === 'json' ? 'active' : ''}
                          onClick={() => {
                            setJsonEditor(JSON.stringify(schema, null, 2))
                            setEditorMode('json')
                          }}
                        >
                          JSON
                        </button>
                      </div>
                    </header>

                    <div
                      className={`custom-fields-validation validation-${selectedVersion.validation_status.toLowerCase()}`}
                    >
                      <strong>
                        {validation?.valid
                          ? 'Схема валидна'
                          : 'Схема требует исправления'}
                      </strong>
                      <span>
                        {validation?.stats.fields ?? schema.fields.length} полей
                        {' · '}
                        {validation?.stats.sensitive ?? 0} sensitive
                        {' · '}
                        {validation?.stats.searchable ?? 0} searchable
                      </span>
                      {(validation?.errors ?? []).map((item) => (
                        <small key={item}>{item}</small>
                      ))}
                    </div>

                    {editorMode === 'json' ? (
                      <div className="custom-fields-json-mode">
                        <textarea
                          className="custom-fields-json-editor"
                          value={jsonEditor}
                          readOnly={
                            !selectedEditable ||
                            !can('custom_fields.design')
                          }
                          spellCheck={false}
                          onChange={(event) =>
                            setJsonEditor(event.target.value)
                          }
                        />
                        {selectedEditable &&
                        can('custom_fields.design') ? (
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={applyJson}
                          >
                            Применить JSON
                          </button>
                        ) : null}
                      </div>
                    ) : (
                      <div className="custom-fields-visual-editor">
                        <div className="custom-fields-schema-header">
                          <label>
                            <span>Заголовок формы</span>
                            <input
                              value={schema.title}
                              readOnly={
                                !selectedEditable ||
                                !can('custom_fields.design')
                              }
                              onChange={(event) =>
                                mutateSchema((current) => {
                                  current.title = event.target.value
                                  return current
                                })
                              }
                            />
                          </label>
                          <label>
                            <span>Вводный текст</span>
                            <textarea
                              value={schema.introduction}
                              readOnly={
                                !selectedEditable ||
                                !can('custom_fields.design')
                              }
                              onChange={(event) =>
                                mutateSchema((current) => {
                                  current.introduction = event.target.value
                                  return current
                                })
                              }
                            />
                          </label>
                        </div>

                        <div className="custom-fields-list">
                          {schema.fields.map((field, index) => (
                            <article
                              className="custom-field-card"
                              key={`${field.key}-${index}`}
                            >
                              <header>
                                <div className="custom-field-order">
                                  <span>{index + 1}</span>
                                  <div>
                                    <button
                                      type="button"
                                      aria-label="Переместить вверх"
                                      disabled={
                                        !selectedEditable || index === 0
                                      }
                                      onClick={() =>
                                        mutateSchema((current) => {
                                          const [moved] =
                                            current.fields.splice(index, 1)
                                          current.fields.splice(
                                            index - 1,
                                            0,
                                            moved,
                                          )
                                          return current
                                        })
                                      }
                                    >
                                      ↑
                                    </button>
                                    <button
                                      type="button"
                                      aria-label="Переместить вниз"
                                      disabled={
                                        !selectedEditable ||
                                        index === schema.fields.length - 1
                                      }
                                      onClick={() =>
                                        mutateSchema((current) => {
                                          const [moved] =
                                            current.fields.splice(index, 1)
                                          current.fields.splice(
                                            index + 1,
                                            0,
                                            moved,
                                          )
                                          return current
                                        })
                                      }
                                    >
                                      ↓
                                    </button>
                                  </div>
                                </div>
                                <div>
                                  <strong>{field.label || field.key}</strong>
                                  <small>
                                    {field.key} · {field.type}
                                  </small>
                                </div>
                                {selectedEditable &&
                                can('custom_fields.design') ? (
                                  <button
                                    type="button"
                                    className="ghost-button"
                                    onClick={() =>
                                      mutateSchema((current) => {
                                        current.fields.splice(index, 1)
                                        return current
                                      })
                                    }
                                  >
                                    Удалить
                                  </button>
                                ) : null}
                              </header>

                              <div className="custom-field-grid">
                                <label>
                                  <span>Ключ</span>
                                  <input
                                    value={field.key}
                                    readOnly={
                                      !selectedEditable ||
                                      !can('custom_fields.design')
                                    }
                                    onChange={(event) =>
                                      updateField(index, (current) => ({
                                        ...current,
                                        key: event.target.value
                                          .toLowerCase()
                                          .replace(/[^a-z0-9_]/g, '_'),
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  <span>Подпись</span>
                                  <input
                                    value={field.label}
                                    readOnly={
                                      !selectedEditable ||
                                      !can('custom_fields.design')
                                    }
                                    onChange={(event) =>
                                      updateField(index, (current) => ({
                                        ...current,
                                        label: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                                <label>
                                  <span>Тип</span>
                                  <select
                                    value={field.type}
                                    disabled={
                                      !selectedEditable ||
                                      !can('custom_fields.design')
                                    }
                                    onChange={(event) =>
                                      updateField(index, (current) => ({
                                        ...current,
                                        type: event.target
                                          .value as CustomFieldDefinition['type'],
                                        options: [
                                          'select',
                                          'multiselect',
                                        ].includes(event.target.value)
                                          ? current.options.length
                                            ? current.options
                                            : [
                                                {
                                                  value: 'option_1',
                                                  label: 'Вариант 1',
                                                },
                                              ]
                                          : [],
                                        indexed: [
                                          'textarea',
                                          'multiselect',
                                        ].includes(event.target.value)
                                          ? false
                                          : current.indexed,
                                      }))
                                    }
                                  >
                                    {(
                                      catalogQuery.data?.field_types ?? [
                                        'text',
                                        'textarea',
                                        'number',
                                        'boolean',
                                        'select',
                                        'multiselect',
                                        'date',
                                        'email',
                                      ]
                                    ).map((type) => (
                                      <option key={type} value={type}>
                                        {type}
                                      </option>
                                    ))}
                                  </select>
                                </label>
                                <label>
                                  <span>Placeholder</span>
                                  <input
                                    value={field.placeholder}
                                    readOnly={
                                      !selectedEditable ||
                                      !can('custom_fields.design')
                                    }
                                    onChange={(event) =>
                                      updateField(index, (current) => ({
                                        ...current,
                                        placeholder: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                                <label className="custom-fields-wide">
                                  <span>Подсказка</span>
                                  <input
                                    value={field.help_text}
                                    readOnly={
                                      !selectedEditable ||
                                      !can('custom_fields.design')
                                    }
                                    onChange={(event) =>
                                      updateField(index, (current) => ({
                                        ...current,
                                        help_text: event.target.value,
                                      }))
                                    }
                                  />
                                </label>
                                {['select', 'multiselect'].includes(
                                  field.type,
                                ) ? (
                                  <label className="custom-fields-wide">
                                    <span>
                                      Варианты (value=Подпись, по одному в строке)
                                    </span>
                                    <textarea
                                      value={fieldOptionsText(field)}
                                      readOnly={
                                        !selectedEditable ||
                                        !can('custom_fields.design')
                                      }
                                      onChange={(event) =>
                                        updateField(index, (current) => ({
                                          ...current,
                                          options: parseOptions(
                                            event.target.value,
                                          ),
                                        }))
                                      }
                                    />
                                  </label>
                                ) : null}
                                <label className="custom-fields-wide">
                                  <span>Правила проверки (JSON)</span>
                                  <input
                                    value={JSON.stringify(field.validations)}
                                    readOnly={
                                      !selectedEditable ||
                                      !can('custom_fields.design')
                                    }
                                    onChange={(event) => {
                                      try {
                                        const validations = parseObject(
                                          event.target.value,
                                          translate('Правила проверки'),
                                          translate,
                                        )
                                        updateField(index, (current) => ({
                                          ...current,
                                          validations,
                                        }))
                                        setError('')
                                      } catch {
                                        setError(
                                          'Правила проверки должны быть корректным JSON-объектом',
                                        )
                                      }
                                    }}
                                  />
                                </label>
                              </div>

                              <div className="custom-field-flags">
                                {(
                                  [
                                    ['required', 'Обязательное'],
                                    ['searchable', 'Поиск'],
                                    ['indexed', 'Индекс'],
                                    ['reportable', 'Отчёты'],
                                    ['sensitive', 'Sensitive / шифровать'],
                                    [
                                      'immutable_after_set',
                                      'Неизменяемое после заполнения',
                                    ],
                                  ] as const
                                ).map(([flag, label]) => (
                                  <label key={flag}>
                                    <input
                                      type="checkbox"
                                      checked={Boolean(field[flag])}
                                      disabled={
                                        !selectedEditable ||
                                        !can('custom_fields.design')
                                      }
                                      onChange={(event) =>
                                        updateField(index, (current) => {
                                          const next = {
                                            ...current,
                                            [flag]: event.target.checked,
                                          }
                                          if (
                                            flag === 'sensitive' &&
                                            event.target.checked
                                          ) {
                                            next.searchable = false
                                            next.indexed = false
                                          }
                                          return next
                                        })
                                      }
                                    />
                                    <span>{label}</span>
                                  </label>
                                ))}
                              </div>

                              <details className="custom-field-visibility">
                                <summary>Условная видимость</summary>
                                <div>
                                  <label>
                                    <span>Управляющее поле</span>
                                    <select
                                      value={
                                        field.visibility?.field_key ?? ''
                                      }
                                      disabled={
                                        !selectedEditable ||
                                        !can('custom_fields.design')
                                      }
                                      onChange={(event) =>
                                        updateField(index, (current) => {
                                          if (!event.target.value) {
                                            const {
                                              visibility: _removed,
                                              ...withoutVisibility
                                            } = current
                                            return withoutVisibility as CustomFieldDefinition
                                          }
                                          return {
                                            ...current,
                                            visibility: {
                                              field_key: event.target.value,
                                              operator: 'eq',
                                              value: '',
                                            },
                                          }
                                        })
                                      }
                                    >
                                      <option value="">
                                        Всегда показывать
                                      </option>
                                      {schema.fields
                                        .slice(0, index)
                                        .map((candidate) => (
                                          <option
                                            key={candidate.key}
                                            value={candidate.key}
                                          >
                                            {candidate.label}
                                          </option>
                                        ))}
                                    </select>
                                  </label>
                                  {field.visibility ? (
                                    <>
                                      <label>
                                        <span>Оператор</span>
                                        <select
                                          value={field.visibility.operator}
                                          disabled={
                                            !selectedEditable ||
                                            !can('custom_fields.design')
                                          }
                                          onChange={(event) =>
                                            updateField(index, (current) => ({
                                              ...current,
                                              visibility: {
                                                ...current.visibility!,
                                                operator: event.target.value as
                                                  | 'eq'
                                                  | 'neq'
                                                  | 'in'
                                                  | 'truthy'
                                                  | 'falsy',
                                              },
                                            }))
                                          }
                                        >
                                          <option value="eq">равно</option>
                                          <option value="neq">не равно</option>
                                          <option value="in">одно из</option>
                                          <option value="truthy">
                                            заполнено / true
                                          </option>
                                          <option value="falsy">
                                            пусто / false
                                          </option>
                                        </select>
                                      </label>
                                      {!['truthy', 'falsy'].includes(
                                        field.visibility.operator,
                                      ) ? (
                                        <label>
                                          <span>Значение</span>
                                          <input
                                            value={String(
                                              field.visibility.value ?? '',
                                            )}
                                            disabled={
                                              !selectedEditable ||
                                              !can('custom_fields.design')
                                            }
                                            onChange={(event) =>
                                              updateField(
                                                index,
                                                (current) => ({
                                                  ...current,
                                                  visibility: {
                                                    ...current.visibility!,
                                                    value:
                                                      current.visibility
                                                        ?.operator === 'in'
                                                        ? event.target.value
                                                            .split(',')
                                                            .map((item) =>
                                                              item.trim(),
                                                            )
                                                            .filter(Boolean)
                                                        : event.target.value,
                                                  },
                                                }),
                                              )
                                            }
                                          />
                                        </label>
                                      ) : null}
                                    </>
                                  ) : null}
                                </div>
                              </details>
                            </article>
                          ))}
                          {schema.fields.length === 0 ? (
                            <div className="empty-state">
                              В схеме пока нет полей. Добавьте первое поле кнопкой
                              ниже.
                            </div>
                          ) : null}
                        </div>

                        {selectedEditable &&
                        can('custom_fields.design') ? (
                          <button
                            type="button"
                            className="custom-field-add"
                            onClick={() =>
                              mutateSchema((current) => {
                                current.fields.push(
                                  emptyField(current.fields.length, translate),
                                )
                                return current
                              })
                            }
                          >
                            + Добавить поле
                          </button>
                        ) : null}
                      </div>
                    )}

                    <footer className="custom-fields-editor-footer">
                      <label>
                        <span>Описание изменения</span>
                        <input
                          value={changeSummary}
                          onChange={(event) =>
                            setChangeSummary(event.target.value)
                          }
                        />
                      </label>
                      <div>
                        {selectedEditable &&
                        can('custom_fields.design') ? (
                          <button
                            type="button"
                            className="secondary-button"
                            disabled={
                              busy !== '' ||
                              changeSummary.trim().length < 3
                            }
                            onClick={() => void saveDraft()}
                          >
                            {busy === 'save-draft'
                              ? 'Сохраняем…'
                              : 'Проверить и сохранить'}
                          </button>
                        ) : null}
                        {selectedEditable &&
                        can('custom_fields.publish') ? (
                          <>
                            <label className="custom-fields-breaking">
                              <input
                                type="checkbox"
                                checked={allowBreaking}
                                onChange={(event) =>
                                  setAllowBreaking(event.target.checked)
                                }
                              />
                              <span>Разрешить breaking change</span>
                            </label>
                            <button
                              type="button"
                              className="primary-button"
                              disabled={
                                busy !== '' ||
                                dirty ||
                                !selectedVersion.validation.valid ||
                                changeSummary.trim().length < 3
                              }
                              onClick={() => void publishDraft()}
                            >
                              {busy === 'publish'
                                ? 'Публикуем…'
                                : 'Опубликовать версию'}
                            </button>
                          </>
                        ) : null}
                      </div>
                    </footer>
                  </>
                )}
              </section>
            </div>
          )
        ) : null}

        {view === 'record-test' ? (
          <section className="custom-fields-record-test">
            <header>
              <div>
                <p className="eyebrow">SAFE RECORD TEST</p>
                <h3>Проверка на существующей записи</h3>
                <p>
                  Платформа загрузит только активные и применимые наборы, а
                  запись пройдёт серверную проверку типов и версий.
                </p>
              </div>
              <div className="custom-fields-test-controls">
                <select
                  value={testEntityType}
                  onChange={(event) => {
                    setTestEntityType(
                      event.target.value as CustomFieldEntityType,
                    )
                    setLoadedEntityId('')
                  }}
                >
                  {Object.entries(entityLabels).map(([value, label]) => (
                    <option key={value} value={value}>
                      {translate(label)}
                    </option>
                  ))}
                </select>
                <input
                  value={testEntityId}
                  onChange={(event) => setTestEntityId(event.target.value)}
                  placeholder="UUID записи"
                />
                <button
                  type="button"
                  className="primary-button"
                  disabled={!testEntityId.trim()}
                  onClick={() => setLoadedEntityId(testEntityId.trim())}
                >
                  Загрузить поля
                </button>
              </div>
            </header>
            {entityFieldSetsQuery.isError ? (
              <div className="error-state">
                {errorText(entityFieldSetsQuery.error)}
              </div>
            ) : null}
            {(entityFieldSetsQuery.data ?? []).map((entry) => (
              <article
                className="custom-fields-value-card"
                key={entry.field_set.id}
              >
                <header>
                  <div>
                    <h4>{entry.field_set.name}</h4>
                    <p>
                      {entry.field_set.code} · schema v
                      {entry.published_version.version_number}
                    </p>
                  </div>
                  <span
                    className={
                      entry.value_schema_current
                        ? 'badge badge-positive'
                        : 'badge badge-warning'
                    }
                  >
                    {entry.value_schema_current
                      ? 'CURRENT SCHEMA'
                      : 'MIGRATION ON SAVE'}
                  </span>
                </header>
                <textarea
                  value={valueEditors[entry.field_set.id] ?? '{}'}
                  readOnly={!can('custom_fields.values.write')}
                  spellCheck={false}
                  onChange={(event) =>
                    setValueEditors((current) => ({
                      ...current,
                      [entry.field_set.id]: event.target.value,
                    }))
                  }
                />
                {can('custom_fields.values.write') ? (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={busy !== ''}
                    onClick={() =>
                      void runAction(
                        `value-${entry.field_set.id}`,
                        () =>
                          saveEntityCustomFieldValues(
                            token,
                            entry.field_set.id,
                            loadedEntityId,
                            parseObject(
                              valueEditors[entry.field_set.id] ?? '{}',
                              translate('Значения'),
                              translate,
                            ),
                            entry.value_record?.version ?? null,
                          ),
                        'Значения проверены и сохранены',
                      )
                    }
                  >
                    {busy === `value-${entry.field_set.id}`
                      ? 'Сохраняем…'
                      : 'Проверить и сохранить'}
                  </button>
                ) : null}
              </article>
            ))}
            {loadedEntityId &&
            !entityFieldSetsQuery.isLoading &&
            (entityFieldSetsQuery.data ?? []).length === 0 &&
            !entityFieldSetsQuery.isError ? (
              <div className="empty-state">
                Для этой записи нет активных применимых наборов полей.
              </div>
            ) : null}
          </section>
        ) : null}

        {view === 'search' ? (
          <section className="custom-fields-search-panel">
            <header>
              <div>
                <p className="eyebrow">CONTROLLED SEARCH</p>
                <h3>Поиск по разрешённым полям</h3>
                <p>
                  В индекс попадают только поля с флагом Searchable.
                  Чувствительные поля никогда не индексируются.
                </p>
              </div>
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  setSubmittedSearch(searchTerm.trim())
                }}
              >
                <input
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                  placeholder="Минимум 2 символа"
                  minLength={2}
                />
                <button type="submit" className="primary-button">
                  Найти
                </button>
              </form>
            </header>
            <div className="custom-fields-search-results">
              {(searchQuery.data ?? []).map((result) => (
                <article key={result.value_record.id}>
                  <header>
                    <div>
                      <h4>{result.field_set.name}</h4>
                      <p>
                        {translate(entityLabels[result.field_set.entity_type])} ·{' '}
                        {result.value_record.entity_id}
                      </p>
                    </div>
                    <span className="badge badge-positive">
                      v{result.value_record.field_set_version_number}
                    </span>
                  </header>
                  <pre>
                    {JSON.stringify(result.value_record.values, null, 2)}
                  </pre>
                </article>
              ))}
              {submittedSearch &&
              !searchQuery.isLoading &&
              (searchQuery.data ?? []).length === 0 ? (
                <div className="empty-state">Совпадений не найдено.</div>
              ) : null}
            </div>
          </section>
        ) : null}
      </section>
    </AppShell>
    </LocalizedContent>
  )
}
