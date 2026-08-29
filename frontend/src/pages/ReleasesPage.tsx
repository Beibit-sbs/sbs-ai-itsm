import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  addReleaseDependency,
  addReleasePackage,
  createRelease,
  createReleaseEnvironment,
  decideReleaseGate,
  decideReleaseGoNoGo,
  fetchChangesPage,
  fetchRelease,
  fetchReleaseAnalytics,
  fetchReleaseCalendar,
  fetchReleaseEnvironments,
  fetchReleasesPage,
  fetchReleaseTimeline,
  fetchTenants,
  linkReleaseChange,
  planReleaseDeployment,
  transitionRelease,
  updateReleaseDeployment,
  updateReleaseEnvironment,
  verifyReleasePackage,
  type ReleaseDeployment,
  type ReleaseEnvironment,
  type ReleaseGate,
  type ReleasePackage,
  type ReleaseRecord,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { useLocalizedDefaultState } from '../experience/useLocalizedDefaultState'

type View = 'PORTFOLIO' | 'CALENDAR' | 'READINESS' | 'DEPLOYMENTS' | 'ENVIRONMENTS' | 'ANALYTICS'

const views: Array<{ key: View; label: string }> = [
  { key: 'PORTFOLIO', label: 'Портфель' },
  { key: 'CALENDAR', label: 'Календарь' },
  { key: 'READINESS', label: 'Readiness и Go/No-Go' },
  { key: 'DEPLOYMENTS', label: 'Развёртывания' },
  { key: 'ENVIRONMENTS', label: 'Среды' },
  { key: 'ANALYTICS', label: 'Метрики' },
]

const statusLabels: Record<string, string> = {
  DRAFT: 'Черновик',
  PLANNING: 'Планирование',
  READY: 'Готов к решению',
  APPROVED: 'Go подтверждён',
  DEPLOYING: 'Развёртывание',
  VALIDATING: 'Валидация',
  RELEASED: 'Выпущен',
  FAILED: 'Ошибка',
  ROLLED_BACK: 'Откат',
  CANCELLED: 'Отменён',
}

const terminalStatuses = ['RELEASED', 'FAILED', 'ROLLED_BACK', 'CANCELLED']
const automatedGates = ['CHANGES', 'PACKAGES', 'DEPENDENCIES', 'WINDOW', 'ROLLBACK']
const releaseEnvironmentTypes: ReleaseEnvironment['environment_type'][] = [
  'DEVELOPMENT',
  'TEST',
  'STAGING',
  'PRODUCTION',
  'DR',
]

function releaseEnvironmentLabel(value: ReleaseEnvironment['environment_type']) {
  return value === 'TEST' ? 'TEST ENVIRONMENT' : value
}

function localInput(value: Date) {
  return new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16)
}

function monthBounds(cursor: Date) {
  return {
    start: new Date(cursor.getFullYear(), cursor.getMonth(), 1),
    end: new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1),
  }
}

function monthDays(cursor: Date) {
  const { start } = monthBounds(cursor)
  const first = new Date(start)
  first.setDate(first.getDate() - ((start.getDay() + 6) % 7))
  return Array.from({ length: 42 }, (_, index) => {
    const day = new Date(first)
    day.setDate(first.getDate() + index)
    return day
  })
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

export default function ReleasesPage() {
  const { session } = useAuth()
  const { formatDateTime: formatDate, translate, uiLocale } = useTenantExperience()
  const token = session?.access_token ?? ''
  const role = session?.user.role ?? ''
  const root = role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const hasPermission = (code: string) => root || permissions.has(code)
  const canCreate = hasPermission('changes.create')
  const canUpdate = hasPermission('changes.update')
  const canSubmit = hasPermission('changes.submit')
  const canApprove = hasPermission('changes.approve')
  const canSchedule = hasPermission('changes.schedule')
  const canExecute = hasPermission('changes.execute')
  const queryClient = useQueryClient()
  const [view, setView] = useState<View>('PORTFOLIO')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [selectedReleaseId, setSelectedReleaseId] = useState('')
  const [monthCursor, setMonthCursor] = useState(() => new Date())

  const [releaseName, setReleaseName] = useLocalizedDefaultState('Плановый выпуск платформы')
  const [releaseVersion, setReleaseVersion] = useState('1.0.0')
  const [releaseService, setReleaseService] = useState('SBS AI ITSM')
  const [releaseType, setReleaseType] = useState<ReleaseRecord['release_type']>('MINOR')
  const [releaseRisk, setReleaseRisk] = useState<ReleaseRecord['risk_level']>('MEDIUM')
  const [targetAt, setTargetAt] = useState(() => localInput(new Date(Date.now() + 7 * 86_400_000)))
  const [windowStart, setWindowStart] = useState(() => localInput(new Date(Date.now() + 7 * 86_400_000)))
  const [windowEnd, setWindowEnd] = useState(() => localInput(new Date(Date.now() + 7 * 86_400_000 + 3_600_000)))
  const [changeId, setChangeId] = useState('')
  const [packageName, setPackageName] = useState('backend')
  const [packageType, setPackageType] = useState<ReleasePackage['package_type']>('APPLICATION')
  const [artifactUri, setArtifactUri] = useState('local://artifacts/backend')
  const [checksum, setChecksum] = useState('0'.repeat(64))
  const [dependencyId, setDependencyId] = useState('')
  const [gateEvidence, setGateEvidence] = useState<Record<string, string>>({})
  const [decisionComment, setDecisionComment] = useLocalizedDefaultState('Все обязательные проверки и доказательства приняты.')
  const [deploymentEnvironment, setDeploymentEnvironment] = useState('')
  const [deploymentAt, setDeploymentAt] = useState(() => localInput(new Date(Date.now() + 7 * 86_400_000)))
  const [deploymentEvidence, setDeploymentEvidence] = useState<Record<string, string>>({})
  const [environmentCode, setEnvironmentCode] = useState('STAGING')
  const [environmentName, setEnvironmentName] = useState('Staging')
  const [environmentType, setEnvironmentType] = useState<ReleaseEnvironment['environment_type']>('STAGING')
  const [promotionOrder, setPromotionOrder] = useState(20)
  const [environmentProduction, setEnvironmentProduction] = useState(false)

  const scopedTenant = root ? tenantId || undefined : undefined
  const creationBlocked = root && !tenantId
  const { start: calendarStart, end: calendarEnd } = monthBounds(monthCursor)

  const tenantsQuery = useQuery({
    queryKey: ['tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && root),
  })
  const releasesQuery = useQuery({
    queryKey: ['releases', token, scopedTenant],
    queryFn: () => fetchReleasesPage(token, { tenant_id: scopedTenant, page_size: 100 }),
    enabled: Boolean(token),
  })
  const releaseQuery = useQuery({
    queryKey: ['release', token, selectedReleaseId],
    queryFn: () => fetchRelease(token, selectedReleaseId),
    enabled: Boolean(token && selectedReleaseId),
  })
  const changesQuery = useQuery({
    queryKey: ['release-change-candidates', token, scopedTenant],
    queryFn: () => fetchChangesPage(token, { tenant_id: scopedTenant, page_size: 100 }),
    enabled: Boolean(token),
  })
  const environmentsQuery = useQuery({
    queryKey: ['release-environments', token, scopedTenant],
    queryFn: () => fetchReleaseEnvironments(token, scopedTenant),
    enabled: Boolean(token),
  })
  const timelineQuery = useQuery({
    queryKey: ['release-timeline', token, selectedReleaseId],
    queryFn: () => fetchReleaseTimeline(token, selectedReleaseId),
    enabled: Boolean(token && selectedReleaseId),
  })
  const calendarQuery = useQuery({
    queryKey: ['release-calendar', token, scopedTenant, calendarStart.toISOString(), calendarEnd.toISOString()],
    queryFn: () => fetchReleaseCalendar(token, calendarStart.toISOString(), calendarEnd.toISOString(), scopedTenant),
    enabled: Boolean(token),
  })
  const analyticsQuery = useQuery({
    queryKey: ['release-analytics', token, scopedTenant],
    queryFn: () => fetchReleaseAnalytics(token, scopedTenant),
    enabled: Boolean(token),
  })

  const selected = releaseQuery.data
  const eligibleChanges = useMemo(
    () => (changesQuery.data?.items ?? []).filter(
      (item) =>
        ['APPROVED', 'SCHEDULED', 'IMPLEMENTING', 'REVIEW', 'COMPLETED'].includes(item.status)
        && !selected?.changes.some((linked) => linked.change_id === item.id),
    ),
    [changesQuery.data?.items, selected?.changes],
  )
  const otherReleases = (releasesQuery.data?.items ?? []).filter(
    (item) => item.id !== selectedReleaseId && !selected?.dependencies.some((dependency) => dependency.release_id === item.id),
  )

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['releases'] }),
      queryClient.invalidateQueries({ queryKey: ['release'] }),
      queryClient.invalidateQueries({ queryKey: ['release-timeline'] }),
      queryClient.invalidateQueries({ queryKey: ['release-calendar'] }),
      queryClient.invalidateQueries({ queryKey: ['release-analytics'] }),
      queryClient.invalidateQueries({ queryKey: ['release-environments'] }),
    ])
  }

  const createMutation = useMutation({
    mutationFn: () => createRelease(token, {
      tenant_id: scopedTenant,
      name: releaseName,
      version_name: releaseVersion,
      release_type: releaseType,
      service_name: releaseService,
      description: `${translate('Управляемый выпуск')} ${releaseName} ${translate('версии выпуска')} ${releaseVersion}.`,
      scope: translate('Проверенные изменения и артефакты из утверждённого состава релиза.'),
      release_notes: `${translate('Версия')} ${releaseVersion}: ${translate('управляемый выпуск через release train.')}`,
      risk_level: releaseRisk,
      target_release_at: new Date(targetAt).toISOString(),
      window_start_at: new Date(windowStart).toISOString(),
      window_end_at: new Date(windowEnd).toISOString(),
      validation_plan: translate('Smoke, health, критические пользовательские сценарии и мониторинг ошибок.'),
      rollback_plan: translate('Остановить продвижение, восстановить предыдущую версию и подтвердить health checks.'),
      communication_plan: translate('Уведомить CAB, Service Desk, владельца сервиса и затронутых пользователей.'),
    }),
    onSuccess: async (data) => {
      setSelectedReleaseId(data.id)
      setView('READINESS')
      await refresh()
    },
  })
  const transitionMutation = useMutation({
    mutationFn: (action: 'SUBMIT' | 'MARK_READY' | 'PUBLISH' | 'CANCEL') => {
      if (!selected) throw new Error(translate('Выберите релиз'))
      return transitionRelease(token, selected.id, {
        expected_version: selected.version,
        action,
        comment: `${translate('Контролируемый переход:')} ${action}.`,
      })
    },
    onSuccess: refresh,
  })
  const linkChangeMutation = useMutation({
    mutationFn: () => {
      if (!selected || !changeId) throw new Error(translate('Выберите RFC'))
      return linkReleaseChange(token, selected.id, {
        change_id: changeId,
        sequence: selected.changes.length + 1,
        is_mandatory: true,
      })
    },
    onSuccess: async () => {
      setChangeId('')
      await refresh()
    },
  })
  const packageMutation = useMutation({
    mutationFn: () => {
      if (!selected) throw new Error(translate('Выберите релиз'))
      return addReleasePackage(token, selected.id, {
        component_name: packageName,
        package_type: packageType,
        version_name: selected.version_name,
        artifact_uri: artifactUri,
        checksum_sha256: checksum,
        dependencies: [],
      })
    },
    onSuccess: refresh,
  })
  const verifyPackageMutation = useMutation({
    mutationFn: (item: ReleasePackage) => {
      if (!selected) throw new Error(translate('Выберите релиз'))
      return verifyReleasePackage(token, selected.id, item.id, {
        expected_version: item.version,
        verification_status: 'VERIFIED',
        evidence: `SHA-256 ${item.checksum_sha256} ${translate('проверен; артефакт неизменяем и доступен.')}`,
      })
    },
    onSuccess: refresh,
  })
  const dependencyMutation = useMutation({
    mutationFn: () => {
      if (!selected || !dependencyId) throw new Error(translate('Выберите зависимый релиз'))
      return addReleaseDependency(token, selected.id, {
        dependency_release_id: dependencyId,
        dependency_type: 'REQUIRES',
        notes: translate('Зависимый релиз должен быть опубликован до продвижения.'),
      })
    },
    onSuccess: async () => {
      setDependencyId('')
      await refresh()
    },
  })
  const gateMutation = useMutation({
    mutationFn: ({ gate, status }: { gate: ReleaseGate; status: 'PASSED' | 'FAILED' | 'WAIVED' }) => {
      if (!selected) throw new Error(translate('Выберите релиз'))
      return decideReleaseGate(token, selected.id, gate.id, {
        expected_version: gate.version,
        status,
        evidence: gateEvidence[gate.id] || translate('Доказательство проверено ответственным согласующим.'),
        comment: status === 'WAIVED'
          ? translate('Исключение документировано, риск принят и назначен ответственный контроль.')
          : translate('Результат проверки принят и зафиксирован.'),
      })
    },
    onSuccess: refresh,
  })
  const decisionMutation = useMutation({
    mutationFn: (decision: 'GO' | 'NO_GO' | 'CONDITIONAL') => {
      if (!selected) throw new Error(translate('Выберите релиз'))
      return decideReleaseGoNoGo(token, selected.id, {
        expected_version: selected.version,
        decision,
        comment: decisionComment,
        conditions: decision === 'CONDITIONAL'
          ? [{ control: 'enhanced_monitoring', owner: session?.user.full_name ?? 'Release approver' }]
          : [],
      })
    },
    onSuccess: refresh,
  })
  const deploymentPlanMutation = useMutation({
    mutationFn: () => {
      if (!selected || !deploymentEnvironment) throw new Error(translate('Выберите среду'))
      return planReleaseDeployment(token, selected.id, {
        environment_id: deploymentEnvironment,
        scheduled_at: new Date(deploymentAt).toISOString(),
        deployment_reference: `manual://${selected.release_number}/${deploymentEnvironment}`,
      })
    },
    onSuccess: async () => {
      setDeploymentEnvironment('')
      await refresh()
    },
  })
  const deploymentActionMutation = useMutation({
    mutationFn: ({ item, action }: {
      item: ReleaseDeployment
      action: 'START' | 'VALIDATE' | 'SUCCEED' | 'FAIL' | 'ROLLBACK' | 'CANCEL'
    }) => {
      if (!selected) throw new Error(translate('Выберите релиз'))
      const evidence = deploymentEvidence[item.id] || translate('Логи выполнения, health checks и операторская отметка сохранены.')
      return updateReleaseDeployment(token, selected.id, item.id, {
        expected_version: item.version,
        action,
        deployment_evidence: evidence,
        validation_evidence: action === 'SUCCEED' ? evidence : undefined,
        smoke_test_status: action === 'SUCCEED' ? 'PASSED' : undefined,
        failure_reason: action === 'FAIL' ? evidence : undefined,
        rollback_evidence: action === 'ROLLBACK' ? evidence : undefined,
      })
    },
    onSuccess: refresh,
  })
  const environmentMutation = useMutation({
    mutationFn: () => createReleaseEnvironment(token, {
      tenant_id: scopedTenant,
      code: environmentCode.toUpperCase(),
      name: environmentName,
      environment_type: environmentType,
      promotion_order: promotionOrder,
      requires_approval: environmentProduction,
      requires_smoke_test: true,
      is_production: environmentProduction,
      is_active: true,
    }),
    onSuccess: refresh,
  })
  const environmentToggleMutation = useMutation({
    mutationFn: (item: ReleaseEnvironment) => updateReleaseEnvironment(token, item.id, {
      expected_version: item.version,
      is_active: !item.is_active,
    }),
    onSuccess: refresh,
  })

  const mutations = [
    createMutation, transitionMutation, linkChangeMutation, packageMutation,
    verifyPackageMutation, dependencyMutation, gateMutation, decisionMutation,
    deploymentPlanMutation, deploymentActionMutation, environmentMutation,
    environmentToggleMutation,
  ]
  const mutationError = mutations.find((mutation) => mutation.error)?.error
  const days = monthDays(monthCursor)

  return (
    <LocalizedContent><AppShell
      title="Управление релизами"
      subtitle="Версии, пакеты, зависимости, readiness gates, Go/No-Go, продвижение по средам, доказательства и управляемый rollback."
    >
      {root ? (
        <section className="foundation-card compact-card">
          <label className="field">
            <span>Организация</span>
            <select value={tenantId} onChange={(event) => {
              setTenantId(event.target.value)
              setSelectedReleaseId('')
            }}>
              <option value="">Все организации</option>
              {(tenantsQuery.data ?? []).map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
          {!tenantId ? <p className="muted">Для создания или настройки выберите организацию.</p> : null}
        </section>
      ) : null}

      <nav className="module-subnav" aria-label="Release Management navigation">
        {views.map((item) => (
          <button type="button" key={item.key} className={`module-subnav-tab ${view === item.key ? 'active' : ''}`} onClick={() => setView(item.key)}>
            {translate(item.label)}
          </button>
        ))}
        <Link className="module-subnav-tab" to="/change-calendar">Change Calendar</Link>
      </nav>
      <QueryFailureNotice
        title="Часть данных Release Management недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: translate('релизы'), query: releasesQuery },
          { label: translate('детали релиза'), query: releaseQuery },
          { label: translate('изменения'), query: changesQuery },
          { label: translate('окружения'), query: environmentsQuery },
          { label: 'timeline', query: timelineQuery },
          { label: translate('календарь'), query: calendarQuery },
          { label: translate('аналитика'), query: analyticsQuery },
        ]}
      />
      {mutationError ? <div className="alert error" role="alert">{errorMessage(mutationError)}</div> : null}

      {view === 'PORTFOLIO' ? (
        <section className="release-layout">
          <section className="foundation-card">
            <p className="eyebrow">RELEASE PORTFOLIO</p><h2>Релизный поезд</h2>
            <div className="release-list">
              {(releasesQuery.data?.items ?? []).map((item) => (
                <button type="button" className={`release-list-item ${selectedReleaseId === item.id ? 'active' : ''}`} key={item.id} onClick={() => {
                  setSelectedReleaseId(item.id)
                  setView('READINESS')
                }}>
                  <span className={`status-pill status-${item.status.toLowerCase()}`}>{translate(statusLabels[item.status])}</span>
                  <strong>{item.release_number} · {item.name}</strong>
                  <small>{item.service_name} · v{item.version_name} · {formatDate(item.target_release_at)}</small>
                  <span>{item.change_count} RFC · {item.package_count} пакетов · {item.deployment_count} сред</span>
                </button>
              ))}
              {!releasesQuery.isLoading && !releasesQuery.data?.items.length ? <p className="empty-state">Релизов пока нет.</p> : null}
            </div>
          </section>
          {canCreate ? (
            <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); createMutation.mutate() }}>
              <p className="eyebrow">NEW RELEASE</p><h2>Создать релиз</h2>
              <div className="form-grid">
                <label className="field"><span>Название</span><input value={releaseName} onChange={(event) => setReleaseName(event.target.value)} required /></label>
                <label className="field"><span>Версия</span><input value={releaseVersion} onChange={(event) => setReleaseVersion(event.target.value)} required /></label>
                <label className="field"><span>Сервис</span><input value={releaseService} onChange={(event) => setReleaseService(event.target.value)} required /></label>
                <label className="field"><span>Тип</span><select value={releaseType} onChange={(event) => setReleaseType(event.target.value as ReleaseRecord['release_type'])}><option>MAJOR</option><option>MINOR</option><option>PATCH</option><option>HOTFIX</option></select></label>
                <label className="field"><span>Риск</span><select value={releaseRisk} onChange={(event) => setReleaseRisk(event.target.value as ReleaseRecord['risk_level'])}><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option></select></label>
                <label className="field"><span>Целевая дата</span><input type="datetime-local" value={targetAt} onChange={(event) => setTargetAt(event.target.value)} /></label>
                <label className="field"><span>Начало production-окна</span><input type="datetime-local" value={windowStart} onChange={(event) => setWindowStart(event.target.value)} /></label>
                <label className="field"><span>Окончание production-окна</span><input type="datetime-local" value={windowEnd} onChange={(event) => setWindowEnd(event.target.value)} /></label>
              </div>
              <button className="primary-button" disabled={creationBlocked || createMutation.isPending}>Создать и открыть план</button>
            </form>
          ) : null}
        </section>
      ) : null}

      {view === 'CALENDAR' ? (
        <>
          <section className="foundation-card release-calendar-toolbar">
            <div><p className="eyebrow">RELEASE CALENDAR</p><h2>{monthCursor.toLocaleString(uiLocale, { month: 'long', year: 'numeric' })}</h2></div>
            <div className="button-row">
              <button type="button" className="secondary-button" onClick={() => setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() - 1, 1))}>← Назад</button>
              <button type="button" className="secondary-button" onClick={() => setMonthCursor(new Date())}>Сегодня</button>
              <button type="button" className="secondary-button" onClick={() => setMonthCursor(new Date(monthCursor.getFullYear(), monthCursor.getMonth() + 1, 1))}>Вперёд →</button>
            </div>
          </section>
          <section className="release-calendar-grid foundation-card">
            {['Пн', 'Вт', 'Ср', 'Чт', 'Пт', 'Сб', 'Вс'].map((day) => <strong className="calendar-day-name" key={day}>{day}</strong>)}
            {days.map((day) => {
              const dayStart = new Date(day.getFullYear(), day.getMonth(), day.getDate())
              const dayEnd = new Date(dayStart.getTime() + 86_400_000)
              const releases = (calendarQuery.data?.releases ?? []).filter((item) => {
                const date = new Date(item.target_release_at)
                return date >= dayStart && date < dayEnd
              })
              const deployments = (calendarQuery.data?.deployments ?? []).filter((item) => {
                const date = new Date(item.scheduled_at)
                return date >= dayStart && date < dayEnd
              })
              return (
                <article key={day.toISOString()} className={`release-calendar-day ${day.getMonth() === monthCursor.getMonth() ? '' : 'outside'}`}>
                  <span>{day.getDate()}</span>
                  {releases.map((item) => <button type="button" key={item.id} className={`calendar-event risk-${item.risk_level.toLowerCase()}`} onClick={() => {
                    setSelectedReleaseId(item.id)
                    setView('READINESS')
                  }}>{item.release_number} · v{item.version_name}</button>)}
                  {deployments.map((item) => <small key={item.id} className={`calendar-event deployment-${item.status.toLowerCase()}`}>{item.is_production ? '◆' : '◇'} {item.environment_name} · {item.status}</small>)}
                </article>
              )
            })}
          </section>
        </>
      ) : null}

      {view === 'READINESS' ? (
        !selected ? <section className="foundation-card empty-state">Выберите релиз в портфеле.</section> : (
          <>
            <section className="foundation-card release-command-header">
              <div><p className="eyebrow">{selected.release_number} · {selected.release_type}</p><h2>{selected.name} <span className="muted">v{selected.version_name}</span></h2><p>{selected.service_name} · владелец {selected.owner_name} · цель {formatDate(selected.target_release_at)}</p></div>
              <div className="release-readiness-score"><strong>{selected.readiness.score_percent}%</strong><span>{selected.readiness.ready ? 'готов к Go' : 'есть блокеры'}</span></div>
              <span className={`status-pill status-${selected.status.toLowerCase()}`}>{translate(statusLabels[selected.status])}</span>
            </section>
            <section className="release-readiness-grid">
              <section className="foundation-card">
                <p className="eyebrow">READINESS GATES</p><h2>Контроль допуска</h2>
                <div className="release-gates">
                  {selected.readiness.gates.map((gate) => (
                    <article className={`release-gate gate-${gate.status.toLowerCase()}`} key={gate.id}>
                      <header><strong>{gate.name}</strong><span>{gate.status}</span></header>
                      <p>{gate.evidence || 'Доказательство ещё не предоставлено.'}</p>
                      {!automatedGates.includes(gate.gate_type) && canApprove && ['PLANNING', 'READY', 'APPROVED'].includes(selected.status) ? (
                        <>
                          <input placeholder="Ссылка, протокол или результат проверки" value={gateEvidence[gate.id] ?? ''} onChange={(event) => setGateEvidence((current) => ({ ...current, [gate.id]: event.target.value }))} />
                          <div className="button-row">
                            <button type="button" className="secondary-button" onClick={() => gateMutation.mutate({ gate, status: 'PASSED' })}>Принять</button>
                            <button type="button" className="danger-button" onClick={() => gateMutation.mutate({ gate, status: 'FAILED' })}>Отклонить</button>
                            <button type="button" className="ghost-button" onClick={() => gateMutation.mutate({ gate, status: 'WAIVED' })}>Waiver</button>
                          </div>
                        </>
                      ) : null}
                    </article>
                  ))}
                </div>
              </section>
              <section className="foundation-card">
                <p className="eyebrow">RELEASE CONTROL</p><h2>Lifecycle и Go/No-Go</h2>
                <div className="check-list">{selected.readiness.checks.map((check) => <div key={check.code} className={check.passed ? 'check-pass' : 'check-fail'}><span>{check.passed ? '✓' : '!'}</span><strong>{check.label}</strong></div>)}</div>
                <div className="button-row">
                  {canSubmit && selected.status === 'DRAFT' ? <button type="button" className="primary-button" onClick={() => transitionMutation.mutate('SUBMIT')}>Передать в планирование</button> : null}
                  {canSubmit && selected.status === 'PLANNING' ? <button type="button" className="primary-button" onClick={() => transitionMutation.mutate('MARK_READY')}>Зафиксировать readiness</button> : null}
                  {canExecute && selected.status === 'VALIDATING' ? <button type="button" className="primary-button" onClick={() => transitionMutation.mutate('PUBLISH')}>Опубликовать релиз</button> : null}
                  {canSubmit && !terminalStatuses.includes(selected.status) && !['DEPLOYING', 'VALIDATING'].includes(selected.status) ? <button type="button" className="danger-button" onClick={() => transitionMutation.mutate('CANCEL')}>Отменить</button> : null}
                </div>
                {selected.status === 'READY' && canApprove ? (
                  <div className="decision-panel">
                    <label className="field"><span>Протокол решения</span><textarea value={decisionComment} onChange={(event) => setDecisionComment(event.target.value)} /></label>
                    <p className="muted">Владелец и автор релиза не могут принять собственное решение.</p>
                    <div className="button-row">
                      <button type="button" className="primary-button" onClick={() => decisionMutation.mutate('GO')}>GO</button>
                      <button type="button" className="secondary-button" onClick={() => decisionMutation.mutate('CONDITIONAL')}>GO с условиями</button>
                      <button type="button" className="danger-button" onClick={() => decisionMutation.mutate('NO_GO')}>NO-GO</button>
                    </div>
                  </div>
                ) : null}
              </section>
            </section>
            <section className="release-readiness-grid">
              <section className="foundation-card">
                <p className="eyebrow">CHANGE SCOPE</p><h2>Одобренные RFC</h2>
                {canUpdate && ['DRAFT', 'PLANNING'].includes(selected.status) ? <form className="inline-form" onSubmit={(event) => { event.preventDefault(); linkChangeMutation.mutate() }}><select value={changeId} onChange={(event) => setChangeId(event.target.value)}><option value="">Выберите одобренное изменение</option>{eligibleChanges.map((item) => <option value={item.id} key={item.id}>{item.change_number} · {item.title}</option>)}</select><button className="secondary-button">Добавить</button></form> : null}
                <div className="activity-list">{selected.changes.map((item) => <Link className="activity-item" to={`/changes?change=${item.change_id}`} key={item.link_id}><header><strong>{item.sequence}. {item.change_number}</strong><span>{item.status}</span></header><p>{item.title}</p><small>{item.risk_level} · {item.is_mandatory ? 'обязательное' : 'опциональное'}</small></Link>)}</div>
              </section>
              <section className="foundation-card">
                <p className="eyebrow">IMMUTABLE ARTIFACTS</p><h2>Пакеты выпуска</h2>
                {canUpdate && ['DRAFT', 'PLANNING'].includes(selected.status) ? (
                  <form className="admin-form compact-form" onSubmit={(event) => { event.preventDefault(); packageMutation.mutate() }}>
                    <div className="form-grid">
                      <label className="field"><span>Компонент</span><input value={packageName} onChange={(event) => setPackageName(event.target.value)} /></label>
                      <label className="field"><span>Тип</span><select value={packageType} onChange={(event) => setPackageType(event.target.value as ReleasePackage['package_type'])}><option>APPLICATION</option><option>DATABASE</option><option>CONFIGURATION</option><option>INFRASTRUCTURE</option><option>DOCUMENTATION</option></select></label>
                      <label className="field"><span>URI</span><input value={artifactUri} onChange={(event) => setArtifactUri(event.target.value)} /></label>
                      <label className="field"><span>SHA-256</span><input value={checksum} onChange={(event) => setChecksum(event.target.value)} maxLength={64} /></label>
                    </div><button className="secondary-button">Добавить пакет</button>
                  </form>
                ) : null}
                <div className="activity-list">{selected.packages.map((item) => <article className="activity-item" key={item.id}><header><strong>{item.component_name} · {item.version_name}</strong><span>{item.verification_status}</span></header><p>{item.package_type} · {item.artifact_uri}</p><small className="checksum">SHA-256 {item.checksum_sha256}</small>{canApprove && item.verification_status !== 'VERIFIED' ? <button type="button" className="secondary-button" onClick={() => verifyPackageMutation.mutate(item)}>Проверить целостность</button> : null}</article>)}</div>
              </section>
            </section>
            <section className="foundation-card">
              <p className="eyebrow">DEPENDENCY GRAPH</p><h2>Зависимости релиза</h2>
              {canUpdate && ['DRAFT', 'PLANNING'].includes(selected.status) ? <form className="inline-form" onSubmit={(event) => { event.preventDefault(); dependencyMutation.mutate() }}><select value={dependencyId} onChange={(event) => setDependencyId(event.target.value)}><option value="">Выберите предшествующий релиз</option>{otherReleases.map((item) => <option value={item.id} key={item.id}>{item.release_number} · {item.name} · {item.status}</option>)}</select><button className="secondary-button">Добавить зависимость</button></form> : null}
              <div className="release-dependency-row">{selected.dependencies.map((item) => <article key={item.id}><strong>{item.dependency_type}</strong><span>{item.release_number} · v{item.version_name}</span><small>{item.status}</small></article>)}{!selected.dependencies.length ? <p className="muted">Внешних зависимостей нет.</p> : null}</div>
            </section>
          </>
        )
      ) : null}

      {view === 'DEPLOYMENTS' ? (
        !selected ? <section className="foundation-card empty-state">Выберите релиз в портфеле.</section> : (
          <section className="release-deployment-layout">
            <section className="foundation-card">
              <p className="eyebrow">PROMOTION PIPELINE</p><h2>{selected.release_number} · v{selected.version_name}</h2>
              <div className="promotion-pipeline">
                {selected.deployments.map((item, index) => (
                  <article className={`promotion-stage stage-${item.status.toLowerCase()}`} key={item.id}>
                    <span>{index + 1}</span><div><strong>{item.environment.name}</strong><small>{translate(releaseEnvironmentLabel(item.environment.environment_type))} · {item.status}</small></div>
                    <p>{formatDate(item.scheduled_at)} · {item.previous_version || 'нет версии'} → {item.deployed_version}</p>
                    <textarea placeholder="Логи, health checks, evidence" value={deploymentEvidence[item.id] ?? ''} onChange={(event) => setDeploymentEvidence((current) => ({ ...current, [item.id]: event.target.value }))} />
                    {canExecute ? <div className="button-row">
                      {item.status === 'PLANNED' ? <button type="button" className="primary-button" onClick={() => deploymentActionMutation.mutate({ item, action: 'START' })}>Старт</button> : null}
                      {item.status === 'IN_PROGRESS' ? <button type="button" className="secondary-button" onClick={() => deploymentActionMutation.mutate({ item, action: 'VALIDATE' })}>Валидация</button> : null}
                      {['IN_PROGRESS', 'VALIDATING'].includes(item.status) ? <button type="button" className="primary-button" onClick={() => deploymentActionMutation.mutate({ item, action: 'SUCCEED' })}>Успешно</button> : null}
                      {['IN_PROGRESS', 'VALIDATING'].includes(item.status) ? <button type="button" className="danger-button" onClick={() => deploymentActionMutation.mutate({ item, action: 'FAIL' })}>Ошибка</button> : null}
                      {['FAILED', 'SUCCEEDED', 'VALIDATING'].includes(item.status) ? <button type="button" className="danger-button" onClick={() => deploymentActionMutation.mutate({ item, action: 'ROLLBACK' })}>Rollback</button> : null}
                    </div> : null}
                  </article>
                ))}
              </div>
            </section>
            {canSchedule && ['APPROVED', 'DEPLOYING'].includes(selected.status) ? (
              <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); deploymentPlanMutation.mutate() }}>
                <p className="eyebrow">PLAN DEPLOYMENT</p><h2>Добавить среду</h2>
                <label className="field"><span>Среда</span><select value={deploymentEnvironment} onChange={(event) => setDeploymentEnvironment(event.target.value)}><option value="">Выберите</option>{(environmentsQuery.data ?? []).filter((environment) => environment.is_active && !selected.deployments.some((deployment) => deployment.environment.id === environment.id)).map((environment) => <option key={environment.id} value={environment.id}>{environment.promotion_order}. {environment.name}{environment.is_production ? ' · PROD' : ''}</option>)}</select></label>
                <label className="field"><span>Время</span><input type="datetime-local" value={deploymentAt} onChange={(event) => setDeploymentAt(event.target.value)} /></label>
                <p className="muted">Production запускается после успешной нижестоящей среды и внутри approved window.</p>
                <button className="primary-button">Запланировать</button>
              </form>
            ) : null}
            <section className="foundation-card">
              <p className="eyebrow">AUDIT TIMELINE</p><h2>Доказательства исполнения</h2>
              <div className="activity-list">{(timelineQuery.data ?? []).map((event) => <article className="activity-item" key={event.id}><header><strong>{event.event_type}</strong><span>{formatDate(event.created_at)}</span></header><p>{event.message}</p><small>{event.actor_name}{event.from_status || event.to_status ? ` · ${event.from_status || '—'} → ${event.to_status || '—'}` : ''}</small></article>)}</div>
            </section>
          </section>
        )
      ) : null}

      {view === 'ENVIRONMENTS' ? (
        <section className="release-layout">
          <section className="foundation-card">
            <p className="eyebrow">ENVIRONMENT REGISTRY</p><h2>Promotion path</h2>
            <div className="promotion-pipeline environment-pipeline">{(environmentsQuery.data ?? []).map((item) => <article className={`promotion-stage ${item.is_active ? '' : 'inactive'}`} key={item.id}><span>{item.promotion_order}</span><div><strong>{item.name}</strong><small>{item.code} · {translate(releaseEnvironmentLabel(item.environment_type))}</small></div><p>Текущая версия: {item.current_version || 'не зафиксирована'} · smoke {item.requires_smoke_test ? 'обязателен' : 'не обязателен'}</p>{canApprove ? <button type="button" className="secondary-button" onClick={() => environmentToggleMutation.mutate(item)}>{item.is_active ? 'Отключить' : 'Включить'}</button> : null}</article>)}</div>
          </section>
          {canApprove ? (
            <form className="foundation-card admin-form" onSubmit={(event) => { event.preventDefault(); environmentMutation.mutate() }}>
              <p className="eyebrow">TARGET CONFIGURATION</p><h2>Новая среда</h2>
              <label className="field"><span>Код</span><input value={environmentCode} onChange={(event) => setEnvironmentCode(event.target.value.toUpperCase())} /></label>
              <label className="field"><span>Название</span><input value={environmentName} onChange={(event) => setEnvironmentName(event.target.value)} /></label>
              <label className="field"><span>Тип</span><select value={environmentType} onChange={(event) => { const type = event.target.value as ReleaseEnvironment['environment_type']; setEnvironmentType(type); setEnvironmentProduction(type === 'PRODUCTION') }}>{releaseEnvironmentTypes.map((type) => <option value={type} key={type}>{translate(releaseEnvironmentLabel(type))}</option>)}</select></label>
              <label className="field"><span>Порядок</span><input type="number" min="1" value={promotionOrder} onChange={(event) => setPromotionOrder(Number(event.target.value))} /></label>
              <label className="checkbox-row"><input type="checkbox" checked={environmentProduction} disabled={environmentType === 'PRODUCTION'} onChange={(event) => setEnvironmentProduction(event.target.checked)} /><span>Production target</span></label>
              <button className="primary-button" disabled={creationBlocked}>Создать среду</button>
            </form>
          ) : null}
        </section>
      ) : null}

      {view === 'ANALYTICS' ? (
        <section className="foundation-card">
          <p className="eyebrow">RELEASE PERFORMANCE · 90 DAYS</p><h2>Качество поставки</h2>
          <div className="release-metrics-grid">
            <article><span>Успех релизов</span><strong>{analyticsQuery.data?.release_success_rate_percent ?? 0}%</strong><small>{analyticsQuery.data?.released ?? 0} опубликовано</small></article>
            <article><span>Deployment frequency</span><strong>{analyticsQuery.data?.deployment_frequency_per_week ?? 0}</strong><small>production / неделю</small></article>
            <article><span>Deployment failure rate</span><strong>{analyticsQuery.data?.deployment_failure_rate_percent ?? 0}%</strong><small>{analyticsQuery.data?.total_deployments ?? 0} развёртываний</small></article>
            <article><span>Rollback rate</span><strong>{analyticsQuery.data?.rollback_rate_percent ?? 0}%</strong><small>координированные откаты</small></article>
            <article><span>Lead time</span><strong>{analyticsQuery.data?.average_release_lead_time_hours ?? 0} ч</strong><small>от создания до выпуска</small></article>
            <article><span>Deployment duration</span><strong>{analyticsQuery.data?.average_deployment_minutes ?? 0} мин</strong><small>среднее исполнение</small></article>
            <article><span>Активно сейчас</span><strong>{analyticsQuery.data?.active_deployments ?? 0}</strong><small>deployment в работе</small></article>
            <article><span>Production deployments</span><strong>{analyticsQuery.data?.production_deployments ?? 0}</strong><small>за период</small></article>
          </div>
        </section>
      ) : null}
    </AppShell></LocalizedContent>
  )
}
