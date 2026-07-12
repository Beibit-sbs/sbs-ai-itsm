import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import { fetchAiProviderStatus, fetchJobRuns, fetchJobRuntime, fetchJobSummary, getDeepHealth, getHealth, getLiveness, getReadiness } from '../api/client'
import { useAuth } from '../auth/AuthContext'

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

function formatDateTime(value: string | null): string {
  if (!value) return '—'
  try {
    return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(value))
  } catch {
    return value
  }
}

export default function AdminSystemPage() {
  const { session } = useAuth()

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

  const aiProviderQuery = useQuery({
    queryKey: ['system-ai-provider', session?.access_token],
    queryFn: () => fetchAiProviderStatus(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
    refetchInterval: 30000,
    retry: false,
  })

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
    <AppShell title="System Diagnostics" subtitle="Операционная диагностика, readiness и базовые проверки runtime">
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
                Active:{' '}
                <span className={statusClass(aiProviderQuery.data?.ready ? 'ok' : 'unknown')}>
                  {aiProviderQuery.data?.active_provider ?? (aiProviderQuery.isLoading ? 'loading' : 'unknown')}
                </span>
              </p>
              <p>Model: {aiProviderQuery.data?.model ?? '—'}</p>
              <p>
                Ready:{' '}
                <span className={statusClass(aiProviderQuery.data?.ready ? 'ok' : 'failed')}>
                  {String(aiProviderQuery.data?.ready ?? '—')}
                </span>
              </p>
              <p>API key configured: {String(aiProviderQuery.data?.api_key_configured ?? '—')}</p>
              <p>PII redaction: {String(aiProviderQuery.data?.pii_redaction_enabled ?? '—')}</p>
              <p>Timeout: {aiProviderQuery.data?.request_timeout_seconds ?? '—'} s</p>
              {aiProviderQuery.data?.reason ? (
                <p>Note: {aiProviderQuery.data.reason}{aiProviderQuery.data.fallback_provider ? ` (fallback: ${aiProviderQuery.data.fallback_provider})` : ''}</p>
              ) : null}
              <p>Supported: {(aiProviderQuery.data?.supported_providers ?? []).join(', ') || '—'}</p>
            </>
          )}
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
  )
}
