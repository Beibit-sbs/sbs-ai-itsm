/**
 * RolloutComparisonTable - Compares multiple rollouts side by side
 * Shows key metrics (health, error rate, latency, alerts) for each rollout
 */

import type { RolloutComparisonItem } from '../../api/client'

interface RolloutComparisonTableProps {
  rollouts: RolloutComparisonItem[]
  isLoading?: boolean
  error?: string
}

export default function RolloutComparisonTable({
  rollouts,
  isLoading = false,
  error,
}: RolloutComparisonTableProps) {
  const getHealthColor = (score: number) => {
    if (score >= 0.8) return 'text-green-700 font-semibold'
    if (score >= 0.5) return 'text-yellow-700 font-semibold'
    return 'text-red-700 font-semibold'
  }

  const getHealthBg = (score: number) => {
    if (score >= 0.8) return 'bg-green-50'
    if (score >= 0.5) return 'bg-yellow-50'
    return 'bg-red-50'
  }

  const getStatusBadge = (status: string) => {
    const isActive = status === 'active' || status === 'running'
    return isActive ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-800'
  }

  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-lg font-semibold">Rollout Comparison</h3>
        <div className="animate-pulse space-y-2">
          {[...Array(2)].map((_, i) => (
            <div key={i} className="h-16 rounded bg-gray-200" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h3 className="mb-2 text-lg font-semibold text-red-900">Rollout Comparison</h3>
        <p className="text-sm text-red-700">{error}</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <h3 className="mb-4 text-lg font-semibold">
        Rollout Comparison ({rollouts.length})
      </h3>

      {rollouts.length === 0 ? (
        <p className="text-sm text-gray-500">No rollouts to compare</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left font-semibold">Rollout</th>
                <th className="px-4 py-2 text-center font-semibold">Status</th>
                <th className="px-4 py-2 text-right font-semibold">Canary %</th>
                <th className="px-4 py-2 text-center font-semibold">Health</th>
                <th className="px-4 py-2 text-right font-semibold">Error Rate</th>
                <th className="px-4 py-2 text-right font-semibold">P99 Latency</th>
                <th className="px-4 py-2 text-right font-semibold">Throughput</th>
                <th className="px-4 py-2 text-center font-semibold">Alerts</th>
                <th className="px-4 py-2 text-center font-semibold">Anomalies</th>
                <th className="px-4 py-2 text-right font-semibold">Duration</th>
              </tr>
            </thead>
            <tbody>
              {rollouts.map((rollout) => (
                <tr key={rollout.rollout_id} className={`border-b hover:bg-gray-50 ${getHealthBg(rollout.health_score)}`}>
                  <td className="px-4 py-3">
                    <div>
                      <p className="font-medium">{rollout.name}</p>
                      <p className="text-xs text-gray-500">{rollout.rollout_id}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-block rounded px-2 py-1 text-xs font-semibold ${getStatusBadge(rollout.status)}`}>
                      {rollout.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {rollout.canary_percentage.toFixed(1)}%
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={getHealthColor(rollout.health_score)}>
                      {(rollout.health_score * 100).toFixed(0)}%
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {rollout.error_rate ? `${(rollout.error_rate * 100).toFixed(2)}%` : '—'}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {rollout.latency_p99_ms ? `${rollout.latency_p99_ms.toFixed(0)}ms` : '—'}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {rollout.throughput_eps ? `${rollout.throughput_eps.toFixed(0)}/s` : '—'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={rollout.active_alerts > 0 ? 'font-semibold text-orange-600' : 'text-green-600'}>
                      {rollout.active_alerts}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={rollout.unresolved_anomalies > 0 ? 'font-semibold text-red-600' : 'text-green-600'}>
                      {rollout.unresolved_anomalies}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700">
                    {rollout.duration_hours.toFixed(1)}h
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
