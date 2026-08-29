import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  acknowledgeEventGroup,
  createEventPolicy,
  createEventSource,
  createEventSuppression,
  evaluateEventEscalations,
  fetchEventGroup,
  fetchEventGroups,
  fetchEventOperationsSummary,
  fetchEventPolicies,
  fetchEventResponders,
  fetchEventSources,
  fetchEventSuppressions,
  fetchNormalizedEvents,
  fetchMonitoringWebhookReceipts,
  fetchTenants,
  rotateEventSourceToken,
  rotateEventSourceHmacSecret,
  reprocessMonitoringWebhookReceipt,
  updateEventPolicy,
  updateEventSource,
  updateEventSuppression,
  type EventCorrelationPolicy,
  type EventPolicyRequest,
  type EventSource,
  type EventSuppressionRequest,
  type EventSuppressionRule,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

type View = 'QUEUE' | 'POLICIES' | 'SOURCES' | 'RECEIPTS' | 'EVENTS'

function inputDate(value: Date) {
  const local = new Date(value.getTime() - value.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function policyRequest(item: EventCorrelationPolicy): EventPolicyRequest {
  return {
    name: item.name,
    description: item.description ?? undefined,
    is_active: item.is_active,
    priority_order: item.priority_order,
    matchers: item.matchers,
    group_by: item.group_by,
    correlation_window_minutes: item.correlation_window_minutes,
    min_occurrences: item.min_occurrences,
    incident_mode: item.incident_mode,
    fixed_priority: item.fixed_priority ?? undefined,
    category: item.category,
    title_template: item.title_template,
    resolution_action: item.resolution_action,
    primary_user_id: item.primary_user_id ?? undefined,
    fallback_user_id: item.fallback_user_id ?? undefined,
    acknowledge_within_minutes: item.acknowledge_within_minutes,
    escalate_after_minutes: item.escalate_after_minutes,
  }
}

function suppressionRequest(item: EventSuppressionRule): EventSuppressionRequest {
  return {
    name: item.name,
    reason: item.reason,
    matchers: item.matchers,
    starts_at: item.starts_at ?? undefined,
    ends_at: item.ends_at ?? undefined,
    is_active: item.is_active,
  }
}

export default function EventOperationsPage() {
  const { session } = useAuth()
  const { formatDateTime: formatDate, translate } = useTenantExperience()
  const token = session?.access_token ?? ''
  const root = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const hasPermission = (permission: string) => root || permissions.has(permission)
  const canReadEvents = hasPermission('monitoring.events.read')
  const canUpdateEvents = hasPermission('monitoring.events.manage')
  const canReadSources = hasPermission('monitoring.connectors.read')
  const canManageSources = hasPermission('monitoring.connectors.manage')
  const canReadReceipts = hasPermission('monitoring.receipts.read')
  const canManageReceipts = hasPermission('monitoring.receipts.manage')
  const canManageEventPolicies = hasPermission('integrations.manage')
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [view, setView] = useState<View>(
    canReadEvents ? 'QUEUE' : canReadSources ? 'SOURCES' : 'RECEIPTS',
  )
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(searchParams.get('group'))
  const [groupStatus, setGroupStatus] = useState('OPEN')
  const [ackNote, setAckNote] = useState('')
  const [eventDisposition, setEventDisposition] = useState('ALL')
  const [eventSeverity, setEventSeverity] = useState('ALL')
  const [revealedToken, setRevealedToken] = useState<{ source: EventSource; secret: string; kind: 'Bearer token' | 'HMAC secret' } | null>(null)
  const [sourceForm, setSourceForm] = useState({
    code: '',
    name: '',
    source_type: 'ALERTMANAGER',
    auth_mode: 'HMAC_SHA256' as 'BEARER' | 'HMAC_SHA256',
    replay_window_seconds: 300,
    rate_limit_per_minute: 120,
    max_payload_kb: 1024,
    allowed_ip_cidrs: '',
    signing_secret: '',
  })
  const [receiptStatus, setReceiptStatus] = useState('ALL')
  const [receiptSourceId, setReceiptSourceId] = useState('')
  const [sourceEdits, setSourceEdits] = useState<Record<string, {
    rate_limit_per_minute: number
    max_payload_kb: number
    replay_window_seconds: number
    allowed_ip_cidrs: string
    signing_secret: string
  }>>({})
  const [policyForm, setPolicyForm] = useState({
    name: '',
    description: '',
    priority_order: 100,
    matcher_field: 'label.alertname',
    matcher_operator: 'EQUALS' as 'EQUALS' | 'NOT_EQUALS' | 'CONTAINS' | 'PREFIX' | 'EXISTS',
    matcher_value: '',
    group_by: 'service,resource',
    correlation_window_minutes: 60,
    min_occurrences: 1,
    incident_mode: 'CREATE_UPDATE' as 'CREATE_UPDATE' | 'CORRELATE_ONLY' | 'IGNORE',
    fixed_priority: '',
    category: 'NETWORK_INTERNET',
    title_template: '{service}: {summary}',
    resolution_action: 'RESOLVE' as 'NONE' | 'RESOLVE' | 'CLOSE',
    primary_user_id: '',
    fallback_user_id: '',
    acknowledge_within_minutes: 15,
    escalate_after_minutes: 15,
  })
  const [suppressionForm, setSuppressionForm] = useState({
    name: '',
    reason: '',
    matcher_field: 'service',
    matcher_operator: 'EQUALS' as 'EQUALS' | 'NOT_EQUALS' | 'CONTAINS' | 'PREFIX' | 'EXISTS',
    matcher_value: '',
    starts_at: inputDate(new Date()),
    ends_at: inputDate(new Date(Date.now() + 60 * 60 * 1_000)),
  })

  const tenantsQuery = useQuery({
    queryKey: ['event-operations-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && root),
  })
  useEffect(() => {
    if (root && !tenantId && tenantsQuery.data?.[0]) setTenantId(tenantsQuery.data[0].id)
  }, [root, tenantId, tenantsQuery.data])
  const scopeReady = Boolean(token && (!root || tenantId))
  const scopedTenant = tenantId || undefined
  const canOpenSourcesView = canReadSources || canReadEvents

  useEffect(() => {
    const allowed = (view === 'QUEUE' || view === 'POLICIES' || view === 'EVENTS')
      ? canReadEvents
      : view === 'SOURCES'
        ? canOpenSourcesView
        : canReadReceipts
    if (allowed) return
    setView(canReadEvents ? 'QUEUE' : canOpenSourcesView ? 'SOURCES' : 'RECEIPTS')
  }, [canOpenSourcesView, canReadEvents, canReadReceipts, view])

  const summaryQuery = useQuery({
    queryKey: ['event-operations-summary', token, scopedTenant],
    queryFn: () => fetchEventOperationsSummary(token, scopedTenant),
    enabled: scopeReady && canReadEvents,
    refetchInterval: 30_000,
  })
  const groupsQuery = useQuery({
    queryKey: ['event-groups', token, scopedTenant, groupStatus],
    queryFn: () => fetchEventGroups(token, { tenant_id: scopedTenant, group_status: groupStatus }),
    enabled: scopeReady && canReadEvents,
    refetchInterval: 30_000,
  })
  const detailQuery = useQuery({
    queryKey: ['event-group', token, selectedGroupId],
    queryFn: () => fetchEventGroup(token, selectedGroupId ?? ''),
    enabled: Boolean(token && selectedGroupId && canReadEvents),
  })
  const respondersQuery = useQuery({
    queryKey: ['event-responders', token, scopedTenant],
    queryFn: () => fetchEventResponders(token, scopedTenant),
    enabled: scopeReady && canReadEvents,
  })
  const sourcesQuery = useQuery({
    queryKey: ['event-sources', token, scopedTenant],
    queryFn: () => fetchEventSources(token, scopedTenant),
    enabled: scopeReady && canReadSources,
  })
  useEffect(() => {
    if (!sourcesQuery.data) return
    setSourceEdits((current) => {
      const next = { ...current }
      for (const item of sourcesQuery.data) {
        if (!next[item.id]) {
          next[item.id] = {
            rate_limit_per_minute: item.rate_limit_per_minute,
            max_payload_kb: Math.round(item.max_payload_bytes / 1024),
            replay_window_seconds: item.replay_window_seconds,
            allowed_ip_cidrs: item.allowed_ip_cidrs.join(', '),
            signing_secret: '',
          }
        }
      }
      return next
    })
  }, [sourcesQuery.data])
  const policiesQuery = useQuery({
    queryKey: ['event-policies', token, scopedTenant],
    queryFn: () => fetchEventPolicies(token, scopedTenant),
    enabled: scopeReady && canReadEvents,
  })
  const suppressionsQuery = useQuery({
    queryKey: ['event-suppressions', token, scopedTenant],
    queryFn: () => fetchEventSuppressions(token, scopedTenant),
    enabled: scopeReady && canReadEvents,
  })
  const eventsQuery = useQuery({
    queryKey: ['normalized-events', token, scopedTenant, eventDisposition, eventSeverity],
    queryFn: () => fetchNormalizedEvents(token, {
      tenant_id: scopedTenant,
      disposition: eventDisposition,
      severity: eventSeverity,
    }),
    enabled: scopeReady && canReadEvents && view === 'EVENTS',
  })
  const receiptsQuery = useQuery({
    queryKey: ['monitoring-webhook-receipts', token, scopedTenant, receiptStatus, receiptSourceId],
    queryFn: () => fetchMonitoringWebhookReceipts(token, {
      tenant_id: scopedTenant,
      source_id: receiptSourceId || undefined,
      status: receiptStatus,
    }),
    enabled: scopeReady && canReadReceipts && view === 'RECEIPTS',
    refetchInterval: 15_000,
  })

  useEffect(() => {
    if (!selectedGroupId && groupsQuery.data?.[0]) setSelectedGroupId(groupsQuery.data[0].id)
  }, [groupsQuery.data, selectedGroupId])

  function selectGroup(id: string) {
    setSelectedGroupId(id)
    setSearchParams({ group: id })
  }

  async function refreshOperations() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['event-operations-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['event-groups'] }),
      queryClient.invalidateQueries({ queryKey: ['event-group'] }),
      queryClient.invalidateQueries({ queryKey: ['normalized-events'] }),
    ])
  }

  const acknowledgeMutation = useMutation({
    mutationFn: () => acknowledgeEventGroup(token, detailQuery.data!, ackNote),
    onSuccess: async (item) => {
      setAckNote('')
      queryClient.setQueryData(['event-group', token, item.id], item)
      await refreshOperations()
    },
  })
  const evaluateMutation = useMutation({
    mutationFn: () => evaluateEventEscalations(token, scopedTenant),
    onSuccess: refreshOperations,
  })
  const sourceCreateMutation = useMutation({
    mutationFn: () => createEventSource(token, {
      tenant_id: scopedTenant,
      code: sourceForm.code,
      name: sourceForm.name,
      source_type: sourceForm.source_type,
      auth_mode: sourceForm.auth_mode,
      replay_window_seconds: sourceForm.replay_window_seconds,
      rate_limit_per_minute: sourceForm.rate_limit_per_minute,
      max_payload_bytes: sourceForm.max_payload_kb * 1024,
      allowed_ip_cidrs: sourceForm.allowed_ip_cidrs
        .split(/[\n,;]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      signing_secret: sourceForm.signing_secret || undefined,
    }),
    onSuccess: async (item) => {
      setSourceForm({
        code: '',
        name: '',
        source_type: 'ALERTMANAGER',
        auth_mode: 'HMAC_SHA256',
        replay_window_seconds: 300,
        rate_limit_per_minute: 120,
        max_payload_kb: 1024,
        allowed_ip_cidrs: '',
        signing_secret: '',
      })
      if (item.ingest_token) setRevealedToken({ source: item, secret: item.ingest_token, kind: 'Bearer token' })
      if (item.signing_secret) setRevealedToken({ source: item, secret: item.signing_secret, kind: 'HMAC secret' })
      await queryClient.invalidateQueries({ queryKey: ['event-sources'] })
    },
  })
  const sourceToggleMutation = useMutation({
    mutationFn: (item: EventSource) => updateEventSource(token, item, { is_enabled: !item.is_enabled }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['event-sources'] }),
  })
  const sourceRotateMutation = useMutation({
    mutationFn: ({ item, signingSecret }: { item: EventSource; signingSecret?: string }) => item.auth_mode === 'HMAC_SHA256'
      ? rotateEventSourceHmacSecret(token, item, signingSecret)
      : rotateEventSourceToken(token, item),
    onSuccess: async (item) => {
      if (item.ingest_token) setRevealedToken({ source: item, secret: item.ingest_token, kind: 'Bearer token' })
      if (item.signing_secret) setRevealedToken({ source: item, secret: item.signing_secret, kind: 'HMAC secret' })
      setSourceEdits((current) => current[item.id]
        ? { ...current, [item.id]: { ...current[item.id], signing_secret: '' } }
        : current)
      await queryClient.invalidateQueries({ queryKey: ['event-sources'] })
    },
  })
  const sourcePolicyMutation = useMutation({
    mutationFn: (item: EventSource) => {
      const draft = sourceEdits[item.id]
      return updateEventSource(token, item, {
        rate_limit_per_minute: draft.rate_limit_per_minute,
        max_payload_bytes: draft.max_payload_kb * 1024,
        replay_window_seconds: draft.replay_window_seconds,
        allowed_ip_cidrs: draft.allowed_ip_cidrs
          .split(/[\n,;]+/)
          .map((value) => value.trim())
          .filter(Boolean),
      })
    },
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['event-sources'] }),
  })
  const receiptReprocessMutation = useMutation({
    mutationFn: (receiptId: string) => reprocessMonitoringWebhookReceipt(token, receiptId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['monitoring-webhook-receipts'] }),
        queryClient.invalidateQueries({ queryKey: ['event-sources'] }),
      ])
    },
  })
  const policyCreateMutation = useMutation({
    mutationFn: () => createEventPolicy(token, {
      tenant_id: scopedTenant,
      name: policyForm.name,
      description: policyForm.description || undefined,
      is_active: true,
      priority_order: policyForm.priority_order,
      matchers: [{
        field: policyForm.matcher_field,
        operator: policyForm.matcher_operator,
        value: policyForm.matcher_operator === 'EXISTS' ? '' : policyForm.matcher_value,
      }],
      group_by: policyForm.group_by.split(',').map((item) => item.trim()).filter(Boolean),
      correlation_window_minutes: policyForm.correlation_window_minutes,
      min_occurrences: policyForm.min_occurrences,
      incident_mode: policyForm.incident_mode,
      fixed_priority: policyForm.fixed_priority || undefined,
      category: policyForm.category,
      title_template: policyForm.title_template,
      resolution_action: policyForm.resolution_action,
      primary_user_id: policyForm.primary_user_id || undefined,
      fallback_user_id: policyForm.fallback_user_id || undefined,
      acknowledge_within_minutes: policyForm.acknowledge_within_minutes,
      escalate_after_minutes: policyForm.escalate_after_minutes,
    }),
    onSuccess: async () => {
      setPolicyForm((value) => ({ ...value, name: '', description: '', matcher_value: '' }))
      await queryClient.invalidateQueries({ queryKey: ['event-policies'] })
    },
  })
  const policyToggleMutation = useMutation({
    mutationFn: (item: EventCorrelationPolicy) => updateEventPolicy(token, item, {
      ...policyRequest(item),
      is_active: !item.is_active,
    }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['event-policies'] }),
  })
  const suppressionCreateMutation = useMutation({
    mutationFn: () => createEventSuppression(token, {
      tenant_id: scopedTenant,
      name: suppressionForm.name,
      reason: suppressionForm.reason,
      matchers: [{
        field: suppressionForm.matcher_field,
        operator: suppressionForm.matcher_operator,
        value: suppressionForm.matcher_operator === 'EXISTS' ? '' : suppressionForm.matcher_value,
      }],
      starts_at: new Date(suppressionForm.starts_at).toISOString(),
      ends_at: new Date(suppressionForm.ends_at).toISOString(),
      is_active: true,
    }),
    onSuccess: async () => {
      setSuppressionForm((value) => ({ ...value, name: '', reason: '', matcher_value: '' }))
      await queryClient.invalidateQueries({ queryKey: ['event-suppressions'] })
    },
  })
  const suppressionToggleMutation = useMutation({
    mutationFn: (item: EventSuppressionRule) => updateEventSuppression(token, item, {
      ...suppressionRequest(item),
      is_active: !item.is_active,
    }),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['event-suppressions'] }),
  })

  const errors = [
    tenantsQuery.error,
    summaryQuery.error,
    groupsQuery.error,
    detailQuery.error,
    respondersQuery.error,
    sourcesQuery.error,
    policiesQuery.error,
    suppressionsQuery.error,
    eventsQuery.error,
    acknowledgeMutation.error,
    evaluateMutation.error,
    sourceCreateMutation.error,
    sourceToggleMutation.error,
    sourceRotateMutation.error,
    sourcePolicyMutation.error,
    receiptReprocessMutation.error,
    receiptsQuery.error,
    policyCreateMutation.error,
    policyToggleMutation.error,
    suppressionCreateMutation.error,
    suppressionToggleMutation.error,
  ].filter(Boolean)
  const detail = detailQuery.data
  const policyFormValid = useMemo(
    () => policyForm.name.trim().length >= 2
      && policyForm.matcher_field.trim().length > 0
      && (policyForm.matcher_operator === 'EXISTS' || policyForm.matcher_value.trim().length > 0)
      && policyForm.group_by.trim().length > 0,
    [policyForm],
  )

  return (
    <LocalizedContent><AppShell
      title="Event Operations"
      subtitle="Нормализация событий, suppression, correlation, автоматические Incidents и on-call escalation"
    >
      {root ? (
        <section className="event-tenant-selector">
          <label>
            Организация
            <select value={tenantId} onChange={(event) => { setTenantId(event.target.value); setSelectedGroupId(null) }}>
              <option value="">Выберите организацию</option>
              {tenantsQuery.data?.map((item) => <option value={item.id} key={item.id}>{item.name}</option>)}
            </select>
          </label>
        </section>
      ) : null}

      {canReadEvents ? (
        <section className="event-summary-grid">
          <article className="metric-card"><span>Events / 24h</span><strong>{summaryQuery.isPending ? '…' : summaryQuery.isError ? '—' : summaryQuery.data?.events_24h ?? 0}</strong></article>
          <article className="metric-card"><span>Open groups</span><strong>{summaryQuery.isPending ? '…' : summaryQuery.isError ? '—' : summaryQuery.data?.open_groups ?? 0}</strong></article>
          <article className="metric-card"><span>Ack overdue</span><strong>{summaryQuery.isPending ? '…' : summaryQuery.isError ? '—' : summaryQuery.data?.ack_overdue ?? 0}</strong></article>
          <article className="metric-card"><span>Incidents / 24h</span><strong>{summaryQuery.isPending ? '…' : summaryQuery.isError ? '—' : summaryQuery.data?.incidents_24h ?? 0}</strong></article>
          <article className="metric-card"><span>Suppressed / 24h</span><strong>{summaryQuery.isPending ? '…' : summaryQuery.isError ? '—' : summaryQuery.data?.suppressed_24h ?? 0}</strong></article>
          <article className="metric-card"><span>Noise reduction</span><strong>{summaryQuery.isPending ? '…' : summaryQuery.isError ? '—' : `${summaryQuery.data?.noise_reduction_percent ?? 0}%`}</strong></article>
          <article className="metric-card"><span>MTTA / 24h</span><strong>{summaryQuery.isPending ? '…' : summaryQuery.isError ? '—' : `${summaryQuery.data?.mtta_minutes_24h ?? '—'} ${translate('min')}`}</strong></article>
        </section>
      ) : null}

      <section className="event-view-tabs" role="tablist">
        {canReadEvents ? <button type="button" className={view === 'QUEUE' ? 'active' : ''} onClick={() => setView('QUEUE')}>Command Queue</button> : null}
        {canReadEvents ? <button type="button" className={view === 'POLICIES' ? 'active' : ''} onClick={() => setView('POLICIES')}>Correlation Policies</button> : null}
        {canOpenSourcesView ? <button type="button" className={view === 'SOURCES' ? 'active' : ''} onClick={() => setView('SOURCES')}>Sources & Suppression</button> : null}
        {canReadReceipts ? <button type="button" className={view === 'RECEIPTS' ? 'active' : ''} onClick={() => setView('RECEIPTS')}>Webhook Intake</button> : null}
        {canReadEvents ? <button type="button" className={view === 'EVENTS' ? 'active' : ''} onClick={() => setView('EVENTS')}>Event Evidence</button> : null}
      </section>

      {errors.length ? (
        <div className="state-panel state-panel-error" role="alert">
          <strong>Часть данных Event Operations недоступна или операция не выполнена.</strong>
          <p>{errors[0] instanceof Error ? errors[0].message : 'Повторите загрузку или проверьте параметры операции.'}</p>
        </div>
      ) : null}

      {view === 'QUEUE' ? (
        <>
          <section className="event-toolbar">
            <select value={groupStatus} onChange={(event) => { setGroupStatus(event.target.value); setSelectedGroupId(null) }}>
              <option>OPEN</option><option>RESOLVED</option><option>ALL</option>
            </select>
            {canUpdateEvents ? <button type="button" className="ghost-button" disabled={evaluateMutation.isPending} onClick={() => evaluateMutation.mutate()}>
              Проверить просроченные escalation
            </button> : null}
            <span>Worker выполняет эту проверку автоматически каждые 30 секунд.</span>
          </section>
          <section className="event-queue-layout">
            <div className="event-group-list">
              {groupsQuery.data?.map((item) => (
                <button type="button" className={selectedGroupId === item.id ? 'active' : ''} onClick={() => selectGroup(item.id)} key={item.id}>
                  <div><strong>{item.severity}</strong><span>{item.status}</span></div>
                  <b>{item.title}</b>
                  <small>{item.occurrence_count} events · {item.ticket_number ?? 'без Ticket'}</small>
                  <small>{item.assigned_user_name ?? 'Не назначено'} · {formatDate(item.last_event_at)}</small>
                </button>
              ))}
              {!groupsQuery.isPending && !groupsQuery.isError && !groupsQuery.data?.length ? <p className="empty-state">Группы с выбранным статусом отсутствуют.</p> : null}
            </div>
            <div className="event-group-detail">
              {detailQuery.isPending ? <p className="state-panel state-panel-loading" role="status">Загрузка correlation group…</p> : null}
              {detailQuery.isError ? <p className="state-panel state-panel-error" role="alert">Не удалось загрузить выбранную correlation group.</p> : null}
              {!detail && !detailQuery.isPending && !detailQuery.isError ? <p className="empty-state">Выберите correlation group.</p> : detail ? (
                <>
                  <div className="section-header">
                    <div><p className="eyebrow">{detail.policy_name} · {detail.severity}</p><h2>{detail.title}</h2><p>{detail.correlation_key}</p></div>
                    <span className={`impact-severity ${detail.severity === 'CRITICAL' ? 'impact-critical' : 'impact-high'}`}>{detail.status}</span>
                  </div>
                  <div className="detail-fields">
                    <div><span>Occurrences</span><strong>{detail.occurrence_count}</strong></div>
                    <div><span>Assigned</span><strong>{detail.assigned_user_name ?? '—'}</strong></div>
                    <div><span>Acknowledged</span><strong>{detail.acknowledged_by_name ?? 'Нет'}</strong></div>
                    <div><span>Next escalation</span><strong>{formatDate(detail.next_escalation_at)}</strong></div>
                    <div><span>Ticket</span><strong>{detail.ticket_number ? <Link to={`/tickets?ticket=${detail.ticket_id}`}>{detail.ticket_number} · {detail.ticket_status}</Link> : '—'}</strong></div>
                    <div><span>Last event</span><strong>{formatDate(detail.last_event_at)}</strong></div>
                  </div>
                  {canUpdateEvents && detail.status === 'OPEN' && !detail.acknowledged_at ? (
                    <section className="event-ack">
                      <textarea value={ackNote} onChange={(event) => setAckNote(event.target.value)} placeholder="Кто принял ответственность и какое действие выполняется" />
                      <button type="button" disabled={ackNote.trim().length < 3 || acknowledgeMutation.isPending} onClick={() => acknowledgeMutation.mutate()}>Acknowledge</button>
                    </section>
                  ) : null}
                  <section className="event-detail-columns">
                    <div>
                      <h3>Authoritative timeline</h3>
                      <div className="event-timeline">
                        {detail.activities?.slice().reverse().map((item) => (
                          <article key={item.id}><div><strong>{item.activity_type}</strong><span>{formatDate(item.created_at)}</span></div><p>{item.message}</p><small>{item.actor_name}</small></article>
                        ))}
                      </div>
                    </div>
                    <div>
                      <h3>Normalized evidence</h3>
                      <div className="event-evidence-list">
                        {detail.events?.map((item) => (
                          <article key={item.id}><div><strong>{item.severity} · {item.state}</strong><span>{item.disposition}</span></div><p>{item.summary}</p><small>{item.source_name} · {item.resource ?? '—'} · hash {item.raw_payload_hash.slice(0, 12)}</small></article>
                        ))}
                      </div>
                    </div>
                  </section>
                </>
              ) : null}
            </div>
          </section>
        </>
      ) : null}

      {view === 'POLICIES' ? (
        <section className="event-config-layout">
          {canManageEventPolicies ? (
            <form className="event-config-form" onSubmit={(event) => { event.preventDefault(); policyCreateMutation.mutate() }}>
              <div><p className="eyebrow">ORDERED MATCHING</p><h2>Новая correlation policy</h2></div>
              <label>Название<input value={policyForm.name} onChange={(event) => setPolicyForm({ ...policyForm, name: event.target.value })} /></label>
              <label>Описание<textarea value={policyForm.description} onChange={(event) => setPolicyForm({ ...policyForm, description: event.target.value })} /></label>
              <label>Порядок<input type="number" min="1" value={policyForm.priority_order} onChange={(event) => setPolicyForm({ ...policyForm, priority_order: Number(event.target.value) })} /></label>
              <fieldset><legend>Matcher</legend><input value={policyForm.matcher_field} onChange={(event) => setPolicyForm({ ...policyForm, matcher_field: event.target.value })} placeholder="label.alertname" /><select value={policyForm.matcher_operator} onChange={(event) => setPolicyForm({ ...policyForm, matcher_operator: event.target.value as typeof policyForm.matcher_operator })}><option>EQUALS</option><option>CONTAINS</option><option>PREFIX</option><option>NOT_EQUALS</option><option>EXISTS</option></select>{policyForm.matcher_operator !== 'EXISTS' ? <input value={policyForm.matcher_value} onChange={(event) => setPolicyForm({ ...policyForm, matcher_value: event.target.value })} placeholder="HighErrorRate" /> : null}</fieldset>
              <label>Group by<input value={policyForm.group_by} onChange={(event) => setPolicyForm({ ...policyForm, group_by: event.target.value })} placeholder="service,resource" /></label>
              <label>Correlation window, min<input type="number" min="1" value={policyForm.correlation_window_minutes} onChange={(event) => setPolicyForm({ ...policyForm, correlation_window_minutes: Number(event.target.value) })} /></label>
              <label>Threshold occurrences<input type="number" min="1" value={policyForm.min_occurrences} onChange={(event) => setPolicyForm({ ...policyForm, min_occurrences: Number(event.target.value) })} /></label>
              <label>Incident mode<select value={policyForm.incident_mode} onChange={(event) => setPolicyForm({ ...policyForm, incident_mode: event.target.value as typeof policyForm.incident_mode })}><option>CREATE_UPDATE</option><option>CORRELATE_ONLY</option><option>IGNORE</option></select></label>
              <label>Fixed priority<select value={policyForm.fixed_priority} onChange={(event) => setPolicyForm({ ...policyForm, fixed_priority: event.target.value })}><option value="">По severity события</option><option>CRITICAL</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option></select></label>
              <label>Ticket category<input value={policyForm.category} onChange={(event) => setPolicyForm({ ...policyForm, category: event.target.value })} /></label>
              <label>Title template<input value={policyForm.title_template} onChange={(event) => setPolicyForm({ ...policyForm, title_template: event.target.value })} /></label>
              <label>Recovery action<select value={policyForm.resolution_action} onChange={(event) => setPolicyForm({ ...policyForm, resolution_action: event.target.value as typeof policyForm.resolution_action })}><option>NONE</option><option>RESOLVE</option><option>CLOSE</option></select></label>
              <label>Primary on-call<select value={policyForm.primary_user_id} onChange={(event) => setPolicyForm({ ...policyForm, primary_user_id: event.target.value })}><option value="">Operations queue</option>{respondersQuery.data?.map((item) => <option value={item.id} key={item.id}>{item.full_name}</option>)}</select></label>
              <label>Fallback on-call<select value={policyForm.fallback_user_id} onChange={(event) => setPolicyForm({ ...policyForm, fallback_user_id: event.target.value })}><option value="">Без fallback</option>{respondersQuery.data?.filter((item) => item.id !== policyForm.primary_user_id).map((item) => <option value={item.id} key={item.id}>{item.full_name}</option>)}</select></label>
              <label>Acknowledge, min<input type="number" min="1" value={policyForm.acknowledge_within_minutes} onChange={(event) => setPolicyForm({ ...policyForm, acknowledge_within_minutes: Number(event.target.value) })} /></label>
              <label>Fallback reminder, min<input type="number" min="1" value={policyForm.escalate_after_minutes} onChange={(event) => setPolicyForm({ ...policyForm, escalate_after_minutes: Number(event.target.value) })} /></label>
              <button type="submit" disabled={!policyFormValid || policyCreateMutation.isPending}>Создать policy</button>
            </form>
          ) : null}
          <div className="event-policy-list">
            <div><p className="eyebrow">FIRST MATCH WINS</p><h2>Активные политики</h2></div>
            {policiesQuery.data?.map((item) => (
              <article className={!item.is_active ? 'disabled' : ''} key={item.id}>
                <header><div><strong>{item.priority_order} · {item.name}</strong><span>{item.incident_mode} · threshold {item.min_occurrences}</span></div><span className={item.is_active ? 'status-ok' : 'status-muted'}>{item.is_active ? 'ACTIVE' : 'DISABLED'}</span></header>
                <p>{item.matchers.map((matcher) => `${matcher.field} ${matcher.operator} ${matcher.value}`).join(' AND ') || 'Все события'}</p>
                <small>Group: {item.group_by.join(', ')} · {item.correlation_window_minutes} min · recovery {item.resolution_action}</small>
                <small>On-call: {item.primary_user_name ?? 'queue'} → {item.fallback_user_name ?? 'no fallback'} · ack {item.acknowledge_within_minutes} min</small>
                {canManageEventPolicies ? <button type="button" className="ghost-button" onClick={() => policyToggleMutation.mutate(item)}>{item.is_active ? 'Отключить' : 'Включить'}</button> : null}
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {view === 'SOURCES' ? (
        <>
          {canManageSources && revealedToken ? (
            <section className="event-secret-box">
              <div><strong>Сохраните {revealedToken.kind} сейчас — повторно секрет не отображается.</strong><span>Webhook: /api/v1/event-operations/webhooks/{revealedToken.source.id}</span></div>
              <code>{revealedToken.secret}</code>
              <button type="button" onClick={() => navigator.clipboard.writeText(revealedToken.secret)}>Копировать</button>
              <button type="button" className="ghost-button" onClick={() => setRevealedToken(null)}>Я сохранил</button>
            </section>
          ) : null}
          <section className="event-config-layout">
            {canReadSources ? <div className="event-source-column">
              {canManageSources ? (
                <form className="event-config-form compact" onSubmit={(event) => { event.preventDefault(); sourceCreateMutation.mutate() }}>
                  <div><p className="eyebrow">SIGNED INGEST</p><h2>Новый event source</h2></div>
                  <label>Code<input value={sourceForm.code} onChange={(event) => setSourceForm({ ...sourceForm, code: event.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '-') })} placeholder="alertmanager-prod" /></label>
                  <label>Название<input value={sourceForm.name} onChange={(event) => setSourceForm({ ...sourceForm, name: event.target.value })} /></label>
                  <label>Тип<select value={sourceForm.source_type} onChange={(event) => setSourceForm({ ...sourceForm, source_type: event.target.value })}><option>ALERTMANAGER</option><option>PROMETHEUS</option><option>ZABBIX</option><option>SENTRY</option><option>GRAFANA</option><option>GENERIC</option></select></label>
                  <label>Аутентификация<select value={sourceForm.auth_mode} onChange={(event) => setSourceForm({ ...sourceForm, auth_mode: event.target.value as 'BEARER' | 'HMAC_SHA256' })}><option value="HMAC_SHA256">HMAC-SHA256 (рекомендуется)</option><option value="BEARER">Bearer token</option></select></label>
                  {sourceForm.auth_mode === 'HMAC_SHA256' ? <label>Секрет провайдера (опционально)<input type="password" autoComplete="new-password" value={sourceForm.signing_secret} onChange={(event) => setSourceForm({ ...sourceForm, signing_secret: event.target.value })} placeholder="Оставьте пустым, чтобы сгенерировать" /></label> : null}
                  {sourceForm.auth_mode === 'HMAC_SHA256' ? <label>Replay window, сек<input type="number" min="30" max="3600" value={sourceForm.replay_window_seconds} onChange={(event) => setSourceForm({ ...sourceForm, replay_window_seconds: Number(event.target.value) })} /></label> : null}
                  <label>Лимит / минуту<input type="number" min="1" max="100000" value={sourceForm.rate_limit_per_minute} onChange={(event) => setSourceForm({ ...sourceForm, rate_limit_per_minute: Number(event.target.value) })} /></label>
                  <label>Макс. payload, KB<input type="number" min="1" max="2048" value={sourceForm.max_payload_kb} onChange={(event) => setSourceForm({ ...sourceForm, max_payload_kb: Number(event.target.value) })} /></label>
                  <label>Разрешённые IP/CIDR<textarea rows={2} value={sourceForm.allowed_ip_cidrs} onChange={(event) => setSourceForm({ ...sourceForm, allowed_ip_cidrs: event.target.value })} placeholder="10.0.0.0/8, 203.0.113.10/32" /></label>
                  <button type="submit" disabled={sourceForm.code.length < 2 || sourceForm.name.length < 2}>Создать безопасный источник</button>
                </form>
              ) : null}
              <div className="event-source-list">
                {sourcesQuery.data?.map((item) => (
                  <article key={item.id}>
                    <header><div><strong>{item.name}</strong><span>{item.source_type} · {item.code}</span></div><span className={item.is_enabled ? 'status-ok' : 'status-muted'}>{item.is_enabled ? 'ENABLED' : 'DISABLED'}</span></header>
                    <div className="event-source-metrics"><span>{item.total_events} events</span><span>{item.success_count} processed</span><span>{item.dead_letter_count} dead-letter</span><span>{item.duplicate_events} duplicate</span></div>
                    <small>{item.auth_mode} · secret …{item.auth_mode === 'HMAC_SHA256' ? item.hmac_secret_hint : item.token_hint} · replay {item.replay_window_seconds}s · {item.rate_limit_per_minute}/min · {Math.round(item.max_payload_bytes / 1024)}KB</small>
                    <small>Webhook: /api/v1/event-operations/webhooks/{item.id}</small>
                    <small>IP allowlist: {item.allowed_ip_cidrs.join(', ') || 'не ограничен'} · последнее: {formatDate(item.last_event_at)}</small>
                    {item.last_error ? <small className="error-message">{item.last_error}</small> : null}
                    {canManageSources ? <div className="analytics-actions"><button type="button" className="ghost-button" onClick={() => sourceToggleMutation.mutate(item)}>{item.is_enabled ? 'Отключить' : 'Включить'}</button><button type="button" className="ghost-button" onClick={() => sourceRotateMutation.mutate({ item })}>Rotate {item.auth_mode === 'HMAC_SHA256' ? 'HMAC secret' : 'token'}</button></div> : null}
                    {canManageSources && sourceEdits[item.id] ? <details>
                      <summary>Изменить intake policy</summary>
                      <form className="event-config-form compact" onSubmit={(event) => { event.preventDefault(); sourcePolicyMutation.mutate(item) }}>
                        <label>Лимит / минуту<input type="number" min="1" max="100000" value={sourceEdits[item.id].rate_limit_per_minute} onChange={(event) => setSourceEdits({ ...sourceEdits, [item.id]: { ...sourceEdits[item.id], rate_limit_per_minute: Number(event.target.value) } })} /></label>
                        <label>Payload, KB<input type="number" min="1" max="2048" value={sourceEdits[item.id].max_payload_kb} onChange={(event) => setSourceEdits({ ...sourceEdits, [item.id]: { ...sourceEdits[item.id], max_payload_kb: Number(event.target.value) } })} /></label>
                        <label>Replay, сек<input type="number" min="30" max="3600" value={sourceEdits[item.id].replay_window_seconds} onChange={(event) => setSourceEdits({ ...sourceEdits, [item.id]: { ...sourceEdits[item.id], replay_window_seconds: Number(event.target.value) } })} /></label>
                        <label>IP/CIDR<textarea rows={2} value={sourceEdits[item.id].allowed_ip_cidrs} onChange={(event) => setSourceEdits({ ...sourceEdits, [item.id]: { ...sourceEdits[item.id], allowed_ip_cidrs: event.target.value } })} /></label>
                        <button type="submit" disabled={sourcePolicyMutation.isPending}>Сохранить policy</button>
                        {item.auth_mode === 'HMAC_SHA256' ? <><label>Секрет, выданный провайдером<input type="password" autoComplete="new-password" value={sourceEdits[item.id].signing_secret} onChange={(event) => setSourceEdits({ ...sourceEdits, [item.id]: { ...sourceEdits[item.id], signing_secret: event.target.value } })} placeholder="Например, secret Sentry service hook" /></label><button type="button" disabled={sourceEdits[item.id].signing_secret.length < 32 || sourceRotateMutation.isPending} onClick={() => sourceRotateMutation.mutate({ item, signingSecret: sourceEdits[item.id].signing_secret })}>Сохранить provider secret</button></> : null}
                      </form>
                    </details> : null}
                  </article>
                ))}
              </div>
            </div> : null}
            {canReadEvents ? <div className="event-source-column">
              {canManageEventPolicies ? (
                <form className="event-config-form compact" onSubmit={(event) => { event.preventDefault(); suppressionCreateMutation.mutate() }}>
                  <div><p className="eyebrow">MAINTENANCE CONTROL</p><h2>Suppression window</h2></div>
                  <label>Название<input value={suppressionForm.name} onChange={(event) => setSuppressionForm({ ...suppressionForm, name: event.target.value })} /></label>
                  <label>Причина<textarea value={suppressionForm.reason} onChange={(event) => setSuppressionForm({ ...suppressionForm, reason: event.target.value })} /></label>
                  <fieldset><legend>Matcher</legend><input value={suppressionForm.matcher_field} onChange={(event) => setSuppressionForm({ ...suppressionForm, matcher_field: event.target.value })} /><select value={suppressionForm.matcher_operator} onChange={(event) => setSuppressionForm({ ...suppressionForm, matcher_operator: event.target.value as typeof suppressionForm.matcher_operator })}><option>EQUALS</option><option>CONTAINS</option><option>PREFIX</option><option>NOT_EQUALS</option><option>EXISTS</option></select>{suppressionForm.matcher_operator !== 'EXISTS' ? <input value={suppressionForm.matcher_value} onChange={(event) => setSuppressionForm({ ...suppressionForm, matcher_value: event.target.value })} /> : null}</fieldset>
                  <label>Начало<input type="datetime-local" value={suppressionForm.starts_at} onChange={(event) => setSuppressionForm({ ...suppressionForm, starts_at: event.target.value })} /></label>
                  <label>Окончание<input type="datetime-local" value={suppressionForm.ends_at} onChange={(event) => setSuppressionForm({ ...suppressionForm, ends_at: event.target.value })} /></label>
                  <button type="submit" disabled={suppressionForm.name.length < 2 || suppressionForm.reason.length < 3 || (!suppressionForm.matcher_value && suppressionForm.matcher_operator !== 'EXISTS')}>Активировать suppression</button>
                </form>
              ) : null}
              <div className="event-suppression-list">
                {suppressionsQuery.data?.map((item) => (
                  <article className={!item.is_active ? 'disabled' : ''} key={item.id}><header><strong>{item.name}</strong><span className={item.is_active ? 'status-ok' : 'status-muted'}>{item.is_active ? 'ACTIVE' : 'DISABLED'}</span></header><p>{item.reason}</p><small>{item.matchers.map((matcher) => `${matcher.field} ${matcher.operator} ${matcher.value}`).join(' AND ')}</small><small>{formatDate(item.starts_at)} → {formatDate(item.ends_at)}</small>{canManageEventPolicies ? <button type="button" className="ghost-button" onClick={() => suppressionToggleMutation.mutate(item)}>{item.is_active ? 'Отключить' : 'Включить'}</button> : null}</article>
                ))}
              </div>
            </div> : null}
          </section>
        </>
      ) : null}

      {view === 'RECEIPTS' ? (
        <>
          <section className="event-toolbar">
            {canReadSources ? <select value={receiptSourceId} onChange={(event) => setReceiptSourceId(event.target.value)}>
              <option value="">Все источники</option>
              {sourcesQuery.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select> : null}
            <select value={receiptStatus} onChange={(event) => setReceiptStatus(event.target.value)}>
              <option>ALL</option><option>RECEIVED</option><option>PROCESSING</option><option>PROCESSED</option><option>RETRY</option><option>FAILED</option><option>DEAD_LETTER</option>
            </select>
          </section>
          <section className="panel">
            <div className="section-heading"><div><p className="eyebrow">SIGNED INTAKE</p><h2>Webhook receipts и dead-letter</h2></div><span className="badge">{receiptsQuery.data?.length ?? 0}</span></div>
            <div className="alert alert-info">
              Generic/Zabbix HMAC: <code>unix_timestamp.raw_body</code> + <code>X-SBS-Timestamp</code>/<code>X-SBS-Signature</code>. Grafana принимает нативные <code>X-Grafana-Alerting-Signature</code> и timestamp с формулой <code>timestamp:body</code>. Sentry принимает <code>Sentry-Hook-Signature</code>. Для повторов используйте стабильный <code>X-Idempotency-Key</code>.
            </div>
            <div className="table-scroll"><table>
              <thead><tr><th>Получено</th><th>Источник</th><th>Проверка</th><th>Состояние</th><th>Результат</th><th>Ошибка</th><th /></tr></thead>
              <tbody>{receiptsQuery.data?.map((item) => {
                const source = sourcesQuery.data?.find((candidate) => candidate.id === item.source_id)
                return <tr key={item.id}>
                  <td>{formatDate(item.received_at)}<small>{Math.round(item.payload_size / 1024)} KB · {item.source_ip ?? 'IP —'}</small></td>
                  <td><strong>{source?.name ?? item.provider_type}</strong><small>{item.provider_type} · hash {item.body_hash.slice(0, 12)}</small></td>
                  <td>{item.signature_verified ? <span className="status-ok">HMAC VERIFIED</span> : <span className="status-muted">BEARER</span>}<small>{formatDate(item.request_timestamp)}</small></td>
                  <td><strong>{item.status}</strong><small>{item.attempts}/{item.max_attempts} · next {formatDate(item.next_attempt_at)}</small></td>
                  <td>{item.normalized_event_count} events<small>{item.duplicate_event_count} duplicate · {item.incident_count} incidents</small></td>
                  <td>{item.last_error ?? '—'}</td>
                  <td>{canManageReceipts && ['FAILED', 'DEAD_LETTER'].includes(item.status) ? <button type="button" className="ghost-button" disabled={receiptReprocessMutation.isPending} onClick={() => receiptReprocessMutation.mutate(item.id)}>Reprocess</button> : null}</td>
                </tr>
              })}</tbody>
            </table></div>
            {!receiptsQuery.isLoading && !receiptsQuery.isError && !receiptsQuery.data?.length ? <p className="empty-state">Webhook receipts по выбранному фильтру отсутствуют.</p> : null}
          </section>
        </>
      ) : null}

      {view === 'EVENTS' ? (
        <>
          <section className="event-toolbar">
            <select value={eventDisposition} onChange={(event) => setEventDisposition(event.target.value)}><option>ALL</option><option>INCIDENT_CREATED</option><option>INCIDENT_UPDATED</option><option>CORRELATED</option><option>SUPPRESSED</option><option>RESOLVED</option><option>IGNORED</option></select>
            <select value={eventSeverity} onChange={(event) => setEventSeverity(event.target.value)}><option>ALL</option><option>CRITICAL</option><option>HIGH</option><option>MEDIUM</option><option>LOW</option><option>INFO</option></select>
          </section>
          <section className="event-ledger">
            <header><span>Время / source</span><span>Event</span><span>Disposition</span><span>Evidence</span></header>
            {eventsQuery.data?.map((item) => (
              <article key={item.id}><div><strong>{formatDate(item.received_at)}</strong><span>{item.source_name}</span></div><div><strong>{item.severity} · {item.state}</strong><span>{item.summary}</span><small>{item.service ?? '—'} · {item.resource ?? '—'}</small></div><div><strong>{item.disposition}</strong><span>{item.ticket_number ?? 'без Ticket'}</span></div><div><code>{item.raw_payload_hash.slice(0, 16)}</code>{item.correlation_group_id ? <button type="button" className="link-button" onClick={() => { setView('QUEUE'); selectGroup(item.correlation_group_id!) }}>Открыть group</button> : null}</div></article>
            ))}
          </section>
        </>
      ) : null}
    </AppShell></LocalizedContent>
  )
}
