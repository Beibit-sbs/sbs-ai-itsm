import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  completeSlaTarget,
  createSlaCalendar,
  createSlaPolicy,
  evaluateSla,
  fetchSlaBreaches,
  fetchSlaCalendar,
  fetchSlaCalendars,
  fetchSlaInstance,
  fetchSlaOverview,
  fetchSlaPolicies,
  fetchSlaQueue,
  fetchTenants,
  pauseSlaInstance,
  resumeSlaInstance,
  updateSlaCalendar,
  updateSlaPolicy,
  upsertSlaCalendarException,
  type SlaInstance,
  type SlaTargetDefinition,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { useLocalizedDefaultState } from '../experience/useLocalizedDefaultState'

type View = 'QUEUE' | 'POLICIES' | 'CALENDARS' | 'BREACHES'

const views: Array<{ key: View; label: string }> = [
  { key: 'QUEUE', label: 'Центр контроля' },
  { key: 'POLICIES', label: 'Политики SLA / OLA' },
  { key: 'CALENDARS', label: 'Календари' },
  { key: 'BREACHES', label: 'Нарушения' },
]

const statusLabels: Record<string, string> = {
  ACTIVE: 'В работе',
  PAUSED: 'На паузе',
  COMPLETED: 'Выполнено',
  BREACHED: 'Нарушено',
  CANCELLED: 'Отменено',
  PENDING: 'Ожидается',
  WARNING: 'Риск',
  MET: 'Выполнено',
}

const priorityLabels: Record<string, string> = {
  CRITICAL: 'Критический',
  HIGH: 'Высокий',
  MEDIUM: 'Средний',
  LOW: 'Низкий',
  P1: 'P1',
  P2: 'P2',
  P3: 'P3',
  P4: 'P4',
}

const targetLabels: Record<string, string> = {
  RESPONSE: 'Первый ответ',
  RESOLUTION: 'Решение',
  FULFILLMENT: 'Исполнение',
  OLA: 'Внутренний OLA',
  SUPPLIER: 'Поставщик',
}

const defaultWeek = {
  '0': [['09:00', '18:00']],
  '1': [['09:00', '18:00']],
  '2': [['09:00', '18:00']],
  '3': [['09:00', '18:00']],
  '4': [['09:00', '18:00']],
}

function targetDefinitions(
  responseMinutes: number,
  resolutionMinutes: number,
  olaMinutes: number,
  supplierMinutes: number,
  warningPercent: number,
): SlaTargetDefinition[] {
  const targets: SlaTargetDefinition[] = [
    {
      type: 'RESPONSE',
      name: 'Первый ответ',
      minutes: responseMinutes,
      warning_percent: warningPercent,
      owner_type: 'SERVICE_DESK',
      owner_ref: '',
    },
    {
      type: 'RESOLUTION',
      name: 'Решение',
      minutes: resolutionMinutes,
      warning_percent: warningPercent,
      owner_type: 'SERVICE_DESK',
      owner_ref: '',
    },
  ]
  if (olaMinutes > 0) {
    targets.push({
      type: 'OLA',
      name: 'Внутренний OLA',
      minutes: olaMinutes,
      warning_percent: warningPercent,
      owner_type: 'TEAM',
      owner_ref: 'support-l2',
    })
  }
  if (supplierMinutes > 0) {
    targets.push({
      type: 'SUPPLIER',
      name: 'Обязательство поставщика',
      minutes: supplierMinutes,
      warning_percent: warningPercent,
      owner_type: 'SUPPLIER',
      owner_ref: 'primary-supplier',
    })
  }
  return targets
}

export default function SlaPage() {
  const { session } = useAuth()
  const { formatDateTime: formatDate, formatNumber, translate } = useTenantExperience()
  const formatMinutes = (value: number) => {
    const absolute = Math.abs(value)
    if (absolute < 60) return `${formatNumber(value)} ${translate('мин')}`
    const hours = Math.floor(absolute / 60)
    const minutes = absolute % 60
    const label = `${formatNumber(hours)} ${translate('ч')}${minutes ? ` ${formatNumber(minutes)} ${translate('мин')}` : ''}`
    return value < 0 ? `−${label}` : label
  }
  const token = session?.access_token ?? ''
  const root = session?.user.role === 'saas_root'
  const canManage = root || Boolean(session?.user.permissions.includes('sla.manage'))
  const queryClient = useQueryClient()
  const [view, setView] = useState<View>('QUEUE')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [queueState, setQueueState] = useState('')
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null)
  const [pauseReason, setPauseReason] = useState('')
  const [selectedCalendarId, setSelectedCalendarId] = useState<string | null>(null)
  const [calendarName, setCalendarName] = useLocalizedDefaultState('Рабочий календарь')
  const [calendarTimezone, setCalendarTimezone] = useState('Asia/Almaty')
  const [workStart, setWorkStart] = useState('09:00')
  const [workEnd, setWorkEnd] = useState('18:00')
  const [holidayDate, setHolidayDate] = useState('')
  const [holidayName, setHolidayName] = useState('')
  const [policyName, setPolicyName] = useLocalizedDefaultState('Стандартный SLA')
  const [policyPriority, setPolicyPriority] = useState('MEDIUM')
  const [policyCalendarId, setPolicyCalendarId] = useState('')
  const [responseMinutes, setResponseMinutes] = useState(60)
  const [resolutionMinutes, setResolutionMinutes] = useState(480)
  const [olaMinutes, setOlaMinutes] = useState(0)
  const [supplierMinutes, setSupplierMinutes] = useState(0)
  const [warningPercent, setWarningPercent] = useState(80)
  const scopedTenant = root ? tenantId || undefined : undefined
  const createBlocked = root && !tenantId

  const tenantsQuery = useQuery({
    queryKey: ['tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && root),
  })
  const overviewQuery = useQuery({
    queryKey: ['sla-overview', token, scopedTenant],
    queryFn: () => fetchSlaOverview(token, scopedTenant),
    enabled: Boolean(token),
    refetchInterval: 60_000,
  })
  const policiesQuery = useQuery({
    queryKey: ['sla-policies', token, scopedTenant],
    queryFn: () => fetchSlaPolicies(token, scopedTenant),
    enabled: Boolean(token),
  })
  const calendarsQuery = useQuery({
    queryKey: ['sla-calendars', token, scopedTenant],
    queryFn: () => fetchSlaCalendars(token, scopedTenant),
    enabled: Boolean(token),
  })
  const queueQuery = useQuery({
    queryKey: ['sla-queue', token, scopedTenant, queueState],
    queryFn: () => fetchSlaQueue(token, {
      tenant_id: scopedTenant,
      states: queueState ? [queueState] : undefined,
    }),
    enabled: Boolean(token),
    refetchInterval: 30_000,
  })
  const breachesQuery = useQuery({
    queryKey: ['sla-breaches', token, scopedTenant],
    queryFn: () => fetchSlaBreaches(token, scopedTenant),
    enabled: Boolean(token),
  })
  const detailQuery = useQuery({
    queryKey: ['sla-instance', token, selectedInstanceId],
    queryFn: () => fetchSlaInstance(token, selectedInstanceId ?? ''),
    enabled: Boolean(token && selectedInstanceId),
  })
  const calendarDetailQuery = useQuery({
    queryKey: ['sla-calendar', token, selectedCalendarId],
    queryFn: () => fetchSlaCalendar(token, selectedCalendarId ?? ''),
    enabled: Boolean(token && selectedCalendarId),
  })

  const refreshOperations = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['sla-overview'] }),
      queryClient.invalidateQueries({ queryKey: ['sla-queue'] }),
      queryClient.invalidateQueries({ queryKey: ['sla-instance'] }),
      queryClient.invalidateQueries({ queryKey: ['sla-breaches'] }),
    ])
  }

  const evaluateMutation = useMutation({
    mutationFn: () => evaluateSla(token, scopedTenant),
    onSuccess: refreshOperations,
  })
  const pauseMutation = useMutation({
    mutationFn: (item: SlaInstance) => pauseSlaInstance(token, item.id, {
      expected_version: item.version,
      reason_code: 'APPROVED_HOLD',
      reason: pauseReason,
    }),
    onSuccess: async (item) => {
      setPauseReason('')
      queryClient.setQueryData(['sla-instance', token, item.id], item)
      await refreshOperations()
    },
  })
  const resumeMutation = useMutation({
    mutationFn: (item: SlaInstance) => resumeSlaInstance(token, item.id, item.version),
    onSuccess: async (item) => {
      queryClient.setQueryData(['sla-instance', token, item.id], item)
      await refreshOperations()
    },
  })
  const completeTargetMutation = useMutation({
    mutationFn: ({ instance, targetId, version }: { instance: SlaInstance; targetId: string; version: number }) =>
      completeSlaTarget(token, instance.id, targetId, {
        expected_version: version,
        reason: translate('Подтверждено оператором SLA'),
      }),
    onSuccess: async (item) => {
      queryClient.setQueryData(['sla-instance', token, item.id], item)
      await refreshOperations()
    },
  })
  const calendarCreateMutation = useMutation({
    mutationFn: () => createSlaCalendar(token, {
      tenant_id: scopedTenant,
      name: calendarName,
      timezone: calendarTimezone,
      weekly_hours: Object.fromEntries(
        Object.keys(defaultWeek).map((day) => [day, [[workStart, workEnd]]]),
      ),
      is_default: (calendarsQuery.data?.length ?? 0) === 0,
      is_active: true,
    }),
    onSuccess: async (item) => {
      setSelectedCalendarId(item.id)
      setPolicyCalendarId(item.id)
      await queryClient.invalidateQueries({ queryKey: ['sla-calendars'] })
    },
  })
  const calendarToggleMutation = useMutation({
    mutationFn: (item: NonNullable<typeof calendarsQuery.data>[number]) =>
      updateSlaCalendar(token, item.id, {
        expected_version: item.version,
        is_active: !item.is_active,
      }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['sla-calendars'] }),
  })
  const calendarScheduleMutation = useMutation({
    mutationFn: (item: NonNullable<typeof calendarDetailQuery.data>) =>
      updateSlaCalendar(token, item.id, {
        expected_version: item.version,
        weekly_hours: Object.fromEntries(
          Object.keys(defaultWeek).map((day) => [day, [[workStart, workEnd]]]),
        ),
      }),
    onSuccess: async (item) => {
      queryClient.setQueryData(['sla-calendar', token, item.id], item)
      await queryClient.invalidateQueries({ queryKey: ['sla-calendars'] })
    },
  })
  const exceptionMutation = useMutation({
    mutationFn: () => upsertSlaCalendarException(token, selectedCalendarId ?? '', {
      exception_date: holidayDate,
      kind: 'HOLIDAY',
      name: holidayName,
      intervals: [],
    }),
    onSuccess: async () => {
      setHolidayDate('')
      setHolidayName('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sla-calendar'] }),
        queryClient.invalidateQueries({ queryKey: ['sla-calendars'] }),
      ])
    },
  })
  const policyCreateMutation = useMutation({
    mutationFn: () => createSlaPolicy(token, {
      tenant_id: scopedTenant,
      name: policyName,
      priority: policyPriority,
      calendar_id: policyCalendarId || null,
      priority_order: 100,
      scope: {},
      targets: targetDefinitions(
        responseMinutes,
        resolutionMinutes,
        olaMinutes,
        supplierMinutes,
        warningPercent,
      ).map((target) => ({ ...target, name: translate(target.name) })),
      pause_statuses: ['WAITING_USER', 'WAITING_VENDOR'],
      pause_reasons: ['WAITING_CUSTOMER', 'WAITING_VENDOR', 'APPROVED_HOLD'],
      warning_percent: warningPercent,
      escalations: [
        { at_percent: warningPercent, label: translate('Предупреждение владельцу') },
        { at_percent: 100, label: translate('Нарушение — эскалация руководителю') },
      ],
      is_active: true,
    }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['sla-policies'] }),
  })
  const policyToggleMutation = useMutation({
    mutationFn: (item: NonNullable<typeof policiesQuery.data>[number]) =>
      updateSlaPolicy(token, item.id, {
        expected_version: item.version,
        is_active: !item.is_active,
      }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['sla-policies'] }),
  })

  const queue = queueQuery.data ?? []
  const selected = detailQuery.data
  const overview = overviewQuery.data
  const nextDeadlines = useMemo(
    () => queue
      .flatMap((item) => item.targets.map((target) => ({ item, target })))
      .filter(({ target }) => ['PENDING', 'WARNING', 'BREACHED'].includes(target.status))
      .sort((left, right) => new Date(left.target.due_at).getTime() - new Date(right.target.due_at).getTime())
      .slice(0, 5),
    [queue],
  )

  useEffect(() => {
    if (!selectedInstanceId && queue.length > 0) setSelectedInstanceId(queue[0].id)
  }, [queue, selectedInstanceId])
  useEffect(() => {
    const calendars = calendarsQuery.data ?? []
    if (!selectedCalendarId && calendars.length > 0) setSelectedCalendarId(calendars[0].id)
    if (!policyCalendarId && calendars.length > 0) setPolicyCalendarId(calendars[0].id)
  }, [calendarsQuery.data, policyCalendarId, selectedCalendarId])

  return (
    <LocalizedContent><AppShell
      title="SLA, OLA и обязательства"
      subtitle="Рабочие календари, прогноз риска, контролируемые паузы и единая очередь обязательств."
    >
      <QueryFailureNotice
        title="Часть данных SLA Management недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: translate('оперативная сводка'), query: overviewQuery },
          { label: 'SLA policies', query: policiesQuery },
          { label: translate('рабочие календари'), query: calendarsQuery },
          { label: translate('очередь обязательств'), query: queueQuery },
          { label: 'breaches', query: breachesQuery },
          { label: translate('детали SLA'), query: detailQuery },
          { label: translate('детали календаря'), query: calendarDetailQuery },
        ]}
      />
      {root ? (
        <section className="foundation-card compact-card">
          <label className="field">
            <span>Организация</span>
            <select value={tenantId} onChange={(event) => setTenantId(event.target.value)}>
              <option value="">Все организации</option>
              {(tenantsQuery.data ?? []).map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
          {createBlocked ? <p className="muted">Выберите организацию, чтобы создавать политики и календари.</p> : null}
        </section>
      ) : null}

      <nav className="module-subnav" aria-label="SLA navigation">
        {views.map((item) => (
          <button
            type="button"
            className={`module-subnav-tab ${view === item.key ? 'active' : ''}`}
            key={item.key}
            onClick={() => setView(item.key)}
          >
            {translate(item.label)}
          </button>
        ))}
      </nav>

      <section className="module-overview-grid sla-metrics">
        <article className="metric-card"><span>Активные SLA</span><strong>{overview?.active_instances ?? 0}</strong><p>Обязательства в работе.</p></article>
        <article className="metric-card warning"><span>В зоне риска</span><strong>{overview?.warning_targets ?? 0}</strong><p>Цели достигли порога предупреждения.</p></article>
        <article className="metric-card danger"><span>Нарушены</span><strong>{overview?.breached_targets ?? 0}</strong><p>Цели, требующие эскалации.</p></article>
        <article className="metric-card"><span>На паузе</span><strong>{overview?.paused_instances ?? 0}</strong><p>Только с разрешённой причиной.</p></article>
      </section>

      {view === 'QUEUE' ? (
        <>
          <section className="foundation-card sla-toolbar">
            <div>
              <p className="eyebrow">SLA CONTROL CENTER</p>
              <h2>Очередь обязательств</h2>
              <p className="muted">Автоматическая оценка выполняется каждые 30 секунд.</p>
            </div>
            <div className="button-row">
              <select value={queueState} onChange={(event) => setQueueState(event.target.value)}>
                <option value="">Все состояния</option>
                <option value="ACTIVE">В работе</option>
                <option value="PAUSED">На паузе</option>
                <option value="BREACHED">Нарушено</option>
                <option value="COMPLETED">Выполнено</option>
              </select>
              {canManage ? (
                <button type="button" className="primary-button" onClick={() => evaluateMutation.mutate()} disabled={evaluateMutation.isPending}>
                  {evaluateMutation.isPending ? 'Проверяем…' : 'Проверить сейчас'}
                </button>
              ) : null}
            </div>
          </section>

          <section className="sla-control-layout">
            <div className="foundation-card sla-queue-list">
              {queueQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка очереди…</p> : null}
              {!queueQuery.isPending && queue.length === 0 ? <p className="state-panel state-panel-empty">SLA-экземпляров пока нет. Новые заявки получат их автоматически.</p> : null}
              {queue.map((item) => {
                const risk = item.targets.find((target) => target.status === 'BREACHED')
                  ?? item.targets.find((target) => target.status === 'WARNING')
                  ?? item.targets[0]
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={`sla-queue-item ${selectedInstanceId === item.id ? 'selected' : ''}`}
                    onClick={() => setSelectedInstanceId(item.id)}
                  >
                    <span className={`status-pill status-${item.status.toLowerCase()}`}>
                      {statusLabels[item.status] ? translate(statusLabels[item.status]) : item.status}
                    </span>
                    <strong>{item.ticket_number ?? item.ticket_id}</strong>
                    <span>{item.ticket_title}</span>
                    <small>
                      {item.policy_name} · {priorityLabels[item.ticket_priority ?? '']
                        ? translate(priorityLabels[item.ticket_priority ?? ''])
                        : item.ticket_priority}
                    </small>
                    {risk ? <small>Ближайшая цель: {translate(targetLabels[risk.target_type])} · {formatDate(risk.due_at)}</small> : null}
                  </button>
                )
              })}
            </div>

            <div className="foundation-card sla-detail">
              {!selected ? <p className="state-panel state-panel-empty">Выберите SLA в очереди.</p> : (
                <>
                  <header className="sla-detail-header">
                    <div>
                      <p className="eyebrow">{selected.policy_name} · v{selected.policy_version}</p>
                      <h2>{selected.ticket_number} — {selected.ticket_title}</h2>
                      <p>{selected.calendar_name} · старт {formatDate(selected.started_at)}</p>
                    </div>
                    <span className={`status-pill status-${selected.status.toLowerCase()}`}>
                      {statusLabels[selected.status] ? translate(statusLabels[selected.status]) : selected.status}
                    </span>
                  </header>
                  <div className="sla-target-list">
                    {selected.targets.map((target) => (
                      <article key={target.id} className={`sla-target-card target-${target.status.toLowerCase()}`}>
                        <header>
                          <div>
                            <strong>{targetLabels[target.target_type] ? translate(targetLabels[target.target_type]) : target.name}</strong>
                            <small>{target.owner_ref || target.owner_type || 'Service Desk'}</small>
                          </div>
                          <span>{statusLabels[target.status] ? translate(statusLabels[target.status]) : target.status}</span>
                        </header>
                        <div className="progress-track"><span style={{ width: `${Math.min(100, target.progress_percent)}%` }} /></div>
                        <div className="sla-target-meta">
                          <span>{target.progress_percent}% использовано</span>
                          <span>{target.remaining_business_minutes < 0 ? 'Просрочка' : 'Осталось'}: {formatMinutes(target.remaining_business_minutes)}</span>
                          <span>Срок: {formatDate(target.due_at)}</span>
                          <span>Эскалация: L{target.escalation_level}</span>
                        </div>
                        {canManage && ['OLA', 'SUPPLIER', 'FULFILLMENT'].includes(target.target_type) && !['MET', 'CANCELLED'].includes(target.status) ? (
                          <button
                            type="button"
                            className="secondary-button"
                            onClick={() => completeTargetMutation.mutate({ instance: selected, targetId: target.id, version: target.version })}
                          >
                            Отметить выполненным
                          </button>
                        ) : null}
                      </article>
                    ))}
                  </div>
                  <div className="button-row">
                    <Link className="secondary-button" to={`/tickets?ticket=${selected.ticket_id}`}>Открыть заявку</Link>
                    {canManage && selected.status === 'PAUSED' ? (
                      <button type="button" className="primary-button" onClick={() => resumeMutation.mutate(selected)}>Возобновить SLA</button>
                    ) : null}
                  </div>
                  {canManage && ['ACTIVE', 'BREACHED'].includes(selected.status) ? (
                    <div className="inline-form">
                      <input value={pauseReason} onChange={(event) => setPauseReason(event.target.value)} placeholder="Обоснование согласованной паузы" />
                      <button type="button" className="secondary-button" disabled={pauseReason.trim().length < 3} onClick={() => pauseMutation.mutate(selected)}>Поставить на паузу</button>
                    </div>
                  ) : null}
                  <div className="sla-timeline">
                    <h3>Аудируемая история SLA</h3>
                    {(selected.timeline ?? []).slice(0, 12).map((event) => (
                      <article key={event.id}>
                        <span>{event.actor_name}</span>
                        <strong>{event.message}</strong>
                        <small>{formatDate(event.created_at)}</small>
                      </article>
                    ))}
                  </div>
                </>
              )}
            </div>
          </section>

          <section className="foundation-card">
            <p className="eyebrow">NEXT DEADLINES</p>
            <h2>Ближайшие контрольные точки</h2>
            <div className="activity-list">
              {nextDeadlines.map(({ item, target }) => (
                <article className="activity-item" key={target.id}>
                  <header><strong>{item.ticket_number}</strong><span>{translate(statusLabels[target.status])}</span></header>
                  <p>{translate(targetLabels[target.target_type])} · {item.ticket_title}</p>
                  <small>{formatDate(target.due_at)} · {formatMinutes(target.remaining_business_minutes)}</small>
                </article>
              ))}
            </div>
          </section>
        </>
      ) : null}

      {view === 'POLICIES' ? (
        <section className="sla-admin-layout">
          {canManage ? (
            <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); policyCreateMutation.mutate() }}>
              <p className="eyebrow">POLICY DESIGNER</p>
              <h2>Новая политика</h2>
              <label className="field"><span>Название</span><input value={policyName} onChange={(event) => setPolicyName(event.target.value)} required /></label>
              <div className="form-grid">
                <label className="field"><span>Приоритет</span><select value={policyPriority} onChange={(event) => setPolicyPriority(event.target.value)}>{['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'P1', 'P2', 'P3', 'P4'].map((value) => <option key={value}>{value}</option>)}</select></label>
                <label className="field"><span>Календарь</span><select value={policyCalendarId} onChange={(event) => setPolicyCalendarId(event.target.value)}><option value="">24×7, календарное время</option>{(calendarsQuery.data ?? []).filter((item) => item.is_active).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                <label className="field"><span>Первый ответ, мин</span><input type="number" min="1" value={responseMinutes} onChange={(event) => setResponseMinutes(Number(event.target.value))} /></label>
                <label className="field"><span>Решение, мин</span><input type="number" min="1" value={resolutionMinutes} onChange={(event) => setResolutionMinutes(Number(event.target.value))} /></label>
                <label className="field"><span>OLA L2, мин (0 — нет)</span><input type="number" min="0" value={olaMinutes} onChange={(event) => setOlaMinutes(Number(event.target.value))} /></label>
                <label className="field"><span>Поставщик, мин (0 — нет)</span><input type="number" min="0" value={supplierMinutes} onChange={(event) => setSupplierMinutes(Number(event.target.value))} /></label>
                <label className="field"><span>Предупреждение, %</span><input type="number" min="1" max="100" value={warningPercent} onChange={(event) => setWarningPercent(Number(event.target.value))} /></label>
              </div>
              <p className="muted">Паузы: ожидание клиента, ожидание поставщика и согласованная остановка. Эскалации создаются на пороге риска и при 100%.</p>
              <button className="primary-button" disabled={createBlocked || policyCreateMutation.isPending}>Создать политику</button>
            </form>
          ) : null}
          <div className="foundation-card">
            <p className="eyebrow">VERSIONED POLICIES</p>
            <h2>Действующие правила</h2>
            <div className="sla-grid">
              {(policiesQuery.data ?? []).map((policy) => (
                <article className="sla-card" key={policy.id}>
                  <div className="sla-card-header">
                    <div>
                      <p className="eyebrow">
                        {priorityLabels[policy.priority] ? translate(priorityLabels[policy.priority]) : policy.priority}
                      </p>
                      <h3>{policy.name}</h3>
                    </div>
                    <span className={`status-pill status-${policy.is_active ? 'active' : 'cancelled'}`}>{policy.is_active ? 'Активна' : 'Выключена'}</span>
                  </div>
                  <p>{policy.description || 'Общая политика без дополнительного ограничения области.'}</p>
                  <div className="sla-meta">
                    <span>{policy.calendar_name}</span>
                    <span>Версия {policy.version}</span>
                    <span>Нарушений: {policy.breach_count}</span>
                    <span>Предупреждение: {policy.warning_percent}%</span>
                  </div>
                  <div className="tag-list">
                    {(policy.targets.length ? policy.targets : [
                      { type: 'RESPONSE', minutes: policy.response_minutes ?? policy.target_response_minutes },
                      { type: 'RESOLUTION', minutes: policy.resolution_minutes ?? policy.target_resolution_minutes },
                    ]).map((target) => <span key={`${target.type}-${target.minutes}`}>{translate(targetLabels[target.type])}: {formatMinutes(target.minutes)}</span>)}
                  </div>
                  {canManage ? <button type="button" className="secondary-button" onClick={() => policyToggleMutation.mutate(policy)}>{policy.is_active ? 'Отключить' : 'Включить'}</button> : null}
                </article>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {view === 'CALENDARS' ? (
        <section className="sla-admin-layout">
          {canManage ? (
            <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); calendarCreateMutation.mutate() }}>
              <p className="eyebrow">BUSINESS TIME</p>
              <h2>Новый календарь</h2>
              <label className="field"><span>Название</span><input value={calendarName} onChange={(event) => setCalendarName(event.target.value)} required /></label>
              <label className="field"><span>Часовой пояс IANA</span><input value={calendarTimezone} onChange={(event) => setCalendarTimezone(event.target.value)} required /></label>
              <div className="form-grid">
                <label className="field"><span>Начало рабочего дня</span><input type="time" value={workStart} onChange={(event) => setWorkStart(event.target.value)} /></label>
                <label className="field"><span>Конец рабочего дня</span><input type="time" value={workEnd} onChange={(event) => setWorkEnd(event.target.value)} /></label>
              </div>
              <p className="muted">Понедельник–пятница. Праздники и рабочие исключения добавляются после создания.</p>
              <button className="primary-button" disabled={createBlocked || calendarCreateMutation.isPending}>Создать календарь</button>
            </form>
          ) : null}
          <div className="foundation-card">
            <p className="eyebrow">CALENDAR REGISTRY</p>
            <h2>Рабочие календари</h2>
            <div className="sla-calendar-list">
              {(calendarsQuery.data ?? []).map((calendar) => (
                <button type="button" className={`sla-calendar-card ${selectedCalendarId === calendar.id ? 'selected' : ''}`} key={calendar.id} onClick={() => setSelectedCalendarId(calendar.id)}>
                  <strong>{calendar.name}</strong><span>{calendar.timezone}</span><small>{calendar.is_default ? 'По умолчанию · ' : ''}{calendar.is_active ? 'Активен' : 'Отключён'} · v{calendar.version}</small>
                </button>
              ))}
            </div>
            {calendarDetailQuery.data ? (
              <div className="calendar-detail">
                <h3>{calendarDetailQuery.data.name}</h3>
                <div className="calendar-week">
                  {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((day, index) => (
                    <span key={day}><strong>{day}</strong>{calendarDetailQuery.data?.weekly_hours[String(index)]?.map((interval) => interval.join('–')).join(', ') || 'выходной'}</span>
                  ))}
                </div>
                <h3>Исключения и праздники</h3>
                {(calendarDetailQuery.data.exceptions ?? []).map((exception) => <p key={exception.id}>{exception.exception_date} · {exception.name} · {exception.kind === 'HOLIDAY' ? 'выходной' : 'рабочий день'}</p>)}
                {canManage ? (
                  <>
                    <form className="inline-form" onSubmit={(event) => { event.preventDefault(); exceptionMutation.mutate() }}>
                      <input type="date" value={holidayDate} onChange={(event) => setHolidayDate(event.target.value)} required />
                      <input value={holidayName} onChange={(event) => setHolidayName(event.target.value)} placeholder="Название праздника" required />
                      <button className="secondary-button">Добавить выходной</button>
                    </form>
                    <div className="inline-form">
                      <input type="time" value={workStart} onChange={(event) => setWorkStart(event.target.value)} aria-label="Начало рабочего дня" />
                      <input type="time" value={workEnd} onChange={(event) => setWorkEnd(event.target.value)} aria-label="Конец рабочего дня" />
                      <button type="button" className="secondary-button" onClick={() => calendarScheduleMutation.mutate(calendarDetailQuery.data)}>
                        Применить график Пн–Пт
                      </button>
                    </div>
                    <button type="button" className="secondary-button" onClick={() => calendarToggleMutation.mutate(calendarDetailQuery.data)}>
                      {calendarDetailQuery.data.is_active ? 'Отключить календарь' : 'Включить календарь'}
                    </button>
                  </>
                ) : null}
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      {view === 'BREACHES' ? (
        <section className="foundation-card">
          <p className="eyebrow">BREACH REGISTER</p>
          <h2>Реестр нарушений</h2>
          {(breachesQuery.data ?? []).length === 0 ? <p className="state-panel state-panel-empty">Активных нарушений нет.</p> : (
            <div className="activity-list">
              {(breachesQuery.data ?? []).map((breach) => (
                <article className="activity-item" key={breach.ticket_id}>
                  <header><strong>{breach.ticket_number ?? breach.ticket_id}</strong><span>Нарушено</span></header>
                  <p>{breach.title}</p>
                  <small>
                    {priorityLabels[breach.priority] ? translate(priorityLabels[breach.priority]) : breach.priority} · {breach.status} · {breach.tenant_name}
                  </small>
                  <small>Ответ: {formatDate(breach.response_due_at)} · Решение: {formatDate(breach.resolution_due_at)}</small>
                  <Link to={`/tickets?ticket=${breach.ticket_id}`}>Открыть заявку</Link>
                </article>
              ))}
            </div>
          )}
        </section>
      ) : null}

      {[evaluateMutation, pauseMutation, resumeMutation, completeTargetMutation, calendarCreateMutation, calendarToggleMutation, calendarScheduleMutation, exceptionMutation, policyCreateMutation, policyToggleMutation].some((mutation) => mutation.isError) ? (
        <p className="error-message">Операция не выполнена. Проверьте данные или обновите страницу: запись могла быть изменена другим администратором.</p>
      ) : null}
    </AppShell></LocalizedContent>
  )
}
