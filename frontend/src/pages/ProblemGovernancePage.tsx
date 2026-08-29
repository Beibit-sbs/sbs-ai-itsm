import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  createProblemAction,
  decideProblemRCA,
  disposeProblemTrend,
  fetchKnownErrorMetrics,
  fetchProblemActions,
  fetchProblemGovernanceAnalytics,
  fetchProblemRCA,
  fetchProblemsPage,
  fetchProblemTrends,
  fetchTenants,
  saveProblemRCA,
  scanProblemTrends,
  submitProblemRCA,
  updateProblemAction,
  type ProblemCorrectiveAction,
  type ProblemRCA,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { useLocalizedDefaultState } from '../experience/useLocalizedDefaultState'

type View = 'TRENDS' | 'RCA' | 'ACTIONS' | 'VALUE'

function localInput(value: Date) {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

function message(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

export default function ProblemGovernancePage() {
  const { session } = useAuth()
  const { formatDateTime, formatNumber, translate } = useTenantExperience()
  const token = session?.access_token ?? ''
  const root = session?.user.role === 'saas_root'
  const canInvestigate = session?.user.role === 'saas_root' || session?.user.permissions.includes('problems.investigate')
  const canResolve = session?.user.role === 'saas_root' || session?.user.permissions.includes('problems.resolve')
  const queryClient = useQueryClient()
  const [view, setView] = useState<View>('TRENDS')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [problemId, setProblemId] = useState('')
  const [method, setMethod] = useState<ProblemRCA['method']>('FIVE_WHYS')
  const [statement, setStatement] = useLocalizedDefaultState('Повторяющиеся инциденты приводят к деградации критического сервиса.')
  const [conclusion, setConclusion] = useLocalizedDefaultState('Корневая причина связана с недостаточным контролем конфигурации и валидации.')
  const [whys, setWhys] = useLocalizedDefaultState((localize) => [
    localize('Компонент получил некорректную конфигурацию.'),
    localize('Проверка конфигурации не выполнялась до развёртывания.'),
    localize('Контроль не был включён в обязательный pipeline gate.'),
    localize('Владелец контроля и критерий не были определены.'),
    localize('Процесс не учитывал повторяемость подобных инцидентов.'),
  ])
  const [actionTitle, setActionTitle] = useLocalizedDefaultState('Добавить обязательную проверку конфигурации')
  const [actionType, setActionType] = useState<ProblemCorrectiveAction['action_type']>('CORRECTIVE')
  const [dueAt, setDueAt] = useState(() => localInput(new Date(Date.now() + 14 * 86_400_000)))
  const scopedTenant = root ? tenantId || undefined : undefined

  const tenantsQuery = useQuery({ queryKey: ['tenants', token], queryFn: () => fetchTenants(token), enabled: Boolean(token && root) })
  const problemsQuery = useQuery({
    queryKey: ['governance-problems', token],
    queryFn: () => fetchProblemsPage(token, { page_size: 100 }),
    enabled: Boolean(token),
  })
  const rcaQuery = useQuery({
    queryKey: ['problem-rca', token, problemId],
    queryFn: () => fetchProblemRCA(token, problemId),
    enabled: Boolean(token && problemId),
    retry: false,
  })
  const actionsQuery = useQuery({
    queryKey: ['problem-actions', token, problemId],
    queryFn: () => fetchProblemActions(token, problemId),
    enabled: Boolean(token && problemId),
  })
  const trendsQuery = useQuery({
    queryKey: ['problem-trends', token, scopedTenant],
    queryFn: () => fetchProblemTrends(token, scopedTenant),
    enabled: Boolean(token),
  })
  const analyticsQuery = useQuery({
    queryKey: ['problem-governance-analytics', token, scopedTenant],
    queryFn: () => fetchProblemGovernanceAnalytics(token, scopedTenant),
    enabled: Boolean(token),
  })
  const valueQuery = useQuery({
    queryKey: ['known-error-value', token, scopedTenant],
    queryFn: () => fetchKnownErrorMetrics(token, scopedTenant),
    enabled: Boolean(token),
  })

  useEffect(() => {
    const rca = rcaQuery.data
    if (!rca) return
    setMethod(rca.method)
    setStatement(rca.problem_statement)
    setConclusion(rca.conclusion)
    if (rca.five_whys.length) {
      setWhys(rca.five_whys.map((item) => String(item.answer ?? '')))
    }
  }, [rcaQuery.data])

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['problem-rca'] }),
      queryClient.invalidateQueries({ queryKey: ['problem-actions'] }),
      queryClient.invalidateQueries({ queryKey: ['problem-trends'] }),
      queryClient.invalidateQueries({ queryKey: ['problem-governance-analytics'] }),
      queryClient.invalidateQueries({ queryKey: ['governance-problems'] }),
    ])
  }
  const saveMutation = useMutation({
    mutationFn: () => saveProblemRCA(token, problemId, {
      expected_version: rcaQuery.data?.version,
      method,
      problem_statement: statement,
      five_whys: whys.map((answer, index) => ({ why: `${translate('Почему')} ${formatNumber(index + 1)}?`, answer })),
      ishikawa: method === 'ISHIKAWA' ? {
        people: [whys[0]], process: [whys[1]], technology: [whys[2]],
      } : {},
      fault_tree: method === 'FAULT_TREE' ? { top_event: statement, causes: whys } : {},
      contributing_factors: [{ factor: whys[3], type: 'PROCESS' }],
      evidence: [{ type: 'INCIDENT_CLUSTER', reference: problemId }],
      conclusion,
    }),
    onSuccess: refresh,
  })
  const submitMutation = useMutation({
    mutationFn: () => {
      if (!rcaQuery.data) throw new Error(translate('Сначала сохраните RCA'))
      return submitProblemRCA(token, problemId, rcaQuery.data.version)
    },
    onSuccess: refresh,
  })
  const decideMutation = useMutation({
    mutationFn: (decision: 'APPROVED' | 'REJECTED') => {
      if (!rcaQuery.data) throw new Error(translate('RCA отсутствует'))
      return decideProblemRCA(token, problemId, rcaQuery.data.version, decision)
    },
    onSuccess: refresh,
  })
  const actionCreateMutation = useMutation({
    mutationFn: () => createProblemAction(token, problemId, {
      action_type: actionType,
      title: actionTitle,
      description: translate('Устранить системную причину и предотвратить повторение инцидента.'),
      is_required: true,
      due_at: new Date(dueAt).toISOString(),
      effectiveness_criteria: translate('Ноль повторных инцидентов в течение 30 дней после внедрения.'),
    }),
    onSuccess: refresh,
  })
  const actionUpdateMutation = useMutation({
    mutationFn: ({ item, status }: { item: ProblemCorrectiveAction; status: ProblemCorrectiveAction['status'] }) => updateProblemAction(
      token,
      problemId,
      item.id,
      {
        expected_version: item.version,
        status,
        implementation_evidence: status === 'IMPLEMENTED' ? translate('Изменение внедрено, логи и контрольные проверки приложены.') : undefined,
        effectiveness_score: ['VERIFIED', 'INEFFECTIVE'].includes(status) ? (status === 'VERIFIED' ? 95 : 30) : undefined,
        effectiveness_evidence: ['VERIFIED', 'INEFFECTIVE'].includes(status) ? translate('Период наблюдения завершён; повторяемость и метрики проверены независимо.') : undefined,
      },
    ),
    onSuccess: refresh,
  })
  const scanMutation = useMutation({ mutationFn: () => scanProblemTrends(token, scopedTenant), onSuccess: refresh })
  const trendMutation = useMutation({
    mutationFn: ({ signal, action }: { signal: Parameters<typeof disposeProblemTrend>[1]; action: 'ACKNOWLEDGE' | 'DISMISS' | 'CONVERT' }) => disposeProblemTrend(token, signal, action),
    onSuccess: refresh,
  })
  const errors = [saveMutation, submitMutation, decideMutation, actionCreateMutation, actionUpdateMutation, scanMutation, trendMutation].find((item) => item.error)?.error

  return (
    <LocalizedContent>
    <AppShell title="RCA и управление проблемами" subtitle="Структурированный анализ причин, proactive trends, корректирующие действия и измеримая ценность Known Error Database.">
      {root ? <section className="foundation-card compact-card"><label className="field"><span>Организация</span><select value={tenantId} onChange={(event) => setTenantId(event.target.value)}><option value="">Все организации</option>{(tenantsQuery.data ?? []).map((tenant) => <option value={tenant.id} key={tenant.id}>{tenant.name}</option>)}</select></label></section> : null}
      <nav className="module-subnav">
        {([['TRENDS', 'Trends'], ['RCA', 'Structured RCA'], ['ACTIONS', 'Corrective actions'], ['VALUE', 'KEDB value']] as Array<[View, string]>).map(([key, label]) => <button type="button" className={`module-subnav-tab ${view === key ? 'active' : ''}`} key={key} onClick={() => setView(key)}>{label}</button>)}
        <Link className="module-subnav-tab" to="/problems">Реестр Problems</Link>
      </nav>
      <QueryFailureNotice
        title="Часть данных Problem Governance недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: translate('проблемы'), query: problemsQuery },
          { label: 'RCA', query: rcaQuery },
          { label: 'corrective actions', query: actionsQuery },
          { label: 'trend signals', query: trendsQuery },
          { label: translate('аналитика'), query: analyticsQuery },
          { label: 'KEDB value', query: valueQuery },
        ]}
      />
      {errors ? <div className="alert error" role="alert">{message(errors)}</div> : null}
      <section className="problem-governance-metrics">
        <article><span>Открытые trends</span><strong>{formatNumber(analyticsQuery.data?.open_trend_signals ?? 0)}</strong></article>
        <article><span>Просроченные actions</span><strong>{formatNumber(analyticsQuery.data?.overdue_actions ?? 0)}</strong></article>
        <article><span>Подтверждённая эффективность</span><strong>{formatNumber(analyticsQuery.data?.verified_effective ?? 0)}</strong></article>
        <article><span>Средний score</span><strong>{formatNumber(analyticsQuery.data?.average_effectiveness_score ?? 0)}%</strong></article>
      </section>

      {view === 'TRENDS' ? <section className="foundation-card">
        <div className="section-heading"><div><p className="eyebrow">PROACTIVE DETECTION</p><h2>Кластеры повторных инцидентов</h2></div>{canInvestigate ? <button type="button" className="primary-button" disabled={root && !tenantId} onClick={() => scanMutation.mutate()}>Сканировать 30 дней</button> : null}</div>
        <div className="trend-signal-grid">{(trendsQuery.data ?? []).map((signal) => <article key={signal.id}><header><strong>{signal.title}</strong><span>{formatNumber(signal.score)}/100</span></header><p>{formatNumber(signal.current_count)} сейчас · {formatNumber(signal.baseline_count)} baseline · рост {formatNumber(signal.growth_percent)}%</p><small>{signal.signal_type} · {signal.status} · {formatNumber(signal.incident_ids.length)} linked incidents</small>{canInvestigate && ['OPEN', 'ACKNOWLEDGED'].includes(signal.status) ? <div className="button-row"><button type="button" className="secondary-button" onClick={() => trendMutation.mutate({ signal, action: 'ACKNOWLEDGE' })}>Принять сигнал</button><button type="button" className="primary-button" onClick={() => trendMutation.mutate({ signal, action: 'CONVERT' })}>Создать Problem</button><button type="button" className="ghost-button" onClick={() => trendMutation.mutate({ signal, action: 'DISMISS' })}>Отклонить</button></div> : null}</article>)}</div>
      </section> : null}

      {view === 'RCA' || view === 'ACTIONS' ? <section className="foundation-card compact-card"><label className="field"><span>Problem</span><select value={problemId} onChange={(event) => setProblemId(event.target.value)}><option value="">Выберите запись</option>{(problemsQuery.data?.items ?? []).map((problem) => <option value={problem.id} key={problem.id}>{problem.problem_number} · {problem.title}</option>)}</select></label></section> : null}

      {view === 'RCA' && problemId ? <section className="problem-governance-split">
        <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); saveMutation.mutate() }}>
          <p className="eyebrow">ROOT CAUSE ANALYSIS</p><h2>{rcaQuery.data?.status ?? 'Новый RCA'}</h2>
          <label className="field"><span>Метод</span><select value={method} onChange={(event) => setMethod(event.target.value as ProblemRCA['method'])}><option>FIVE_WHYS</option><option>ISHIKAWA</option><option>FAULT_TREE</option><option>CUSTOM</option></select></label>
          <label className="field"><span>Problem statement</span><textarea value={statement} onChange={(event) => setStatement(event.target.value)} /></label>
          {whys.map((why, index) => <label className="field" key={index}><span>{translate('Почему')} {formatNumber(index + 1)}?</span><input value={why} onChange={(event) => setWhys((current) => current.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} /></label>)}
          <label className="field"><span>Подтверждённая корневая причина</span><textarea value={conclusion} onChange={(event) => setConclusion(event.target.value)} /></label>
          {canInvestigate && (!rcaQuery.data || ['DRAFT', 'REJECTED'].includes(rcaQuery.data.status)) ? <button className="primary-button">Сохранить RCA</button> : null}
        </form>
        <section className="foundation-card"><p className="eyebrow">INDEPENDENT REVIEW</p><h2>Governance</h2><p>Автор: {rcaQuery.data?.prepared_by_name ?? '—'}</p><p>Статус: {rcaQuery.data?.status ?? 'DRAFT'}</p><div className="button-row">{rcaQuery.data && ['DRAFT', 'REJECTED'].includes(rcaQuery.data.status) ? <button type="button" className="secondary-button" onClick={() => submitMutation.mutate()}>Передать на review</button> : null}{rcaQuery.data?.status === 'SUBMITTED' && canResolve ? <><button type="button" className="primary-button" onClick={() => decideMutation.mutate('APPROVED')}>Утвердить</button><button type="button" className="danger-button" onClick={() => decideMutation.mutate('REJECTED')}>Вернуть</button></> : null}</div>{rcaQuery.data?.approved_by_name ? <p>Проверил: {rcaQuery.data.approved_by_name}</p> : null}</section>
      </section> : null}

      {view === 'ACTIONS' && problemId ? <section className="problem-governance-split">
        <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); actionCreateMutation.mutate() }}><p className="eyebrow">ACTION OWNERSHIP</p><h2>Новое действие</h2><label className="field"><span>Тип</span><select value={actionType} onChange={(event) => setActionType(event.target.value as ProblemCorrectiveAction['action_type'])}><option>CORRECTIVE</option><option>PREVENTIVE</option><option>DETECTION</option></select></label><label className="field"><span>Название</span><input value={actionTitle} onChange={(event) => setActionTitle(event.target.value)} /></label><label className="field"><span>Срок</span><input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label><button className="primary-button">Назначить</button></form>
        <section className="foundation-card"><p className="eyebrow">EFFECTIVENESS REVIEW</p><h2>Контроль результата</h2><div className="activity-list">{(actionsQuery.data ?? []).map((item) => <article className="activity-item" key={item.id}><header><strong>{item.title}</strong><span>{item.status}</span></header><p>{item.effectiveness_criteria}</p><small>{item.owner_name} · до {formatDateTime(item.due_at, { dateStyle: 'medium' })}</small><div className="button-row">{item.status === 'OPEN' ? <button type="button" className="secondary-button" onClick={() => actionUpdateMutation.mutate({ item, status: 'IN_PROGRESS' })}>Начать</button> : null}{item.status === 'IN_PROGRESS' ? <button type="button" className="primary-button" onClick={() => actionUpdateMutation.mutate({ item, status: 'IMPLEMENTED' })}>Внедрено</button> : null}{item.status === 'IMPLEMENTED' ? <><button type="button" className="primary-button" onClick={() => actionUpdateMutation.mutate({ item, status: 'VERIFIED' })}>Эффективно</button><button type="button" className="danger-button" onClick={() => actionUpdateMutation.mutate({ item, status: 'INEFFECTIVE' })}>Неэффективно</button></> : null}</div></article>)}</div></section>
      </section> : null}

      {view === 'VALUE' ? <section className="foundation-card"><p className="eyebrow">KNOWN ERROR VALUE · 90 DAYS</p><h2>Измеримый эффект KEDB</h2><div className="release-metrics-grid"><article><span>Просмотры</span><strong>{formatNumber(valueQuery.data?.views ?? 0)}</strong></article><article><span>Применения</span><strong>{formatNumber(valueQuery.data?.applications ?? 0)}</strong></article><article><span>Полезность</span><strong>{formatNumber(valueQuery.data?.helpfulness_percent ?? 0)}%</strong></article><article><span>Сэкономлено</span><strong>{formatNumber(valueQuery.data?.minutes_saved ?? 0)} мин</strong></article><article><span>Избежали эскалации</span><strong>{formatNumber(valueQuery.data?.avoided_escalations ?? 0)}</strong></article></div></section> : null}
    </AppShell>
    </LocalizedContent>
  )
}
