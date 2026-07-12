import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import { getDeepHealth, getHealth, getLiveness, getReadiness } from '../api/client'
import { useAuth } from '../auth/AuthContext'

function statusClass(value: string | undefined) {
  const normalized = String(value ?? '').toLowerCase()
  if (normalized === 'ok' || normalized === 'ready' || normalized === 'alive') return 'badge badge-positive'
  if (normalized === 'unknown') return 'badge badge-warning'
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
