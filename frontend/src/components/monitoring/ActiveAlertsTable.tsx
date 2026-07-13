/**
 * ActiveAlertsTable - Displays current alerts with severity and context
 * Shows alert details, duration, and breach information
 */

import type { AlertSummaryItem } from '../../api/client'

interface ActiveAlertsTableProps {
  alerts: AlertSummaryItem[]
  isLoading?: boolean
  error?: string
}

export default function ActiveAlertsTable({
  alerts,
  isLoading = false,
  error,
}: ActiveAlertsTableProps) {
  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case 'critical':
        return 'bg-red-100 text-red-800'
      case 'high':
        return 'bg-orange-100 text-orange-800'
      case 'medium':
        return 'bg-yellow-100 text-yellow-800'
      case 'low':
        return 'bg-blue-100 text-blue-800'
      default:
        return 'bg-gray-100 text-gray-800'
    }
  }

  const formatDuration = (seconds: number) => {
    if (seconds < 60) return `${Math.round(seconds)}s`
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`
    return `${Math.round(seconds / 3600)}h`
  }

  const formatTimestamp = (timestamp: string) => {
    try {
      return new Date(timestamp).toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return timestamp
    }
  }

  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-lg font-semibold">Active Alerts</h3>
        <div className="animate-pulse space-y-2">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="h-12 rounded bg-gray-200" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h3 className="mb-2 text-lg font-semibold text-red-900">Active Alerts</h3>
        <p className="text-sm text-red-700">{error}</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <h3 className="mb-4 text-lg font-semibold">
        Active Alerts ({alerts.length})
      </h3>

      {alerts.length === 0 ? (
        <p className="text-sm text-gray-500">No active alerts</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b bg-gray-50">
              <tr>
                <th className="px-4 py-2 text-left font-semibold">Rule</th>
                <th className="px-4 py-2 text-left font-semibold">Metric</th>
                <th className="px-4 py-2 text-center font-semibold">Severity</th>
                <th className="px-4 py-2 text-right font-semibold">Value</th>
                <th className="px-4 py-2 text-right font-semibold">Threshold</th>
                <th className="px-4 py-2 text-right font-semibold">Duration</th>
                <th className="px-4 py-2 text-right font-semibold">Breaches</th>
              </tr>
            </thead>
            <tbody>
              {alerts.map((alert) => (
                <tr key={alert.id} className="border-b hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div>
                      <p className="font-medium">{alert.rule_name}</p>
                      <p className="text-xs text-gray-500">{alert.rollout_id}</p>
                    </div>
                  </td>
                  <td className="px-4 py-3 text-gray-700">{alert.metric}</td>
                  <td className="px-4 py-3 text-center">
                    <span className={`inline-block rounded px-2 py-1 text-xs font-semibold ${getSeverityColor(alert.severity)}`}>
                      {alert.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right font-mono">
                    {alert.current_value.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-gray-600">
                    {alert.threshold.toFixed(2)}
                  </td>
                  <td className="px-4 py-3 text-right text-gray-700">
                    {formatDuration(alert.duration_seconds)}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="font-semibold">
                      {alert.breach_count} ({alert.breach_percentage.toFixed(0)}%)
                    </span>
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
