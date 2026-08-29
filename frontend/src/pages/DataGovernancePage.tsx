import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import {
  createDataLegalHold,
  decideDataDeletion,
  downloadTenantDataExport,
  executeDataDeletion,
  fetchDataGovernanceDashboard,
  fetchTenants,
  previewDataDeletion,
  releaseDataLegalHold,
  submitDataDeletion,
  updateRetentionPolicy,
  type DataDeletionRequest,
  type RetentionCategory,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import type { UiMessageKey } from '../i18n/catalog'

const categories: RetentionCategory[] = [
  'TICKETS',
  'SERVICE_REQUESTS',
  'COMMENTS',
  'NOTIFICATIONS',
  'LOGIN_EVENTS',
  'AUDIT',
  'EMAIL',
  'ATTACHMENTS',
  'AI_CONVERSATIONS',
  'AI_PROMPTS_RESPONSES',
  'VECTOR_EMBEDDINGS',
  'EXPORTS',
  'BACKGROUND_JOBS',
  'DEAD_LETTER',
]

const categoryKeys: Record<RetentionCategory, UiMessageKey> = {
  TICKETS: 'dataGovernance.category.tickets',
  SERVICE_REQUESTS: 'dataGovernance.category.serviceRequests',
  COMMENTS: 'dataGovernance.category.comments',
  NOTIFICATIONS: 'dataGovernance.category.notifications',
  LOGIN_EVENTS: 'dataGovernance.category.loginEvents',
  AUDIT: 'dataGovernance.category.audit',
  EMAIL: 'dataGovernance.category.email',
  ATTACHMENTS: 'dataGovernance.category.attachments',
  AI_CONVERSATIONS: 'dataGovernance.category.aiConversations',
  AI_PROMPTS_RESPONSES: 'dataGovernance.category.aiPromptsResponses',
  VECTOR_EMBEDDINGS: 'dataGovernance.category.vectorEmbeddings',
  EXPORTS: 'dataGovernance.category.exports',
  BACKGROUND_JOBS: 'dataGovernance.category.backgroundJobs',
  DEAD_LETTER: 'dataGovernance.category.deadLetter',
}

const statusKeys: Record<DataDeletionRequest['status'], UiMessageKey> = {
  PREVIEWED: 'dataGovernance.status.previewed',
  PENDING_APPROVAL: 'status.pendingApproval',
  APPROVED: 'status.approved',
  REJECTED: 'status.rejected',
  EXECUTING: 'dataGovernance.status.executing',
  COMPLETED: 'status.completed',
  FAILED: 'dataGovernance.status.failed',
  CANCELLED: 'status.cancelled',
  BLOCKED_EXTERNAL: 'dataGovernance.status.blockedExternal',
}

function statusClass(status: string) {
  if (status === 'COMPLETED') return 'badge badge-positive'
  if (['REJECTED', 'FAILED', 'BLOCKED_EXTERNAL'].includes(status)) return 'badge badge-danger'
  return 'badge badge-warning'
}

export default function DataGovernancePage() {
  const { session } = useAuth()
  const { t, formatDateTime } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const root = session?.user.role === 'saas_root'
  const permissions = useMemo(() => new Set(session?.user.permissions ?? []), [session?.user.permissions])
  const can = (permission: string) => root || permissions.has(permission)
  const categoryLabel = (category: RetentionCategory) => t(categoryKeys[category])
  const statusLabel = (status: DataDeletionRequest['status']) => t(statusKeys[status])
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [category, setCategory] = useState<RetentionCategory>('NOTIFICATIONS')
  const [retentionDays, setRetentionDays] = useState('90')
  const [holdName, setHoldName] = useState('')
  const [holdReason, setHoldReason] = useState('')
  const [deletionReason, setDeletionReason] = useState('')
  const [decisionReason, setDecisionReason] = useState('')
  const [releaseReason, setReleaseReason] = useState('')
  const [confirmations, setConfirmations] = useState<Record<string, string>>({})
  const [requestType, setRequestType] = useState<'RETENTION_PURGE' | 'TENANT_DELETION'>('RETENTION_PURGE')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const tenantsQuery = useQuery({
    queryKey: ['data-governance-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token) && root,
    retry: false,
  })

  useEffect(() => {
    if (root && !tenantId && tenantsQuery.data?.[0]) setTenantId(tenantsQuery.data[0].id)
  }, [root, tenantId, tenantsQuery.data])

  const dashboardQuery = useQuery({
    queryKey: ['data-governance-dashboard', token, tenantId],
    queryFn: () => fetchDataGovernanceDashboard(token, tenantId),
    enabled: Boolean(token) && Boolean(tenantId) && can('data.retention.read'),
    retry: false,
  })

  const selectedPolicy = dashboardQuery.data?.policies.find((item) => item.category === category)
  useEffect(() => {
    if (selectedPolicy) setRetentionDays(String(selectedPolicy.tenant_requested_days))
  }, [selectedPolicy])

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ['data-governance-dashboard'] })
  }
  const mutationOptions = {
    onSuccess: async () => {
      setError('')
      setNotice(t('dataGovernance.operationSaved'))
      await refresh()
    },
    onError: (value: unknown) => {
      setNotice('')
      setError(value instanceof Error ? value.message : t('dataGovernance.operationFailed'))
    },
  }

  const policyMutation = useMutation({
    mutationFn: () => updateRetentionPolicy(token, {
      tenant_id: tenantId,
      scope: 'TENANT',
      category,
      retention_days: Number(retentionDays),
      archive_before_delete: true,
      anonymize_before_delete: true,
      is_enabled: true,
      expected_revision: selectedPolicy?.tenant_revision ?? 0,
    }),
    ...mutationOptions,
  })
  const holdMutation = useMutation({
    mutationFn: () => createDataLegalHold(token, {
      tenant_id: tenantId,
      name: holdName,
      reason: holdReason,
      scope_type: 'CATEGORY',
      category,
    }),
    ...mutationOptions,
  })
  const releaseMutation = useMutation({
    mutationFn: (holdId: string) => releaseDataLegalHold(token, holdId, releaseReason),
    ...mutationOptions,
  })
  const previewMutation = useMutation({
    mutationFn: () => previewDataDeletion(token, {
      tenant_id: tenantId,
      request_type: requestType,
      category: requestType === 'RETENTION_PURGE' ? category : null,
      reason: deletionReason,
    }),
    ...mutationOptions,
  })
  const submitMutation = useMutation({
    mutationFn: (requestId: string) => submitDataDeletion(token, requestId),
    ...mutationOptions,
  })
  const decisionMutation = useMutation({
    mutationFn: ({ item, decision }: { item: DataDeletionRequest; decision: 'APPROVE' | 'REJECT' }) => (
      decideDataDeletion(token, item.id, decision, decisionReason)
    ),
    ...mutationOptions,
  })
  const executeMutation = useMutation({
    mutationFn: (item: DataDeletionRequest) => executeDataDeletion(token, item.id, confirmations[item.id] ?? ''),
    ...mutationOptions,
  })
  const exportMutation = useMutation({
    mutationFn: () => downloadTenantDataExport(token, tenantId),
    onSuccess: ({ blob, sha256 }) => {
      const href = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = href
      anchor.download = `tenant-${tenantId}-export.zip`
      anchor.click()
      URL.revokeObjectURL(href)
      setError('')
      setNotice(t('dataGovernance.exportReady', { sha256 }))
    },
    onError: mutationOptions.onError,
  })

  return (
    <AppShell
      title={t('page.dataGovernance.title')}
      subtitle={t('page.dataGovernance.subtitle')}
    >
      <QueryFailureNotice
        title={t('dataGovernance.queryFailureTitle')}
        sources={[{ label: t('nav.dataGovernance'), query: dashboardQuery }]}
      />
      {root && (
        <section className="card form-grid">
          <label>
            {t('dataGovernance.organization')}
            <select value={tenantId} onChange={(event) => setTenantId(event.target.value)}>
              {(tenantsQuery.data ?? []).map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name} · {tenant.slug}</option>
              ))}
            </select>
          </label>
        </section>
      )}
      {notice && <p className="success-banner" role="status">{notice}</p>}
      {error && <p className="error-banner" role="alert">{error}</p>}

      <section className="module-grid module-grid--two">
        <article className="card">
          <div className="section-heading">
            <div>
              <span className="eyebrow">{t('dataGovernance.retention')}</span>
              <h2>{t('dataGovernance.retentionPolicy')}</h2>
            </div>
          </div>
          <div className="form-grid">
            <label>
              {t('dataGovernance.dataCategory')}
              <select value={category} onChange={(event) => setCategory(event.target.value as RetentionCategory)}>
                {categories.map((item) => <option key={item} value={item}>{categoryLabel(item)}</option>)}
              </select>
            </label>
            <label>
              {t('dataGovernance.retentionDays')}
              <input type="number" min={selectedPolicy?.global_minimum_days ?? 30} max={3650} value={retentionDays} onChange={(event) => setRetentionDays(event.target.value)} />
            </label>
          </div>
          <p>{t('dataGovernance.globalMinimum', { days: selectedPolicy?.global_minimum_days ?? '—' })}</p>
          <p>{t('dataGovernance.effectiveRetention', { days: selectedPolicy?.effective_retention_days ?? '—' })}</p>
          {can('data.retention.manage') && (
            <button type="button" className="primary-button" disabled={policyMutation.isPending} onClick={() => policyMutation.mutate()}>
              {t('dataGovernance.savePolicy')}
            </button>
          )}
        </article>

        <article className="card">
          <span className="eyebrow">{t('dataGovernance.legalHold')}</span>
          <h2>{t('dataGovernance.legalHold')}</h2>
          <div className="form-grid">
            <label>{t('dataGovernance.name')}<input value={holdName} onChange={(event) => setHoldName(event.target.value)} /></label>
            <label>{t('dataGovernance.rationale')}<textarea value={holdReason} onChange={(event) => setHoldReason(event.target.value)} /></label>
          </div>
          {can('data.legal_hold.manage') && (
            <button type="button" className="secondary-button" disabled={holdMutation.isPending || holdName.length < 3 || holdReason.length < 10} onClick={() => holdMutation.mutate()}>
              {t('dataGovernance.createHold')}
            </button>
          )}
          <label>
            {t('dataGovernance.releaseRationale')}
            <input value={releaseReason} onChange={(event) => setReleaseReason(event.target.value)} />
          </label>
          <div className="stack-list">
            {(dashboardQuery.data?.active_holds ?? []).map((hold) => (
              <div className="list-card" key={hold.id}>
                <strong>{hold.name}</strong>
                <span>{hold.category ? categoryLabel(hold.category) : t('dataGovernance.allOrganization')}</span>
                <small>{hold.reason}</small>
                {can('data.legal_hold.manage') && (
                  <button type="button" className="ghost-button" disabled={releaseReason.length < 10 || releaseMutation.isPending} onClick={() => releaseMutation.mutate(hold.id)}>{t('dataGovernance.releaseHold')}</button>
                )}
              </div>
            ))}
            {!dashboardQuery.data?.active_holds.length && <p>{t('dataGovernance.noActiveHolds')}</p>}
          </div>
        </article>
      </section>

      <section className="card">
        <div className="section-heading">
          <div>
            <span className="eyebrow">{t('dataGovernance.controlledDeletion')}</span>
            <h2>{t('dataGovernance.deletionFlow')}</h2>
          </div>
          {can('data.export') && (
            <button type="button" className="secondary-button" disabled={exportMutation.isPending} onClick={() => exportMutation.mutate()}>
              {t('dataGovernance.exportTenant')}
            </button>
          )}
        </div>
        <div className="form-grid form-grid--three">
          {root && (
            <label>
              {t('dataGovernance.operationType')}
              <select value={requestType} onChange={(event) => setRequestType(event.target.value as 'RETENTION_PURGE' | 'TENANT_DELETION')}>
                <option value="RETENTION_PURGE">{t('dataGovernance.retentionPurge')}</option>
                <option value="TENANT_DELETION">{t('dataGovernance.tenantDeletion')}</option>
              </select>
            </label>
          )}
          <label>
            {t('dataGovernance.category')}
            <select disabled={requestType === 'TENANT_DELETION'} value={category} onChange={(event) => setCategory(event.target.value as RetentionCategory)}>
              {categories.map((item) => <option key={item} value={item}>{categoryLabel(item)}</option>)}
            </select>
          </label>
          <label>
            {t('dataGovernance.reason')}
            <input value={deletionReason} onChange={(event) => setDeletionReason(event.target.value)} />
          </label>
        </div>
        {can('data.deletion.request') && (
          <button type="button" className="primary-button" disabled={previewMutation.isPending || deletionReason.length < 10} onClick={() => previewMutation.mutate()}>
            {t('dataGovernance.createPreview')}
          </button>
        )}
        <label>
          {t('dataGovernance.decisionRationale')}
          <input value={decisionReason} onChange={(event) => setDecisionReason(event.target.value)} />
        </label>

        <div className="table-shell">
          <table>
            <thead><tr><th>{t('dataGovernance.created')}</th><th>{t('dataGovernance.category')}</th><th>{t('common.status')}</th><th>{t('dataGovernance.rows')}</th><th>{t('dataGovernance.control')}</th><th>{t('dataGovernance.actions')}</th></tr></thead>
            <tbody>
              {(dashboardQuery.data?.recent_requests ?? []).map((item) => (
                <tr key={item.id}>
                  <td>{formatDateTime(item.created_at)}</td>
                  <td>{item.category ? categoryLabel(item.category) : t('dataGovernance.allOrganization')}</td>
                  <td><span className={statusClass(item.status)}>{statusLabel(item.status)}</span></td>
                  <td>{item.estimated_rows}</td>
                  <td><code>{item.plan_sha256.slice(0, 12)}…</code>{item.preview.blocked_by_legal_hold && <div className="badge badge-danger">{t('dataGovernance.legalHold')}</div>}</td>
                  <td>
                    <div className="button-row">
                      {item.status === 'PREVIEWED' && can('data.deletion.request') && <button type="button" className="secondary-button" onClick={() => submitMutation.mutate(item.id)}>{t('dataGovernance.submitApproval')}</button>}
                      {item.status === 'PENDING_APPROVAL' && can('data.deletion.approve') && <>
                        <button type="button" className="secondary-button" disabled={decisionReason.length < 10} onClick={() => decisionMutation.mutate({ item, decision: 'APPROVE' })}>{t('dataGovernance.approve')}</button>
                        <button type="button" className="danger-button" disabled={decisionReason.length < 10} onClick={() => decisionMutation.mutate({ item, decision: 'REJECT' })}>{t('dataGovernance.reject')}</button>
                      </>}
                      {item.status === 'APPROVED' && can('data.deletion.execute') && <div>
                        <small>{t('dataGovernance.enterConfirmation', { phrase: item.required_execution_confirmation })}</small>
                        <input aria-label={t('dataGovernance.enterConfirmation', { phrase: item.id })} value={confirmations[item.id] ?? ''} onChange={(event) => setConfirmations((current) => ({ ...current, [item.id]: event.target.value }))} />
                        <button type="button" className="danger-button" disabled={confirmations[item.id] !== item.required_execution_confirmation} onClick={() => executeMutation.mutate(item)}>{t('dataGovernance.executeIrreversible')}</button>
                      </div>}
                      {item.failure_reason && <small>{item.failure_reason}</small>}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </AppShell>
  )
}
