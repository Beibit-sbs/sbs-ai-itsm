import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  addCABAgendaItem,
  approveChangePIR,
  createCABMeeting,
  createChangeTask,
  createChangeWindow,
  createStandardChangeModel,
  decideCABAgendaItem,
  fetchCABMeetings,
  fetchChangeAnalytics,
  fetchChangeCalendar,
  fetchChangePIR,
  fetchChangeReadiness,
  fetchChangesPage,
  fetchChangeTasks,
  fetchChangeWindows,
  fetchStandardChangeModels,
  fetchTenants,
  instantiateStandardChange,
  saveChangePIR,
  submitChangePIR,
  updateCABMeeting,
  updateChangeTask,
  updateChangeWindow,
  updateStandardChangeModel,
  type CABMeeting,
  type ChangePIR,
  type ChangeTask,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { useLocalizedDefaultState } from '../experience/useLocalizedDefaultState'

type View = 'CALENDAR' | 'EXECUTION' | 'MODELS' | 'CAB' | 'ANALYTICS'

const views: Array<{ key: View; label: string }> = [
  { key: 'CALENDAR', label: 'Календарь' },
  { key: 'EXECUTION', label: 'Исполнение и PIR' },
  { key: 'MODELS', label: 'Standard Change' },
  { key: 'CAB', label: 'CAB / ECAB' },
  { key: 'ANALYTICS', label: 'Результативность' },
]

function localInput(value: Date) {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16)
}

function calendarBounds(cursor: Date) {
  const start = new Date(cursor.getFullYear(), cursor.getMonth(), 1)
  const end = new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1)
  return { start, end }
}

function calendarDays(cursor: Date) {
  const { start } = calendarBounds(cursor)
  const mondayOffset = (start.getDay() + 6) % 7
  const first = new Date(start)
  first.setDate(first.getDate() - mondayOffset)
  return Array.from({ length: 42 }, (_, index) => {
    const date = new Date(first)
    date.setDate(first.getDate() + index)
    return date
  })
}

export default function ChangeGovernancePage() {
  const { session } = useAuth()
  const { formatDateTime: formatDate, translate, uiLocale } = useTenantExperience()
  const token = session?.access_token ?? ''
  const root = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const hasPermission = (code: string) => root || permissions.has(code)
  const canCreate = hasPermission('changes.create')
  const canUpdate = hasPermission('changes.update')
  const canSchedule = hasPermission('changes.schedule')
  const canApprove = hasPermission('changes.approve')
  const canExecute = hasPermission('changes.execute')
  const queryClient = useQueryClient()
  const [view, setView] = useState<View>('CALENDAR')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [monthCursor, setMonthCursor] = useState(() => new Date())
  const [windowName, setWindowName] = useLocalizedDefaultState('Плановое окно')
  const [windowType, setWindowType] = useState<'MAINTENANCE' | 'BLACKOUT'>('MAINTENANCE')
  const [windowStart, setWindowStart] = useState(() => localInput(new Date(Date.now() + 86_400_000)))
  const [windowEnd, setWindowEnd] = useState(() => localInput(new Date(Date.now() + 90_000_000)))
  const [windowService, setWindowService] = useState('')
  const [windowEnvironment, setWindowEnvironment] = useState('PRODUCTION')
  const [windowTimezone, setWindowTimezone] = useState('Asia/Almaty')
  const [modelCode, setModelCode] = useState('STD-SAFE-RESTART')
  const [modelName, setModelName] = useLocalizedDefaultState('Безопасный перезапуск сервиса')
  const [modelService, setModelService] = useState('')
  const [modelDuration, setModelDuration] = useState(30)
  const [selectedChangeId, setSelectedChangeId] = useState('')
  const [taskType, setTaskType] = useState<ChangeTask['task_type']>('IMPLEMENTATION')
  const [taskTitle, setTaskTitle] = useState('')
  const [taskEvidence, setTaskEvidence] = useState<Record<string, string>>({})
  const [pirOutcome, setPirOutcome] = useState<ChangePIR['outcome']>('SUCCESS')
  const [pirImpact, setPirImpact] = useLocalizedDefaultState('Изменение выполнено в согласованных пределах.')
  const [pirLessons, setPirLessons] = useLocalizedDefaultState('Контрольные шаги и валидация сработали ожидаемо.')
  const [pirApprovalComment, setPirApprovalComment] = useLocalizedDefaultState('Результат и доказательства PIR подтверждены.')
  const [meetingTitle, setMeetingTitle] = useLocalizedDefaultState('Еженедельный CAB')
  const [meetingType, setMeetingType] = useState<'CAB' | 'ECAB'>('CAB')
  const [meetingAt, setMeetingAt] = useState(() => localInput(new Date(Date.now() + 86_400_000)))
  const [selectedMeetingId, setSelectedMeetingId] = useState('')
  const [agendaChangeId, setAgendaChangeId] = useState('')
  const scopedTenant = root ? tenantId || undefined : undefined
  const createBlocked = root && !tenantId
  const { start: monthStart, end: monthEnd } = calendarBounds(monthCursor)

  const tenantsQuery = useQuery({
    queryKey: ['tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && root),
  })
  const calendarQuery = useQuery({
    queryKey: ['change-calendar', token, scopedTenant, monthStart.toISOString(), monthEnd.toISOString()],
    queryFn: () => fetchChangeCalendar(token, monthStart.toISOString(), monthEnd.toISOString(), scopedTenant),
    enabled: Boolean(token),
  })
  const windowsQuery = useQuery({
    queryKey: ['change-windows', token, scopedTenant],
    queryFn: () => fetchChangeWindows(token, scopedTenant),
    enabled: Boolean(token),
  })
  const modelsQuery = useQuery({
    queryKey: ['standard-change-models', token, scopedTenant],
    queryFn: () => fetchStandardChangeModels(token, scopedTenant),
    enabled: Boolean(token),
  })
  const changesQuery = useQuery({
    queryKey: ['governance-changes', token, scopedTenant],
    queryFn: () => fetchChangesPage(token, { page_size: 100, tenant_id: scopedTenant }),
    enabled: Boolean(token),
  })
  const approvalQueueQuery = useQuery({
    queryKey: ['governance-approval-queue', token, scopedTenant],
    queryFn: () =>
      fetchChangesPage(token, {
        status: 'APPROVAL_PENDING',
        page_size: 100,
        tenant_id: scopedTenant,
      }),
    enabled: Boolean(token),
  })
  const tasksQuery = useQuery({
    queryKey: ['change-tasks', token, selectedChangeId],
    queryFn: () => fetchChangeTasks(token, selectedChangeId),
    enabled: Boolean(token && selectedChangeId),
  })
  const readinessQuery = useQuery({
    queryKey: ['change-readiness', token, selectedChangeId],
    queryFn: () => fetchChangeReadiness(token, selectedChangeId),
    enabled: Boolean(token && selectedChangeId),
  })
  const pirQuery = useQuery({
    queryKey: ['change-pir', token, selectedChangeId],
    queryFn: () => fetchChangePIR(token, selectedChangeId),
    enabled: Boolean(token && selectedChangeId),
    retry: false,
  })
  const meetingsQuery = useQuery({
    queryKey: ['cab-meetings', token, scopedTenant],
    queryFn: () => fetchCABMeetings(token, scopedTenant),
    enabled: Boolean(token),
  })
  const analyticsQuery = useQuery({
    queryKey: ['change-analytics', token, scopedTenant],
    queryFn: () => fetchChangeAnalytics(token, scopedTenant),
    enabled: Boolean(token),
  })

  const selectedChange = (changesQuery.data?.items ?? []).find((item) => item.id === selectedChangeId)
  const selectedMeeting = (meetingsQuery.data ?? []).find((item) => item.id === selectedMeetingId)
  const days = useMemo(() => calendarDays(monthCursor), [monthCursor])

  const refreshCalendar = async () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['change-calendar'] }),
    queryClient.invalidateQueries({ queryKey: ['change-windows'] }),
  ])
  const refreshExecution = async () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['change-tasks'] }),
    queryClient.invalidateQueries({ queryKey: ['change-readiness'] }),
    queryClient.invalidateQueries({ queryKey: ['change-pir'] }),
    queryClient.invalidateQueries({ queryKey: ['governance-changes'] }),
  ])

  const windowCreateMutation = useMutation({
    mutationFn: () => createChangeWindow(token, {
      tenant_id: scopedTenant,
      name: windowName,
      window_type: windowType,
      starts_at: new Date(windowStart).toISOString(),
      ends_at: new Date(windowEnd).toISOString(),
      timezone: windowTimezone,
      services: windowService ? [windowService] : [],
      asset_ids: [],
      environments: windowEnvironment ? [windowEnvironment] : [],
      is_active: true,
    }),
    onSuccess: refreshCalendar,
  })
  const windowToggleMutation = useMutation({
    mutationFn: (item: NonNullable<typeof windowsQuery.data>[number]) =>
      updateChangeWindow(token, item.id, { expected_version: item.version, is_active: !item.is_active }),
    onSuccess: refreshCalendar,
  })
  const modelCreateMutation = useMutation({
    mutationFn: () => {
      const now = new Date()
      const review = new Date(now.getTime() + 90 * 86_400_000)
      const expiry = new Date(now.getTime() + 365 * 86_400_000)
      return createStandardChangeModel(token, {
        tenant_id: scopedTenant,
        code: modelCode,
        name: modelName,
        description: translate('Повторяемое низкорисковое изменение с проверенным планом и откатом.'),
        service_name: modelService || undefined,
        environment: 'PRODUCTION',
        default_duration_minutes: modelDuration,
        implementation_plan: translate('Проверить состояние, уведомить владельца, выполнить контролируемый перезапуск.'),
        test_plan: translate('Проверить health endpoint и синтетические транзакции до начала.'),
        rollback_plan: translate('Вернуть предыдущую конфигурацию и восстановить экземпляр сервиса.'),
        validation_plan: translate('Проверить SLO, журналы ошибок и подтверждение владельца сервиса.'),
        task_templates: [
          { type: 'IMPLEMENTATION', title: translate('Выполнить проверенный план'), required: true },
          { type: 'VALIDATION', title: translate('Подтвердить SLO и health checks'), required: true },
          { type: 'ROLLBACK', title: translate('Проверить готовность отката'), required: false },
        ],
        scope: { maximum_assets: 1 },
        review_due_at: review.toISOString(),
        preauthorized_until: expiry.toISOString(),
        is_active: true,
      })
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['standard-change-models'] }),
  })
  const modelToggleMutation = useMutation({
    mutationFn: (item: NonNullable<typeof modelsQuery.data>[number]) =>
      updateStandardChangeModel(token, item.id, { expected_version: item.version, is_active: !item.is_active }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['standard-change-models'] }),
  })
  const instantiateMutation = useMutation({
    mutationFn: (modelId: string) => instantiateStandardChange(token, modelId, {}),
    onSuccess: async (change) => {
      setSelectedChangeId(change.id)
      setView('EXECUTION')
      await queryClient.invalidateQueries({ queryKey: ['governance-changes'] })
    },
  })
  const taskCreateMutation = useMutation({
    mutationFn: () => createChangeTask(token, selectedChangeId, {
      task_type: taskType,
      title: taskTitle,
      is_required: true,
    }),
    onSuccess: async () => {
      setTaskTitle('')
      await refreshExecution()
    },
  })
  const taskUpdateMutation = useMutation({
    mutationFn: ({ item, status }: { item: ChangeTask; status: ChangeTask['status'] }) =>
      updateChangeTask(token, selectedChangeId, item.id, {
        expected_version: item.version,
        status,
        evidence: taskEvidence[item.id] || `${translate('Подтверждено оператором:')} ${status}`,
      }),
    onSuccess: refreshExecution,
  })
  const pirSaveMutation = useMutation({
    mutationFn: () => saveChangePIR(token, selectedChangeId, {
      expected_version: pirQuery.data?.version,
      outcome: pirOutcome,
      objectives_met: pirOutcome === 'SUCCESS',
      actual_impact: pirImpact,
      actual_outage_minutes: 0,
      incidents_caused: 0,
      lessons_learned: pirLessons,
      follow_up_actions: [],
    }),
    onSuccess: refreshExecution,
  })
  const pirSubmitMutation = useMutation({
    mutationFn: (item: ChangePIR) => submitChangePIR(token, selectedChangeId, item.version),
    onSuccess: refreshExecution,
  })
  const pirApproveMutation = useMutation({
    mutationFn: (item: ChangePIR) => approveChangePIR(token, selectedChangeId, item.version, pirApprovalComment),
    onSuccess: refreshExecution,
  })
  const meetingCreateMutation = useMutation({
    mutationFn: () => createCABMeeting(token, {
      tenant_id: scopedTenant,
      title: meetingTitle,
      meeting_type: meetingType,
      scheduled_at: new Date(meetingAt).toISOString(),
      duration_minutes: 60,
      participant_user_ids: [],
    }),
    onSuccess: async (item) => {
      setSelectedMeetingId(item.id)
      await queryClient.invalidateQueries({ queryKey: ['cab-meetings'] })
    },
  })
  const agendaAddMutation = useMutation({
    mutationFn: () => addCABAgendaItem(token, selectedMeetingId, {
      change_id: agendaChangeId,
      recommendation: translate('Рассмотреть готовность, риск, окно и план отката.'),
    }),
    onSuccess: async () => {
      setAgendaChangeId('')
      await queryClient.invalidateQueries({ queryKey: ['cab-meetings'] })
    },
  })
  const meetingStatusMutation = useMutation({
    mutationFn: ({ meeting, status }: { meeting: CABMeeting; status: CABMeeting['status'] }) =>
      updateCABMeeting(token, meeting.id, {
        expected_version: meeting.version,
        status,
        minutes: status === 'COMPLETED' ? translate('Решения и доказательства зафиксированы по каждому пункту повестки.') : undefined,
      }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['cab-meetings'] }),
  })
  const agendaDecisionMutation = useMutation({
    mutationFn: ({ agendaId, decision }: { agendaId: string; decision: 'APPROVED' | 'REJECTED' }) =>
      decideCABAgendaItem(token, agendaId, {
        decision,
        comment: decision === 'APPROVED' ? translate('CAB подтвердил риск, окно и план отката.') : translate('CAB отклонил RFC до устранения замечаний.'),
        evidence: { quorum_confirmed: true, conflict_reviewed: true, rollback_reviewed: true },
      }),
    onSuccess: async () => Promise.all([
      queryClient.invalidateQueries({ queryKey: ['cab-meetings'] }),
      queryClient.invalidateQueries({ queryKey: ['governance-approval-queue'] }),
    ]),
  })

  const mutations = [
    windowCreateMutation, windowToggleMutation, modelCreateMutation, modelToggleMutation,
    instantiateMutation, taskCreateMutation, taskUpdateMutation, pirSaveMutation,
    pirSubmitMutation, pirApproveMutation, meetingCreateMutation, agendaAddMutation,
    meetingStatusMutation, agendaDecisionMutation,
  ]

  return (
    <LocalizedContent><AppShell
      title="Управление изменениями"
      subtitle="Визуальный календарь, blackout-контроль, Standard Change, CAB evidence, задачи исполнения и PIR."
    >
      {root ? (
        <section className="foundation-card compact-card">
          <label className="field"><span>Организация</span><select value={tenantId} onChange={(event) => setTenantId(event.target.value)}><option value="">Все организации</option>{(tenantsQuery.data ?? []).map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></label>
          {!tenantId ? <p className="muted">Для создания выберите организацию.</p> : null}
        </section>
      ) : null}

      <nav className="module-subnav" aria-label="Change governance navigation">
        {views.map((item) => <button type="button" key={item.key} className={`module-subnav-tab ${view === item.key ? 'active' : ''}`} onClick={() => setView(item.key)}>{translate(item.label)}</button>)}
        <Link className="module-subnav-tab" to="/changes">Реестр RFC</Link>
      </nav>
      <QueryFailureNotice
        title="Часть данных Change Governance недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: translate('календарь'), query: calendarQuery },
          { label: 'maintenance windows', query: windowsQuery },
          { label: 'standard change models', query: modelsQuery },
          { label: translate('изменения'), query: changesQuery },
          { label: 'approval queue', query: approvalQueueQuery },
          { label: translate('задачи'), query: tasksQuery },
          { label: 'readiness', query: readinessQuery },
          { label: 'PIR', query: pirQuery },
          { label: 'CAB meetings', query: meetingsQuery },
          { label: translate('аналитика'), query: analyticsQuery },
        ]}
      />

      {view === 'CALENDAR' ? (
        <>
          <section className="foundation-card change-calendar-toolbar">
            <div><p className="eyebrow">CHANGE CALENDAR</p><h2>{monthCursor.toLocaleString(uiLocale, { month: 'long', year: 'numeric' })}</h2></div>
            <div className="button-row">
              <button type="button" className="secondary-button" onClick={() => setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() - 1, 1))}>← Предыдущий</button>
              <button type="button" className="secondary-button" onClick={() => setMonthCursor(new Date())}>Сегодня</button>
              <button type="button" className="secondary-button" onClick={() => setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() + 1, 1))}>Следующий →</button>
            </div>
          </section>
          <section className="change-calendar-grid foundation-card">
            {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((day) => <strong className="calendar-day-name" key={day}>{day}</strong>)}
            {days.map((day) => {
              const dayStart = new Date(day.getFullYear(), day.getMonth(), day.getDate())
              const dayEnd = new Date(dayStart.getTime() + 86_400_000)
              const changes = (calendarQuery.data?.changes ?? []).filter((item) => new Date(item.planned_start_at) < dayEnd && new Date(item.planned_end_at) > dayStart)
              const windows = (calendarQuery.data?.windows ?? []).filter((item) => new Date(item.starts_at) < dayEnd && new Date(item.ends_at) > dayStart)
              return (
                <article key={day.toISOString()} className={`change-calendar-day ${day.getMonth() === monthCursor.getMonth() ? '' : 'outside'}`}>
                  <span>{day.getDate()}</span>
                  {windows.map((item) => <small key={item.id} className={`calendar-event window-${item.window_type.toLowerCase()}`}>{item.window_type === 'BLACKOUT' ? '⛔' : '🛠'} {item.name}</small>)}
                  {changes.map((item) => <Link key={item.id} to={`/changes?change=${item.id}`} className={`calendar-event risk-${item.risk_level.toLowerCase()}`}>{item.change_number} · {item.title}</Link>)}
                </article>
              )
            })}
          </section>
          <section className="change-governance-split">
            {canSchedule ? (
              <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); windowCreateMutation.mutate() }}>
                <p className="eyebrow">WINDOW CONTROL</p><h2>Новое окно</h2>
                <label className="field"><span>Название</span><input value={windowName} onChange={(event) => setWindowName(event.target.value)} required /></label>
                <label className="field"><span>Тип</span><select value={windowType} onChange={(event) => setWindowType(event.target.value as typeof windowType)}><option value="MAINTENANCE">Maintenance — разрешённое окно</option><option value="BLACKOUT">Blackout — запрет изменений</option></select></label>
                <div className="form-grid">
                  <label className="field"><span>Начало</span><input type="datetime-local" value={windowStart} onChange={(event) => setWindowStart(event.target.value)} /></label>
                  <label className="field"><span>Окончание</span><input type="datetime-local" value={windowEnd} onChange={(event) => setWindowEnd(event.target.value)} /></label>
                  <label className="field"><span>Сервис (пусто — все)</span><input value={windowService} onChange={(event) => setWindowService(event.target.value)} /></label>
                  <label className="field"><span>Среда</span><input value={windowEnvironment} onChange={(event) => setWindowEnvironment(event.target.value)} /></label>
                  <label className="field"><span>Часовой пояс</span><input value={windowTimezone} onChange={(event) => setWindowTimezone(event.target.value)} /></label>
                </div>
                <button className={windowType === 'BLACKOUT' ? 'danger-button' : 'primary-button'} disabled={createBlocked}>Создать окно</button>
              </form>
            ) : null}
            <section className="foundation-card">
              <p className="eyebrow">WINDOW REGISTRY</p><h2>Окна и запреты</h2>
              <div className="activity-list">
                {(windowsQuery.data ?? []).map((item) => (
                  <article className="activity-item" key={item.id}>
                    <header><strong>{item.name}</strong><span>{item.window_type}</span></header>
                    <p>{formatDate(item.starts_at)} — {formatDate(item.ends_at)}</p>
                    <small>{item.services.join(', ') || 'Все сервисы'} · {item.environments.join(', ') || 'Все среды'} · {item.timezone}</small>
                    {canSchedule ? <button type="button" className="secondary-button" onClick={() => windowToggleMutation.mutate(item)}>{item.is_active ? 'Отключить' : 'Включить'}</button> : null}
                  </article>
                ))}
              </div>
            </section>
          </section>
        </>
      ) : null}

      {view === 'MODELS' ? (
        <section className="change-governance-split">
          {canApprove ? (
            <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); modelCreateMutation.mutate() }}>
              <p className="eyebrow">STANDARD CHANGE MODEL</p><h2>Новая модель</h2>
              <label className="field"><span>Код</span><input value={modelCode} onChange={(event) => setModelCode(event.target.value.toUpperCase())} required /></label>
              <label className="field"><span>Название</span><input value={modelName} onChange={(event) => setModelName(event.target.value)} required /></label>
              <label className="field"><span>Сервис</span><input value={modelService} onChange={(event) => setModelService(event.target.value)} /></label>
              <label className="field"><span>Длительность, мин</span><input type="number" min="5" value={modelDuration} onChange={(event) => setModelDuration(Number(event.target.value))} /></label>
              <p className="muted">Создаётся проверенный комплект implementation, validation и rollback шагов с ежегодной преавторизацией и квартальным review.</p>
              <button className="primary-button" disabled={createBlocked}>Создать и преавторизовать</button>
            </form>
          ) : null}
          <section className="foundation-card">
            <p className="eyebrow">PREAUTHORIZED LIBRARY</p><h2>Каталог стандартных изменений</h2>
            <div className="sla-grid">
              {(modelsQuery.data ?? []).map((item) => (
                <article className="sla-card" key={item.id}>
                  <header className="sla-card-header"><div><p className="eyebrow">{item.code}</p><h3>{item.name}</h3></div><span className={`status-pill status-${item.is_active ? 'active' : 'cancelled'}`}>{item.is_active ? 'Активна' : 'Отключена'}</span></header>
                  <p>{item.description}</p>
                  <div className="sla-meta"><span>{item.service_name || 'Все сервисы'}</span><span>{item.environment}</span><span>{item.default_duration_minutes} мин</span><span>Надёжность: {item.reliability_percent}%</span><span>Использований: {item.usage_count}</span></div>
                  <small>Review: {formatDate(item.review_due_at)} · действует до {formatDate(item.preauthorized_until)}</small>
                  <div className="button-row">
                    {canCreate ? <button type="button" className="primary-button" onClick={() => instantiateMutation.mutate(item.id)} disabled={!item.is_active}>Создать RFC по модели</button> : null}
                    {canApprove ? <button type="button" className="secondary-button" onClick={() => modelToggleMutation.mutate(item)}>{item.is_active ? 'Отключить' : 'Включить'}</button> : null}
                  </div>
                </article>
              ))}
            </div>
          </section>
        </section>
      ) : null}

      {view === 'EXECUTION' ? (
        <section className="change-execution-layout">
          <aside className="foundation-card">
            <p className="eyebrow">RFC SELECTOR</p><h2>Изменение</h2>
            <select value={selectedChangeId} onChange={(event) => setSelectedChangeId(event.target.value)}>
              <option value="">Выберите RFC</option>
              {(changesQuery.data?.items ?? []).map((item) => <option key={item.id} value={item.id}>{item.change_number} · {item.title}</option>)}
            </select>
            {selectedChange ? (
              <div className="detail-fields">
                <div><span>Статус</span><strong>{selectedChange.status}</strong></div>
                <div><span>Риск</span><strong>{selectedChange.risk_level}</strong></div>
                <div><span>Validation</span><strong>{selectedChange.validation_status}</strong></div>
                <div><span>PIR</span><strong>{selectedChange.pir_status}</strong></div>
              </div>
            ) : null}
            {readinessQuery.data ? (
              <div className="readiness-score">
                <strong>{readinessQuery.data.score_percent}%</strong>
                <span>{readinessQuery.data.ready ? 'Готово к окну' : 'Есть блокирующие проверки'}</span>
                {readinessQuery.data.checks.map((check) => <small key={check.code} className={check.passed ? 'passed' : check.blocking ? 'failed' : 'warning'}>{check.passed ? '✓' : check.blocking ? '✕' : '!' } {check.label}</small>)}
              </div>
            ) : null}
            {selectedChangeId ? <Link className="secondary-button" to={`/changes?change=${selectedChangeId}`}>Открыть RFC</Link> : null}
          </aside>
          <div className="foundation-card">
            <p className="eyebrow">EXECUTION CONTROL</p><h2>Задачи и доказательства</h2>
            <div className="change-task-list">
              {(tasksQuery.data ?? []).map((item) => (
                <article key={item.id} className={`change-task task-${item.status.toLowerCase()}`}>
                  <header><div><strong>{item.sequence}. {item.title}</strong><small>{item.task_type} · {item.owner_name || 'Без владельца'}</small></div><span>{item.status}</span></header>
                  <input disabled={!canExecute} value={taskEvidence[item.id] ?? ''} onChange={(event) => setTaskEvidence({ ...taskEvidence, [item.id]: event.target.value })} placeholder="Доказательство выполнения / ссылка / результат" />
                  {canExecute ? <div className="button-row">
                    {item.status === 'PENDING' ? <button type="button" className="secondary-button" onClick={() => taskUpdateMutation.mutate({ item, status: 'IN_PROGRESS' })}>Начать</button> : null}
                    {['PENDING', 'IN_PROGRESS'].includes(item.status) ? <button type="button" className="primary-button" onClick={() => taskUpdateMutation.mutate({ item, status: 'COMPLETED' })}>Завершить с evidence</button> : null}
                    {item.status === 'IN_PROGRESS' ? <button type="button" className="danger-button" onClick={() => taskUpdateMutation.mutate({ item, status: 'FAILED' })}>Сбой</button> : null}
                  </div> : null}
                </article>
              ))}
            </div>
            {selectedChangeId && canUpdate ? (
              <form className="inline-form" onSubmit={(event) => { event.preventDefault(); taskCreateMutation.mutate() }}>
                <select value={taskType} onChange={(event) => setTaskType(event.target.value as ChangeTask['task_type'])}><option value="IMPLEMENTATION">Implementation</option><option value="VALIDATION">Validation</option><option value="ROLLBACK">Rollback</option></select>
                <input value={taskTitle} onChange={(event) => setTaskTitle(event.target.value)} placeholder="Новая обязательная задача" required />
                <button className="secondary-button">Добавить</button>
              </form>
            ) : null}

            {selectedChange && ['REVIEW', 'FAILED', 'ROLLED_BACK', 'COMPLETED'].includes(selectedChange.status) ? (
              <section className="pir-panel">
                <p className="eyebrow">POST-IMPLEMENTATION REVIEW</p><h2>Структурированный PIR</h2>
                <div className="form-grid">
                  <label className="field"><span>Результат</span><select disabled={!canExecute} value={pirOutcome} onChange={(event) => setPirOutcome(event.target.value as ChangePIR['outcome'])}><option value="SUCCESS">Успех</option><option value="PARTIAL">Частичный успех</option><option value="FAILED">Сбой</option><option value="ROLLED_BACK">Откат</option></select></label>
                  <label className="field"><span>Фактическое влияние</span><textarea disabled={!canExecute} value={pirImpact} onChange={(event) => setPirImpact(event.target.value)} /></label>
                  <label className="field"><span>Уроки</span><textarea disabled={!canExecute} value={pirLessons} onChange={(event) => setPirLessons(event.target.value)} /></label>
                </div>
                <div className="button-row">
                  {canExecute && (!pirQuery.data || pirQuery.data.status === 'DRAFT') ? <button type="button" className="secondary-button" onClick={() => pirSaveMutation.mutate()}>Сохранить PIR</button> : null}
                  {canExecute && pirQuery.data?.status === 'DRAFT' ? <button type="button" className="primary-button" onClick={() => pirSubmitMutation.mutate(pirQuery.data!)}>Передать на независимое одобрение</button> : null}
                </div>
                {pirQuery.data ? <p>Статус: <strong>{pirQuery.data.status}</strong> · автор {pirQuery.data.prepared_by_name}</p> : null}
                {canApprove && pirQuery.data?.status === 'SUBMITTED' && pirQuery.data.prepared_by_id !== session?.user.id ? (
                  <div className="inline-form"><input value={pirApprovalComment} onChange={(event) => setPirApprovalComment(event.target.value)} /><button type="button" className="primary-button" onClick={() => pirApproveMutation.mutate(pirQuery.data!)}>Одобрить PIR</button></div>
                ) : null}
              </section>
            ) : null}
          </div>
        </section>
      ) : null}

      {view === 'CAB' ? (
        <section className="change-governance-split">
          {canApprove ? (
            <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); meetingCreateMutation.mutate() }}>
              <p className="eyebrow">CAB ORCHESTRATION</p><h2>Новое заседание</h2>
              <label className="field"><span>Название</span><input value={meetingTitle} onChange={(event) => setMeetingTitle(event.target.value)} /></label>
              <label className="field"><span>Тип</span><select value={meetingType} onChange={(event) => setMeetingType(event.target.value as typeof meetingType)}><option value="CAB">CAB</option><option value="ECAB">ECAB</option></select></label>
              <label className="field"><span>Дата и время</span><input type="datetime-local" value={meetingAt} onChange={(event) => setMeetingAt(event.target.value)} /></label>
              <button className="primary-button" disabled={createBlocked}>Создать повестку</button>
            </form>
          ) : null}
          <section className="foundation-card">
            <p className="eyebrow">EVIDENCE-BASED DECISIONS</p><h2>Заседания и повестки</h2>
            <select value={selectedMeetingId} onChange={(event) => setSelectedMeetingId(event.target.value)}><option value="">Выберите заседание</option>{(meetingsQuery.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.meeting_type} · {formatDate(item.scheduled_at)} · {item.title}</option>)}</select>
            {selectedMeeting ? (
              <div className="cab-meeting">
                <header><div><h3>{selectedMeeting.title}</h3><p>{selectedMeeting.meeting_type} · {selectedMeeting.status} · председатель {selectedMeeting.chair_user_name}</p></div><span className="status-pill">{selectedMeeting.agenda.length} RFC</span></header>
                {canApprove && ['DRAFT', 'PUBLISHED'].includes(selectedMeeting.status) ? (
                  <form className="inline-form" onSubmit={(event) => { event.preventDefault(); agendaAddMutation.mutate() }}>
                    <select value={agendaChangeId} onChange={(event) => setAgendaChangeId(event.target.value)} required><option value="">RFC, ожидающий CAB</option>{(approvalQueueQuery.data?.items ?? []).map((item) => <option key={item.id} value={item.id}>{item.change_number} · {item.title}</option>)}</select>
                    <button className="secondary-button">Добавить в повестку</button>
                  </form>
                ) : null}
                <div className="cab-agenda">
                  {selectedMeeting.agenda.map((item) => (
                    <article key={item.id}><header><strong>{item.sequence}. {item.change_number}</strong><span>{item.decision || 'PENDING'}</span></header><p>{item.recommendation}</p>{canApprove && !item.decision && ['PUBLISHED', 'IN_PROGRESS'].includes(selectedMeeting.status) ? <div className="button-row"><button type="button" className="primary-button" onClick={() => agendaDecisionMutation.mutate({ agendaId: item.id, decision: 'APPROVED' })}>Одобрить с evidence</button><button type="button" className="danger-button" onClick={() => agendaDecisionMutation.mutate({ agendaId: item.id, decision: 'REJECTED' })}>Отклонить</button></div> : null}</article>
                  ))}
                </div>
                {canApprove ? (
                  <div className="button-row">
                    {selectedMeeting.status === 'DRAFT' ? <button type="button" className="primary-button" onClick={() => meetingStatusMutation.mutate({ meeting: selectedMeeting, status: 'PUBLISHED' })}>Опубликовать повестку</button> : null}
                    {selectedMeeting.status === 'PUBLISHED' ? <button type="button" className="primary-button" onClick={() => meetingStatusMutation.mutate({ meeting: selectedMeeting, status: 'IN_PROGRESS' })}>Начать CAB</button> : null}
                    {selectedMeeting.status === 'IN_PROGRESS' ? <button type="button" className="primary-button" onClick={() => meetingStatusMutation.mutate({ meeting: selectedMeeting, status: 'COMPLETED' })}>Завершить и сохранить minutes</button> : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>
        </section>
      ) : null}

      {view === 'ANALYTICS' ? (
        <>
          <section className="module-overview-grid">
            <article className="metric-card"><span>Успешность</span><strong>{analyticsQuery.data?.success_rate_percent ?? 0}%</strong><p>Успешно завершённые изменения.</p></article>
            <article className="metric-card danger"><span>Change failure rate</span><strong>{analyticsQuery.data?.change_failure_rate_percent ?? 0}%</strong><p>Сбои и откаты.</p></article>
            <article className="metric-card warning"><span>Emergency rate</span><strong>{analyticsQuery.data?.emergency_rate_percent ?? 0}%</strong><p>Доля экстренных RFC.</p></article>
            <article className="metric-card"><span>Lead time</span><strong>{analyticsQuery.data?.average_lead_time_hours ?? 0} ч</strong><p>От создания до начала.</p></article>
          </section>
          <section className="foundation-card analytics-detail-grid">
            <div><span>Всего RFC</span><strong>{analyticsQuery.data?.total_changes ?? 0}</strong></div>
            <div><span>Завершено</span><strong>{analyticsQuery.data?.completed_changes ?? 0}</strong></div>
            <div><span>Сбой</span><strong>{analyticsQuery.data?.failed_changes ?? 0}</strong></div>
            <div><span>Откат</span><strong>{analyticsQuery.data?.rolled_back_changes ?? 0}</strong></div>
            <div><span>Открытые задачи</span><strong>{analyticsQuery.data?.open_tasks ?? 0}</strong></div>
            <div><span>Просрочен review моделей</span><strong>{analyticsQuery.data?.overdue_standard_reviews ?? 0}</strong></div>
          </section>
        </>
      ) : null}

      {mutations.some((mutation) => mutation.isError) ? <p className="error-message" role="alert">Операция не выполнена. Проверьте данные, статус объекта и его актуальную версию.</p> : null}
    </AppShell></LocalizedContent>
  )
}
