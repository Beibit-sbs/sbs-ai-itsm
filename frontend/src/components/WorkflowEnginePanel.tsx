import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  cancelWorkflowExecution,
  compareWorkflowVersions,
  createProductionWorkflow,
  createWorkflowDraft,
  decideWorkflowApproval,
  decideWorkflowReview,
  fetchProductionWorkflows,
  fetchWorkflowApprovals,
  fetchWorkflowCatalog,
  fetchWorkflowDashboard,
  fetchWorkflowExecution,
  fetchWorkflowExecutions,
  fetchWorkflowReviews,
  fetchWorkflowVersion,
  fetchWorkflowVersions,
  publishWorkflowVersion,
  requestWorkflowReview,
  replayWorkflowExecution,
  rollbackWorkflowVersion,
  saveWorkflowDraft,
  simulateWorkflowVersion,
  startProductionWorkflow,
  updateProductionWorkflow,
  validateWorkflowVersion,
  type ProductionWorkflow,
  type WorkflowDefinitionDocument,
  type WorkflowVersion,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { useLocalizedDefaultState } from '../experience/useLocalizedDefaultState'
import WorkflowVisualDesigner from './WorkflowVisualDesigner'
import QueryFailureNotice from './QueryFailureNotice'

type ViewKey = 'designer' | 'executions' | 'approvals' | 'reviews'
type EditorMode = 'visual' | 'json' | 'diff'

const initialContext = JSON.stringify(
  {
    entity_type: 'ticket',
    entity_id: 'preview-ticket',
    ticket: {
      id: 'preview-ticket',
      priority: 'high',
      status: 'open',
    },
  },
  null,
  2,
)

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

function parseObject(value: string, label: string, invalidTypeMessage: string) {
  const parsed = JSON.parse(value) as unknown
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
    throw new Error(`${label} ${invalidTypeMessage}`)
  }
  return parsed as Record<string, unknown>
}

export default function WorkflowEnginePanel() {
  const { session } = useAuth()
  const { translate, formatDateTime } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [view, setView] = useState<ViewKey>('designer')
  const [editorMode, setEditorMode] = useState<EditorMode>('visual')
  const [selectedWorkflowId, setSelectedWorkflowId] = useState('')
  const [selectedVersionNumber, setSelectedVersionNumber] = useState<number | null>(null)
  const [selectedExecutionId, setSelectedExecutionId] = useState('')
  const [editor, setEditor] = useState('')
  const [editorDirty, setEditorDirty] = useState(false)
  const [contextEditor, setContextEditor] = useState(initialContext)
  const [changeSummary, setChangeSummary] = useLocalizedDefaultState('Изменение workflow через конструктор')
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState({
    code: '',
    name: '',
    description: '',
    trigger_type: 'ticket_created',
    concurrency_policy: 'ALLOW' as 'ALLOW' | 'SERIALIZE',
    max_active_executions: 100,
    publish_approval_required: false,
  })

  const effectiveTenantId = tenantId || null
  const scopeReady = Boolean(token && (!isRoot || effectiveTenantId))
  const permissions = new Set(session?.user.permissions ?? [])
  const can = (permission: string) =>
    session?.user.role === 'saas_root' || permissions.has(permission)

  const dashboardQuery = useQuery({
    queryKey: ['workflow-dashboard', token, effectiveTenantId],
    queryFn: () => fetchWorkflowDashboard(token, effectiveTenantId),
    enabled: scopeReady && can('workflows.read'),
  })
  const catalogQuery = useQuery({
    queryKey: ['workflow-catalog', token],
    queryFn: () => fetchWorkflowCatalog(token),
    enabled: Boolean(token) && can('workflows.read'),
    staleTime: 300_000,
  })
  const workflowsQuery = useQuery({
    queryKey: ['production-workflows', token, effectiveTenantId],
    queryFn: () => fetchProductionWorkflows(token, effectiveTenantId),
    enabled: scopeReady && can('workflows.read'),
  })

  const workflows = workflowsQuery.data ?? []
  const selectedWorkflow = useMemo(
    () => workflows.find((item) => item.id === selectedWorkflowId) ?? null,
    [selectedWorkflowId, workflows],
  )

  const versionsQuery = useQuery({
    queryKey: ['workflow-versions', token, selectedWorkflowId],
    queryFn: () => fetchWorkflowVersions(token, selectedWorkflowId),
    enabled: Boolean(token && selectedWorkflowId),
    refetchInterval: 15_000,
  })
  const selectedVersionQuery = useQuery({
    queryKey: [
      'workflow-version',
      token,
      selectedWorkflowId,
      selectedVersionNumber,
    ],
    queryFn: () =>
      fetchWorkflowVersion(token, selectedWorkflowId, selectedVersionNumber ?? 0),
    enabled: Boolean(token && selectedWorkflowId && selectedVersionNumber),
    refetchInterval: 15_000,
  })
  const executionsQuery = useQuery({
    queryKey: ['workflow-executions', token, effectiveTenantId, selectedWorkflowId],
    queryFn: () =>
      fetchWorkflowExecutions(
        token,
        effectiveTenantId,
        selectedWorkflowId || null,
      ),
    enabled:
      scopeReady &&
      can('workflows.executions.read') &&
      view === 'executions',
    refetchInterval: 10_000,
  })
  const executionQuery = useQuery({
    queryKey: ['workflow-execution', token, selectedExecutionId],
    queryFn: () => fetchWorkflowExecution(token, selectedExecutionId),
    enabled: Boolean(token && selectedExecutionId && view === 'executions'),
    refetchInterval: 5_000,
  })
  const approvalsQuery = useQuery({
    queryKey: ['workflow-approvals', token, effectiveTenantId],
    queryFn: () => fetchWorkflowApprovals(token, effectiveTenantId),
    enabled:
      scopeReady &&
      can('workflows.approvals.read') &&
      view === 'approvals',
    refetchInterval: 10_000,
  })
  const reviewsQuery = useQuery({
    queryKey: ['workflow-reviews', token, effectiveTenantId],
    queryFn: () => fetchWorkflowReviews(token, effectiveTenantId),
    enabled:
      scopeReady &&
      can('workflows.reviews.read') &&
      view === 'reviews',
    refetchInterval: 10_000,
  })

  const diffFromVersion =
    selectedWorkflow?.published_version_number &&
    selectedWorkflow.published_version_number !== selectedVersionNumber
      ? selectedWorkflow.published_version_number
      : (versionsQuery.data ?? []).find(
          (version) => version.version_number !== selectedVersionNumber,
        )?.version_number ?? null
  const diffQuery = useQuery({
    queryKey: [
      'workflow-version-diff',
      token,
      selectedWorkflowId,
      diffFromVersion,
      selectedVersionNumber,
    ],
    queryFn: () =>
      compareWorkflowVersions(
        token,
        selectedWorkflowId,
        diffFromVersion ?? 0,
        selectedVersionNumber ?? 0,
      ),
    enabled: Boolean(
      token &&
        selectedWorkflowId &&
        diffFromVersion &&
        selectedVersionNumber &&
        editorMode === 'diff',
    ),
  })

  useEffect(() => {
    if (!selectedWorkflowId && workflows.length) {
      setSelectedWorkflowId(workflows[0].id)
    }
    if (
      selectedWorkflowId &&
      workflows.length &&
      !workflows.some((item) => item.id === selectedWorkflowId)
    ) {
      setSelectedWorkflowId(workflows[0].id)
    }
  }, [selectedWorkflowId, workflows])

  useEffect(() => {
    if (!selectedWorkflow) {
      setSelectedVersionNumber(null)
      return
    }
    setSelectedVersionNumber(
      selectedWorkflow.draft_version_number ??
        selectedWorkflow.published_version_number ??
        selectedWorkflow.latest_version_number,
    )
  }, [selectedWorkflow])

  useEffect(() => {
    const definition = selectedVersionQuery.data?.definition
    if (definition && !editorDirty) {
      setEditor(JSON.stringify(definition, null, 2))
    }
  }, [editorDirty, selectedVersionQuery.data])

  useEffect(() => {
    setEditorDirty(false)
  }, [selectedVersionNumber, selectedWorkflowId])

  const refreshAll = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['workflow-dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['production-workflows'] }),
      queryClient.invalidateQueries({ queryKey: ['workflow-versions'] }),
      queryClient.invalidateQueries({ queryKey: ['workflow-version'] }),
      queryClient.invalidateQueries({ queryKey: ['workflow-executions'] }),
      queryClient.invalidateQueries({ queryKey: ['workflow-approvals'] }),
      queryClient.invalidateQueries({ queryKey: ['workflow-reviews'] }),
      queryClient.invalidateQueries({ queryKey: ['workflow-version-diff'] }),
    ])
  }

  const success = async (text: string) => {
    setError('')
    setMessage(text)
    await refreshAll()
  }
  const failure = (reason: unknown) => {
    setMessage('')
    setError(errorText(reason))
  }

  const createMutation = useMutation({
    mutationFn: () =>
      createProductionWorkflow(token, {
        tenant_id: effectiveTenantId,
        ...createForm,
      }),
    onSuccess: async (data) => {
      setSelectedWorkflowId(data.workflow.id)
      setCreateOpen(false)
      setCreateForm({
        code: '',
        name: '',
        description: '',
        trigger_type: 'ticket_created',
        concurrency_policy: 'ALLOW',
      max_active_executions: 100,
      publish_approval_required: false,
      })
      await success('Workflow создан. Откройте draft и настройте шаги.')
    },
    onError: failure,
  })

  const createDraftMutation = useMutation({
    mutationFn: (workflow: ProductionWorkflow) =>
      createWorkflowDraft(token, workflow, changeSummary),
    onSuccess: async (draft) => {
      setSelectedVersionNumber(draft.version_number)
      await success(`${translate('Создан draft v')}${draft.version_number}.`)
    },
    onError: failure,
  })

  const saveMutation = useMutation({
    mutationFn: ({
      workflow,
      version,
    }: {
      workflow: ProductionWorkflow
      version: WorkflowVersion
    }) =>
      saveWorkflowDraft(
        token,
        workflow.id,
        version,
        parseObject(
          editor,
          'Definition',
          translate('должен быть JSON-объектом'),
        ) as WorkflowDefinitionDocument,
        changeSummary,
      ),
    onSuccess: async (version) => {
      setEditorDirty(false)
      if (version.definition) {
        setEditor(JSON.stringify(version.definition, null, 2))
      }
      setResult(version.validation as unknown as Record<string, unknown>)
      await success(
        version.validation_status === 'VALID'
          ? `Draft v${version.version_number} ${translate('сохранён и валиден.')}`
          : `Draft v${version.version_number} ${translate('сохранён, но требует исправлений.')}`,
      )
    },
    onError: failure,
  })

  const validateMutation = useMutation({
    mutationFn: ({
      workflowId,
      versionNumber,
    }: {
      workflowId: string
      versionNumber: number
    }) => validateWorkflowVersion(token, workflowId, versionNumber),
    onSuccess: (validation) => {
      setError('')
      setMessage(validation.valid ? 'Версия прошла валидацию.' : 'Есть ошибки валидации.')
      setResult(validation as unknown as Record<string, unknown>)
    },
    onError: failure,
  })

  const simulateMutation = useMutation({
    mutationFn: ({
      workflowId,
      versionNumber,
    }: {
      workflowId: string
      versionNumber: number
    }) =>
      simulateWorkflowVersion(
        token,
        workflowId,
        versionNumber,
        parseObject(
          contextEditor,
          translate('Контекст'),
          translate('должен быть JSON-объектом'),
        ),
      ),
    onSuccess: (simulation) => {
      setError('')
      setMessage('Dry-run завершён без изменения данных.')
      setResult(simulation)
    },
    onError: failure,
  })

  const publishMutation = useMutation({
    mutationFn: ({
      workflow,
      version,
    }: {
      workflow: ProductionWorkflow
      version: WorkflowVersion
    }) => publishWorkflowVersion(token, workflow, version, changeSummary),
    onSuccess: async (data) => {
      setSelectedVersionNumber(data.version.version_number)
      await success(
        `${translate('Версия v')}${data.version.version_number} ${translate('опубликована и активна.')}`,
      )
    },
    onError: failure,
  })

  const requestReviewMutation = useMutation({
    mutationFn: ({
      workflow,
      version,
    }: {
      workflow: ProductionWorkflow
      version: WorkflowVersion
    }) =>
      requestWorkflowReview(
        token,
        workflow.id,
        version,
        changeSummary,
      ),
    onSuccess: async (version) =>
      success(`Draft v${version.version_number} ${translate('отправлен на four-eyes review.')}`),
    onError: failure,
  })

  const stateMutation = useMutation({
    mutationFn: ({
      workflow,
      nextStatus,
    }: {
      workflow: ProductionWorkflow
      nextStatus: 'ACTIVE' | 'PAUSED' | 'ARCHIVED'
    }) =>
      updateProductionWorkflow(token, workflow.id, {
        expected_revision: workflow.revision,
        status: nextStatus,
        reason: `Статус изменён в панели управления на ${nextStatus}`,
      }),
    onSuccess: async (workflow) =>
      success(`${translate('Workflow переведён в статус')} ${workflow.status}.`),
    onError: failure,
  })

  const governanceMutation = useMutation({
    mutationFn: (workflow: ProductionWorkflow) =>
      updateProductionWorkflow(token, workflow.id, {
        expected_revision: workflow.revision,
        publish_approval_required: !workflow.publish_approval_required,
        reason: workflow.publish_approval_required
          ? 'Отключён обязательный four-eyes review'
          : 'Включён обязательный four-eyes review',
      }),
    onSuccess: async (workflow) =>
      success(
        workflow.publish_approval_required
          ? 'Four-eyes review включён.'
          : 'Four-eyes review отключён.',
      ),
    onError: failure,
  })

  const rollbackMutation = useMutation({
    mutationFn: ({
      workflow,
      target,
    }: {
      workflow: ProductionWorkflow
      target: WorkflowVersion
    }) =>
      rollbackWorkflowVersion(
        token,
        workflow,
        target.version_number,
        `Rollback через панель: ${changeSummary}`,
      ),
    onSuccess: async (data) => {
      setSelectedVersionNumber(data.version.version_number)
      await success(
        `${translate('Выполнен rollback: опубликована новая версия v')}${data.version.version_number}.`,
      )
    },
    onError: failure,
  })

  const startMutation = useMutation({
    mutationFn: (workflow: ProductionWorkflow) =>
      startProductionWorkflow(token, workflow.id, {
        context: parseObject(
          contextEditor,
          translate('Контекст'),
          translate('должен быть JSON-объектом'),
        ),
        idempotency_key: `ui:${workflow.id}:${crypto.randomUUID()}`,
        correlation_id: `ui-${crypto.randomUUID()}`,
      }),
    onSuccess: async (data) => {
      setSelectedExecutionId(data.execution.id)
      setView('executions')
      await success(
        data.deduplicated
          ? 'Повторный запрос безопасно дедуплицирован.'
          : 'Исполнение поставлено в очередь.',
      )
    },
    onError: failure,
  })

  const executionActionMutation = useMutation({
    mutationFn: ({
      executionId,
      action,
    }: {
      executionId: string
      action: 'cancel' | 'replay'
    }) =>
      action === 'cancel'
        ? cancelWorkflowExecution(
            token,
            executionId,
            'Отменено оператором через панель workflow',
          )
        : replayWorkflowExecution(
            token,
            executionId,
            'Повторный запуск оператором через панель workflow',
          ),
    onSuccess: async (execution) => {
      setSelectedExecutionId(execution.id)
      await success(`${translate('Операция выполнена. Статус:')} ${execution.status}.`)
    },
    onError: failure,
  })

  const approvalMutation = useMutation({
    mutationFn: ({
      approvalId,
      decision,
    }: {
      approvalId: string
      decision: 'APPROVED' | 'REJECTED'
    }) => {
      const approval = approvalsQuery.data?.find((item) => item.id === approvalId)
      if (!approval) throw new Error('Approval уже изменён или недоступен')
      return decideWorkflowApproval(
        token,
        approval,
        decision,
        decision === 'APPROVED'
          ? 'Согласовано через панель workflow'
          : 'Отклонено через панель workflow',
      )
    },
    onSuccess: async (approval) =>
      success(`${translate('Решение сохранено:')} ${approval.status}.`),
    onError: failure,
  })

  const reviewMutation = useMutation({
    mutationFn: ({
      reviewId,
      decision,
    }: {
      reviewId: string
      decision: 'APPROVED' | 'REJECTED'
    }) => {
      const review = reviewsQuery.data?.find((item) => item.id === reviewId)
      if (!review) throw new Error('Review уже изменён или недоступен')
      return decideWorkflowReview(
        token,
        review,
        decision,
        decision === 'APPROVED'
          ? 'Workflow проверен и согласован'
          : 'Workflow возвращён автору на доработку',
      )
    },
    onSuccess: async (review) =>
      success(`Review v${review.version_number}: ${review.review_status}.`),
    onError: failure,
  })

  const currentVersion = selectedVersionQuery.data ?? null
  const isDraft = currentVersion?.status === 'DRAFT'
  const editorDefinition = useMemo(() => {
    try {
      return parseObject(
        editor,
        'Definition',
        translate('должен быть JSON-объектом'),
      ) as WorkflowDefinitionDocument
    } catch {
      return null
    }
  }, [editor, translate])
  const busy =
    createMutation.isPending ||
    createDraftMutation.isPending ||
    saveMutation.isPending ||
    publishMutation.isPending ||
    rollbackMutation.isPending ||
    stateMutation.isPending ||
    governanceMutation.isPending ||
    requestReviewMutation.isPending

  if (!can('workflows.read')) {
    return (
      <LocalizedContent>
        <section className="section-card">
          <p className="state-panel state-panel-empty">
            Для production workflow engine требуется право <code>workflows.read</code>.
          </p>
        </section>
      </LocalizedContent>
    )
  }

  return (
    <LocalizedContent>
      <section className="workflow-engine">
      <header className="workflow-hero">
        <div>
          <p className="eyebrow">PRODUCTION WORKFLOW ENGINE</p>
          <h2>Оркестрация ITSM-процессов</h2>
          <p>
            Версии, approvals, timers, retry, compensation и полный журнал
            исполнения. Старые Rules остаются доступными в соседних вкладках.
          </p>
        </div>
        <div className="workflow-hero-actions">
          {isRoot ? (
            <label>
              <span>Tenant ID</span>
              <input
                value={tenantId}
                onChange={(event) => setTenantId(event.target.value.trim())}
                placeholder="Выберите tenant"
              />
            </label>
          ) : null}
          {can('workflows.design') ? (
            <button type="button" onClick={() => setCreateOpen((value) => !value)}>
              {createOpen ? 'Закрыть форму' : 'Создать workflow'}
            </button>
          ) : null}
        </div>
      </header>

      {!scopeReady ? (
        <p className="state-panel state-panel-empty">
          Укажите tenant ID, чтобы открыть контур workflow.
        </p>
      ) : null}
      {message ? <p className="success-state">{message}</p> : null}
      <QueryFailureNotice
        title="Часть данных Workflow Engine недоступна."
        sources={[
          { label: 'оперативная сводка', query: dashboardQuery },
          { label: 'каталог workflow', query: catalogQuery },
          { label: 'workflows', query: workflowsQuery },
          { label: 'версии', query: versionsQuery },
          { label: 'выбранная версия', query: selectedVersionQuery },
          { label: 'executions', query: executionsQuery },
          { label: 'выбранное execution', query: executionQuery },
          { label: 'approvals', query: approvalsQuery },
          { label: 'reviews', query: reviewsQuery },
          { label: 'version diff', query: diffQuery },
        ]}
      />
      {error ? <p className="error-state" role="alert">{error}</p> : null}

      {createOpen ? (
        <form
          className="workflow-create-form"
          onSubmit={(event) => {
            event.preventDefault()
            createMutation.mutate()
          }}
        >
          <label>
            <span>Код</span>
            <input
              required
              minLength={2}
              value={createForm.code}
              onChange={(event) =>
                setCreateForm({ ...createForm, code: event.target.value })
              }
              placeholder="critical_incident_flow"
            />
          </label>
          <label>
            <span>Название</span>
            <input
              required
              minLength={2}
              value={createForm.name}
              onChange={(event) =>
                setCreateForm({ ...createForm, name: event.target.value })
              }
              placeholder="Критический инцидент"
            />
          </label>
          <label>
            <span>Trigger</span>
            <input
              required
              value={createForm.trigger_type}
              onChange={(event) =>
                setCreateForm({
                  ...createForm,
                  trigger_type: event.target.value,
                })
              }
              list="workflow-trigger-catalog"
            />
            <datalist id="workflow-trigger-catalog">
              {(catalogQuery.data?.triggers ?? []).map((trigger) => (
                <option
                  key={String(trigger.code ?? trigger.type)}
                  value={String(trigger.code ?? trigger.type)}
                />
              ))}
            </datalist>
          </label>
          <label>
            <span>Concurrency</span>
            <select
              value={createForm.concurrency_policy}
              onChange={(event) =>
                setCreateForm({
                  ...createForm,
                  concurrency_policy: event.target.value as 'ALLOW' | 'SERIALIZE',
                })
              }
            >
              <option value="ALLOW">Параллельно</option>
              <option value="SERIALIZE">Последовательно</option>
            </select>
          </label>
          <label className="workflow-checkbox">
            <input
              type="checkbox"
              checked={createForm.publish_approval_required}
              onChange={(event) =>
                setCreateForm({
                  ...createForm,
                  publish_approval_required: event.target.checked,
                })
              }
            />
            <span>Требовать four-eyes review перед publish</span>
          </label>
          <label className="workflow-form-wide">
            <span>Описание</span>
            <input
              value={createForm.description}
              onChange={(event) =>
                setCreateForm({
                  ...createForm,
                  description: event.target.value,
                })
              }
            />
          </label>
          <button type="submit" disabled={createMutation.isPending || !scopeReady}>
            {createMutation.isPending ? 'Создание…' : 'Создать draft'}
          </button>
        </form>
      ) : null}

      <section className="workflow-metrics">
        <article>
          <span>Workflow</span>
          <strong>{dashboardQuery.data?.workflows.total ?? 0}</strong>
          <small>Активных: {dashboardQuery.data?.workflows.by_status.ACTIVE ?? 0}</small>
        </article>
        <article>
          <span>Исполнения</span>
          <strong>{dashboardQuery.data?.executions.total ?? 0}</strong>
          <small>
            Ошибки:{' '}
            {(dashboardQuery.data?.executions.by_status.FAILED ?? 0) +
              (dashboardQuery.data?.executions.by_status.DEAD_LETTER ?? 0)}
          </small>
        </article>
        <article>
          <span>Ожидают решения</span>
          <strong>{dashboardQuery.data?.pending_approvals ?? 0}</strong>
          <small>Approval tasks</small>
        </article>
        <article>
          <span>Schema</span>
          <strong>{catalogQuery.data?.schema_version ?? '—'}</strong>
          <small>{catalogQuery.data?.actions.length ?? 0} безопасных actions</small>
        </article>
      </section>

      <nav className="workflow-view-tabs" aria-label="Production workflow sections">
        {(
          [
            ['designer', 'Конструктор'],
            ['executions', 'Исполнения'],
            ['approvals', 'Согласования'],
            ['reviews', 'Review публикации'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            className={view === key ? 'active' : ''}
            onClick={() => setView(key)}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="workflow-selector">
        <label>
          <span>Workflow</span>
          <select
            value={selectedWorkflowId}
            onChange={(event) => setSelectedWorkflowId(event.target.value)}
          >
            <option value="">Выберите workflow</option>
            {workflows.map((workflow) => (
              <option key={workflow.id} value={workflow.id}>
                {workflow.name} · {workflow.status}
              </option>
            ))}
          </select>
        </label>
        {selectedWorkflow ? (
          <div className="workflow-status-actions">
            <span className={`workflow-status status-${selectedWorkflow.status.toLowerCase()}`}>
              {selectedWorkflow.status}
            </span>
            {selectedWorkflow.status !== 'ARCHIVED' && can('workflows.design') ? (
              <button
                type="button"
                className="ghost-button"
                disabled={stateMutation.isPending}
                onClick={() =>
                  stateMutation.mutate({
                    workflow: selectedWorkflow,
                    nextStatus:
                      selectedWorkflow.status === 'ACTIVE' ? 'PAUSED' : 'ACTIVE',
                  })
                }
              >
                {selectedWorkflow.status === 'ACTIVE' ? 'Пауза' : 'Активировать'}
              </button>
            ) : null}
            {selectedWorkflow.status !== 'ARCHIVED' && can('workflows.design') ? (
              <button
                type="button"
                className={
                  selectedWorkflow.publish_approval_required
                    ? 'workflow-governance-enabled'
                    : 'ghost-button'
                }
                disabled={governanceMutation.isPending}
                onClick={() => {
                  if (
                    window.confirm(
                      selectedWorkflow.publish_approval_required
                        ? translate('Отключить обязательный review перед публикацией?')
                        : translate('Включить обязательный four-eyes review?'),
                    )
                  ) {
                    governanceMutation.mutate(selectedWorkflow)
                  }
                }}
              >
                Four-eyes {selectedWorkflow.publish_approval_required ? 'ON' : 'OFF'}
              </button>
            ) : null}
          </div>
        ) : null}
      </div>

      {view === 'designer' ? (
        selectedWorkflow ? (
          <div className="workflow-designer-grid">
            <aside className="workflow-version-panel">
              <header>
                <div>
                  <p className="eyebrow">VERSION HISTORY</p>
                  <h3>{selectedWorkflow.name}</h3>
                </div>
                {!selectedWorkflow.draft_version_number &&
                selectedWorkflow.status !== 'ARCHIVED' &&
                can('workflows.design') ? (
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={createDraftMutation.isPending}
                    onClick={() => createDraftMutation.mutate(selectedWorkflow)}
                  >
                    Новый draft
                  </button>
                ) : null}
              </header>
              <p>{selectedWorkflow.description || 'Описание не задано.'}</p>
              <dl className="workflow-definition-meta">
                <div><dt>Код</dt><dd>{selectedWorkflow.code}</dd></div>
                <div><dt>Trigger</dt><dd>{selectedWorkflow.trigger_type}</dd></div>
                <div><dt>Concurrency</dt><dd>{selectedWorkflow.concurrency_policy}</dd></div>
                <div><dt>Запусков</dt><dd>{selectedWorkflow.total_executions}</dd></div>
              </dl>
              <div className="workflow-version-list">
                {(versionsQuery.data ?? []).map((version) => (
                  <article
                    key={version.id}
                    className={
                      selectedVersionNumber === version.version_number
                        ? 'selected'
                        : ''
                    }
                  >
                    <button
                      type="button"
                      onClick={() => setSelectedVersionNumber(version.version_number)}
                    >
                      <strong>v{version.version_number}</strong>
                      <span>{version.status}</span>
                      <small>{version.change_summary || 'Без комментария'}</small>
                      <small>Review: {version.review_status}</small>
                      <small>{formatDateTime(version.published_at ?? version.updated_at)}</small>
                    </button>
                    {version.status === 'RETIRED' &&
                    can('workflows.publish') &&
                    !selectedWorkflow.draft_version_number ? (
                      <button
                        type="button"
                        className="workflow-rollback"
                        disabled={rollbackMutation.isPending}
                        onClick={() => {
                          if (
                            window.confirm(
                              `${translate('Опубликовать содержимое v')}${version.version_number} ${translate('как новую версию?')}`,
                            )
                          ) {
                            rollbackMutation.mutate({
                              workflow: selectedWorkflow,
                              target: version,
                            })
                          }
                        }}
                      >
                        Rollback
                      </button>
                    ) : null}
                  </article>
                ))}
              </div>
            </aside>

            <div className="workflow-editor-panel">
              <header className="workflow-editor-header">
                <div>
                  <p className="eyebrow">DEFINITION</p>
                  <h3>
                    {currentVersion
                      ? <>{translate('Версия')} {currentVersion.version_number} · {currentVersion.status}</>
                      : 'Загрузка версии…'}
                  </h3>
                </div>
                <span
                  className={`workflow-validation validation-${(
                    currentVersion?.integrity_valid === false
                      ? 'invalid'
                      : currentVersion?.validation_status ?? 'unknown'
                  ).toLowerCase()}`}
                >
                  {currentVersion?.integrity_valid === false
                    ? 'INTEGRITY ERROR'
                    : currentVersion?.validation_status ?? 'UNKNOWN'}
                </span>
                {editorDirty ? (
                  <span className="workflow-validation validation-unknown">
                    UNSAVED
                  </span>
                ) : null}
              </header>
              <label>
                <span>Комментарий / change ticket</span>
                <input
                  value={changeSummary}
                  maxLength={2_000}
                  onChange={(event) => setChangeSummary(event.target.value)}
                />
              </label>
              <nav className="workflow-editor-modes" aria-label="Режим конструктора">
                {(
                  [
                    ['visual', 'Визуально'],
                    ['json', 'JSON'],
                    ['diff', 'Diff версий'],
                  ] as const
                ).map(([mode, label]) => (
                  <button
                    key={mode}
                    type="button"
                    className={editorMode === mode ? 'active' : ''}
                    onClick={() => setEditorMode(mode)}
                  >
                    {label}
                  </button>
                ))}
              </nav>
              {editorMode === 'visual' && editorDefinition ? (
                <WorkflowVisualDesigner
                  definition={editorDefinition}
                  catalog={catalogQuery.data}
                  workflows={workflows}
                  currentWorkflowId={selectedWorkflow.id}
                  readOnly={!isDraft || !can('workflows.design')}
                  onChange={(definition) =>
                    {
                      setEditor(JSON.stringify(definition, null, 2))
                      setEditorDirty(true)
                    }
                  }
                />
              ) : null}
              {editorMode === 'visual' && !editorDefinition ? (
                <p className="error-state">
                  JSON definition повреждён. Исправьте его в режиме JSON.
                </p>
              ) : null}
              {editorMode === 'json' ? (
                <label>
                  <span>Workflow JSON</span>
                  <textarea
                    className="workflow-json-editor"
                    spellCheck={false}
                    readOnly={!isDraft || !can('workflows.design')}
                    value={editor}
                    onChange={(event) => {
                      setEditor(event.target.value)
                      setEditorDirty(true)
                    }}
                  />
                </label>
              ) : null}
              {editorMode === 'diff' ? (
                <section className="workflow-diff-panel">
                  <header>
                    <div>
                      <p className="eyebrow">STRUCTURAL DIFF</p>
                      <h3>
                        {diffFromVersion && selectedVersionNumber
                          ? `v${diffFromVersion} → v${selectedVersionNumber}`
                          : 'Нужны две версии'}
                      </h3>
                    </div>
                    {diffQuery.data ? (
                      <span>{diffQuery.data.summary.total} изменений</span>
                    ) : null}
                  </header>
                  {diffQuery.isPending ? (
                    <p className="state-panel state-panel-loading">Сравнение версий…</p>
                  ) : null}
                  {diffQuery.data ? (
                    <div className="workflow-diff-groups">
                      <article className="diff-added">
                        <h4>Добавлено · {diffQuery.data.summary.added}</h4>
                        {diffQuery.data.added.map((item) => (
                          <div key={item.path}>
                            <code>{item.path}</code>
                            <pre>{JSON.stringify(item.value, null, 2)}</pre>
                          </div>
                        ))}
                      </article>
                      <article className="diff-changed">
                        <h4>Изменено · {diffQuery.data.summary.changed}</h4>
                        {diffQuery.data.changed.map((item) => (
                          <div key={item.path}>
                            <code>{item.path}</code>
                            <pre>- {JSON.stringify(item.before)}</pre>
                            <pre>+ {JSON.stringify(item.after)}</pre>
                          </div>
                        ))}
                      </article>
                      <article className="diff-removed">
                        <h4>Удалено · {diffQuery.data.summary.removed}</h4>
                        {diffQuery.data.removed.map((item) => (
                          <div key={item.path}>
                            <code>{item.path}</code>
                            <pre>{JSON.stringify(item.value, null, 2)}</pre>
                          </div>
                        ))}
                      </article>
                    </div>
                  ) : null}
                  {!diffFromVersion ? (
                    <p className="empty-state">Создайте вторую версию для сравнения.</p>
                  ) : null}
                </section>
              ) : null}
              <div className="workflow-editor-actions">
                {isDraft && can('workflows.design') ? (
                  <button
                    type="button"
                    disabled={!currentVersion || busy}
                    onClick={() =>
                      currentVersion &&
                      saveMutation.mutate({
                        workflow: selectedWorkflow,
                        version: currentVersion,
                      })
                    }
                  >
                    Сохранить draft
                  </button>
                ) : null}
                <button
                  type="button"
                  className="ghost-button"
                  disabled={!currentVersion || validateMutation.isPending}
                  onClick={() =>
                    currentVersion &&
                    validateMutation.mutate({
                      workflowId: selectedWorkflow.id,
                      versionNumber: currentVersion.version_number,
                    })
                  }
                >
                  Проверить
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={!currentVersion || simulateMutation.isPending}
                  onClick={() =>
                    currentVersion &&
                    simulateMutation.mutate({
                      workflowId: selectedWorkflow.id,
                      versionNumber: currentVersion.version_number,
                    })
                  }
                >
                  Dry-run
                </button>
                {isDraft &&
                selectedWorkflow.publish_approval_required &&
                can('workflows.reviews.request') &&
                currentVersion?.review_status !== 'APPROVED' &&
                !currentVersion?.review_requested_at ? (
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={
                      !currentVersion ||
                      currentVersion.validation_status !== 'VALID' ||
                      requestReviewMutation.isPending
                    }
                    onClick={() =>
                      currentVersion &&
                      requestReviewMutation.mutate({
                        workflow: selectedWorkflow,
                        version: currentVersion,
                      })
                    }
                  >
                    Отправить на review
                  </button>
                ) : null}
                {isDraft &&
                selectedWorkflow.publish_approval_required &&
                currentVersion?.review_requested_at ? (
                  <span
                    className={`workflow-validation validation-${(
                      currentVersion.review_status === 'APPROVED'
                        ? 'valid'
                        : currentVersion.review_status === 'REJECTED'
                          ? 'invalid'
                          : 'unknown'
                    )}`}
                  >
                    REVIEW {currentVersion.review_status}
                  </span>
                ) : null}
                {isDraft && can('workflows.publish') ? (
                  <button
                    type="button"
                    className="primary-danger-safe"
                    disabled={
                      !currentVersion ||
                      !currentVersion.integrity_valid ||
                      currentVersion.validation_status !== 'VALID' ||
                      (selectedWorkflow.publish_approval_required &&
                        currentVersion.review_status !== 'APPROVED') ||
                      publishMutation.isPending
                    }
                    onClick={() => {
                      if (
                        currentVersion &&
                        window.confirm(
                          `${translate('Опубликовать v')}${currentVersion.version_number} ${translate('и активировать workflow?')}`,
                        )
                      ) {
                        publishMutation.mutate({
                          workflow: selectedWorkflow,
                          version: currentVersion,
                        })
                      }
                    }}
                  >
                    Publish
                  </button>
                ) : null}
              </div>

              <div className="workflow-simulation">
                <label>
                  <span>Контекст для dry-run / ручного запуска</span>
                  <textarea
                    spellCheck={false}
                    value={contextEditor}
                    onChange={(event) => setContextEditor(event.target.value)}
                  />
                </label>
                {can('workflows.execute') &&
                selectedWorkflow.published_version_number ? (
                  <button
                    type="button"
                    disabled={startMutation.isPending}
                    onClick={() => startMutation.mutate(selectedWorkflow)}
                  >
                    Запустить опубликованную версию
                  </button>
                ) : null}
                <pre>{JSON.stringify(result ?? {}, null, 2)}</pre>
              </div>
            </div>
          </div>
        ) : (
          <p className="state-panel state-panel-empty">
            Создайте или выберите workflow. Первый draft содержит безопасный END-шаг.
          </p>
        )
      ) : null}

      {view === 'executions' ? (
        <div className="workflow-execution-grid">
          <section className="section-card">
            <header className="section-header">
              <h3 className="section-title">История исполнения</h3>
              <p className="section-subtitle">
                Автообновление каждые 10 секунд. Фильтр учитывает выбранный workflow.
              </p>
            </header>
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Старт</th>
                    <th>Версия</th>
                    <th>Источник</th>
                    <th>Статус</th>
                  </tr>
                </thead>
                <tbody>
                  {(executionsQuery.data ?? []).map((execution) => (
                    <tr
                      key={execution.id}
                      className={
                        selectedExecutionId === execution.id ? 'selected-row' : ''
                      }
                      onClick={() => setSelectedExecutionId(execution.id)}
                    >
                      <td>{formatDateTime(execution.created_at)}</td>
                      <td>v{execution.workflow_version_number}</td>
                      <td>{execution.source}</td>
                      <td>{execution.status}</td>
                    </tr>
                  ))}
                  {!executionsQuery.isPending &&
                  !(executionsQuery.data ?? []).length ? (
                    <tr>
                      <td colSpan={4}>Исполнений пока нет.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </section>
          <aside className="workflow-execution-detail">
            {executionQuery.data ? (
              <>
                <header>
                  <div>
                    <p className="eyebrow">EXECUTION DETAIL</p>
                    <h3>{executionQuery.data.status}</h3>
                  </div>
                  <small>{executionQuery.data.id}</small>
                </header>
                <dl className="workflow-definition-meta">
                  <div><dt>Version</dt><dd>v{executionQuery.data.workflow_version_number}</dd></div>
                  <div><dt>Node</dt><dd>{executionQuery.data.current_node_key || '—'}</dd></div>
                  <div><dt>Attempts</dt><dd>{executionQuery.data.attempts}/{executionQuery.data.max_attempts}</dd></div>
                  <div><dt>Correlation</dt><dd>{executionQuery.data.correlation_id || '—'}</dd></div>
                </dl>
                {executionQuery.data.last_error ? (
                  <p className="error-state">{executionQuery.data.last_error}</p>
                ) : null}
                <div className="workflow-step-list">
                  {(executionQuery.data.steps ?? []).map((step) => (
                    <article key={step.id}>
                      <span>{step.sequence_number}</span>
                      <div>
                        <strong>{step.node_key}</strong>
                        <small>{step.node_type} · {step.status} · {step.attempts}/{step.max_attempts}</small>
                        {step.last_error ? <p>{step.last_error}</p> : null}
                      </div>
                    </article>
                  ))}
                </div>
                {can('workflows.executions.manage') ? (
                  <div className="workflow-editor-actions">
                    {[
                      'QUEUED',
                      'RUNNING',
                      'WAITING_TIMER',
                      'WAITING_APPROVAL',
                      'WAITING_SUBFLOW',
                      'RETRY',
                    ].includes(executionQuery.data.status) ? (
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() =>
                          executionActionMutation.mutate({
                            executionId: executionQuery.data!.id,
                            action: 'cancel',
                          })
                        }
                      >
                        Отменить
                      </button>
                    ) : null}
                    {['FAILED', 'DEAD_LETTER', 'CANCELLED'].includes(
                      executionQuery.data.status,
                    ) ? (
                      <button
                        type="button"
                        onClick={() =>
                          executionActionMutation.mutate({
                            executionId: executionQuery.data!.id,
                            action: 'replay',
                          })
                        }
                      >
                        Replay
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : (
              <p className="empty-state">Выберите исполнение для просмотра шагов.</p>
            )}
          </aside>
        </div>
      ) : null}

      {view === 'approvals' ? (
        <section className="section-card">
          <header className="section-header">
            <h3 className="section-title">Очередь согласований</h3>
            <p className="section-subtitle">
              Показываются только задачи вашей роли, если нет права override.
            </p>
          </header>
          <div className="workflow-approval-list">
            {(approvalsQuery.data ?? []).map((approval) => (
              <article key={approval.id}>
                <div>
                  <span className="workflow-status status-paused">PENDING</span>
                  <h3>{approval.node_key}</h3>
                  <p>
                    Роль: <strong>{approval.approver_role}</strong> · истекает{' '}
                    {formatDateTime(approval.expires_at)}
                  </p>
                  <small>Execution: {approval.execution_id}</small>
                </div>
                {can('workflows.approvals.decide') ? (
                  <div>
                    <button
                      type="button"
                      disabled={approvalMutation.isPending}
                      onClick={() =>
                        approvalMutation.mutate({
                          approvalId: approval.id,
                          decision: 'APPROVED',
                        })
                      }
                    >
                      Согласовать
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      disabled={approvalMutation.isPending}
                      onClick={() =>
                        approvalMutation.mutate({
                          approvalId: approval.id,
                          decision: 'REJECTED',
                        })
                      }
                    >
                      Отклонить
                    </button>
                  </div>
                ) : null}
              </article>
            ))}
            {!approvalsQuery.isPending && !(approvalsQuery.data ?? []).length ? (
              <p className="state-panel state-panel-empty">
                Нет ожидающих согласований для вашей роли.
              </p>
            ) : null}
          </div>
        </section>
      ) : null}

      {view === 'reviews' ? (
        <section className="section-card">
          <header className="section-header">
            <h3 className="section-title">Four-eyes review публикации</h3>
            <p className="section-subtitle">
              Автор не может согласовать собственный draft. После изменения
              согласование автоматически сбрасывается.
            </p>
          </header>
          <div className="workflow-approval-list workflow-review-list">
            {(reviewsQuery.data ?? []).map((review) => (
              <article key={review.id}>
                <div>
                  <span className="workflow-status status-paused">
                    {review.review_status}
                  </span>
                  <h3>{review.workflow_name} · v{review.version_number}</h3>
                  <p>
                    {review.workflow_code} · запросил{' '}
                    {review.review_requested_by_id ?? '—'} ·{' '}
                    {formatDateTime(review.review_requested_at)}
                  </p>
                  <small>{review.review_comment || 'Комментарий отсутствует'}</small>
                </div>
                {can('workflows.reviews.decide') &&
                review.review_requested_by_id !== session?.user.id ? (
                  <div>
                    <button
                      type="button"
                      disabled={reviewMutation.isPending}
                      onClick={() =>
                        reviewMutation.mutate({
                          reviewId: review.id,
                          decision: 'APPROVED',
                        })
                      }
                    >
                      Одобрить
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      disabled={reviewMutation.isPending}
                      onClick={() =>
                        reviewMutation.mutate({
                          reviewId: review.id,
                          decision: 'REJECTED',
                        })
                      }
                    >
                      Вернуть автору
                    </button>
                  </div>
                ) : review.review_requested_by_id === session?.user.id ? (
                  <small>Ожидается решение другого уполномоченного пользователя.</small>
                ) : null}
              </article>
            ))}
            {!reviewsQuery.isPending && !(reviewsQuery.data ?? []).length ? (
              <p className="state-panel state-panel-empty">
                Нет workflow, ожидающих независимого review.
              </p>
            ) : null}
          </div>
        </section>
      ) : null}
      </section>
    </LocalizedContent>
  )
}
