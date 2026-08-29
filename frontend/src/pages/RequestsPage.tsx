import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  assignFulfillmentTask,
  cancelServiceRequest,
  commentServiceRequest,
  controlRequestedItemSla,
  decideRequestApproval,
  evaluateRequestSla,
  fetchRequestGovernanceAnalytics,
  fetchServiceRequest,
  fetchServiceRequests,
  reworkRequestedItem,
  transitionFulfillmentTask,
  type FulfillmentTask,
  type RequestApproval,
  type ServiceRequestDetail,
  type ServiceRequestStatus,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import EntityCustomFieldsPanel from '../components/EntityCustomFieldsPanel'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const statusLabels: Record<ServiceRequestStatus, string> = {
  SUBMITTED: 'Принят',
  PENDING_APPROVAL: 'На согласовании',
  APPROVED: 'Согласован',
  IN_FULFILLMENT: 'В исполнении',
  COMPLETED: 'Выполнен',
  REJECTED: 'Отклонён',
  CANCELLED: 'Отменён',
}

const taskLabels: Record<FulfillmentTask['status'], string> = {
  OPEN: 'Открыта',
  IN_PROGRESS: 'В работе',
  WAITING: 'Ожидание',
  COMPLETED: 'Выполнена',
  FAILED: 'Ошибка',
  CANCELLED: 'Отменена',
}

const transitionLabels: Record<FulfillmentTask['status'], string> = {
  OPEN: 'Вернуть в очередь',
  IN_PROGRESS: 'Начать работу',
  WAITING: 'Перевести в ожидание',
  COMPLETED: 'Завершить',
  FAILED: 'Зафиксировать ошибку',
  CANCELLED: 'Отменить задачу',
}

const priorityLabels = {
  LOW: 'Низкий',
  MEDIUM: 'Обычный',
  HIGH: 'Высокий',
  CRITICAL: 'Критический',
} as const

type WorkflowAction =
  | { kind: 'approve'; approval: RequestApproval; decision: 'APPROVED' | 'REJECTED'; comment?: string }
  | { kind: 'assign'; task: FulfillmentTask }
  | { kind: 'transition'; task: FulfillmentTask; target: FulfillmentTask['status']; comment?: string }
  | { kind: 'cancel'; detail: ServiceRequestDetail; reason: string }
  | { kind: 'rework'; detail: ServiceRequestDetail; itemId: string; itemVersion: number; reason: string }
  | { kind: 'sla'; detail: ServiceRequestDetail; itemId: string; itemVersion: number; action: 'pause' | 'resume'; reason: string }
  | { kind: 'comment'; detail: ServiceRequestDetail; body: string; isInternal: boolean }

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const slaLabels: Record<string, string> = {
  NOT_STARTED: 'Не запущен',
  ACTIVE: 'В норме',
  AT_RISK: 'Под риском',
  PAUSED: 'Приостановлен',
  MET: 'Выполнен',
  BREACHED: 'Нарушен',
  CANCELLED: 'Отменён',
  REJECTED: 'Отклонён',
}

function workflowStage(status: ServiceRequestStatus) {
  if (status === 'COMPLETED') return 4
  if (status === 'IN_FULFILLMENT' || status === 'APPROVED') return 3
  if (status === 'PENDING_APPROVAL') return 2
  if (status === 'REJECTED' || status === 'CANCELLED') return 1
  return 1
}

export default function RequestsPage() {
  const { session } = useAuth()
  const {
    formatDateTime: formatDate,
    formatCurrency,
    t,
    translate,
  } = useTenantExperience()
  const money = (minor: number, currency: string) =>
    formatCurrency(minor / 100, currency)
  const priorityLabel = (value: string) => translate(
    priorityLabels[value as keyof typeof priorityLabels] ?? value,
  )
  const token = session?.access_token ?? ''
  const role = session?.user.role ?? ''
  const root = role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const canReadAllRequests = root
    || permissions.has('requests.scope.all')
    || ['requests.manage', 'requests.fulfill', 'requests.approve'].some(
      (permission) => permissions.has(permission),
    )
  const isRequester = !canReadAllRequests && permissions.has('requests.scope.requester')
  const canManageRequests = root || Boolean(session?.user.permissions.includes('requests.manage'))
  const canCommentRequests = root || Boolean(session?.user.permissions.includes('requests.comment'))
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const selectedId = searchParams.get('request_id')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [decisionComments, setDecisionComments] = useState<Record<string, string>>({})
  const [taskComments, setTaskComments] = useState<Record<string, string>>({})
  const [reworkReasons, setReworkReasons] = useState<Record<string, string>>({})
  const [cancelReason, setCancelReason] = useState('')
  const [comment, setComment] = useState('')
  const [internalComment, setInternalComment] = useState(false)
  const [slaReasons, setSlaReasons] = useState<Record<string, string>>({})
  const [actionError, setActionError] = useState<string | null>(null)
  const detailPanelRef = useRef<HTMLDivElement>(null)
  const detailHeadingRef = useRef<HTMLHeadingElement>(null)

  const listQuery = useQuery({
    queryKey: ['service-requests', token, search, statusFilter],
    queryFn: () => fetchServiceRequests(token, {
      search: search.trim() || undefined,
      status: statusFilter,
      page_size: 100,
    }),
    enabled: Boolean(token),
  })
  const detailQuery = useQuery({
    queryKey: ['service-request', token, selectedId],
    queryFn: () => fetchServiceRequest(token, selectedId ?? ''),
    enabled: Boolean(token && selectedId),
  })
  const governanceQuery = useQuery({
    queryKey: ['request-governance-analytics', token],
    queryFn: () => fetchRequestGovernanceAnalytics(token),
    enabled: Boolean(token && canManageRequests),
  })
  const requests = listQuery.data?.items ?? []
  const detail = detailQuery.data

  useEffect(() => {
    if (!detail?.id) return
    detailHeadingRef.current?.focus()
    if (window.matchMedia('(max-width: 850px)').matches) {
      const reducedMotion = window.matchMedia(
        '(prefers-reduced-motion: reduce)',
      ).matches
      detailPanelRef.current?.scrollIntoView({
        behavior: reducedMotion ? 'auto' : 'smooth',
        block: 'start',
      })
    }
  }, [detail?.id])

  async function refresh(next: ServiceRequestDetail) {
    queryClient.setQueryData(['service-request', token, next.id], next)
    await queryClient.invalidateQueries({ queryKey: ['service-requests'] })
  }

  const actionMutation = useMutation({
    mutationFn: async (action: WorkflowAction) => {
      if (action.kind === 'approve') {
        return decideRequestApproval(token, action.approval.id, {
          decision: action.decision,
          comment: action.comment,
        })
      }
      if (action.kind === 'assign') {
        return assignFulfillmentTask(token, action.task.id, {
          expected_version: action.task.version,
        })
      }
      if (action.kind === 'transition') {
        return transitionFulfillmentTask(token, action.task.id, {
          expected_version: action.task.version,
          target_status: action.target,
          comment: action.comment,
          evidence: action.target === 'COMPLETED'
            ? { completed_from: 'requests_workspace', completed_at: new Date().toISOString() }
            : undefined,
        })
      }
      if (action.kind === 'cancel') {
        return cancelServiceRequest(token, action.detail.id, {
          expected_version: action.detail.version,
          reason: action.reason,
        })
      }
      if (action.kind === 'rework') {
        return reworkRequestedItem(token, action.detail.id, action.itemId, {
          expected_version: action.itemVersion,
          reason: action.reason,
        })
      }
      if (action.kind === 'sla') {
        return controlRequestedItemSla(token, action.itemId, action.action, {
          expected_version: action.itemVersion,
          reason: action.reason,
        })
      }
      await commentServiceRequest(token, action.detail.id, {
        body: action.body,
        is_internal: action.isInternal,
      })
      return fetchServiceRequest(token, action.detail.id)
    },
    onSuccess: async (next) => {
      setActionError(null)
      setComment('')
      setInternalComment(false)
      await refresh(next)
      await queryClient.invalidateQueries({ queryKey: ['request-governance-analytics'] })
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Операция не выполнена.')
    },
  })
  const evaluateSlaMutation = useMutation({
    mutationFn: () => evaluateRequestSla(token),
    onSuccess: async () => {
      setActionError(null)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['service-request'] }),
        queryClient.invalidateQueries({ queryKey: ['service-requests'] }),
        queryClient.invalidateQueries({ queryKey: ['request-governance-analytics'] }),
      ])
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : 'Проверка SLA не выполнена.')
    },
  })

  const metrics = useMemo(() => ({
    total: listQuery.data?.total ?? 0,
    approval: requests.filter((entry) => entry.status === 'PENDING_APPROVAL').length,
    fulfillment: requests.filter((entry) => entry.status === 'IN_FULFILLMENT').length,
    completed: requests.filter((entry) => entry.status === 'COMPLETED').length,
  }), [listQuery.data?.total, requests])

  function selectRequest(requestId: string) {
    setSearchParams({ request_id: requestId })
    setActionError(null)
  }

  function canActSequential(approval: RequestApproval) {
    if (!detail || !approval.can_decide) return false
    if (approval.approval_mode !== 'SEQUENTIAL') return true
    return !detail.approvals.some((candidate) => (
      candidate.requested_item_id === approval.requested_item_id
      && candidate.round === approval.round
      && candidate.sequence < approval.sequence
      && candidate.status !== 'APPROVED'
    ))
  }

  const isBusy = actionMutation.isPending

  return (
    <AppShell
      title="Запросы услуг"
      subtitle="От заявки из каталога до согласования, исполнения и подтверждённого результата — в одном управляемом процессе."
    >
      <section className="request-metrics" aria-label="Сводка запросов">
        <article><span>Всего в выборке</span><strong>{metrics.total}</strong></article>
        <article><span>Ждут согласования</span><strong>{metrics.approval}</strong></article>
        <article><span>В исполнении</span><strong>{metrics.fulfillment}</strong></article>
        <article><span>Выполнено</span><strong>{metrics.completed}</strong></article>
      </section>

      {canManageRequests ? (
        <section className="request-governance foundation-card" aria-label="Governance запросов">
          <header>
            <div>
              <span>GOVERNANCE & SHOWBACK</span>
              <h2>Стоимость, спрос и SLA</h2>
            </div>
            <button
              type="button"
              onClick={() => evaluateSlaMutation.mutate()}
              disabled={evaluateSlaMutation.isPending}
            >
              {evaluateSlaMutation.isPending ? 'Проверяем…' : 'Проверить SLA'}
            </button>
          </header>
          {governanceQuery.isError ? (
            <div className="state-panel state-panel-error" role="alert">
              <span>Не удалось загрузить governance-аналитику запросов.</span>
              <button type="button" className="ghost-button" onClick={() => void governanceQuery.refetch()}>
                Повторить
              </button>
            </div>
          ) : null}
          <div className="request-governance-grid" aria-busy={governanceQuery.isPending}>
            <article>
              <span>Стоимость</span>
              <strong>
                {governanceQuery.isPending ? '…' : governanceQuery.isError ? '—' : Object.entries(governanceQuery.data?.currency_totals ?? {})
                  .map(([currency, total]) => money(total, currency))
                  .join(' · ') || '—'}
              </strong>
            </article>
            <article>
              <span>Требуют согласования</span>
              <strong>{governanceQuery.isPending ? '…' : governanceQuery.isError ? '—' : `${governanceQuery.data?.approval_rate_percent ?? 0}%`}</strong>
            </article>
            <article>
              <span>SLA нарушен / под риском</span>
              <strong>{governanceQuery.isPending ? '…' : governanceQuery.isError ? '—' : `${governanceQuery.data?.sla.BREACHED ?? 0} / ${governanceQuery.data?.sla.AT_RISK ?? 0}`}</strong>
            </article>
            <article>
              <span>Среднее исполнение</span>
              <strong>{governanceQuery.isPending ? '…' : governanceQuery.isError ? '—' : governanceQuery.data?.average_fulfillment_hours != null ? t('requests.hoursShort', { count: governanceQuery.data.average_fulfillment_hours }) : '—'}</strong>
            </article>
          </div>
          {governanceQuery.data?.demand_by_item.length ? (
            <div className="request-demand-list">
              {governanceQuery.data.demand_by_item.slice(0, 5).map((entry) => (
                <div key={entry.item_code}>
                  <span>{entry.item_name}</span>
                  <strong>{entry.request_count} запр. · {money(entry.total_cost_minor, entry.currency)}</strong>
                </div>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      <section className="request-toolbar foundation-card">
        <div>
          <strong>Единое рабочее место</strong>
          <p>Заявитель видит только свои запросы. Согласующие и исполнители получают доступные им действия без обхода процесса.</p>
        </div>
        <div className="request-toolbar-fields">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Номер, тема или заявитель"
            aria-label="Поиск запросов"
          />
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            aria-label="Фильтр по статусу"
          >
            <option value="ALL">Все статусы</option>
            {Object.entries(statusLabels).map(([value, label]) => (
              <option key={value} value={value}>{translate(label)}</option>
            ))}
          </select>
          <Link to="/catalog" className="request-catalog-link">+ Новый запрос</Link>
        </div>
      </section>

      {actionError ? <div className="error-banner request-banner" role="alert">{actionError}</div> : null}

      <section className="request-workspace" aria-label="Запросы и детали процесса">
        <aside className="request-list-panel" aria-label="Список запросов">
          <header>
            <div>
              <span>Очередь</span>
              <strong>{listQuery.data?.total ?? 0} запросов</strong>
            </div>
            {listQuery.isFetching ? <small role="status">Обновление…</small> : null}
          </header>
          <div className="request-list">
            {listQuery.isPending ? (
              <div className="state-panel state-panel-loading" role="status">Загрузка запросов…</div>
            ) : null}
            {listQuery.isError ? (
              <div className="state-panel state-panel-error" role="alert">
                <strong>Не удалось загрузить очередь запросов.</strong>
                <button type="button" className="ghost-button" onClick={() => void listQuery.refetch()}>
                  Повторить
                </button>
              </div>
            ) : null}
            {requests.map((entry) => (
              <button
                type="button"
                key={entry.id}
                className={`request-list-card ${selectedId === entry.id ? 'active' : ''}`}
                aria-pressed={selectedId === entry.id}
                onClick={() => selectRequest(entry.id)}
              >
                <div className="request-list-card-top">
                  <span>{entry.request_number}</span>
                  <span className={`request-status status-${entry.status.toLowerCase()}`}>
                    {translate(statusLabels[entry.status])}
                  </span>
                </div>
                <strong>{entry.title}</strong>
                <p>{entry.requester_name}</p>
                <small>{formatDate(entry.created_at)} · {priorityLabel(entry.priority)}</small>
              </button>
            ))}
            {!listQuery.isLoading && !listQuery.isError && requests.length === 0 ? (
              <div className="request-empty">
                <strong>Запросов пока нет</strong>
                <p>Выберите услугу в каталоге и заполните опубликованную форму.</p>
                <Link to="/catalog">Открыть каталог услуг</Link>
              </div>
            ) : null}
          </div>
        </aside>

        <div
          ref={detailPanelRef}
          className="request-detail-panel"
          aria-live="polite"
          aria-busy={detailQuery.isLoading}
        >
          {!selectedId ? (
            <div className="request-detail-empty">
              <span>SR</span>
              <h2>Выберите запрос</h2>
              <p>Справа появятся маршрут согласования, задачи исполнения, параметры формы и вся история.</p>
            </div>
          ) : detailQuery.isLoading ? (
            <div className="request-detail-empty" role="status"><p>Загружаем процесс…</p></div>
          ) : detailQuery.isError || !detail ? (
            <div className="request-detail-empty" role="alert">
              <h2>Запрос недоступен</h2>
              <p>{detailQuery.error instanceof Error ? detailQuery.error.message : 'Проверьте права и повторите попытку.'}</p>
            </div>
          ) : (
            <div className="request-detail">
              <header className="request-detail-header">
                <div>
                  <div className="request-detail-kicker">
                    <span>{detail.request_number}</span>
                    <span className={`request-status status-${detail.status.toLowerCase()}`}>
                      {translate(statusLabels[detail.status])}
                    </span>
                  </div>
                  <h2 ref={detailHeadingRef} tabIndex={-1}>{detail.title}</h2>
                  <p>{detail.description}</p>
                </div>
                <button type="button" className="ghost-button" onClick={() => setSearchParams({})}>
                  Закрыть
                </button>
              </header>

              <div className="request-progress" aria-label="Прогресс запроса">
                {['Запрос принят', 'Согласование', 'Исполнение', 'Результат'].map((label, index) => (
                  <div
                    key={label}
                    className={index + 1 <= workflowStage(detail.status) ? 'done' : ''}
                  >
                    <span>{index + 1}</span>
                    <strong>{label}</strong>
                  </div>
                ))}
              </div>

              <section className="request-facts">
                <div><span>Заявитель</span><strong>{detail.requester_name}</strong><small>{detail.requester_email}</small></div>
                <div><span>Приоритет</span><strong>{priorityLabel(detail.priority)}</strong></div>
                <div><span>Риск</span><strong>{priorityLabel(detail.risk_level)}</strong></div>
                <div><span>Cost center</span><strong>{detail.cost_center ?? 'Не назначен'}</strong></div>
                <div><span>Showback</span><strong>{money(detail.total_cost_minor, detail.currency)}</strong></div>
                <div><span>Создан</span><strong>{formatDate(detail.created_at)}</strong></div>
                <div><span>Версия процесса</span><strong>v{detail.version}</strong></div>
              </section>

              <EntityCustomFieldsPanel
                entityType="request"
                entityId={detail.id}
                tenantId={detail.tenant_id}
                compact
              />

              <section className="request-section">
                <div className="request-section-heading">
                  <div><span>Requested items</span><h3>Состав запроса</h3></div>
                  <small>{detail.items.length} поз.</small>
                </div>
                {detail.items.map((item) => (
                  <article className="requested-item-card" key={item.id}>
                    <header>
                      <div>
                        <small>{item.item_code} · форма v{item.form_version ?? '—'}</small>
                        <h4>{item.item_name}</h4>
                      </div>
                      <span className={`request-status status-${item.status.toLowerCase()}`}>
                        {translate(statusLabels[item.status])}
                      </span>
                    </header>
                    <div className="request-form-values">
                      {Object.entries(item.form_values).map(([key, value]) => (
                        <div key={key}><span>{item.field_labels[key] ?? key.replaceAll('_', ' ')}</span><strong>{displayValue(value)}</strong></div>
                      ))}
                    </div>
                    <div className="request-item-governance">
                      <div><span>Стоимость</span><strong>{money(item.total_cost_minor, item.currency)}</strong></div>
                      <div><span>Cost center</span><strong>{item.cost_center ?? 'Не назначен'}</strong></div>
                      <div><span>Риск</span><strong>{priorityLabel(item.risk_level)}</strong></div>
                      <div>
                        <span>SLA</span>
                        <strong className={`request-sla-state sla-${item.sla_status.toLowerCase()}`}>
                          {translate(slaLabels[item.sla_status] ?? item.sla_status)}
                        </strong>
                        <small>{formatDate(item.sla_due_at)} · эскалация L{item.sla_escalation_level}</small>
                      </div>
                    </div>
                    <footer>
                      <span>Группа: {item.support_group ?? 'не назначена'}</span>
                      <span>Ожидаемый срок: {formatDate(item.expected_delivery_at)}</span>
                    </footer>
                    {canManageRequests && !['COMPLETED', 'CANCELLED', 'REJECTED'].includes(item.status) ? (
                      <div className="request-inline-action request-sla-control">
                        <input
                          value={slaReasons[item.id] ?? ''}
                          onChange={(event) => setSlaReasons((current) => ({ ...current, [item.id]: event.target.value }))}
                          placeholder={item.sla_status === 'PAUSED' ? 'Причина возобновления SLA' : 'Причина приостановки SLA'}
                        />
                        <button
                          type="button"
                          disabled={isBusy || (slaReasons[item.id] ?? '').trim().length < 3}
                          onClick={() => actionMutation.mutate({
                            kind: 'sla',
                            detail,
                            itemId: item.id,
                            itemVersion: item.version,
                            action: item.sla_status === 'PAUSED' ? 'resume' : 'pause',
                            reason: slaReasons[item.id] ?? '',
                          })}
                        >
                          {item.sla_status === 'PAUSED' ? 'Возобновить SLA' : 'Приостановить SLA'}
                        </button>
                      </div>
                    ) : null}
                    {item.status === 'REJECTED' ? (
                      <div className="request-inline-action">
                        <input
                          value={reworkReasons[item.id] ?? ''}
                          onChange={(event) => setReworkReasons((current) => ({ ...current, [item.id]: event.target.value }))}
                          placeholder="Что уточнено перед повторной отправкой"
                        />
                        <button
                          type="button"
                          disabled={isBusy || (reworkReasons[item.id] ?? '').trim().length < 3}
                          onClick={() => actionMutation.mutate({
                            kind: 'rework',
                            detail,
                            itemId: item.id,
                            itemVersion: item.version,
                            reason: reworkReasons[item.id] ?? '',
                          })}
                        >
                          Отправить повторно
                        </button>
                      </div>
                    ) : null}
                  </article>
                ))}
              </section>

              {detail.approvals.length ? (
                <section className="request-section">
                  <div className="request-section-heading">
                    <div><span>Approvals</span><h3>Маршрут согласования</h3></div>
                    <small>{detail.approvals.filter((entry) => entry.status === 'PENDING').length} ожидают</small>
                  </div>
                  <div className="approval-route">
                    {detail.approvals.map((approval) => {
                      const canDecide = canActSequential(approval)
                      const decisionComment = decisionComments[approval.id] ?? ''
                      return (
                        <article key={approval.id} className={`approval-card approval-${approval.status.toLowerCase()}`}>
                          <div className="approval-sequence">{approval.round}.{approval.sequence}</div>
                          <div className="approval-body">
                            <header>
                              <div><strong>{approval.approver_name}</strong><small>{approval.approver_email ?? 'Назначит менеджер'}</small></div>
                              <span>{translate(approval.status === 'PENDING' ? 'Ожидает решения' : statusLabels[approval.status as ServiceRequestStatus] ?? approval.status)}</span>
                            </header>
                            {approval.comment ? <p>{approval.comment}</p> : null}
                            {canDecide ? (
                              <div className="approval-actions">
                                <input
                                  value={decisionComment}
                                  onChange={(event) => setDecisionComments((current) => ({ ...current, [approval.id]: event.target.value }))}
                                  placeholder="Комментарий к решению"
                                />
                                <button
                                  type="button"
                                  disabled={isBusy}
                                  onClick={() => actionMutation.mutate({
                                    kind: 'approve',
                                    approval,
                                    decision: 'APPROVED',
                                    comment: decisionComment,
                                  })}
                                >
                                  Согласовать
                                </button>
                                <button
                                  type="button"
                                  className="danger-button"
                                  disabled={isBusy || decisionComment.trim().length < 3}
                                  onClick={() => actionMutation.mutate({
                                    kind: 'approve',
                                    approval,
                                    decision: 'REJECTED',
                                    comment: decisionComment,
                                  })}
                                >
                                  Отклонить
                                </button>
                              </div>
                            ) : null}
                          </div>
                        </article>
                      )
                    })}
                  </div>
                </section>
              ) : null}

              {detail.tasks.length ? (
                <section className="request-section">
                  <div className="request-section-heading">
                    <div><span>Fulfillment</span><h3>Задачи исполнения</h3></div>
                    <small>{detail.tasks.filter((entry) => !['COMPLETED', 'CANCELLED'].includes(entry.status)).length} активных</small>
                  </div>
                  <div className="fulfillment-grid">
                    {detail.tasks.map((task) => {
                      const taskComment = taskComments[task.id] ?? ''
                      return (
                        <article className="fulfillment-card" key={task.id}>
                          <header>
                            <div><small>{task.task_number}</small><h4>{task.title}</h4></div>
                            <span className={`task-status task-${task.status.toLowerCase()}`}>{translate(taskLabels[task.status])}</span>
                          </header>
                          <div className="fulfillment-meta">
                            <span>Исполнитель</span><strong>{task.assignee_name ?? 'Не назначен'}</strong>
                            <span>Группа</span><strong>{task.support_group ?? '—'}</strong>
                            <span>OLA до</span><strong>{formatDate(task.due_at)}</strong>
                          </div>
                          {Object.keys(task.evidence).length ? (
                            <div className="task-evidence"><span>Результат</span><code>{JSON.stringify(task.evidence)}</code></div>
                          ) : null}
                          {task.can_fulfill
                            && task.allowed_transitions.length > 0
                            && !task.assignee_id
                            && role !== 'saas_root' ? (
                            <button
                              type="button"
                              className="request-claim-button"
                              disabled={isBusy}
                              onClick={() => actionMutation.mutate({ kind: 'assign', task })}
                            >
                              Взять в работу
                            </button>
                          ) : null}
                          {task.can_fulfill && task.allowed_transitions.length ? (
                            <div className="task-actions">
                              <input
                                value={taskComment}
                                onChange={(event) => setTaskComments((current) => ({ ...current, [task.id]: event.target.value }))}
                                placeholder="Комментарий исполнителя"
                              />
                              <div>
                                {task.allowed_transitions.map((target) => (
                                  <button
                                    type="button"
                                    key={target}
                                    disabled={isBusy || (
                                      ['COMPLETED', 'FAILED'].includes(target)
                                      && taskComment.trim().length < 3
                                    )}
                                    onClick={() => actionMutation.mutate({
                                      kind: 'transition',
                                      task,
                                      target,
                                      comment: taskComment,
                                    })}
                                  >
                                    {translate(transitionLabels[target])}
                                  </button>
                                ))}
                              </div>
                            </div>
                          ) : null}
                        </article>
                      )
                    })}
                  </div>
                </section>
              ) : null}

              <section className="request-section">
                <div className="request-section-heading">
                  <div><span>Activity</span><h3>Временная шкала</h3></div>
                  <small>{detail.activities.length} событий</small>
                </div>
                {canCommentRequests ? <div className="request-comment-box">
                  <textarea
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    placeholder="Добавить комментарий в историю запроса"
                  />
                  <div>
                    {!isRequester ? (
                      <label><input type="checkbox" checked={internalComment} onChange={(event) => setInternalComment(event.target.checked)} /> Внутренняя заметка</label>
                    ) : <span />}
                    <button
                      type="button"
                      disabled={isBusy || comment.trim().length < 1}
                      onClick={() => actionMutation.mutate({
                        kind: 'comment',
                        detail,
                        body: comment,
                        isInternal: internalComment,
                      })}
                    >
                      Добавить
                    </button>
                  </div>
                </div> : null}
                <div className="request-timeline">
                  {[...detail.activities].reverse().map((activity) => (
                    <article key={activity.id}>
                      <div className="timeline-dot" />
                      <div>
                        <header><strong>{activity.actor_name}</strong><time>{formatDate(activity.created_at)}</time></header>
                        <p>{activity.message}</p>
                        <small>{activity.event_type}{activity.visibility === 'INTERNAL' ? ' · внутренняя заметка' : ''}</small>
                      </div>
                    </article>
                  ))}
                </div>
              </section>

              {detail.can_cancel ? (
                <section className="request-cancel-zone">
                  <div><strong>Отмена запроса</strong><p>Остановит открытые согласования и задачи исполнения.</p></div>
                  <input
                    value={cancelReason}
                    onChange={(event) => setCancelReason(event.target.value)}
                    placeholder="Причина отмены"
                  />
                  <button
                    type="button"
                    className="danger-button"
                    disabled={isBusy || cancelReason.trim().length < 3}
                    onClick={() => actionMutation.mutate({
                      kind: 'cancel',
                      detail,
                      reason: cancelReason,
                    })}
                  >
                    Отменить запрос
                  </button>
                </section>
              ) : null}
            </div>
          )}
        </div>
      </section>
    </AppShell>
  )
}
