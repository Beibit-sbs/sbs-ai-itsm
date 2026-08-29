import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  changeTeamsConnectorState,
  createTeamsConnector,
  fetchTeamsConnectors,
  fetchTeamsDashboard,
  fetchTeamsDeliveries,
  fetchTeamsMajorIncidentRooms,
  fetchTenants,
  retryTeamsDelivery,
  rotateTeamsWebhook,
  testTeamsConnector,
  updateTeamsConnector,
  type TeamsConnector,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

type View = 'overview' | 'connectors' | 'deliveries' | 'rooms' | 'setup'

const views: Array<{ key: View; label: string }> = [
  { key: 'overview', label: 'Обзор' },
  { key: 'connectors', label: 'Каналы Teams' },
  { key: 'deliveries', label: 'Доставка' },
  { key: 'rooms', label: 'Major Incident' },
  { key: 'setup', label: 'Подключение' },
]
const eventDefaults = [
  'ticket_created', 'ticket_assigned', 'ticket_status_changed', 'ticket_resolved',
  'sla_warning', 'sla_breached', 'approval_required', 'approval.requested',
  'security_high_risk', 'major_incident.declared', 'major_incident.update',
  'major_incident.transitioned', 'automation_failed',
].join(', ')

function statusClass(value: string) {
  const normalized = value.toLowerCase()
  if (['active', 'sent', 'open', 'healthy'].includes(normalized)) return 'badge badge-positive'
  if (['draft', 'paused', 'queued', 'retry', 'not_configured', 'simulated'].includes(normalized)) return 'badge badge-warning'
  return 'badge badge-danger'
}
function splitValues(value: string) {
  return value.split(/[\n,;]+/).map((item) => item.trim().toLowerCase()).filter(Boolean)
}
function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

const emptyDraft = {
  name: 'Service Desk Teams',
  provider_type: 'WORKFLOW_WEBHOOK' as const,
  purpose: 'DEFAULT' as TeamsConnector['purpose'],
  webhook_url: '',
  team_name: '',
  channel_name: '',
  channel_url: '',
  meeting_url: '',
  event_types: eventDefaults,
  minimum_severity: 'INFO' as TeamsConnector['minimum_severity'],
}

export default function TeamsCollaborationPage() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const canManage = isRoot || session?.user.permissions.includes('teams.connectors.manage')
  const canRetry = isRoot || session?.user.permissions.includes('teams.deliveries.manage')
  const [view, setView] = useState<View>('overview')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [selectedId, setSelectedId] = useState('')
  const [deliveryStatus, setDeliveryStatus] = useState('ALL')
  const [busyAction, setBusyAction] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [newWebhook, setNewWebhook] = useState('')
  const [createDraft, setCreateDraft] = useState(emptyDraft)
  const [editDraft, setEditDraft] = useState({
    name: '',
    purpose: 'DEFAULT' as TeamsConnector['purpose'],
    team_name: '',
    channel_name: '',
    channel_url: '',
    meeting_url: '',
    event_types: eventDefaults,
    minimum_severity: 'INFO' as TeamsConnector['minimum_severity'],
  })

  const tenantsQuery = useQuery({
    queryKey: ['teams-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot),
  })
  useEffect(() => {
    if (isRoot && !tenantId && tenantsQuery.data?.length) setTenantId(tenantsQuery.data[0].id)
  }, [isRoot, tenantId, tenantsQuery.data])
  const scopedTenant = isRoot ? tenantId || null : session?.user.tenant_id ?? null

  const dashboardQuery = useQuery({
    queryKey: ['teams-dashboard', token, scopedTenant],
    queryFn: () => fetchTeamsDashboard(token, scopedTenant),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 30_000,
  })
  const connectorsQuery = useQuery({
    queryKey: ['teams-connectors', token, scopedTenant],
    queryFn: () => fetchTeamsConnectors(token, scopedTenant),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 30_000,
  })
  const deliveriesQuery = useQuery({
    queryKey: ['teams-deliveries', token, scopedTenant, selectedId, deliveryStatus],
    queryFn: () => fetchTeamsDeliveries(token, {
      tenant_id: scopedTenant,
      connector_id: selectedId || undefined,
      status: deliveryStatus,
    }),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 15_000,
  })
  const roomsQuery = useQuery({
    queryKey: ['teams-rooms', token, scopedTenant],
    queryFn: () => fetchTeamsMajorIncidentRooms(token, scopedTenant),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 30_000,
  })
  const selected = useMemo(
    () => (connectorsQuery.data ?? []).find((item) => item.id === selectedId) ?? null,
    [connectorsQuery.data, selectedId],
  )
  useEffect(() => {
    if (!selectedId && connectorsQuery.data?.length) setSelectedId(connectorsQuery.data[0].id)
  }, [connectorsQuery.data, selectedId])
  useEffect(() => {
    if (!selected) return
    setEditDraft({
      name: selected.name,
      purpose: selected.purpose,
      team_name: selected.team_name ?? '',
      channel_name: selected.channel_name ?? '',
      channel_url: selected.channel_url ?? '',
      meeting_url: selected.meeting_url ?? '',
      event_types: selected.event_types.join(', '),
      minimum_severity: selected.minimum_severity,
    })
  }, [selected])

  const invalidate = () => Promise.all([
    queryClient.invalidateQueries({ queryKey: ['teams-dashboard'] }),
    queryClient.invalidateQueries({ queryKey: ['teams-connectors'] }),
    queryClient.invalidateQueries({ queryKey: ['teams-deliveries'] }),
    queryClient.invalidateQueries({ queryKey: ['teams-rooms'] }),
  ])
  const runAction = async (key: string, action: () => Promise<unknown>, message: string) => {
    setBusyAction(key)
    setError('')
    setNotice('')
    try {
      await action()
      setNotice(message)
      await invalidate()
    } catch (actionError) {
      setError(errorText(actionError))
    } finally {
      setBusyAction('')
    }
  }
  const dashboard = dashboardQuery.data
  const busy = Boolean(busyAction)

  return (
    <LocalizedContent><AppShell title="Microsoft Teams" subtitle="Production-уведомления, безопасные согласования и комнаты Major Incident.">
      {isRoot ? (
        <section className="tenant-context-bar"><label>Организация
          <select value={tenantId} onChange={(event) => { setTenantId(event.target.value); setSelectedId('') }}>
            <option value="">Выберите организацию</option>
            {(tenantsQuery.data ?? []).map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
          </select>
        </label></section>
      ) : null}
      <nav className="module-subnav" aria-label="Microsoft Teams">
        {views.map((item) => <button key={item.key} type="button" className={view === item.key ? 'module-subnav-tab active' : 'module-subnav-tab'} onClick={() => setView(item.key)}>{translate(item.label)}</button>)}
      </nav>
      {notice ? <div className="alert alert-success">{notice}</div> : null}
      <QueryFailureNotice
        title="Часть данных Teams Collaboration недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: translate('оперативная сводка'), query: dashboardQuery },
          { label: translate('коннекторы'), query: connectorsQuery },
          { label: translate('доставки'), query: deliveriesQuery },
          { label: 'collaboration rooms', query: roomsQuery },
        ]}
      />
      {error ? <div className="alert alert-error" role="alert">{error}</div> : null}

      {view === 'overview' ? <>
        <section className="identity-metrics email-metrics">
          <article><strong>{dashboard?.active_production_connectors ?? 0}</strong><span>production-каналов</span></article>
          <article><strong>{dashboard?.sent_last_24h ?? 0}</strong><span>отправлено за 24 часа</span></article>
          <article><strong>{dashboard?.simulated_deliveries ?? 0}</strong><span>локальных симуляций</span></article>
          <article><strong>{(dashboard?.queued_deliveries ?? 0) + (dashboard?.retrying_deliveries ?? 0)}</strong><span>в очереди</span></article>
          <article className={(dashboard?.failed_deliveries ?? 0) > 0 ? 'metric-danger' : ''}><strong>{dashboard?.failed_deliveries ?? 0}</strong><span>ошибок</span></article>
          <article><strong>{dashboard?.open_incident_rooms ?? 0}</strong><span>war room</span></article>
        </section>
        <section className="identity-overview-grid">
          <article className="panel">
            <div className="section-heading"><div><p className="eyebrow">СОСТОЯНИЕ</p><h2>Готовность Teams</h2></div><span className={statusClass(dashboard?.channel_health ?? 'NOT_CONFIGURED')}>{dashboard?.channel_health ?? 'NOT_CONFIGURED'}</span></div>
            <ul className="identity-checklist">
              <li>{(dashboard?.active_production_connectors ?? 0) > 0 ? '✓' : '○'} Активный Teams Workflow webhook</li>
              <li>{dashboard?.public_base_url_configured ? '✓' : '○'} HTTPS URL для защищённых переходов</li>
              <li>{(dashboard?.failed_deliveries ?? 0) === 0 ? '✓' : '!'} Нет необработанных ошибок доставки</li>
              <li>✓ Webhook зашифрован и скрыт от UI и журналов</li>
            </ul>
          </article>
          <article className="panel"><p className="eyebrow">БЕЗОПАСНОСТЬ</p><h2>Решение остаётся в ITSM</h2>
            <ol className="identity-steps">
              <li><strong>1</strong><span>Teams получает Adaptive Card без секретов.</span></li>
              <li><strong>2</strong><span>Кнопка ведёт только на настроенный домен ITSM.</span></li>
              <li><strong>3</strong><span>Система заново проверяет вход, tenant и RBAC.</span></li>
              <li><strong>4</strong><span>Согласование фиксируется в audit trail.</span></li>
            </ol>
          </article>
        </section>
      </> : null}

      {view === 'connectors' ? <section className="email-channel-grid">
        <article className="panel">
          <div className="section-heading"><div><p className="eyebrow">CONTROL PLANE</p><h2>Каналы назначения</h2></div><span className="badge">{connectorsQuery.data?.length ?? 0}</span></div>
          <div className="identity-connector-list">{(connectorsQuery.data ?? []).map((connector) => (
            <button type="button" key={connector.id} className={selectedId === connector.id ? 'identity-connector-card selected' : 'identity-connector-card'} onClick={() => setSelectedId(connector.id)}>
              <strong>{connector.name}</strong><span>{connector.purpose} · {connector.team_name ?? 'Team'} / {connector.channel_name ?? 'канал'}</span>
              <span className={statusClass(connector.status)}>{connector.status}</span><span className="identity-card-stats">{connector.provider_type === 'MOCK' ? translate('simulation only') : `${connector.success_count} ${translate('success')}`} · {connector.failure_count} {translate('errors')}</span>
            </button>
          ))}</div>
          {!connectorsQuery.isLoading && !connectorsQuery.data?.length ? <p className="empty-state">Каналов пока нет. Создайте первый в разделе «Подключение».</p> : null}
          {selected ? <div className="email-channel-details">
            {selected.provider_type === 'MOCK' ? <p className="inline-warning">Локальная симуляция: Microsoft Teams webhook не вызывается, доставка не считается отправленной.</p> : null}
            <div className="key-value-list">
              <div><span>Webhook</span><strong>{selected.webhook_configured ? 'настроен' : 'не настроен'}</strong></div>
              <div><span>Последний успех</span><strong>{formatDateTime(selected.last_success_at)}</strong></div>
              <div><span>Последняя ошибка</span><strong>{formatDateTime(selected.last_failure_at)}</strong></div>
              <div><span>Важность</span><strong>{selected.minimum_severity}</strong></div>
            </div>
            {selected.last_error ? <p className="inline-error">{selected.last_error}</p> : null}
            {canManage ? <>
              <div className="button-row">
                <button type="button" disabled={busy} onClick={() => runAction('test', () => testTeamsConnector(token, selected.id), selected.provider_type === 'MOCK' ? 'Проверена локальная симуляция; Teams webhook не вызывался.' : 'Тестовая карточка отправлена.')}>Проверить</button>
                {selected.status === 'ACTIVE'
                  ? <button type="button" className="secondary" disabled={busy} onClick={() => runAction('pause', () => changeTeamsConnectorState(token, selected.id, { expected_version: selected.version, action: 'PAUSE', reason: translate('Приостановлено администратором') }), 'Канал приостановлен.')}>Приостановить</button>
                  : <button type="button" className="secondary" disabled={busy} onClick={() => runAction('activate', () => changeTeamsConnectorState(token, selected.id, { expected_version: selected.version, action: 'ACTIVATE', reason: translate('Активировано администратором') }), 'Канал активирован.')}>Активировать</button>}
              </div>
              <form className="form-grid email-config-form" onSubmit={(event) => {
                event.preventDefault()
                void runAction('update', () => updateTeamsConnector(token, selected.id, {
                  expected_version: selected.version, name: editDraft.name, purpose: editDraft.purpose,
                  team_name: editDraft.team_name || null, channel_name: editDraft.channel_name || null,
                  channel_url: editDraft.channel_url || null, meeting_url: editDraft.meeting_url || null,
                  event_types: splitValues(editDraft.event_types), minimum_severity: editDraft.minimum_severity,
                }), 'Настройки сохранены.')
              }}>
                <label>Название<input required value={editDraft.name} onChange={(event) => setEditDraft({ ...editDraft, name: event.target.value })} /></label>
                <label>Назначение<select value={editDraft.purpose} onChange={(event) => setEditDraft({ ...editDraft, purpose: event.target.value as TeamsConnector['purpose'] })}><option value="DEFAULT">Service Desk</option><option value="APPROVALS">Согласования</option><option value="MAJOR_INCIDENT">Major Incident</option><option value="SECURITY">Безопасность</option></select></label>
                <label>Team<input value={editDraft.team_name} onChange={(event) => setEditDraft({ ...editDraft, team_name: event.target.value })} /></label>
                <label>Канал<input value={editDraft.channel_name} onChange={(event) => setEditDraft({ ...editDraft, channel_name: event.target.value })} /></label>
                <label className="span-2">События<textarea rows={3} value={editDraft.event_types} onChange={(event) => setEditDraft({ ...editDraft, event_types: event.target.value })} /></label>
                <label>Важность<select value={editDraft.minimum_severity} onChange={(event) => setEditDraft({ ...editDraft, minimum_severity: event.target.value as TeamsConnector['minimum_severity'] })}><option>INFO</option><option>WARNING</option><option>CRITICAL</option></select></label>
                <label>Ссылка на канал<input value={editDraft.channel_url} onChange={(event) => setEditDraft({ ...editDraft, channel_url: event.target.value })} placeholder="https://teams.microsoft.com/..." /></label>
                <label className="span-2">Ссылка на встречу<input value={editDraft.meeting_url} onChange={(event) => setEditDraft({ ...editDraft, meeting_url: event.target.value })} placeholder="https://teams.microsoft.com/l/meetup-join/..." /></label>
                <button type="submit" disabled={busy}>Сохранить</button>
              </form>
              {selected.provider_type === 'WORKFLOW_WEBHOOK' ? <div className="email-secret-rotation"><input type="password" autoComplete="new-password" value={newWebhook} onChange={(event) => setNewWebhook(event.target.value)} placeholder="Новый Workflow webhook URL" /><button type="button" className="secondary" disabled={busy || newWebhook.length < 20} onClick={() => runAction('rotate', async () => { await rotateTeamsWebhook(token, selected.id, newWebhook); setNewWebhook('') }, 'Webhook заменён. Проверьте и активируйте канал.')}>Заменить webhook</button></div> : null}
              <button type="button" className="danger" disabled={busy || selected.status === 'REVOKED'} onClick={() => {
                if (window.confirm(translate('Отозвать webhook и отключить канал?'))) void runAction('revoke', () => changeTeamsConnectorState(token, selected.id, { expected_version: selected.version, action: 'REVOKE', reason: translate('Отозван администратором') }), 'Канал отозван, секрет удалён.')
              }}>Отозвать канал</button>
            </> : null}
          </div> : null}
        </article>
        <article className="panel"><p className="eyebrow">РАЗДЕЛЕНИЕ ПОТОКОВ</p><h2>Рекомендуемая схема</h2>
          <ul className="identity-checklist"><li><strong>Service Desk</strong> — заявки, назначения и SLA.</li><li><strong>Согласования</strong> — запросы, изменения, automation.</li><li><strong>Major Incident</strong> — SEV1/SEV2, war room и встреча.</li><li><strong>Безопасность</strong> — high-risk события без чувствительных деталей.</li></ul>
          <div className="alert alert-info">Для разных аудиторий создавайте отдельные Teams Workflows и направления.</div>
        </article>
      </section> : null}

      {view === 'deliveries' ? <section className="panel">
        <div className="section-heading"><div><p className="eyebrow">OUTBOX</p><h2>Очередь и история доставки</h2></div><span className="badge">{deliveriesQuery.data?.length ?? 0}</span></div>
        <div className="filter-row"><select value={selectedId} onChange={(event) => setSelectedId(event.target.value)}><option value="">Все каналы</option>{(connectorsQuery.data ?? []).map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
          <select value={deliveryStatus} onChange={(event) => setDeliveryStatus(event.target.value)}><option value="ALL">Все состояния</option>{['QUEUED', 'RETRY', 'SIMULATED', 'SENT', 'FAILED', 'DEAD_LETTER', 'CANCELLED'].map((item) => <option key={item}>{item}</option>)}</select></div>
        <div className="table-scroll"><table><thead><tr><th>Время</th><th>Событие</th><th>Сообщение</th><th>Состояние</th><th>Попытки</th><th>Ошибка</th><th /></tr></thead><tbody>
          {(deliveriesQuery.data ?? []).map((item) => <tr key={item.id}><td>{formatDateTime(item.created_at)}</td><td><strong>{item.event_type}</strong><small>{item.severity}</small></td><td><strong>{item.title}</strong><small>{item.message}</small></td><td><span className={statusClass(item.status)}>{item.status}</span><small>{item.status === 'SIMULATED' ? 'Webhook не вызывался' : `HTTP ${item.provider_status_code ?? '—'}`}</small></td><td>{item.attempts}/{item.max_attempts}<small>{formatDateTime(item.next_attempt_at)}</small></td><td>{item.last_error ?? '—'}</td><td>{canRetry && ['FAILED', 'DEAD_LETTER', 'CANCELLED'].includes(item.status) ? <button type="button" className="secondary compact" disabled={busy} onClick={() => runAction(`retry-${item.id}`, () => retryTeamsDelivery(token, item.id, translate('Ручной повтор администратором')), 'Сообщение возвращено в очередь.')}>Повторить</button> : null}</td></tr>)}
        </tbody></table></div>
        {!deliveriesQuery.isLoading && !deliveriesQuery.data?.length ? <p className="empty-state">Сообщений по фильтру нет.</p> : null}
      </section> : null}

      {view === 'rooms' ? <section className="panel">
        <div className="section-heading"><div><p className="eyebrow">MAJOR INCIDENT</p><h2>Комнаты реагирования</h2></div><span className="badge">{roomsQuery.data?.length ?? 0}</span></div>
        <div className="table-scroll"><table><thead><tr><th>Открыта</th><th>Инцидент</th><th>Состояние</th><th>Канал</th><th>Встреча</th><th>Закрыта</th></tr></thead><tbody>
          {(roomsQuery.data ?? []).map((room) => <tr key={room.id}><td>{formatDateTime(room.opened_at)}</td><td><code>{room.major_incident_id.slice(0, 12)}</code></td><td><span className={statusClass(room.status)}>{room.status}</span></td><td>{room.channel_url ? <a href={room.channel_url} target="_blank" rel="noreferrer">Открыть</a> : '—'}</td><td>{room.meeting_url ? <a href={room.meeting_url} target="_blank" rel="noreferrer">Подключиться</a> : '—'}</td><td>{formatDateTime(room.closed_at)}</td></tr>)}
        </tbody></table></div><p className="muted">Комната создаётся автоматически при объявлении Major Incident, если активен канал MAJOR_INCIDENT.</p>
      </section> : null}

      {view === 'setup' ? <section className="email-channel-grid">
        <article className="panel"><p className="eyebrow">MICROSOFT TEAMS WORKFLOWS</p><h2>Пошаговое подключение</h2>
          <ol className="identity-steps"><li><strong>1</strong><span>В канале Teams откройте Workflows и выберите «Post to a channel when a webhook request is received».</span></li><li><strong>2</strong><span>Укажите владельцев и целевой Team/Channel, скопируйте HTTPS URL.</span></li><li><strong>3</strong><span>Создайте направление: URL сразу шифруется AES-256-GCM.</span></li><li><strong>4</strong><span>Отправьте тестовую карточку и активируйте канал.</span></li><li><strong>5</strong><span>На сервере задайте TEAMS_PUBLIC_BASE_URL для безопасных кнопок.</span></li></ol>
          <div className="alert alert-info">Прямое app-only сообщение через Graph не используется: Microsoft разрешает это только для миграции данных.</div>
        </article>
        <article className="panel"><p className="eyebrow">НОВЫЙ КАНАЛ</p><h2>Создать направление</h2>
          {canManage ? <form className="form-grid email-create-form" onSubmit={(event) => {
            event.preventDefault()
            void runAction('create', async () => {
              const created = await createTeamsConnector(token, {
                tenant_id: scopedTenant, name: createDraft.name, provider_type: 'WORKFLOW_WEBHOOK',
                purpose: createDraft.purpose, webhook_url: createDraft.webhook_url,
                team_name: createDraft.team_name || null, channel_name: createDraft.channel_name || null,
                channel_url: createDraft.channel_url || null, meeting_url: createDraft.meeting_url || null,
                event_types: splitValues(createDraft.event_types), minimum_severity: createDraft.minimum_severity,
              })
              setSelectedId(created.id); setCreateDraft(emptyDraft); setView('connectors')
            }, 'Направление создано. Проверьте и активируйте его.')
          }}>
            <label>Название<input required value={createDraft.name} onChange={(event) => setCreateDraft({ ...createDraft, name: event.target.value })} /></label>
            <label>Назначение<select value={createDraft.purpose} onChange={(event) => setCreateDraft({ ...createDraft, purpose: event.target.value as TeamsConnector['purpose'] })}><option value="DEFAULT">Service Desk</option><option value="APPROVALS">Согласования</option><option value="MAJOR_INCIDENT">Major Incident</option><option value="SECURITY">Безопасность</option></select></label>
            <label>Team<input value={createDraft.team_name} onChange={(event) => setCreateDraft({ ...createDraft, team_name: event.target.value })} /></label>
            <label>Канал<input value={createDraft.channel_name} onChange={(event) => setCreateDraft({ ...createDraft, channel_name: event.target.value })} /></label>
            <label className="span-2">Workflow Webhook URL<input required type="password" autoComplete="new-password" value={createDraft.webhook_url} onChange={(event) => setCreateDraft({ ...createDraft, webhook_url: event.target.value })} /></label>
            <label className="span-2">События<textarea rows={4} value={createDraft.event_types} onChange={(event) => setCreateDraft({ ...createDraft, event_types: event.target.value })} /></label>
            <label>Важность<select value={createDraft.minimum_severity} onChange={(event) => setCreateDraft({ ...createDraft, minimum_severity: event.target.value as TeamsConnector['minimum_severity'] })}><option>INFO</option><option>WARNING</option><option>CRITICAL</option></select></label>
            {createDraft.purpose === 'MAJOR_INCIDENT' ? <><label className="span-2">Ссылка на канал<input value={createDraft.channel_url} onChange={(event) => setCreateDraft({ ...createDraft, channel_url: event.target.value })} placeholder="https://teams.microsoft.com/..." /></label><label className="span-2">Ссылка на встречу<input value={createDraft.meeting_url} onChange={(event) => setCreateDraft({ ...createDraft, meeting_url: event.target.value })} placeholder="https://teams.microsoft.com/l/meetup-join/..." /></label></> : null}
            <button type="submit" disabled={busy || !scopedTenant}>Создать</button>
          </form> : <p className="empty-state">Недостаточно прав для настройки Teams.</p>}
        </article>
      </section> : null}
    </AppShell></LocalizedContent>
  )
}
