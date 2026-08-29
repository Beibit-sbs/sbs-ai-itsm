import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  createProblem,
  fetchAssets,
  fetchChangesPage,
  fetchKnownErrors,
  fetchProblem,
  fetchProblemsPage,
  fetchProblemSummary,
  fetchTicketsPage,
  transitionProblem,
  type CreateProblemRequest,
  type ProblemDetail,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { canAccessPath } from '../auth/accessControl'
import AppShell from '../components/AppShell'
import CMDBImpactPanel from '../components/CMDBImpactPanel'
import EntityCustomFieldsPanel from '../components/EntityCustomFieldsPanel'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const statusOptions = [
  'ALL',
  'NEW',
  'INVESTIGATING',
  'ROOT_CAUSE_IDENTIFIED',
  'KNOWN_ERROR',
  'RESOLVED',
  'CLOSED',
  'CANCELLED',
]

const statusLabels: Record<string, string> = {
  ALL: 'Все статусы',
  NEW: 'Новая',
  INVESTIGATING: 'Расследование',
  ROOT_CAUSE_IDENTIFIED: 'Причина найдена',
  KNOWN_ERROR: 'Known Error',
  RESOLVED: 'Устранена',
  CLOSED: 'Закрыта',
  CANCELLED: 'Отменена',
}

const actionLabels: Record<string, string> = {
  START_INVESTIGATION: 'Начать расследование',
  IDENTIFY_ROOT_CAUSE: 'Зафиксировать root cause',
  PUBLISH_KNOWN_ERROR: 'Опубликовать Known Error',
  RESOLVE: 'Подтвердить устранение',
  CLOSE: 'Закрыть после проверки',
  REOPEN: 'Переоткрыть',
  RETIRE_KNOWN_ERROR: 'Вывести workaround из обращения',
  CANCEL: 'Отменить запись',
}

type FormState = {
  title: string
  description: string
  problem_type: 'REACTIVE' | 'PROACTIVE'
  service_name: string
  category: string
  impact_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'ENTERPRISE'
  urgency_level: 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'
  detection_source: string
  symptoms: string
  first_observed_at: string
  target_resolution_at: string
  ticket_id: string
  asset_id: string
  change_id: string
}

const emptyForm: FormState = {
  title: '',
  description: '',
  problem_type: 'REACTIVE',
  service_name: '',
  category: '',
  impact_level: 'MEDIUM',
  urgency_level: 'MEDIUM',
  detection_source: '',
  symptoms: '',
  first_observed_at: '',
  target_resolution_at: '',
  ticket_id: '',
  asset_id: '',
  change_id: '',
}

function toIso(value: string) {
  return value ? new Date(value).toISOString() : undefined
}

function permission(session: ReturnType<typeof useAuth>['session'], code: string) {
  return session?.user.role === 'saas_root' || Boolean(session?.user.permissions.includes(code))
}

function nextActions(problem: ProblemDetail, session: ReturnType<typeof useAuth>['session']) {
  const actions: string[] = []
  if (problem.status === 'NEW' && permission(session, 'problems.investigate')) actions.push('START_INVESTIGATION')
  if (problem.status === 'INVESTIGATING' && permission(session, 'problems.investigate')) actions.push('IDENTIFY_ROOT_CAUSE')
  if (['ROOT_CAUSE_IDENTIFIED', 'KNOWN_ERROR'].includes(problem.status) && permission(session, 'problems.publish_known_error')) actions.push('PUBLISH_KNOWN_ERROR')
  if (['ROOT_CAUSE_IDENTIFIED', 'KNOWN_ERROR'].includes(problem.status) && permission(session, 'problems.resolve')) actions.push('RESOLVE')
  if (problem.status === 'RESOLVED' && permission(session, 'problems.resolve')) actions.push('CLOSE', 'REOPEN')
  if (problem.status === 'CLOSED' && permission(session, 'problems.resolve')) actions.push('REOPEN')
  if (['RESOLVED', 'CLOSED'].includes(problem.status) && problem.workaround_status === 'PUBLISHED' && permission(session, 'problems.publish_known_error')) actions.push('RETIRE_KNOWN_ERROR')
  if (['NEW', 'INVESTIGATING'].includes(problem.status) && permission(session, 'problems.update')) actions.push('CANCEL')
  return actions
}

export default function ProblemsPage() {
  const { session } = useAuth()
  const { formatDateTime, formatNumber, translate } = useTenantExperience()
  const formatDate = (value: string | null | undefined) => formatDateTime(value)
  const formatCount = (value: number | null | undefined) => value == null ? '—' : formatNumber(value)
  const token = session?.access_token ?? ''
  const canCreate = permission(session, 'problems.create')
  const canReadTicketCandidates = Boolean(
    session?.user && canAccessPath(session.user, '/tickets'),
  )
  const canReadAssets = permission(session, 'assets.read')
  const canReadChanges = permission(session, 'changes.read')
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [view, setView] = useState<'REGISTER' | 'KEDB'>('REGISTER')
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [priorityFilter, setPriorityFilter] = useState('ALL')
  const [page, setPage] = useState(1)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [form, setForm] = useState<FormState>(emptyForm)
  const [selectedAction, setSelectedAction] = useState('')
  const [rootCause, setRootCause] = useState('')
  const [knownErrorTitle, setKnownErrorTitle] = useState('')
  const [workaround, setWorkaround] = useState('')
  const [resolutionSummary, setResolutionSummary] = useState('')
  const [validationSummary, setValidationSummary] = useState('')
  const [actionComment, setActionComment] = useState('')
  const [feedback, setFeedback] = useState<string | null>(null)

  useEffect(() => {
    const linkedProblemId = searchParams.get('problem')
    if (!linkedProblemId) return
    setView('REGISTER')
    setSelectedId(linkedProblemId)
    const next = new URLSearchParams(searchParams)
    next.delete('problem')
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const listQuery = useQuery({
    queryKey: ['problems', token, q, statusFilter, typeFilter, priorityFilter, page],
    queryFn: () => fetchProblemsPage(token, {
      q: q || undefined,
      status: statusFilter,
      problem_type: typeFilter,
      priority: priorityFilter,
      page,
      page_size: 20,
    }),
    enabled: Boolean(token && view === 'REGISTER'),
  })
  const summaryQuery = useQuery({
    queryKey: ['problem-summary', token],
    queryFn: () => fetchProblemSummary(token),
    enabled: Boolean(token),
  })
  const knownErrorsQuery = useQuery({
    queryKey: ['known-errors', token, q, page],
    queryFn: () => fetchKnownErrors(token, { q: q || undefined, page, page_size: 20 }),
    enabled: Boolean(token && view === 'KEDB'),
  })
  const detailQuery = useQuery({
    queryKey: ['problem-detail', token, selectedId],
    queryFn: () => fetchProblem(token, selectedId ?? ''),
    enabled: Boolean(token && selectedId),
  })
  const ticketsQuery = useQuery({
    queryKey: ['problem-create-tickets', token],
    queryFn: () => fetchTicketsPage(token, { page_size: 100 }),
    enabled: Boolean(token && showCreate && canCreate && canReadTicketCandidates),
  })
  const assetsQuery = useQuery({
    queryKey: ['problem-create-assets', token],
    queryFn: () => fetchAssets(token, { page_size: 100 }),
    enabled: Boolean(token && showCreate && canCreate && canReadAssets),
  })
  const changesQuery = useQuery({
    queryKey: ['problem-create-changes', token],
    queryFn: () => fetchChangesPage(token, { page_size: 100 }),
    enabled: Boolean(token && showCreate && canCreate && canReadChanges),
  })

  useEffect(() => {
    const first = listQuery.data?.items[0]
    if (!selectedId && first) setSelectedId(first.id)
  }, [listQuery.data, selectedId])

  const problem = detailQuery.data
  const actions = useMemo(() => problem ? nextActions(problem, session) : [], [problem, session])

  useEffect(() => {
    setSelectedAction((current) => actions.includes(current) ? current : (actions[0] ?? ''))
    if (problem) {
      setRootCause(problem.root_cause ?? '')
      setKnownErrorTitle(problem.known_error_title ?? problem.title)
      setWorkaround(problem.workaround ?? '')
    }
  }, [actions, problem])

  async function refreshProblem(updated: ProblemDetail) {
    setSelectedId(updated.id)
    queryClient.setQueryData(['problem-detail', token, updated.id], updated)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['problems'] }),
      queryClient.invalidateQueries({ queryKey: ['problem-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['known-errors'] }),
    ])
  }

  const createMutation = useMutation({
    mutationFn: (payload: CreateProblemRequest) => createProblem(token, payload),
    onSuccess: async (created) => {
      await refreshProblem(created)
      setForm(emptyForm)
      setShowCreate(false)
      setFeedback(`${created.problem_number} ${translate('создана')}`)
    },
  })
  const transitionMutation = useMutation({
    mutationFn: ({ current, action }: { current: ProblemDetail; action: string }) => transitionProblem(
      token,
      current.id,
      {
        action,
        expected_version: current.version,
        comment: actionComment || undefined,
        root_cause: action === 'IDENTIFY_ROOT_CAUSE' ? rootCause : undefined,
        known_error_title: action === 'PUBLISH_KNOWN_ERROR' ? knownErrorTitle : undefined,
        workaround: action === 'PUBLISH_KNOWN_ERROR' ? workaround : undefined,
        resolution_summary: action === 'RESOLVE' ? resolutionSummary : undefined,
        validation_summary: action === 'CLOSE' ? validationSummary : undefined,
      },
    ),
    onSuccess: async (updated) => {
      await refreshProblem(updated)
      setResolutionSummary('')
      setValidationSummary('')
      setActionComment('')
      setFeedback(`${updated.problem_number}: ${translate(statusLabels[updated.status] ?? updated.status)}`)
    },
  })

  function submitCreate(event: FormEvent) {
    event.preventDefault()
    createMutation.mutate({
      title: form.title.trim(),
      description: form.description.trim(),
      problem_type: form.problem_type,
      service_name: form.service_name.trim() || undefined,
      category: form.category.trim() || undefined,
      impact_level: form.impact_level,
      urgency_level: form.urgency_level,
      detection_source: form.detection_source.trim() || undefined,
      symptoms: form.symptoms.trim(),
      first_observed_at: toIso(form.first_observed_at),
      target_resolution_at: toIso(form.target_resolution_at),
      ticket_ids: form.ticket_id ? [form.ticket_id] : [],
      asset_ids: form.asset_id ? [form.asset_id] : [],
      change_ids: form.change_id ? [form.change_id] : [],
    })
  }

  function executeAction() {
    if (!problem || !selectedAction) return
    transitionMutation.mutate({ current: problem, action: selectedAction })
  }

  function openKnownError(problemId: string) {
    setSelectedId(problemId)
    setView('REGISTER')
    setQ('')
  }

  const totalPages = Math.max(1, Math.ceil(
    ((view === 'REGISTER' ? listQuery.data?.total : knownErrorsQuery.data?.total) ?? 0) / 20,
  ))
  const mutationError = createMutation.error || transitionMutation.error

  return (
    <LocalizedContent>
    <AppShell
      title="Problem Management"
      subtitle="RCA, повторяемость инцидентов, Known Error Database и контроль эффективности исправлений"
    >
      <section className="change-summary-grid problem-summary-grid">
        <article className="metric-card"><span>Открыто</span><strong>{formatCount(summaryQuery.data?.open_problems)}</strong></article>
        <article className="metric-card"><span>Расследуется</span><strong>{formatCount(summaryQuery.data?.investigating)}</strong></article>
        <article className="metric-card"><span>Known Errors</span><strong>{formatCount(summaryQuery.data?.known_errors)}</strong></article>
        <article className="metric-card"><span>Просрочено</span><strong>{formatCount(summaryQuery.data?.overdue)}</strong></article>
        <article className="metric-card"><span>Повторяемые</span><strong>{formatCount(summaryQuery.data?.recurring_problems)}</strong></article>
        <article className="metric-card"><span>Критические P1</span><strong>{formatCount(summaryQuery.data?.critical_open)}</strong></article>
      </section>
      {summaryQuery.isError ? (
        <div className="state-panel state-panel-error" role="alert">
          <span>Сводка Problem Management временно недоступна.</span>
          <button type="button" className="ghost-button" onClick={() => void summaryQuery.refetch()}>Повторить</button>
        </div>
      ) : null}

      <section className="ticket-table-shell change-toolbar problem-toolbar">
        <div className="problem-view-switch" role="tablist" aria-label="Problem Management views">
          <button type="button" className={view === 'REGISTER' ? 'active' : ''} onClick={() => { setView('REGISTER'); setPage(1) }}>Реестр Problems</button>
          <button type="button" className={view === 'KEDB' ? 'active' : ''} onClick={() => { setView('KEDB'); setPage(1) }}>Known Error Database</button>
        </div>
        <input value={q} onChange={(event) => { setQ(event.target.value); setPage(1) }} placeholder={view === 'KEDB' ? 'Симптом, workaround, сервис…' : 'PRB, название, сервис…'} />
        {view === 'REGISTER' ? (
          <>
            <select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1) }}>{statusOptions.map((item) => <option value={item} key={item}>{translate(statusLabels[item])}</option>)}</select>
            <select value={typeFilter} onChange={(event) => { setTypeFilter(event.target.value); setPage(1) }}><option value="ALL">Все типы</option><option value="REACTIVE">Reactive</option><option value="PROACTIVE">Proactive</option></select>
            <select value={priorityFilter} onChange={(event) => { setPriorityFilter(event.target.value); setPage(1) }}><option value="ALL">Все приоритеты</option>{['P1', 'P2', 'P3', 'P4'].map((item) => <option value={item} key={item}>{item}</option>)}</select>
            {canCreate ? <button type="button" onClick={() => setShowCreate((value) => !value)}>{showCreate ? 'Закрыть форму' : 'Новая Problem'}</button> : null}
          </>
        ) : null}
      </section>

      {feedback ? <p className="change-feedback">{feedback}<button type="button" onClick={() => setFeedback(null)}>×</button></p> : null}
      {mutationError ? <p className="error-state">{mutationError.message}</p> : null}

      {showCreate && canCreate ? (
        <form className="ticket-table-shell change-create-panel problem-create-form" onSubmit={submitCreate}>
          <div className="section-header"><div><p className="eyebrow">Problem Control</p><h2 className="section-title">Новая Problem Record</h2></div><span>Priority рассчитывается сервером</span></div>
          <div className="change-form-grid">
            <label className="wide-field">Название<input required minLength={3} value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} /></label>
            <label>Тип<select value={form.problem_type} onChange={(event) => setForm({ ...form, problem_type: event.target.value as FormState['problem_type'] })}><option value="REACTIVE">Reactive</option><option value="PROACTIVE">Proactive</option></select></label>
            <label>Сервис<input value={form.service_name} onChange={(event) => setForm({ ...form, service_name: event.target.value })} /></label>
            <label>Категория<input value={form.category} onChange={(event) => setForm({ ...form, category: event.target.value })} /></label>
            <label>Impact<select value={form.impact_level} onChange={(event) => setForm({ ...form, impact_level: event.target.value as FormState['impact_level'] })}>{['LOW', 'MEDIUM', 'HIGH', 'ENTERPRISE'].map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
            <label>Urgency<select value={form.urgency_level} onChange={(event) => setForm({ ...form, urgency_level: event.target.value as FormState['urgency_level'] })}>{['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'].map((item) => <option value={item} key={item}>{item}</option>)}</select></label>
            <label>Источник обнаружения<input value={form.detection_source} onChange={(event) => setForm({ ...form, detection_source: event.target.value })} /></label>
            <label>Первое наблюдение<input type="datetime-local" value={form.first_observed_at} onChange={(event) => setForm({ ...form, first_observed_at: event.target.value })} /></label>
            <label>Target resolution<input type="datetime-local" value={form.target_resolution_at} onChange={(event) => setForm({ ...form, target_resolution_at: event.target.value })} /></label>
            <label className="wide-field">Описание<textarea required minLength={10} value={form.description} onChange={(event) => setForm({ ...form, description: event.target.value })} /></label>
            <label className="wide-field">Наблюдаемые симптомы<textarea required minLength={10} value={form.symptoms} onChange={(event) => setForm({ ...form, symptoms: event.target.value })} /></label>
            {canReadTicketCandidates ? <label>Связанный инцидент<select value={form.ticket_id} onChange={(event) => setForm({ ...form, ticket_id: event.target.value })}><option value="">Без инцидента</option>{ticketsQuery.data?.items.map((item) => <option key={item.id} value={item.id}>{item.ticket_number} · {item.title}</option>)}</select></label> : null}
            {canReadAssets ? <label>Затронутый актив<select value={form.asset_id} onChange={(event) => setForm({ ...form, asset_id: event.target.value })}><option value="">Без актива</option>{assetsQuery.data?.map((item) => <option key={item.id} value={item.id}>{item.asset_tag} · {item.name}</option>)}</select></label> : null}
            {canReadChanges ? <label>Corrective RFC<select value={form.change_id} onChange={(event) => setForm({ ...form, change_id: event.target.value })}><option value="">Без RFC</option>{changesQuery.data?.items.map((item) => <option key={item.id} value={item.id}>{item.change_number} · {item.title}</option>)}</select></label> : null}
          </div>
          <div className="form-actions"><button type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? 'Создание…' : 'Создать Problem'}</button></div>
        </form>
      ) : null}

      {view === 'KEDB' ? (
        <section className="known-error-grid">
          {knownErrorsQuery.isPending ? <div className="empty-state">Загрузка KEDB…</div> : null}
          {knownErrorsQuery.isError ? (
            <div className="state-panel state-panel-error" role="alert">
              <span>Не удалось загрузить Known Error Database.</span>
              <button type="button" className="ghost-button" onClick={() => void knownErrorsQuery.refetch()}>Повторить</button>
            </div>
          ) : null}
          {knownErrorsQuery.data?.items.map((item) => (
            <article className="known-error-card" key={item.id}>
              <div className="known-error-card-head"><div><span>{item.problem_number} · {item.service_name ?? 'Сервис не указан'}</span><h2>{item.known_error_title}</h2></div><span className={`problem-priority ${item.priority.toLowerCase()}`}>{item.priority}</span></div>
              <p><strong>Симптомы:</strong> {item.symptoms}</p>
              <div className="known-error-workaround"><strong>Подтверждённый workaround</strong><p>{item.workaround}</p></div>
              <div className="known-error-meta"><span>{formatNumber(item.incident_count)} связанных инцидента</span><span>Опубликовано {formatDate(item.published_at)}</span><button type="button" onClick={() => openKnownError(item.id)}>Открыть RCA</button></div>
            </article>
          ))}
          {!knownErrorsQuery.isPending && !knownErrorsQuery.isError && !knownErrorsQuery.data?.items.length ? <div className="empty-state">Активные Known Errors не найдены.</div> : null}
        </section>
      ) : (
        <section className="change-workspace problem-workspace">
          <div className="ticket-table-shell change-register">
            <div className="ticket-table-wrap"><table className="ticket-table problem-table"><thead><tr><th>Problem</th><th>Статус</th><th>Priority</th><th>Связи</th><th>Возраст</th></tr></thead><tbody>
              {listQuery.data?.items.map((item) => (
                <tr key={item.id} className={selectedId === item.id ? 'row-selected' : ''} onClick={() => setSelectedId(item.id)}>
                  <td><strong>{item.problem_number}</strong><p>{item.title}</p><span>{item.service_name ?? 'Без сервиса'} · {item.problem_type}</span></td>
                  <td><span className="status-badge">{translate(statusLabels[item.status] ?? item.status)}</span>{item.is_known_error ? <small className="known-error-chip">KEDB</small> : null}</td>
                  <td><span className={`problem-priority ${item.priority.toLowerCase()}`}>{item.priority}</span><small>{item.impact_level}/{item.urgency_level}</small></td>
                  <td><strong>{formatNumber(item.incident_count)}</strong><small>инц. · {formatNumber(item.asset_count)} CI · {formatNumber(item.change_count)} RFC</small></td>
                  <td className={item.overdue ? 'problem-overdue' : ''}><strong>{formatNumber(item.age_days)} дн.</strong><small>{item.overdue ? 'Просрочено' : formatDate(item.target_resolution_at)}</small></td>
                </tr>
              ))}
            </tbody></table></div>
            {listQuery.isPending ? <div className="empty-state">Загрузка Problem register…</div> : null}
            {listQuery.isError ? (
              <div className="state-panel state-panel-error" role="alert">
                <span>Не удалось загрузить реестр Problems.</span>
                <button type="button" className="ghost-button" onClick={() => void listQuery.refetch()}>Повторить</button>
              </div>
            ) : null}
            {!listQuery.isPending && !listQuery.isError && !listQuery.data?.items.length ? <div className="empty-state">Problems по выбранным условиям не найдены.</div> : null}
          </div>

          <aside className="asset-detail-panel change-detail problem-detail">
            {detailQuery.isPending ? <div className="empty-state">Загрузка RCA…</div> : null}
            {detailQuery.isError ? (
              <div className="state-panel state-panel-error" role="alert">
                <span>Не удалось загрузить RCA выбранной проблемы.</span>
                <button type="button" className="ghost-button" onClick={() => void detailQuery.refetch()}>Повторить</button>
              </div>
            ) : null}
            {problem ? (
              <>
                <div className="change-detail-head"><div><span>{problem.problem_number} · v{problem.version}</span><h2>{problem.title}</h2><p>{problem.description}</p></div><div><span className={`problem-priority ${problem.priority.toLowerCase()}`}>{problem.priority}</span><span className="status-badge">{translate(statusLabels[problem.status] ?? problem.status)}</span></div></div>
                <div className="detail-fields problem-facts"><div><span>Владелец</span><strong>{problem.owner_name ?? 'Не назначен'}</strong></div><div><span>Сервис</span><strong>{problem.service_name ?? '—'}</strong></div><div><span>Возраст</span><strong>{formatNumber(problem.age_days)} дн.</strong></div><div><span>Target resolution</span><strong className={problem.overdue ? 'problem-overdue' : ''}>{formatDate(problem.target_resolution_at)}</strong></div></div>
                <section className="problem-evidence"><div><span>Симптомы</span><p>{problem.symptoms}</p></div><div><span>Root cause</span><p>{problem.root_cause ?? 'Расследование ещё не завершено'}</p></div>{problem.workaround ? <div className="known-error-workaround"><span>Workaround · {problem.workaround_status}</span><p>{problem.workaround}</p></div> : null}{problem.resolution_summary ? <div><span>Устранение</span><p>{problem.resolution_summary}</p></div> : null}{problem.validation_summary ? <div><span>Проверка эффективности</span><p>{problem.validation_summary}</p></div> : null}</section>
                <EntityCustomFieldsPanel
                  entityType="problem"
                  entityId={problem.id}
                  tenantId={problem.tenant_id}
                  compact
                />
                <div className="change-linked-strip">{problem.tickets.map((item) => <span className="inline-pill" key={item.id}>{item.ticket_number} · {item.title}</span>)}{problem.assets.map((item) => <span className="inline-pill" key={item.id}>{item.asset_tag} · {item.name}</span>)}{problem.changes.map((item) => <span className="inline-pill" key={item.id}>{item.change_number} · {item.title}</span>)}{!problem.tickets.length && !problem.assets.length && !problem.changes.length ? <span className="muted">Связи не добавлены</span> : null}</div>
                {permission(session, 'assets.read') ? (
                  <CMDBImpactPanel
                    accessToken={token}
                    tenantId={problem.tenant_id}
                    rootCiIds={problem.assets.map((asset) => asset.id)}
                    entityType="PROBLEM"
                    entityId={problem.id}
                    entityVersion={problem.version}
                    title="Влияние проблемы"
                    compact
                  />
                ) : null}

                {actions.length ? (
                  <section className="change-action-panel problem-action-panel">
                    <h3>Управление lifecycle</h3>
                    <label>Действие<select value={selectedAction} onChange={(event) => setSelectedAction(event.target.value)}>{actions.map((action) => <option value={action} key={action}>{translate(actionLabels[action])}</option>)}</select></label>
                    {selectedAction === 'IDENTIFY_ROOT_CAUSE' ? <textarea value={rootCause} onChange={(event) => setRootCause(event.target.value)} placeholder="Проверенная первопричина и доказательства" /> : null}
                    {selectedAction === 'PUBLISH_KNOWN_ERROR' ? <><input value={knownErrorTitle} onChange={(event) => setKnownErrorTitle(event.target.value)} placeholder="Название Known Error" /><textarea value={workaround} onChange={(event) => setWorkaround(event.target.value)} placeholder="Пошаговый безопасный workaround" /></> : null}
                    {selectedAction === 'RESOLVE' ? <textarea value={resolutionSummary} onChange={(event) => setResolutionSummary(event.target.value)} placeholder="Что исправлено и каким RFC" /> : null}
                    {selectedAction === 'CLOSE' ? <textarea value={validationSummary} onChange={(event) => setValidationSummary(event.target.value)} placeholder="Доказательства отсутствия повторений и контрольный период" /> : null}
                    {['REOPEN', 'RETIRE_KNOWN_ERROR', 'CANCEL'].includes(selectedAction) ? <textarea value={actionComment} onChange={(event) => setActionComment(event.target.value)} placeholder="Обязательное обоснование" /> : null}
                    <button type="button" className={['REOPEN', 'RETIRE_KNOWN_ERROR', 'CANCEL'].includes(selectedAction) ? 'danger-button' : ''} disabled={transitionMutation.isPending} onClick={executeAction}>{transitionMutation.isPending ? 'Сохранение…' : actionLabels[selectedAction] ? translate(actionLabels[selectedAction]) : selectedAction}</button>
                  </section>
                ) : null}

                <section className="change-timeline"><h3>Неизменяемая история RCA</h3>{problem.history.map((item) => <article key={item.id}><div><strong>{item.message}</strong><span>{formatDate(item.created_at)}</span></div><p>{item.actor_name} · {item.event_type}{item.from_status ? ` · ${item.from_status} → ${item.to_status}` : ''}</p></article>)}</section>
              </>
            ) : null}
          </aside>
        </section>
      )}

      <div className="table-pagination"><button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((value) => value - 1)}>Назад</button><span>{formatNumber(page)} / {formatNumber(totalPages)}</span><button type="button" className="ghost-button" disabled={page >= totalPages} onClick={() => setPage((value) => value + 1)}>Вперёд</button></div>
    </AppShell>
    </LocalizedContent>
  )
}
