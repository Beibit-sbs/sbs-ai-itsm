import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { fetchAdminAiProviderConfig, fetchAiProviderStatus, fetchJobOutboxDiagnostics, fetchJobOutboxSummary, fetchJobRuns, fetchJobRuntime, fetchJobSummary, getDeepHealth, getHealth, getLiveness, getReadiness, patchAdminAiProviderConfig, testAdminAiProviderConfig, type AdminAiProviderConfigTestResult } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

type AiConfigFormState = {
  provider: 'mock' | 'openai' | 'gemini'
  openai_model: string
  openai_base_url: string
  gemini_model: string
  pii_redaction_enabled: boolean
  request_timeout_seconds: string
  openai_api_key: string
  gemini_api_key: string
}

function statusClass(value: string | undefined) {
  const normalized = String(value ?? '').toLowerCase()
  if (normalized === 'ok' || normalized === 'ready' || normalized === 'alive' || normalized === 'success') return 'badge badge-positive'
  if (normalized === 'unknown' || normalized === 'queued' || normalized === 'running') return 'badge badge-warning'
  return 'badge badge-danger'
}

function toPrettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return 'Unable to render diagnostics payload'
  }
}

export default function AdminSystemPage() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const root = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const hasPermission = (permission: string) => root || permissions.has(permission)
  const canReadAiConfig = hasPermission('admin.settings.read')
  const canUpdateAiConfig = hasPermission('admin.settings.update')
  const [aiConfigMessage, setAiConfigMessage] = useState<string | null>(null)
  const [aiConfigTestResult, setAiConfigTestResult] = useState<AdminAiProviderConfigTestResult | null>(null)
  const [aiConfigForm, setAiConfigForm] = useState<AiConfigFormState>({
    provider: 'mock',
    openai_model: 'gpt-4o-mini',
    openai_base_url: 'https://api.openai.com/v1',
    gemini_model: 'gemini-2.0-flash-exp',
    pii_redaction_enabled: true,
    request_timeout_seconds: '15',
    openai_api_key: '',
    gemini_api_key: '',
  })

  const healthQuery = useQuery({
    queryKey: ['system-health-basic'],
    queryFn: () => getHealth(),
    refetchInterval: 15000,
  })

  const livenessQuery = useQuery({
    queryKey: ['system-health-liveness'],
    queryFn: () => getLiveness(),
    refetchInterval: 15000,
  })

  const readinessQuery = useQuery({
    queryKey: ['system-health-readiness'],
    queryFn: () => getReadiness(),
    refetchInterval: 15000,
  })

  const deepHealthQuery = useQuery({
    queryKey: ['system-health-deep', session?.access_token],
    queryFn: () => getDeepHealth(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
    refetchInterval: 20000,
    retry: false,
  })

  const jobsSummaryQuery = useQuery({
    queryKey: ['system-jobs-summary', session?.access_token],
    queryFn: () => fetchJobSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
    refetchInterval: 15000,
    retry: false,
  })

  const jobsRuntimeQuery = useQuery({
    queryKey: ['system-jobs-runtime', session?.access_token],
    queryFn: () => fetchJobRuntime(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
    refetchInterval: 30000,
    retry: false,
  })

  const jobRunsQuery = useQuery({
    queryKey: ['system-jobs-recent', session?.access_token],
    queryFn: () => fetchJobRuns(session?.access_token ?? '', 15),
    enabled: Boolean(session?.access_token),
    refetchInterval: 15000,
    retry: false,
  })

  const jobsOutboxQuery = useQuery({
    queryKey: ['system-jobs-outbox', session?.access_token],
    queryFn: () => fetchJobOutboxSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
    refetchInterval: 15000,
    retry: false,
  })

  const jobsOutboxDiagnosticsQuery = useQuery({
    queryKey: ['system-jobs-outbox-diagnostics', session?.access_token],
    queryFn: () => fetchJobOutboxDiagnostics(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
    refetchInterval: 15000,
    retry: false,
  })

  const aiProviderQuery = useQuery({
    queryKey: ['system-ai-provider', session?.access_token],
    queryFn: () => fetchAiProviderStatus(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
    refetchInterval: 30000,
    retry: false,
  })

  const aiProviderConfigQuery = useQuery({
    queryKey: ['admin-ai-provider-config', session?.access_token],
    queryFn: () => fetchAdminAiProviderConfig(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && canReadAiConfig,
    retry: false,
  })

  const aiProviderConfigMutation = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => patchAdminAiProviderConfig(session?.access_token ?? '', payload),
    onSuccess: async (config) => {
      setAiConfigMessage(
        config.provider === 'mock'
          ? 'Local AI simulation selected; no external provider is active.'
          : `${config.provider} configuration saved and selected for external AI calls.`,
      )
      setAiConfigForm((current) => ({ ...current, openai_api_key: '', gemini_api_key: '' }))
      await queryClient.invalidateQueries({ queryKey: ['admin-ai-provider-config'] })
      await queryClient.invalidateQueries({ queryKey: ['system-ai-provider'] })
    },
    onError: (error) => {
      setAiConfigMessage(error instanceof Error ? error.message : 'Unable to update AI provider configuration.')
    },
  })

  const aiProviderTestMutation = useMutation({
    mutationFn: async () =>
      testAdminAiProviderConfig(session?.access_token ?? '', {
        provider: aiConfigForm.provider,
        openai_model: aiConfigForm.openai_model,
        openai_base_url: aiConfigForm.openai_base_url,
        gemini_model: aiConfigForm.gemini_model,
        request_timeout_seconds: Number(aiConfigForm.request_timeout_seconds || '15'),
        ...(aiConfigForm.openai_api_key.trim() ? { openai_api_key: aiConfigForm.openai_api_key.trim() } : {}),
        ...(aiConfigForm.gemini_api_key.trim() ? { gemini_api_key: aiConfigForm.gemini_api_key.trim() } : {}),
      }),
    onSuccess: (payload) => {
      setAiConfigMessage(
        payload.simulation
          ? 'Local AI simulation verified; no external provider connection was tested.'
          : payload.success
            ? 'AI provider test succeeded.'
            : `AI provider test failed: ${payload.reason ?? 'unknown error'}`,
      )
      setAiConfigTestResult(payload)
    },
    onError: (error) => {
      setAiConfigMessage(error instanceof Error ? error.message : 'Unable to test AI provider configuration.')
      setAiConfigTestResult(null)
    },
  })

  useEffect(() => {
    if (!aiProviderConfigQuery.data) return
    setAiConfigForm((current) => ({
      ...current,
      provider: aiProviderConfigQuery.data.provider,
      openai_model: aiProviderConfigQuery.data.openai_model,
      openai_base_url: aiProviderConfigQuery.data.openai_base_url,
      gemini_model: aiProviderConfigQuery.data.gemini_model,
      pii_redaction_enabled: aiProviderConfigQuery.data.pii_redaction_enabled,
      request_timeout_seconds: String(aiProviderConfigQuery.data.request_timeout_seconds),
    }))
  }, [aiProviderConfigQuery.data])

  const liveProviderRequiresTest = aiConfigForm.provider !== 'mock'
  const liveProviderActivationReady = !liveProviderRequiresTest || Boolean(
    aiConfigTestResult?.success
      && aiConfigTestResult.requested_provider === aiConfigForm.provider
      && (
        (aiConfigForm.provider === 'openai' && aiConfigTestResult.model === aiConfigForm.openai_model)
        || (aiConfigForm.provider === 'gemini' && aiConfigTestResult.model === aiConfigForm.gemini_model)
      )
  )

  const appMode = useMemo(() => {
    const env = healthQuery.data?.environment ?? 'unknown'
    const demo = deepHealthQuery.data?.demo_mode
    const ddl = deepHealthQuery.data?.run_startup_ddl
    return {
      environment: env,
      demoMode: demo,
      startupDdl: ddl,
    }
  }, [deepHealthQuery.data, healthQuery.data?.environment])

  return (
    <LocalizedContent>
    <AppShell title="System Diagnostics" subtitle="Операционная диагностика, readiness и базовые проверки runtime">
      <QueryFailureNotice
        title="Часть данных System Diagnostics недоступна."
        sources={[
          { label: 'health', query: healthQuery },
          { label: 'liveness', query: livenessQuery },
          { label: 'readiness', query: readinessQuery },
          { label: 'deep health', query: deepHealthQuery },
          { label: 'jobs summary', query: jobsSummaryQuery },
          { label: 'jobs runtime', query: jobsRuntimeQuery },
          { label: 'job runs', query: jobRunsQuery },
          { label: 'outbox', query: jobsOutboxQuery },
          { label: 'outbox diagnostics', query: jobsOutboxDiagnosticsQuery },
          { label: 'AI provider status', query: aiProviderQuery },
          { label: 'AI provider config', query: aiProviderConfigQuery },
        ]}
      />
      <section className="module-grid module-grid--two">
        <article className="card state-panel state-panel-neutral">
          <h2>Backend Health</h2>
          <p>
            Status:{' '}
            <span className={statusClass(healthQuery.data?.status)}>
              {healthQuery.data?.status ?? (healthQuery.isLoading ? 'loading' : 'unknown')}
            </span>
          </p>
          <p>Service: {healthQuery.data?.service ?? '—'}</p>
          <p>Version: {healthQuery.data?.version ?? '—'}</p>
          <p>Environment: {healthQuery.data?.environment ?? '—'}</p>
        </article>

        <article className="card state-panel state-panel-neutral">
          <h2>Liveness / Readiness</h2>
          <p>
            Liveness:{' '}
            <span className={statusClass(livenessQuery.data?.status)}>
              {livenessQuery.data?.status ?? (livenessQuery.isLoading ? 'loading' : 'unknown')}
            </span>
          </p>
          <p>
            Readiness:{' '}
            <span className={statusClass(readinessQuery.data?.status)}>
              {readinessQuery.data?.status ?? (readinessQuery.isLoading ? 'loading' : 'unknown')}
            </span>
          </p>
          <p>Postgres: {readinessQuery.data?.checks?.postgres ?? '—'}</p>
          <p>Redis: {readinessQuery.data?.checks?.redis ?? '—'}</p>
        </article>

        <article className="card state-panel state-panel-neutral">
          <h2>Application Mode</h2>
          <p>Environment: {appMode.environment}</p>
          <p>DEMO_MODE: {String(appMode.demoMode ?? 'n/a')}</p>
          <p>RUN_STARTUP_DDL: {String(appMode.startupDdl ?? 'n/a')}</p>
          <p>Last Basic Check: {healthQuery.data?.timestamp ?? '—'}</p>
        </article>

        <article className="card state-panel state-panel-neutral">
          <h2>Deep Diagnostics</h2>
          {deepHealthQuery.isError ? (
            <p className="state-panel-text">Deep health requires admin permissions.</p>
          ) : (
            <>
              <p>
                Deep status:{' '}
                <span className={statusClass(deepHealthQuery.data?.status)}>
                  {deepHealthQuery.data?.status ?? (deepHealthQuery.isLoading ? 'loading' : 'unknown')}
                </span>
              </p>
              <p>Postgres: {String(deepHealthQuery.data?.checks?.postgres?.status ?? '—')}</p>
              <p>Redis: {String(deepHealthQuery.data?.checks?.redis?.status ?? '—')}</p>
              <p>Alembic: {String(deepHealthQuery.data?.checks?.alembic?.status ?? '—')}</p>
            </>
          )}
        </article>
      </section>

      <section className="module-grid module-grid--single">
        <article className="card">
          <h2>Background Jobs</h2>
          {jobsSummaryQuery.isError ? (
            <p className="state-panel-text">Jobs telemetry requires admin/security permissions.</p>
          ) : (
            <>
              <p>
                Executor:{' '}
                <span className={statusClass(jobsRuntimeQuery.data?.executor_mode === 'redis' ? 'running' : 'ok')}>
                  {jobsRuntimeQuery.data?.executor_mode ?? 'unknown'}
                </span>
              </p>
              <p>Queue: {jobsRuntimeQuery.data?.queue_name ?? '—'}</p>
              <p>Dead-letter queue: {jobsRuntimeQuery.data?.dead_letter_queue_name ?? '—'}</p>
              <p>Worker required: {String(jobsRuntimeQuery.data?.worker_required ?? '—')}</p>
              <p>
                Retry policy: base {jobsRuntimeQuery.data?.retry_base_seconds ?? '—'}s / max {jobsRuntimeQuery.data?.retry_max_seconds ?? '—'}s
              </p>
              <p>Total: {jobsSummaryQuery.data?.total ?? '—'}</p>
              <p>Queued: {jobsSummaryQuery.data?.queued ?? '—'}</p>
              <p>Running: {jobsSummaryQuery.data?.running ?? '—'}</p>
              <p>
                Success:{' '}
                <span className={statusClass('success')}>{jobsSummaryQuery.data?.success ?? 0}</span>
              </p>
              <p>
                Failed:{' '}
                <span className={statusClass((jobsSummaryQuery.data?.failed ?? 0) > 0 ? 'failed' : 'ok')}>
                  {jobsSummaryQuery.data?.failed ?? 0}
                </span>
              </p>
              <p>
                Dead-letter:{' '}
                <span className={statusClass((jobsSummaryQuery.data?.dead_letter ?? 0) > 0 ? 'failed' : 'ok')}>
                  {jobsSummaryQuery.data?.dead_letter ?? 0}
                </span>
              </p>
              <p>Outbox total: {jobsOutboxQuery.data?.total ?? '—'}</p>
              <p>
                Outbox pending:{' '}
                <span className={statusClass((jobsOutboxQuery.data?.pending ?? 0) > 0 ? 'running' : 'ok')}>
                  {jobsOutboxQuery.data?.pending ?? 0}
                </span>
              </p>
              <p>Outbox published: {jobsOutboxQuery.data?.published ?? '—'}</p>
              <p>
                Outbox failures:{' '}
                <span className={statusClass((jobsOutboxQuery.data?.with_failures ?? 0) > 0 ? 'failed' : 'ok')}>
                  {jobsOutboxQuery.data?.with_failures ?? 0}
                </span>
              </p>
              <p>
                Outbox status:{' '}
                <span className={statusClass(jobsOutboxDiagnosticsQuery.data?.status)}>
                  {jobsOutboxDiagnosticsQuery.data?.status ?? 'unknown'}
                </span>
              </p>
              <p>Locked rows: {jobsOutboxDiagnosticsQuery.data?.locked ?? '—'}</p>
              <p>
                Stale locks:{' '}
                <span className={statusClass((jobsOutboxDiagnosticsQuery.data?.stale_locks ?? 0) > 0 ? 'failed' : 'ok')}>
                  {jobsOutboxDiagnosticsQuery.data?.stale_locks ?? 0}
                </span>
              </p>
              <p>Dedup skips: {jobsOutboxDiagnosticsQuery.data?.dedup_skips ?? '—'}</p>
              <p>Publish failure rate: {jobsOutboxDiagnosticsQuery.data?.publish_failure_rate_pct ?? '—'}%</p>
              <p>
                Thresholds: pending {jobsOutboxDiagnosticsQuery.data?.pending_alert_threshold ?? '—'}, failures {jobsOutboxDiagnosticsQuery.data?.failure_alert_threshold ?? '—'}, stale locks {jobsOutboxDiagnosticsQuery.data?.stale_lock_alert_threshold ?? '—'}
              </p>
              <p>Recommended action: {(jobsOutboxDiagnosticsQuery.data?.recommended_actions ?? ['—']).join(' ')}</p>
            </>
          )}
        </article>

        <article className="card">
          <h2>Recent Job Runs</h2>
          {jobRunsQuery.isError ? (
            <p className="state-panel-text">Job history requires admin/security permissions.</p>
          ) : (jobRunsQuery.data ?? []).length === 0 ? (
            <p className="state-panel-text">No job runs recorded yet.</p>
          ) : (
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Task</th>
                  <th>Status</th>
                  <th>Attempts</th>
                  <th>Duration ms</th>
                  <th>Queued</th>
                  <th>Correlation</th>
                </tr>
              </thead>
              <tbody>
                {(jobRunsQuery.data ?? []).map((job) => (
                  <tr key={job.id}>
                    <td>{job.task_name}</td>
                    <td>
                      <span className={statusClass(job.status)}>{job.status}</span>
                    </td>
                    <td>{job.attempts}/{job.max_attempts}</td>
                    <td>{job.duration_ms ?? '—'}</td>
                    <td>{formatDateTime(job.queued_at)}</td>
                    <td>{job.correlation_id ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </article>
      </section>

      <section className="module-grid module-grid--single">
        <article className="card">
          <h2>AI Provider</h2>
          {aiProviderQuery.isError ? (
            <p className="state-panel-text">AI provider status requires admin/security permissions.</p>
          ) : (
            <>
              <p>
                Effective provider:{' '}
                <span className={statusClass(aiProviderQuery.data?.ready ? 'ok' : 'unknown')}>
                  {aiProviderQuery.data?.active_provider ?? (aiProviderQuery.isLoading ? 'loading' : 'unknown')}
                </span>
              </p>
              <p>Configured provider: {aiProviderQuery.data?.configured_provider ?? '—'}</p>
              <p>Execution mode: {aiProviderQuery.data?.execution_mode ?? '—'}</p>
              <p>Model: {aiProviderQuery.data?.model ?? '—'}</p>
              <p>
                External configured:{' '}
                <span className={statusClass(aiProviderQuery.data?.ready ? 'ok' : 'failed')}>
                  {String(aiProviderQuery.data?.external_configured ?? '—')}
                </span>
              </p>
              <p>API key configured: {String(aiProviderQuery.data?.api_key_configured ?? '—')}</p>
              <p>PII redaction: {String(aiProviderQuery.data?.pii_redaction_enabled ?? '—')}</p>
              <p>Timeout: {aiProviderQuery.data?.request_timeout_seconds ?? '—'} s</p>
              {aiProviderQuery.data?.reason ? (
                <p>Note: {aiProviderQuery.data.reason}{aiProviderQuery.data.fallback_provider ? ` ${translate('(fallback:')} ${aiProviderQuery.data.fallback_provider})` : ''}</p>
              ) : null}
              <p>Supported: {(aiProviderQuery.data?.supported_providers ?? []).join(', ') || '—'}</p>
            </>
          )}

          {canReadAiConfig ? <div className="form-stack" style={{ marginTop: 16 }}>
            <h3 style={{ margin: 0 }}>AI Provider Configuration</h3>
            <p className="muted" style={{ margin: 0 }}>Admin can switch between mock, OpenAI and Gemini without exposing saved API keys in the UI.</p>

            {aiConfigMessage ? <p className="state-panel state-panel-neutral">{aiConfigMessage}</p> : null}
            {liveProviderRequiresTest && !liveProviderActivationReady ? (
              <p className="state-panel state-panel-error">Для production-активации live AI provider сначала выполните успешный Test current config.</p>
            ) : null}

            <label>
              <span>Provider</span>
              <select disabled={!canUpdateAiConfig} value={aiConfigForm.provider} onChange={(event) => setAiConfigForm((prev) => ({ ...prev, provider: event.target.value as AiConfigFormState['provider'] }))}>
                <option value="mock">mock</option>
                <option value="openai">openai</option>
                <option value="gemini">gemini</option>
              </select>
            </label>

            <div className="detail-fields">
              <label>
                <span>OpenAI model</span>
                <input disabled={!canUpdateAiConfig} value={aiConfigForm.openai_model} onChange={(event) => setAiConfigForm((prev) => ({ ...prev, openai_model: event.target.value }))} />
              </label>
              <label>
                <span>Gemini model</span>
                <input disabled={!canUpdateAiConfig} value={aiConfigForm.gemini_model} onChange={(event) => setAiConfigForm((prev) => ({ ...prev, gemini_model: event.target.value }))} />
              </label>
            </div>

            <label>
              <span>OpenAI base URL</span>
              <input disabled={!canUpdateAiConfig} value={aiConfigForm.openai_base_url} onChange={(event) => setAiConfigForm((prev) => ({ ...prev, openai_base_url: event.target.value }))} />
            </label>

            <div className="detail-fields">
              <label>
                <span>Timeout seconds</span>
                <input disabled={!canUpdateAiConfig} value={aiConfigForm.request_timeout_seconds} onChange={(event) => setAiConfigForm((prev) => ({ ...prev, request_timeout_seconds: event.target.value }))} />
              </label>
              <label>
                <span>PII redaction</span>
                <select disabled={!canUpdateAiConfig} value={aiConfigForm.pii_redaction_enabled ? 'true' : 'false'} onChange={(event) => setAiConfigForm((prev) => ({ ...prev, pii_redaction_enabled: event.target.value === 'true' }))}>
                  <option value="true">Enabled</option>
                  <option value="false">Disabled</option>
                </select>
              </label>
            </div>

            <div className="detail-fields">
              <label>
                <span>OpenAI API key</span>
                <input disabled={!canUpdateAiConfig} type="password" value={aiConfigForm.openai_api_key} onChange={(event) => setAiConfigForm((prev) => ({ ...prev, openai_api_key: event.target.value }))} placeholder={aiProviderConfigQuery.data?.openai_api_key_configured ? 'Configured. Enter new key to rotate.' : 'sk-...'} />
              </label>
              <label>
                <span>Gemini API key</span>
                <input disabled={!canUpdateAiConfig} type="password" value={aiConfigForm.gemini_api_key} onChange={(event) => setAiConfigForm((prev) => ({ ...prev, gemini_api_key: event.target.value }))} placeholder={aiProviderConfigQuery.data?.gemini_api_key_configured ? 'Configured. Enter new key to rotate.' : 'AIza...'} />
              </label>
            </div>

            {canUpdateAiConfig ? <div className="analytics-actions" style={{ justifyContent: 'flex-start', flexWrap: 'wrap' }}>
              <button
                type="button"
                className="ghost-button"
                disabled={aiProviderTestMutation.isPending || aiProviderConfigMutation.isPending}
                onClick={() => {
                  setAiConfigMessage(null)
                  aiProviderTestMutation.mutate()
                }}
              >
                {aiProviderTestMutation.isPending ? 'Testing...' : 'Test current config'}
              </button>
              <button
                type="button"
                disabled={aiProviderConfigMutation.isPending || !liveProviderActivationReady}
                title={!liveProviderActivationReady ? 'Run a successful provider test before activating OpenAI or Gemini' : undefined}
                onClick={() => {
                  setAiConfigMessage(null)
                  aiProviderConfigMutation.mutate({
                    provider: aiConfigForm.provider,
                    openai_model: aiConfigForm.openai_model,
                    openai_base_url: aiConfigForm.openai_base_url,
                    gemini_model: aiConfigForm.gemini_model,
                    pii_redaction_enabled: aiConfigForm.pii_redaction_enabled,
                    request_timeout_seconds: Number(aiConfigForm.request_timeout_seconds || '15'),
                    ...(aiConfigForm.openai_api_key.trim() ? { openai_api_key: aiConfigForm.openai_api_key.trim() } : {}),
                    ...(aiConfigForm.gemini_api_key.trim() ? { gemini_api_key: aiConfigForm.gemini_api_key.trim() } : {}),
                  })
                }}
              >
                {aiProviderConfigMutation.isPending ? 'Saving...' : 'Save AI configuration'}
              </button>
              <button
                type="button"
                className="ghost-button"
                disabled={aiProviderConfigMutation.isPending || !aiProviderConfigQuery.data?.openai_api_key_configured}
                onClick={() => {
                  setAiConfigMessage(null)
                  aiProviderConfigMutation.mutate({ clear_openai_api_key: true })
                }}
              >
                Clear OpenAI key
              </button>
              <button
                type="button"
                className="ghost-button"
                disabled={aiProviderConfigMutation.isPending || !aiProviderConfigQuery.data?.gemini_api_key_configured}
                onClick={() => {
                  setAiConfigMessage(null)
                  aiProviderConfigMutation.mutate({ clear_gemini_api_key: true })
                }}
              >
                Clear Gemini key
              </button>
            </div> : null}

            {aiConfigTestResult ? (
              <div className={`state-panel ${aiConfigTestResult.simulation ? 'state-panel-warning' : aiConfigTestResult.success ? 'state-panel-loading' : 'state-panel-error'}`}>
                <p style={{ margin: 0 }}>Requested: {aiConfigTestResult.requested_provider} · Effective: {aiConfigTestResult.effective_provider} · Model: {aiConfigTestResult.model}</p>
                <p style={{ margin: '6px 0 0' }}>
                  {aiConfigTestResult.simulation ? 'Simulation only; no external provider connection was tested.' : `${translate('Success:')} ${String(aiConfigTestResult.success)}`}
                  {aiConfigTestResult.response_status != null ? ` · HTTP ${aiConfigTestResult.response_status}` : ''}
                </p>
                {aiConfigTestResult.reason ? <p style={{ margin: '6px 0 0' }}>Reason: {aiConfigTestResult.reason}</p> : null}
                {aiConfigTestResult.summary ? <p style={{ margin: '6px 0 0' }}>Summary: {aiConfigTestResult.summary}</p> : null}
                {aiConfigTestResult.category ? <p style={{ margin: '6px 0 0' }}>Category: {aiConfigTestResult.category} · Priority: {aiConfigTestResult.priority} · Confidence: {aiConfigTestResult.confidence}</p> : null}
              </div>
            ) : null}
          </div> : null}
        </article>
      </section>

      <section className="module-grid module-grid--single">
        <article className="card">
          <h2>Operational Hints</h2>
          <ul className="state-panel-list">
            <li>Use make health and make smoke for local runtime validation.</li>
            <li>Use scripts/check-production-env.sh before production compose deploy.</li>
            <li>Use scripts/backup-db.sh before migrations.</li>
            <li>Ensure .env.production is local-only and never committed.</li>
          </ul>
        </article>

        <article className="card">
          <h2>Deep Payload (sanitized)</h2>
          <pre>{toPrettyJson(deepHealthQuery.data ?? { info: 'No deep payload available' })}</pre>
        </article>
      </section>
    </AppShell>
    </LocalizedContent>
  )
}
