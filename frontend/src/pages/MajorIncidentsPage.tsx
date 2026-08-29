import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addMajorIncidentParticipant,
  addMajorIncidentUpdate,
  approveMajorIncidentPIR,
  createMajorIncidentAction,
  declareMajorIncident,
  fetchMajorIncident,
  fetchMajorIncidentResponders,
  fetchMajorIncidents,
  fetchMajorIncidentSummary,
  fetchTicketsPage,
  linkMajorIncidentChild,
  saveMajorIncidentPIR,
  transitionMajorIncident,
  updateMajorIncidentAction,
  type MajorIncident,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { canAccessPath } from '../auth/accessControl'
import AppShell from '../components/AppShell'
import CMDBImpactPanel from '../components/CMDBImpactPanel'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import type { UiMessageKey } from '../i18n/catalog'

function defaultDueAt() {
  const due = new Date(Date.now() + 24 * 60 * 60 * 1_000)
  const local = new Date(due.getTime() - due.getTimezoneOffset() * 60_000)
  return local.toISOString().slice(0, 16)
}

function lifecycleActions(incident: MajorIncident) {
  if (incident.status === 'DECLARED') return ['START_MITIGATION', 'CANCEL']
  if (incident.status === 'MITIGATING') return ['MONITOR', 'RESOLVE', 'CANCEL']
  if (incident.status === 'MONITORING') return ['RESUME_MITIGATION', 'RESOLVE', 'CANCEL']
  if (incident.status === 'RESOLVED') return ['CLOSE']
  return []
}

const pirLabelKeys: Record<string, UiMessageKey> = {
  summary: 'major.pir.summary',
  root_cause: 'major.pir.root_cause',
  contributing_factors: 'major.pir.contributing_factors',
  lessons_learned: 'major.pir.lessons_learned',
  prevention_plan: 'major.pir.prevention_plan',
}

export default function MajorIncidentsPage() {
  const { session } = useAuth()
  const { t, formatDateTime } = useTenantExperience()
  const token = session?.access_token ?? ''
  const root = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const hasPermission = (permission: string) => root || permissions.has(permission)
  const canRead = hasPermission('major_incidents.read')
  const canManage = canRead && hasPermission('major_incidents.manage')
  const canReadAssets = hasPermission('assets.read')
  const canReadTicketCandidates = Boolean(
    session?.user && canAccessPath(session.user, '/tickets'),
  )
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [showDeclare, setShowDeclare] = useState(false)
  const [form, setForm] = useState({
    ticket_id: '',
    severity: 'SEV1' as 'SEV1' | 'SEV2',
    title: '',
    executive_summary: '',
    impact_statement: '',
    affected_service: '',
    customer_impact: '',
    war_room_url: '',
    commander_user_id: '',
    communications_lead_user_id: '',
  })
  const [update, setUpdate] = useState({
    update_type: 'STATUS_UPDATE',
    audience: 'STAKEHOLDERS',
    message: '',
    service_status: 'MAJOR_OUTAGE',
    channel: 'email',
  })
  const [transitionComment, setTransitionComment] = useState('')
  const [participant, setParticipant] = useState({
    role: 'SME',
    user_id: '',
    display_name: '',
    contact: '',
  })
  const [childTicketId, setChildTicketId] = useState('')
  const [actionForm, setActionForm] = useState({
    title: '',
    description: '',
    owner_user_id: '',
    due_at: defaultDueAt(),
  })
  const [actionEvidence, setActionEvidence] = useState<Record<string, string>>({})
  const [pir, setPir] = useState({
    summary: '',
    root_cause: '',
    contributing_factors: '',
    lessons_learned: '',
    prevention_plan: '',
  })

  const listQuery = useQuery({
    queryKey: ['major-incidents', token],
    queryFn: () => fetchMajorIncidents(token),
    enabled: Boolean(token && canRead),
  })
  const summaryQuery = useQuery({
    queryKey: ['major-incident-summary', token],
    queryFn: () => fetchMajorIncidentSummary(token),
    enabled: Boolean(token && canRead),
  })
  const detailQuery = useQuery({
    queryKey: ['major-incident', token, selectedId],
    queryFn: () => fetchMajorIncident(token, selectedId ?? ''),
    enabled: Boolean(token && selectedId && canRead),
  })
  const incident = detailQuery.data
  const responderTicketId = form.ticket_id || incident?.ticket_id
  const respondersQuery = useQuery({
    queryKey: ['major-incident-responders', token, responderTicketId],
    queryFn: () => fetchMajorIncidentResponders(token, responderTicketId),
    enabled: Boolean(token && canRead),
  })
  const declarationTicketsQuery = useQuery({
    queryKey: ['major-incident-candidate-tickets', token],
    queryFn: async () => {
      const pages = await Promise.all([
        fetchTicketsPage(token, { priority: 'P1', page_size: 100 }),
        fetchTicketsPage(token, { priority: 'P2', page_size: 100 }),
        fetchTicketsPage(token, { priority: 'CRITICAL', page_size: 100 }),
        fetchTicketsPage(token, { priority: 'HIGH', page_size: 100 }),
      ])
      return pages.flatMap((page) => page.items).filter(
        (item, index, rows) => rows.findIndex((other) => other.id === item.id) === index,
      )
    },
    enabled: Boolean(token && showDeclare && canManage && canReadTicketCandidates),
  })
  const childTicketsQuery = useQuery({
    queryKey: ['major-incident-child-candidates', token, incident?.tenant_id],
    queryFn: () => fetchTicketsPage(token, { page_size: 100 }),
    enabled: Boolean(token && incident && canManage && canReadTicketCandidates),
  })

  useEffect(() => {
    if (!selectedId && listQuery.data?.[0]) setSelectedId(listQuery.data[0].id)
  }, [listQuery.data, selectedId])

  useEffect(() => {
    const responders = respondersQuery.data ?? []
    const preferred = responders.find((item) => item.id === session?.user.id) ?? responders[0]
    if (!preferred) return
    setForm((value) => ({
      ...value,
      commander_user_id: value.commander_user_id || preferred.id,
      communications_lead_user_id: value.communications_lead_user_id || preferred.id,
    }))
    setActionForm((value) => ({
      ...value,
      owner_user_id: value.owner_user_id || preferred.id,
    }))
  }, [respondersQuery.data, session?.user.id])

  useEffect(() => {
    if (!incident?.pir) return
    setPir({
      summary: incident.pir.summary,
      root_cause: incident.pir.root_cause,
      contributing_factors: incident.pir.contributing_factors,
      lessons_learned: incident.pir.lessons_learned,
      prevention_plan: incident.pir.prevention_plan,
    })
  }, [incident?.pir])

  async function refresh(item: MajorIncident) {
    setSelectedId(item.id)
    queryClient.setQueryData(['major-incident', token, item.id], item)
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['major-incidents'] }),
      queryClient.invalidateQueries({ queryKey: ['major-incident-summary'] }),
    ])
  }

  const declareMutation = useMutation({
    mutationFn: () => declareMajorIncident(token, {
      ...form,
      war_room_url: form.war_room_url || undefined,
    }),
    onSuccess: async (item) => {
      setShowDeclare(false)
      await refresh(item)
    },
  })
  const updateMutation = useMutation({
    mutationFn: (item: MajorIncident) => addMajorIncidentUpdate(token, item.id, update),
    onSuccess: async (item) => {
      setUpdate((value) => ({ ...value, message: '' }))
      await refresh(item)
    },
  })
  const transitionMutation = useMutation({
    mutationFn: ({ item, action }: { item: MajorIncident; action: string }) =>
      transitionMajorIncident(token, item, action, transitionComment || action),
    onSuccess: async (item) => {
      setTransitionComment('')
      await refresh(item)
    },
  })
  const participantMutation = useMutation({
    mutationFn: (item: MajorIncident) => {
      const responder = respondersQuery.data?.find((entry) => entry.id === participant.user_id)
      return addMajorIncidentParticipant(token, item.id, {
        ...participant,
        user_id: participant.user_id || undefined,
        display_name: responder?.full_name || participant.display_name,
        contact: participant.contact || undefined,
      })
    },
    onSuccess: async (item) => {
      setParticipant({ role: 'SME', user_id: '', display_name: '', contact: '' })
      await refresh(item)
    },
  })
  const childMutation = useMutation({
    mutationFn: (item: MajorIncident) => linkMajorIncidentChild(token, item.id, childTicketId),
    onSuccess: async (item) => {
      setChildTicketId('')
      await refresh(item)
    },
  })
  const actionMutation = useMutation({
    mutationFn: (item: MajorIncident) => createMajorIncidentAction(token, item.id, {
      ...actionForm,
      due_at: new Date(actionForm.due_at).toISOString(),
    }),
    onSuccess: async (item) => {
      setActionForm((value) => ({
        title: '',
        description: '',
        owner_user_id: value.owner_user_id,
        due_at: defaultDueAt(),
      }))
      await refresh(item)
    },
  })
  const actionStatusMutation = useMutation({
    mutationFn: ({
      item,
      action,
      status,
    }: {
      item: MajorIncident
      action: MajorIncident['actions'][number]
      status: string
    }) => updateMajorIncidentAction(
      token,
      item.id,
      action,
      status,
      actionEvidence[action.id],
    ),
    onSuccess: refresh,
  })
  const pirMutation = useMutation({
    mutationFn: (item: MajorIncident) => saveMajorIncidentPIR(token, item, pir),
    onSuccess: refresh,
  })
  const approveMutation = useMutation({
    mutationFn: (item: MajorIncident) => approveMajorIncidentPIR(token, item),
    onSuccess: refresh,
  })

  const linkedTicketIds = useMemo(
    () => new Set(incident?.child_tickets.map((item) => item.id) ?? []),
    [incident?.child_tickets],
  )
  const childCandidates = (childTicketsQuery.data?.items ?? []).filter(
    (item) => item.id !== incident?.ticket_id && !linkedTicketIds.has(item.id),
  )
  const mutationError = [
    declareMutation.error,
    updateMutation.error,
    transitionMutation.error,
    participantMutation.error,
    childMutation.error,
    actionMutation.error,
    actionStatusMutation.error,
    pirMutation.error,
    approveMutation.error,
  ].find(Boolean)

  return (
    <AppShell
      title="Major Incident Command Center"
      subtitle="SEV-командование, единая временная шкала, коммуникации, CMDB impact и управляемый Post-Incident Review"
    >
      <section className="major-toolbar">
        <div>
          <p className="eyebrow">INCIDENT COMMAND SYSTEM</p>
          <strong>{t('major.commandCenter')}</strong>
        </div>
        {canManage ? (
          <button type="button" onClick={() => setShowDeclare((value) => !value)}>
            {showDeclare ? t('major.closeForm') : t('major.declare')}
          </button>
        ) : null}
      </section>

      <section className="module-overview-grid">
        <article className="metric-card"><span>{t('major.active')}</span><strong>{summaryQuery.data?.active ?? 0}</strong></article>
        <article className="metric-card"><span>SEV1</span><strong>{summaryQuery.data?.sev1_active ?? 0}</strong></article>
        <article className="metric-card"><span>{t('major.commsOverdue')}</span><strong>{summaryQuery.data?.communications_overdue ?? 0}</strong></article>
        <article className="metric-card"><span>{t('major.awaitingPir')}</span><strong>{summaryQuery.data?.resolved_awaiting_pir ?? 0}</strong></article>
      </section>
      {summaryQuery.isError ? (
        <div className="state-panel state-panel-error" role="alert">
          <span>{t('major.summaryError')}</span>
          <button type="button" className="ghost-button" onClick={() => void summaryQuery.refetch()}>{t('common.retry')}</button>
        </div>
      ) : null}

      {mutationError ? (
        <p className="error-message">
          {mutationError instanceof Error ? mutationError.message : t('major.operationFailed')}
        </p>
      ) : null}

      {showDeclare && canManage ? (
        <form
          className="section-card major-declare-form"
          onSubmit={(event) => {
            event.preventDefault()
            declareMutation.mutate()
          }}
        >
          <div className="section-header"><div><p className="eyebrow">SEV DECLARATION</p><h2>{t('major.new')}</h2></div></div>
          <label>
            {t('major.parentTicket')}
            <select
              value={form.ticket_id}
              onChange={(event) => setForm({ ...form, ticket_id: event.target.value })}
              required
            >
              <option value="">{t('major.chooseTicket')}</option>
              {declarationTicketsQuery.data?.map((item) => (
                <option value={item.id} key={item.id}>{item.ticket_number} · {item.title}</option>
              ))}
            </select>
          </label>
          <label>
            {t('major.severity')}
            <select
              value={form.severity}
              onChange={(event) => setForm({ ...form, severity: event.target.value as 'SEV1' | 'SEV2' })}
            >
              <option>SEV1</option>
              <option>SEV2</option>
            </select>
          </label>
          <label>
            {t('major.commander')}
            <select
              value={form.commander_user_id}
              onChange={(event) => setForm({ ...form, commander_user_id: event.target.value })}
              required
            >
              <option value="">{t('major.chooseOwner')}</option>
              {respondersQuery.data?.map((item) => <option value={item.id} key={item.id}>{item.full_name}</option>)}
            </select>
          </label>
          <label>
            {t('major.commsLead')}
            <select
              value={form.communications_lead_user_id}
              onChange={(event) => setForm({ ...form, communications_lead_user_id: event.target.value })}
              required
            >
              <option value="">{t('major.chooseOwner')}</option>
              {respondersQuery.data?.map((item) => <option value={item.id} key={item.id}>{item.full_name}</option>)}
            </select>
          </label>
          <label>
            {t('major.title')}
            <input value={form.title} onChange={(event) => setForm({ ...form, title: event.target.value })} required />
          </label>
          <label>
            {t('major.executiveSummary')}
            <textarea value={form.executive_summary} onChange={(event) => setForm({ ...form, executive_summary: event.target.value })} required />
          </label>
          <label>
            {t('major.impactStatement')}
            <textarea value={form.impact_statement} onChange={(event) => setForm({ ...form, impact_statement: event.target.value })} required />
          </label>
          <label>
            {t('major.affectedService')}
            <input value={form.affected_service} onChange={(event) => setForm({ ...form, affected_service: event.target.value })} required />
          </label>
          <label>
            {t('major.customerImpact')}
            <textarea value={form.customer_impact} onChange={(event) => setForm({ ...form, customer_impact: event.target.value })} required />
          </label>
          <label>
            War-room URL
            <input type="url" value={form.war_room_url} onChange={(event) => setForm({ ...form, war_room_url: event.target.value })} />
          </label>
          <button
            type="submit"
            disabled={
              declareMutation.isPending
              || !form.commander_user_id
              || !form.communications_lead_user_id
            }
          >
            {t('major.declareAndOpen')}
          </button>
        </form>
      ) : null}

      <section className="major-layout">
        <div className="major-list">
          {listQuery.isPending ? <p className="state-panel state-panel-loading" role="status">{t('major.loadingList')}</p> : null}
          {listQuery.isError ? (
            <div className="state-panel state-panel-error" role="alert">
              <span>{t('major.listError')}</span>
              <button type="button" className="ghost-button" onClick={() => void listQuery.refetch()}>{t('common.retry')}</button>
            </div>
          ) : null}
          {listQuery.data?.map((item) => (
            <button
              type="button"
              className={selectedId === item.id ? 'active' : ''}
              onClick={() => setSelectedId(item.id)}
              key={item.id}
            >
              <strong>{item.major_number} · {item.severity}</strong>
              <span>{item.title}</span>
              <small>{item.status} · {item.affected_service}</small>
            </button>
          ))}
          {!listQuery.isPending && !listQuery.isError && !listQuery.data?.length ? <p className="empty-state">{t('major.empty')}</p> : null}
        </div>

        <div className="major-detail">
          {detailQuery.isPending ? (
            <p className="state-panel state-panel-loading" role="status">{t('major.loadingDetail')}</p>
          ) : detailQuery.isError ? (
            <div className="state-panel state-panel-error" role="alert">
              <span>{t('major.detailError')}</span>
              <button type="button" className="ghost-button" onClick={() => void detailQuery.refetch()}>{t('common.retry')}</button>
            </div>
          ) : !incident ? (
            <p className="empty-state">{t('major.chooseIncident')}</p>
          ) : (
            <>
              <div className="section-header">
                <div>
                  <p className="eyebrow">{incident.major_number} · {incident.severity}</p>
                  <h2>{incident.title}</h2>
                  <p>{incident.executive_summary}</p>
                </div>
                <span className={`impact-severity ${incident.communication_overdue ? 'impact-critical' : 'impact-high'}`}>
                  {incident.status}
                </span>
              </div>

              <div className="detail-fields">
                <div><span>{t('major.service')}</span><strong>{incident.affected_service}</strong></div>
                <div><span>{t('major.serviceStatus')}</span><strong>{incident.service_status}</strong></div>
                <div><span>{t('major.commander')}</span><strong>{incident.commander_name}</strong></div>
                <div><span>{t('major.commsLead')}</span><strong>{incident.communications_lead_name}</strong></div>
                <div><span>{t('major.nextUpdate')}</span><strong>{formatDateTime(incident.next_update_due_at)}</strong></div>
                <div>
                  <span>{t('major.warRoom')}</span>
                  <strong>{incident.war_room_url ? <a href={incident.war_room_url} target="_blank" rel="noreferrer">{t('major.open')}</a> : '—'}</strong>
                </div>
              </div>

              <section className="major-impact">
                <strong>{t('major.customerImpact')}</strong>
                <p>{incident.customer_impact}</p>
                <strong>{t('major.impactStatement')}</strong>
                <p>{incident.impact_statement}</p>
              </section>

              {canReadAssets ? (
                <CMDBImpactPanel
                  accessToken={token}
                  rootCiIds={[]}
                  entityType="TICKET"
                  entityId={incident.ticket_id}
                  title={t('major.cmdbImpact')}
                  compact
                />
              ) : null}

              <section className="major-governance-grid">
                <div className="major-command">
                  <h3>{t('major.responseTeam')}</h3>
                  <div className="major-compact-list">
                    {incident.participants.map((item) => (
                      <article key={item.id}><strong>{item.display_name}</strong><span>{item.role}{item.contact ? ` · ${item.contact}` : ''}</span></article>
                    ))}
                    {!incident.participants.length ? <p className="muted">{t('major.noParticipants')}</p> : null}
                  </div>
                  {canManage && !['CLOSED', 'CANCELLED'].includes(incident.status) ? (
                    <div className="major-inline-form">
                      <select value={participant.role} onChange={(event) => setParticipant({ ...participant, role: event.target.value })}>
                        <option>TECHNICAL_LEAD</option><option>SME</option><option>SCRIBE</option><option>STAKEHOLDER</option>
                      </select>
                      <select
                        value={participant.user_id}
                        onChange={(event) => setParticipant({ ...participant, user_id: event.target.value, display_name: '' })}
                      >
                        <option value="">{t('major.externalParticipant')}</option>
                        {respondersQuery.data?.map((item) => <option value={item.id} key={item.id}>{item.full_name}</option>)}
                      </select>
                      {!participant.user_id ? <input value={participant.display_name} onChange={(event) => setParticipant({ ...participant, display_name: event.target.value })} placeholder={t('major.participantName')} /> : null}
                      <input value={participant.contact} onChange={(event) => setParticipant({ ...participant, contact: event.target.value })} placeholder={t('major.contactChannel')} />
                      <button
                        type="button"
                        disabled={participantMutation.isPending || (!participant.user_id && participant.display_name.trim().length < 2)}
                        onClick={() => participantMutation.mutate(incident)}
                      >
                        {t('major.add')}
                      </button>
                    </div>
                  ) : null}
                </div>

                <div className="major-command">
                  <h3>{t('major.linkedTickets')}</h3>
                  <div className="major-compact-list">
                    {incident.child_tickets.map((item) => (
                      <article key={item.id}><strong>{item.ticket_number} · {item.title}</strong><span>{item.priority} · {item.status}</span></article>
                    ))}
                    {!incident.child_tickets.length ? <p className="muted">{t('major.noLinkedTickets')}</p> : null}
                  </div>
                  {canManage && !['CLOSED', 'CANCELLED'].includes(incident.status) ? (
                    <div className="major-inline-form">
                      <select value={childTicketId} onChange={(event) => setChildTicketId(event.target.value)}>
                        <option value="">{t('major.chooseTicket')}</option>
                        {childCandidates.map((item) => <option value={item.id} key={item.id}>{item.ticket_number} · {item.title}</option>)}
                      </select>
                      <button type="button" disabled={!childTicketId || childMutation.isPending} onClick={() => childMutation.mutate(incident)}>{t('major.link')}</button>
                    </div>
                  ) : null}
                </div>
              </section>

              {canManage && !['CLOSED', 'CANCELLED'].includes(incident.status) ? (
                <section className="major-command">
                  <h3>{t('major.publishUpdate')}</h3>
                  <div className="form-grid">
                    <select value={update.update_type} onChange={(event) => setUpdate({ ...update, update_type: event.target.value })}>
                      <option>STATUS_UPDATE</option><option>STAKEHOLDER_COMMUNICATION</option><option>TECHNICAL_EVENT</option><option>DECISION</option>
                    </select>
                    <select value={update.audience} onChange={(event) => setUpdate({ ...update, audience: event.target.value })}>
                      <option>INTERNAL</option><option>STAKEHOLDERS</option><option>PUBLIC</option>
                    </select>
                    <select value={update.service_status} onChange={(event) => setUpdate({ ...update, service_status: event.target.value })}>
                      <option>MAJOR_OUTAGE</option><option>PARTIAL_OUTAGE</option><option>DEGRADED</option><option>OPERATIONAL</option><option>UNKNOWN</option>
                    </select>
                    <input value={update.channel} onChange={(event) => setUpdate({ ...update, channel: event.target.value })} placeholder="email / Teams / status page" />
                  </div>
                  <textarea value={update.message} onChange={(event) => setUpdate({ ...update, message: event.target.value })} placeholder={t('major.updatePlaceholder')} />
                  <button
                    type="button"
                    disabled={update.message.trim().length < 3 || updateMutation.isPending}
                    onClick={() => updateMutation.mutate(incident)}
                  >
                    {t('major.publish')}
                  </button>
                </section>
              ) : null}

              {canManage && lifecycleActions(incident).length ? (
                <section className="major-command">
                  <h3>{t('major.lifecycle')}</h3>
                  <textarea value={transitionComment} onChange={(event) => setTransitionComment(event.target.value)} placeholder={t('major.transitionEvidence')} />
                  <div className="analytics-actions">
                    {lifecycleActions(incident).map((action) => (
                      <button
                        type="button"
                        key={action}
                        disabled={transitionMutation.isPending}
                        onClick={() => transitionMutation.mutate({ item: incident, action })}
                      >
                        {action}
                      </button>
                    ))}
                  </div>
                </section>
              ) : null}

              <section className="major-command">
                <h3>{t('major.actions')}</h3>
                <div className="major-action-list">
                  {incident.actions.map((action) => (
                    <article className={action.overdue ? 'overdue' : ''} key={action.id}>
                      <div><strong>{action.title}</strong><span>{action.status} · {action.owner_name} · {t('major.due', { date: formatDateTime(action.due_at) })}</span></div>
                      <p>{action.description}</p>
                      {action.completion_evidence ? <small>{t('major.evidence', { evidence: action.completion_evidence })}</small> : null}
                      {canManage && !['DONE', 'CANCELLED'].includes(action.status) ? (
                        <div className="major-action-controls">
                          <input
                            value={actionEvidence[action.id] ?? ''}
                            onChange={(event) => setActionEvidence({ ...actionEvidence, [action.id]: event.target.value })}
                            placeholder={t('major.evidencePlaceholder')}
                          />
                          {action.status === 'OPEN' ? (
                            <button type="button" onClick={() => actionStatusMutation.mutate({ item: incident, action, status: 'IN_PROGRESS' })}>{t('major.startWork')}</button>
                          ) : null}
                          <button
                            type="button"
                            disabled={(actionEvidence[action.id] ?? '').trim().length < 3}
                            onClick={() => actionStatusMutation.mutate({ item: incident, action, status: 'DONE' })}
                          >
                            {t('major.done')}
                          </button>
                        </div>
                      ) : null}
                    </article>
                  ))}
                  {!incident.actions.length ? <p className="muted">{t('major.noActions')}</p> : null}
                </div>
                {canManage ? <div className="major-action-form">
                  <input value={actionForm.title} onChange={(event) => setActionForm({ ...actionForm, title: event.target.value })} placeholder={t('major.actionTitle')} />
                  <textarea value={actionForm.description} onChange={(event) => setActionForm({ ...actionForm, description: event.target.value })} placeholder={t('major.actionDescription')} />
                  <select value={actionForm.owner_user_id} onChange={(event) => setActionForm({ ...actionForm, owner_user_id: event.target.value })}>
                    <option value="">{t('major.owner')}</option>
                    {respondersQuery.data?.map((item) => <option value={item.id} key={item.id}>{item.full_name}</option>)}
                  </select>
                  <input type="datetime-local" value={actionForm.due_at} onChange={(event) => setActionForm({ ...actionForm, due_at: event.target.value })} />
                  <button
                    type="button"
                    disabled={actionMutation.isPending || actionForm.title.trim().length < 3 || actionForm.description.trim().length < 3 || !actionForm.owner_user_id || !actionForm.due_at}
                    onClick={() => actionMutation.mutate(incident)}
                  >
                    {t('major.assignAction')}
                  </button>
                </div> : null}
              </section>

              <section className="major-timeline">
                <h3>{t('major.timeline')}</h3>
                {[...incident.updates].reverse().map((item) => (
                  <article key={item.id}>
                    <div><strong>{item.update_type} · {item.audience}</strong><span>{formatDateTime(item.created_at)}</span></div>
                    <p>{item.message}</p>
                    <small>{item.actor_name}{item.channel ? ` · ${item.channel}` : ''}</small>
                  </article>
                ))}
              </section>

              {incident.status === 'RESOLVED' || incident.status === 'CLOSED' || incident.pir ? (
                <section className="major-command">
                  <h3>Post-Incident Review</h3>
                  {(Object.keys(pir) as Array<keyof typeof pir>).map((key) => (
                    <label key={key}>
                      {t(pirLabelKeys[key])}
                      <textarea
                        value={pir[key]}
                        disabled={!canManage}
                        onChange={(event) => setPir({ ...pir, [key]: event.target.value })}
                      />
                    </label>
                  ))}
                  {incident.pir?.status === 'APPROVED' ? (
                    <p className="form-success">{t('major.pirApproved', { date: formatDateTime(incident.pir.approved_at) })}</p>
                  ) : canManage ? (
                    <div className="analytics-actions">
                      <button type="button" onClick={() => pirMutation.mutate(incident)}>{t('major.savePir')}</button>
                      {incident.pir && incident.pir.prepared_by_id !== session?.user.id ? (
                        <button type="button" className="ghost-button" onClick={() => approveMutation.mutate(incident)}>{t('major.approvePir')}</button>
                      ) : incident.pir ? (
                        <span className="muted">{t('major.pirDifferentApprover')}</span>
                      ) : null}
                    </div>
                  ) : (
                    <p className="muted">{t('major.pirReadOnly')}</p>
                  )}
                </section>
              ) : null}
            </>
          )}
        </div>
      </section>
    </AppShell>
  )
}
