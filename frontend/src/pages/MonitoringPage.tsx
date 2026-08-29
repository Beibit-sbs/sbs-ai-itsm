/**
 * MonitoringPage - Real-time monitoring dashboard for canary rollouts
 * Displays system health, metrics, alerts, and anomalies
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import SystemHealthCard from '../components/monitoring/SystemHealthCard'
import MetricsTimelineChart from '../components/monitoring/MetricsTimelineChart'
import ActiveAlertsTable from '../components/monitoring/ActiveAlertsTable'
import RolloutComparisonTable from '../components/monitoring/RolloutComparisonTable'
import AnomalyTimelineCard from '../components/monitoring/AnomalyTimelineCard'
import CorrelationMatrixCard from '../components/monitoring/CorrelationMatrixCard'
import QueryFailureNotice from '../components/QueryFailureNotice'
import {
  API_BASE_URL,
  fetchDashboardSummary,
  fetchMetricsTimeline,
  fetchActiveAlerts,
  fetchRolloutComparison,
  fetchAnomalyTimeline,
  fetchCorrelationMatrix,
} from '../api/client'
import { useDashboardWebSocket, type DashboardStreamListener } from '../api/websocket'
import { useTenantExperience } from '../experience/TenantExperienceContext'

export default function MonitoringPage() {
  const { session } = useAuth()
  const { uiLocale } = useTenantExperience()
  const accessToken = session?.access_token ?? ''
  const queryClient = useQueryClient()

  // State for filtering
  const [selectedMetric, setSelectedMetric] = useState('error_rate')
  const [alertSeverityFilter, setAlertSeverityFilter] = useState<string | undefined>(undefined)
  const [timeWindow, setTimeWindow] = useState(60) // minutes
  const [anomalyWindow, setAnomalyWindow] = useState(1440) // minutes (24h)

  const websocketBaseUrl = useMemo(
    () => API_BASE_URL.replace(/\/api\/v1\/?$/, ''),
    []
  )
  const { client, isConnected: isRealtimeConnected, error: realtimeError } = useDashboardWebSocket(
    websocketBaseUrl,
    accessToken
  )

  // Dashboard Summary Query
  const summaryQuery = useQuery({
    queryKey: ['monitoring-summary', accessToken],
    queryFn: () => fetchDashboardSummary(accessToken),
    enabled: !!accessToken,
  })

  // Active Rollouts - needed for metrics and comparison
  const activeRollouts = summaryQuery.data?.active_rollout_ids ?? []

  const primaryRollout = activeRollouts[0]

  // Metrics Timeline Query
  const metricsQuery = useQuery({
    queryKey: ['monitoring-metrics', accessToken, primaryRollout, selectedMetric, timeWindow],
    queryFn: () => fetchMetricsTimeline(accessToken, primaryRollout!, selectedMetric, timeWindow),
    enabled: !!accessToken && !!primaryRollout,
  })

  // Active Alerts Query
  const alertsQuery = useQuery({
    queryKey: ['monitoring-alerts', accessToken, alertSeverityFilter],
    queryFn: () => fetchActiveAlerts(accessToken, alertSeverityFilter, 50),
    enabled: !!accessToken,
  })

  // Rollout Comparison Query
  const comparisonQuery = useQuery({
    queryKey: ['monitoring-comparison', accessToken, activeRollouts.join(',')],
    queryFn: () => fetchRolloutComparison(accessToken, activeRollouts),
    enabled: !!accessToken && activeRollouts.length > 0,
  })

  // Anomaly Timeline Query
  const anomaliesQuery = useQuery({
    queryKey: ['monitoring-anomalies', accessToken, anomalyWindow],
    queryFn: () => fetchAnomalyTimeline(accessToken, undefined, anomalyWindow),
    enabled: !!accessToken,
  })

  // Correlation Matrix Query
  const correlationQuery = useQuery({
    queryKey: ['monitoring-correlation', accessToken, primaryRollout],
    queryFn: () => fetchCorrelationMatrix(accessToken, primaryRollout!, timeWindow),
    enabled: !!accessToken && !!primaryRollout,
  })

  useEffect(() => {
    if (!client || !accessToken) {
      return
    }

    const listener: DashboardStreamListener = {
      onSummaryUpdate: () => {
        queryClient.invalidateQueries({ queryKey: ['monitoring-summary', accessToken] })
      },
      onMetricsUpdate: () => {
        queryClient.invalidateQueries({ queryKey: ['monitoring-metrics', accessToken] })
      },
      onAlertsUpdate: () => {
        queryClient.invalidateQueries({ queryKey: ['monitoring-alerts', accessToken] })
      },
      onComparisonUpdate: () => {
        queryClient.invalidateQueries({ queryKey: ['monitoring-comparison', accessToken] })
      },
      onAnomaliesUpdate: () => {
        queryClient.invalidateQueries({ queryKey: ['monitoring-anomalies', accessToken] })
      },
      onCorrelationUpdate: () => {
        queryClient.invalidateQueries({ queryKey: ['monitoring-correlation', accessToken] })
      },
    }

    client.addListener(listener)
    return () => {
      client.removeListener(listener)
    }
  }, [accessToken, client, queryClient])

  useEffect(() => {
    if (!client || !isRealtimeConnected) {
      return
    }

    const streams = ['summary', 'metrics', 'alerts', 'comparison', 'anomalies', 'correlation'] as const
    client.subscribe([...streams])
    return () => {
      client.unsubscribe([...streams])
    }
  }, [client, isRealtimeConnected])

  const summary = summaryQuery.data
  const metrics = metricsQuery.data
  const alerts = alertsQuery.data
  const comparison = comparisonQuery.data
  const anomalies = anomaliesQuery.data
  const correlation = correlationQuery.data

  const isLoading =
    summaryQuery.isLoading ||
    metricsQuery.isLoading ||
    alertsQuery.isLoading ||
    comparisonQuery.isLoading ||
    anomaliesQuery.isLoading ||
    correlationQuery.isLoading

  const error = realtimeError ? new Error(realtimeError) : null

  return (
    <AppShell
      title="Real-Time Monitoring Dashboard"
      subtitle="Monitor your canary rollouts, metrics, and system health"
    >
      <div className="space-y-6 p-6">
        <QueryFailureNotice
          title="Часть данных мониторинга недоступна."
          sources={[
            { label: 'system summary', query: summaryQuery },
            { label: 'metrics timeline', query: metricsQuery },
            { label: 'active alerts', query: alertsQuery },
            { label: 'rollout comparison', query: comparisonQuery },
            { label: 'anomalies', query: anomaliesQuery },
            { label: 'correlation matrix', query: correlationQuery },
          ]}
        />
        {/* Page Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold">Real-Time Monitoring Dashboard</h1>
            <p className="mt-1 text-gray-600">
              Monitor your canary rollouts, metrics, and system health
            </p>
          </div>
          <div className="text-right text-xs text-gray-500">
            {summary?.timestamp && new Date(summary.timestamp).toLocaleTimeString(uiLocale)}
            <p className={isRealtimeConnected ? 'animate-pulse text-emerald-600' : 'text-amber-600'}>
              ● {isRealtimeConnected ? 'Real-time connected' : 'Real-time reconnecting'}
            </p>
          </div>
        </div>

        {/* Health Overview */}
        {summary && (
          <SystemHealthCard
            activeRollouts={summary.active_rollouts}
            avgHealthScore={summary.avg_health_score}
            healthStatus={summary.health_status}
            activeAlerts={summary.active_alerts}
            criticalAlerts={summary.critical_alerts}
            unresolved_anomalies={summary.unresolved_anomalies}
            systemStatus={summary.system_status}
          />
        )}

        {/* Metrics and Alerts Row */}
        <div className="grid gap-6 md:grid-cols-2">
          {/* Metrics Timeline */}
          <div>
            <div className="mb-3 flex items-center space-x-2">
              <label className="text-sm font-medium">Metric:</label>
              <select
                value={selectedMetric}
                onChange={(e) => setSelectedMetric(e.target.value)}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
              >
                <option value="error_rate">Error Rate</option>
                <option value="latency_p99">Latency (P99)</option>
                <option value="throughput">Throughput</option>
                <option value="cpu">CPU Usage</option>
                <option value="memory">Memory Usage</option>
              </select>

              <label className="ml-4 text-sm font-medium">Time Window:</label>
              <select
                value={timeWindow}
                onChange={(e) => setTimeWindow(Number(e.target.value))}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
              >
                <option value="5">5 min</option>
                <option value="15">15 min</option>
                <option value="60">1 hour</option>
                <option value="1440">24 hours</option>
              </select>
            </div>

            {metrics && (
              <MetricsTimelineChart
                rolloutId={metrics.rollout_id}
                metricType={metrics.metric_type}
                values={metrics.values}
                timestamps={metrics.timestamps}
                statistics={metrics.statistics}
                isLoading={metricsQuery.isLoading}
                error={metricsQuery.error?.message}
              />
            )}
          </div>

          {/* Active Alerts */}
          <div>
            <div className="mb-3 flex items-center space-x-2">
              <label className="text-sm font-medium">Severity:</label>
              <select
                value={alertSeverityFilter || ''}
                onChange={(e) => setAlertSeverityFilter(e.target.value || undefined)}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
              >
                <option value="">All Severities</option>
                <option value="critical">Critical Only</option>
                <option value="high">High & Critical</option>
                <option value="medium">Medium & Above</option>
                <option value="low">All</option>
              </select>
            </div>

            {alerts && (
              <ActiveAlertsTable
                alerts={alerts.alerts}
                isLoading={alertsQuery.isLoading}
                error={alertsQuery.error?.message}
              />
            )}
          </div>
        </div>

        {/* Rollout Comparison */}
        {comparison && (
          <RolloutComparisonTable
            rollouts={comparison.comparison}
            isLoading={comparisonQuery.isLoading}
            error={comparisonQuery.error?.message}
          />
        )}

        {/* Anomalies and Correlation */}
        <div className="grid gap-6 md:grid-cols-2">
          {/* Anomaly Timeline */}
          <div>
            <div className="mb-3 flex items-center space-x-2">
              <label className="text-sm font-medium">Time Window:</label>
              <select
                value={anomalyWindow}
                onChange={(e) => setAnomalyWindow(Number(e.target.value))}
                className="rounded border border-gray-300 px-2 py-1 text-sm"
              >
                <option value="60">1 hour</option>
                <option value="360">6 hours</option>
                <option value="1440">24 hours</option>
                <option value="10080">7 days</option>
              </select>
            </div>

            {anomalies && (
              <AnomalyTimelineCard
                anomalies={anomalies.anomalies}
                isLoading={anomaliesQuery.isLoading}
                error={anomaliesQuery.error?.message}
              />
            )}
          </div>

          {/* Correlation Matrix */}
          {correlation && (
            <CorrelationMatrixCard
              rolloutId={correlation.rollout_id}
              correlationMatrix={correlation.correlation_matrix}
              metricCount={correlation.metric_count}
              dataPoints={correlation.data_points}
              isLoading={correlationQuery.isLoading}
              error={correlationQuery.error?.message}
            />
          )}
        </div>

        {/* Error State */}
        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-6" role="alert">
            <h3 className="text-lg font-semibold text-red-900">Error Loading Dashboard</h3>
            <p className="mt-2 text-sm text-red-700">{(error as Error).message}</p>
          </div>
        )}

        {/* Loading State */}
        {isLoading && !summary && (
          <div className="rounded-lg border border-gray-200 bg-gray-50 p-6">
            <div className="animate-pulse space-y-4">
              <div className="h-8 rounded bg-gray-200" />
              <div className="h-64 rounded bg-gray-200" />
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
