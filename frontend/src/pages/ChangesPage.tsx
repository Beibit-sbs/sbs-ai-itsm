import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  createChange,
  decideChange,
  fetchAssets,
  fetchChange,
  fetchChangesPage,
  fetchChangeSummary,
  transitionChange,
  type ChangeDetail,
  type CreateChangeRequest,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import CMDBImpactPanel from '../components/CMDBImpactPanel'
import EntityCustomFieldsPanel from '../components/EntityCustomFieldsPanel'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const statusOptions = [
  'ALL',
  'DRAFT',
  'ASSESSMENT',
  'APPROVAL_PENDING',
  'APPROVED',
  'SCHEDULED',
  'IMPLEMENTING',
  'REVIEW',
  'COMPLETED',
  'REJECTED',
  'FAILED',
  'ROLLED_BACK',
  'CANCELLED',
]

const statusLabels: Record<string, string> = {
  ALL: 'Все статусы',
  DRAFT: 'Черновик',
  ASSESSMENT: 'Оценка',
  APPROVAL_PENDING: 'Ожидает CAB',
  APPROVED: 'Одобрено',
  SCHEDULED: 'Запланировано',
  IMPLEMENTING: 'Внедрение',
  REVIEW: 'Проверка',
  COMPLETED: 'Завершено',
  REJECTED: 'Отклонено',
  FAILED: 'Сбой',
  ROLLED_BACK: 'Откат выполнен',
  CANCELLED: 'Отменено',
}

const typeLabels: Record<string, string> = {
  STANDARD: 'Стандартное',
  NORMAL: 'Обычное',
  EMERGENCY: 'Экстренное',
}

const riskLabels: Record<string, string> = {
  LOW: 'Низкий',
  MEDIUM: 'Средний',
  HIGH: 'Высокий',
  CRITICAL: 'Критический',
}

const impactLabels: Record<FormState['impact_level'], string> = {
  LOW: 'Низкий',
  MEDIUM: 'Средний',
  HIGH: 'Высокий',
  ENTERPRISE: 'Корпоративный',
}

const approvalStatusLabels: Record<string, string> = {
  NOT_REQUIRED: 'Предварительно одобрено',
  PENDING: 'Ожидает решения',
  APPROVED: 'Одобрено',
  REJECTED: 'Отклонено',
}

type FormState = {
  title: string
  description: string
  change_type: 'STANDARD' | 'NORMAL' | 'EMERGENCY'
  service_name: string
  impact_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'ENTERPRISE'
  likelihood: number
  business_justification: string
  implementation_plan: string
  test_plan: string
  rollback_plan: string
  validation_plan: string
  planned_start_at: string
  planned_end_at: string
  outage_required: boolean
  outage_minutes: number
  asset_id: string
}

const emptyForm: FormState = {
  title: '',
  description: '',
  change_type: 'NORMAL',
  service_name: '',
  impact_level: 'MEDIUM',
  likelihood: 2,
  business_justification: '',
  implementation_plan: '',
  test_plan: '',
  rollback_plan: '',
  validation_plan: '',
  planned_start_at: '',
  planned_end_at: '',
  outage_required: false,
  outage_minutes: 0,
  asset_id: '',
}

function toIso(value: string) {
  return value ? new Date(value).toISOString() : undefined
}

function permission(session: ReturnType<typeof useAuth>['session'], code: string) {
  return session?.user.role === 'saas_root' || Boolean(session?.user.permissions.includes(code))
}

function transitionLabel(action: string) {
  return {
    SUBMIT: 'Передать на оценку',
    REQUEST_APPROVAL: 'Запросить CAB',
    SCHEDULE: 'Зафиксировать окно',
    START: 'Начать внедрение',
    COMPLETE: 'Завершить внедрение',
    CLOSE: 'Закрыть изменение',
    FAIL: 'Зафиксировать сбой',
    ROLLBACK: 'Подтвердить откат',
    CANCEL: 'Отменить изменение',
  }[action] ?? action
}

function nextActions(change: ChangeDetail, session: ReturnType<typeof useAuth>['session']) {
  const actions: string[] = []
  if (['DRAFT', 'REJECTED'].includes(change.status) && permission(session, 'changes.submit')) actions.push('SUBMIT')
  if (change.status === 'ASSESSMENT' && permission(session, 'changes.submit')) actions.push('REQUEST_APPROVAL')
  if (change.status === 'APPROVED' && permission(session, 'changes.schedule')) actions.push('SCHEDULE')
  if (change.status === 'SCHEDULED' && permission(session, 'changes.execute')) actions.push('START')
  if (change.status === 'IMPLEMENTING' && permission(session, 'changes.execute')) actions.push('COMPLETE', 'FAIL', 'ROLLBACK')
  if (change.status === 'REVIEW' && permission(session, 'changes.execute')) actions.push('CLOSE')
  if (change.status === 'FAILED' && permission(session, 'changes.execute')) actions.push('ROLLBACK')
  if (
    ['DRAFT', 'ASSESSMENT', 'APPROVAL_PENDING', 'APPROVED', 'SCHEDULED', 'REJECTED'].includes(change.status)
    && permission(session, 'changes.submit')
  ) actions.push('CANCEL')
  return actions
}

export default function ChangesPage() {
  const { session } = useAuth()
  const { formatDateTime: formatDate, translate } = useTenantExperience()
  const [urlSearchParams, setUrlSearchParams] = useSearchParams()
  const token = session?.access_token ?? ''
  const canCreate = permission(session, 'changes.create')
  const canReadAssets = permission(session, 'assets.read')
  const queryClient = useQueryClient()
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [riskFilter, setRiskFilter] = useState('ALL')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [cabComment, setCabComment] = useState('')
  const [actionComment, setActionComment] = useState('')
  const [scheduleStart, setScheduleStart] = useState('')
  const [scheduleEnd, setScheduleEnd] = useState('')
  const [feedback, setFeedback] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ['changes', token, q, statusFilter, typeFilter, riskFilter, page],
    queryFn: () => fetchChangesPage(token, {
      q: q || undefined,
      status: statusFilter,
      change_type: typeFilter,
      risk_level: riskFilter,
      page,
      page_size: 20,
    }),
    enabled: Boolean(token),
  })
  const summaryQuery = useQuery({
    queryKey: ['change-summary', token],
    queryFn: () => fetchChangeSummary(token),
    enabled: Boolean(token),
  })
  const detailQuery = useQuery({
    queryKey: ['change-detail', token, selectedId],
    queryFn: () => fetchChange(token, selectedId ?? ''),
    enabled: Boolean(token && selectedId),
  })
  const assetsQuery = useQuery({
    queryKey: ['change-assets', token],
    queryFn: () => fetchAssets(token, { page_size: 100 }),
    enabled: Boolean(token && showCreate && canCreate && canReadAssets),
  })

  useEffect(() => {
    const changeId = urlSearchParams.get('change')
    if (!changeId) return
    setSelectedId(changeId)
    const nextParams = new URLSearchParams(urlSearchParams)
    nextParams.delete('change')
    setUrlSearchParams(nextParams, { replace: true })
  }, [setUrlSearchParams, urlSearchParams])

  useEffect(() => {
    const first = listQuery.data?.items[0]
    if (!selectedId && first) setSelectedId(first.id)
    if (
      selectedId
      && listQuery.data
      && !listQuery.data.items.some((item) => item.id === selectedId)
      && detailQuery.isError
    ) {
      setSelectedId(first?.id ?? null)
    }
  }, [detailQuery.isError, listQuery.data, selectedId])

  useEffect(() => {
    const change = detailQuery.data
    if (!change) return
    setScheduleStart(change.planned_start_at?.slice(0, 16) ?? '')
    setScheduleEnd(change.planned_end_at?.slice(0, 16) ?? '')
  }, [detailQuery.data])

  async function refreshChange(change: ChangeDetail) {
    setSelectedId(change.id)
    queryClient.setQueryData(['change-detail', token, change.id], change)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['changes'] }),
      queryClient.invalidateQueries({ queryKey: ['change-summary'] }),
    ])
  }

  const createMutation = useMutation({
    mutationFn: (payload: CreateChangeRequest) => createChange(token, payload),
    onSuccess: async (change) => {
      await refreshChange(change)
      setForm(emptyForm)
      setShowCreate(false)
      setFeedback(`${change.change_number} ${translate('создано')}`)
    },
  })
  const transitionMutation = useMutation({
    mutationFn: ({ change, action }: { change: ChangeDetail; action: string }) => transitionChange(
      token,
      change.id,
      {
        action,
        expected_version: change.version,
        comment: actionComment || undefined,
        planned_start_at: action === 'SCHEDULE' ? toIso(scheduleStart) : undefined,
        planned_end_at: action === 'SCHEDULE' ? toIso(scheduleEnd) : undefined,
      },
    ),
    onSuccess: async (change) => {
      await refreshChange(change)
      setActionComment('')
      setFeedback(`${change.change_number}: ${translate(statusLabels[change.status] ?? change.status)}`)
    },
  })
  const decisionMutation = useMutation({
    mutationFn: ({ change, decision }: { change: ChangeDetail; decision: 'APPROVED' | 'REJECTED' }) => decideChange(
      token,
      change.id,
      { decision, comment: cabComment, expected_version: change.version },
    ),
    onSuccess: async (change) => {
      await refreshChange(change)
      setCabComment('')
      setFeedback(`CAB: ${translate(approvalStatusLabels[change.approval_status] ?? change.approval_status)}`)
    },
  })

  const mutationError = createMutation.error || transitionMutation.error || decisionMutation.error
  const change = detailQuery.data
  const actions = useMemo(() => change ? nextActions(change, session) : [], [change, session])
  const totalPages = Math.max(1, Math.ceil((listQuery.data?.total ?? 0) / 20))

  function submitCreate(event: React.FormEvent) {
    event.preventDefault()
    setFeedback(null)
    createMutation.mutate({
      title: form.title,
      description: form.description,
      change_type: form.change_type,
      service_name: form.service_name || null,
      impact_level: form.impact_level,
      likelihood: form.likelihood,
      business_justification: form.business_justification || null,
      implementation_plan: form.implementation_plan || null,
      test_plan: form.test_plan || null,
      rollback_plan: form.rollback_plan || null,
      validation_plan: form.validation_plan || null,
      planned_start_at: toIso(form.planned_start_at),
      planned_end_at: toIso(form.planned_end_at),
      outage_required: form.outage_required,
      outage_minutes: form.outage_required ? form.outage_minutes : 0,
      asset_ids: form.asset_id ? [form.asset_id] : [],
    })
  }

  function act(action: string) {
    if (!change) return
    if (['CLOSE', 'FAIL', 'ROLLBACK', 'CANCEL'].includes(action) && !actionComment.trim()) {
      setFeedback('Для этого действия нужен комментарий оператора.')
      return
    }
    if (action === 'SCHEDULE' && (!scheduleStart || !scheduleEnd)) {
      setFeedback('Укажите начало и окончание окна внедрения.')
      return
    }
    setFeedback(null)
    transitionMutation.mutate({ change, action })
  }

  const summary = summaryQuery.data

  return (
    <LocalizedContent><AppShell
      title="Управление изменениями"
      subtitle="Контролируемый RFC-процесс: риск, CAB/ECAB, окна внедрения, конфликты активов и rollback."
    >
      <section className="change-summary-grid" aria-label="Сводка изменений">
        {[
          ['Открытые', summary?.open_changes ?? '—'],
          ['Ожидают CAB', summary?.awaiting_approval ?? '—'],
          ['7 дней', summary?.scheduled_next_7_days ?? '—'],
          ['Высокий риск', summary?.high_risk_open ?? '—'],
          ['Сбои 30 дней', summary?.failed_last_30_days ?? '—'],
        ].map(([label, value]) => (
          <article className="metric-card" key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </section>

      <section className="ticket-table-shell change-toolbar">
        <div className="change-filter-grid">
          <label>
            Поиск
            <input value={q} onChange={(event) => { setQ(event.target.value); setPage(1) }} placeholder="CHG, заголовок, сервис" />
          </label>
          <label>
            Статус
            <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1) }}>
              {statusOptions.map((item) => <option value={item} key={item}>{translate(statusLabels[item])}</option>)}
            </select>
          </label>
          <label>
            Тип
            <select value={typeFilter} onChange={(event) => { setTypeFilter(event.target.value); setPage(1) }}>
              <option value="ALL">Все типы</option>
              {Object.entries(typeLabels).map(([value, label]) => <option value={value} key={value}>{translate(label)}</option>)}
            </select>
          </label>
          <label>
            Риск
            <select value={riskFilter} onChange={(event) => { setRiskFilter(event.target.value); setPage(1) }}>
              <option value="ALL">Все уровни</option>
              {Object.entries(riskLabels).map(([value, label]) => <option value={value} key={value}>{translate(label)}</option>)}
            </select>
          </label>
          {canCreate ? (
            <button type="button" className="change-create-button" onClick={() => setShowCreate((value) => !value)}>
              {showCreate ? 'Закрыть форму' : 'Новый RFC'}
            </button>
          ) : null}
        </div>
      </section>

      {showCreate && canCreate ? (
        <section className="ticket-table-shell change-create-panel">
          <div className="section-header">
            <div>
              <h2 className="section-title">Новый запрос на изменение</h2>
              <p className="section-subtitle">Планы обязательны перед передачей на оценку. Риск рассчитывается сервером.</p>
            </div>
          </div>
          <form onSubmit={submitCreate}>
            <div className="change-form-grid">
              <label>Заголовок<input required minLength={3} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></label>
              <label>Сервис<input value={form.service_name} onChange={(e) => setForm({ ...form, service_name: e.target.value })} /></label>
              <label>Тип<select value={form.change_type} onChange={(e) => setForm({ ...form, change_type: e.target.value as FormState['change_type'] })}>{Object.entries(typeLabels).map(([value, label]) => <option value={value} key={value}>{translate(label)}</option>)}</select></label>
              <label>Влияние<select value={form.impact_level} onChange={(e) => setForm({ ...form, impact_level: e.target.value as FormState['impact_level'] })}>{(Object.keys(impactLabels) as FormState['impact_level'][]).map((value) => <option key={value} value={value}>{translate(impactLabels[value])}</option>)}</select></label>
              <label>Вероятность (1–5)<input type="number" min={1} max={5} value={form.likelihood} onChange={(e) => setForm({ ...form, likelihood: Number(e.target.value) })} /></label>
              {canReadAssets ? <label>Связанный актив<select value={form.asset_id} onChange={(e) => setForm({ ...form, asset_id: e.target.value })}><option value="">Без актива</option>{assetsQuery.data?.map((asset) => <option value={asset.id} key={asset.id}>{asset.asset_tag} · {asset.name}</option>)}</select></label> : null}
              <label>Начало окна<input type="datetime-local" value={form.planned_start_at} onChange={(e) => setForm({ ...form, planned_start_at: e.target.value })} /></label>
              <label>Окончание окна<input type="datetime-local" value={form.planned_end_at} onChange={(e) => setForm({ ...form, planned_end_at: e.target.value })} /></label>
              <label className="change-checkbox"><input type="checkbox" checked={form.outage_required} onChange={(e) => setForm({ ...form, outage_required: e.target.checked })} /> Требуется простой</label>
              {form.outage_required ? <label>Простой, минут<input type="number" min={0} value={form.outage_minutes} onChange={(e) => setForm({ ...form, outage_minutes: Number(e.target.value) })} /></label> : null}
            </div>
            <label>Описание<textarea required minLength={10} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
            <div className="change-plan-grid">
              <label>Бизнес-обоснование<textarea value={form.business_justification} onChange={(e) => setForm({ ...form, business_justification: e.target.value })} /></label>
              <label>План внедрения<textarea value={form.implementation_plan} onChange={(e) => setForm({ ...form, implementation_plan: e.target.value })} /></label>
              <label>План тестирования<textarea value={form.test_plan} onChange={(e) => setForm({ ...form, test_plan: e.target.value })} /></label>
              <label>План отката<textarea value={form.rollback_plan} onChange={(e) => setForm({ ...form, rollback_plan: e.target.value })} /></label>
              <label>План валидации<textarea value={form.validation_plan} onChange={(e) => setForm({ ...form, validation_plan: e.target.value })} /></label>
            </div>
            <button type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? 'Создаём…' : 'Создать черновик RFC'}</button>
          </form>
        </section>
      ) : null}

      {feedback ? <p className="change-feedback">{feedback}</p> : null}
      {mutationError ? <p className="error-state">{mutationError.message}</p> : null}

      <section className="change-workspace">
        <div className="ticket-table-shell change-register">
          <div className="section-header">
            <div>
              <h2 className="section-title">Реестр RFC</h2>
              <p className="section-subtitle">{listQuery.data?.total ?? 0} изменений</p>
            </div>
          </div>
          {listQuery.isLoading ? <p className="loading-state">Загрузка реестра…</p> : null}
          {listQuery.isError ? <p className="error-state">{listQuery.error.message}</p> : null}
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>RFC</th><th>Тип / риск</th><th>Статус</th><th>Окно</th></tr></thead>
              <tbody>
                {listQuery.data?.items.map((item) => (
                  <tr key={item.id} className={selectedId === item.id ? 'row-selected' : ''} onClick={() => setSelectedId(item.id)}>
                    <td><strong>{item.change_number}</strong><p className="table-subtext">{item.title}</p></td>
                    <td><span className="status-badge">{translate(typeLabels[item.change_type])}</span><p className={`table-subtext risk-${item.risk_level.toLowerCase()}`}>{translate(riskLabels[item.risk_level])} · {item.risk_score}</p></td>
                    <td><span className="status-badge">{statusLabels[item.status] ? translate(statusLabels[item.status]) : item.status}</span><p className="table-subtext">{item.owner_name ?? 'Без владельца'}</p></td>
                    <td>{formatDate(item.planned_start_at)}<p className="table-subtext">{item.asset_count} активов · {item.ticket_count} заявок</p></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {!listQuery.isLoading && !listQuery.isError && !listQuery.data?.items.length ? <p className="empty-state">Изменения не найдены.</p> : null}
          <div className="table-pagination">
            <button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Назад</button>
            <span>Страница {page} из {totalPages}</span>
            <button type="button" className="ghost-button" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>Далее</button>
          </div>
        </div>

        <aside className="asset-detail-panel change-detail">
          {detailQuery.isLoading ? <p className="loading-state">Загрузка карточки…</p> : null}
          {detailQuery.isError ? (
            <div className="state-panel state-panel-error" role="alert">
              <span>Не удалось загрузить выбранный RFC.</span>
              <button type="button" className="ghost-button" onClick={() => void detailQuery.refetch()}>Повторить</button>
            </div>
          ) : null}
          {!change && !detailQuery.isLoading && !detailQuery.isError ? <p className="empty-state">Выберите RFC в реестре.</p> : null}
          {change ? (
            <>
              <div className="section-header">
                <div><p className="eyebrow">{change.change_number}</p><h2 className="section-title">{change.title}</h2></div>
                <span className={`change-risk-badge risk-${change.risk_level.toLowerCase()}`}>{translate(riskLabels[change.risk_level])} · {change.risk_score}</span>
              </div>
              <div className="detail-fields">
                <div><span>Статус</span><strong>{statusLabels[change.status] ? translate(statusLabels[change.status]) : change.status}</strong></div>
                <div><span>Тип</span><strong>{translate(typeLabels[change.change_type])}</strong></div>
                <div><span>Владелец</span><strong>{change.owner_name ?? '—'}</strong></div>
                <div><span>CAB</span><strong>{change.cab_required
                  ? (approvalStatusLabels[change.approval_status]
                      ? translate(approvalStatusLabels[change.approval_status])
                      : change.approval_status)
                  : translate('Предварительно одобрено')}</strong></div>
                <div><span>Окно</span><strong>{formatDate(change.planned_start_at)}</strong></div>
                <div><span>Версия</span><strong>v{change.version}</strong></div>
              </div>
              <p className="change-description">{change.description}</p>
              <EntityCustomFieldsPanel
                entityType="change"
                entityId={change.id}
                tenantId={change.tenant_id}
                compact
              />
              <div className="change-linked-strip">
                {change.assets.map((asset) => <span className="inline-pill" key={asset.id}>{asset.asset_tag} · {asset.name}</span>)}
                {change.tickets.map((ticket) => <span className="inline-pill" key={ticket.id}>{ticket.ticket_number} · {ticket.title}</span>)}
                {!change.assets.length && !change.tickets.length ? <span className="muted">Связи не добавлены</span> : null}
              </div>
              <details className="change-plans"><summary>Контрольные планы</summary>
                {[['Обоснование', change.business_justification], ['Внедрение', change.implementation_plan], ['Тестирование', change.test_plan], ['Откат', change.rollback_plan], ['Валидация', change.validation_plan]].map(([label, value]) => <div key={label}><strong>{label}</strong><p>{value || 'Не заполнено'}</p></div>)}
              </details>
              {permission(session, 'assets.read') ? (
                <CMDBImpactPanel
                  accessToken={token}
                  tenantId={change.tenant_id}
                  rootCiIds={change.assets.map((asset) => asset.id)}
                  entityType="CHANGE"
                  entityId={change.id}
                  entityVersion={change.version}
                  title="Blast radius изменения"
                  compact
                />
              ) : null}

              {change.status === 'APPROVAL_PENDING' && permission(session, 'changes.approve') ? (
                change.requested_by_id === session?.user.id || change.requested_by_email === session?.user.email ? (
                  <section className="change-action-panel">
                    <h3>CAB / ECAB решение</h3>
                    <p className="section-subtitle">Разделение полномочий: решение должен принять другой CAB-участник.</p>
                  </section>
                ) : (
                  <section className="change-action-panel"><h3>CAB / ECAB решение</h3><textarea value={cabComment} onChange={(e) => setCabComment(e.target.value)} placeholder="Обоснование решения" /><div className="change-action-buttons"><button type="button" disabled={cabComment.trim().length < 3 || decisionMutation.isPending} onClick={() => decisionMutation.mutate({ change, decision: 'APPROVED' })}>Одобрить</button><button type="button" className="danger-button" disabled={cabComment.trim().length < 3 || decisionMutation.isPending} onClick={() => decisionMutation.mutate({ change, decision: 'REJECTED' })}>Отклонить</button></div></section>
                )
              ) : null}

              {actions.length ? (
                <section className="change-action-panel">
                  <h3>Следующее действие</h3>
                  {actions.includes('SCHEDULE') ? <div className="change-schedule-grid"><label>Начало<input type="datetime-local" value={scheduleStart} onChange={(e) => setScheduleStart(e.target.value)} /></label><label>Окончание<input type="datetime-local" value={scheduleEnd} onChange={(e) => setScheduleEnd(e.target.value)} /></label></div> : null}
                  <textarea value={actionComment} onChange={(e) => setActionComment(e.target.value)} placeholder="Комментарий / результат / причина (обязательно для закрытия, сбоя, отката и отмены)" />
                  <div className="change-action-buttons">{actions.map((action) => <button type="button" key={action} className={['FAIL', 'ROLLBACK', 'CANCEL'].includes(action) ? 'danger-button' : ''} disabled={transitionMutation.isPending} onClick={() => act(action)}>{transitionLabel(action)}</button>)}</div>
                </section>
              ) : null}

              <section className="change-timeline"><h3>Неизменяемая история</h3>{change.history.map((item) => <article key={item.id}><div><strong>{item.message}</strong><span>{formatDate(item.created_at)}</span></div><p>{item.actor_name} · {item.event_type}{item.from_status ? <> · {statusLabels[item.from_status] ? translate(statusLabels[item.from_status]) : item.from_status} → {statusLabels[item.to_status ?? ''] ? translate(statusLabels[item.to_status ?? '']) : item.to_status}</> : null}</p></article>)}</section>
            </>
          ) : null}
        </aside>
      </section>
    </AppShell></LocalizedContent>
  )
}
