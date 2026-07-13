/**
 * AnomalyTimelineCard - Displays anomaly detection events over time
 * Shows anomalies with severity, scores, and resolution status
 */

import type { AnomalyTimelineItem } from '../../api/client'

interface AnomalyTimelineCardProps {
  anomalies: AnomalyTimelineItem[]
  isLoading?: boolean
  error?: string
}

export default function AnomalyTimelineCard({
  anomalies,
  isLoading = false,
  error,
}: AnomalyTimelineCardProps) {
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

  const getAnomalyScoreColor = (score: number) => {
    if (score >= 0.8) return 'text-red-700 font-semibold'
    if (score >= 0.6) return 'text-orange-700 font-semibold'
    return 'text-yellow-700 font-semibold'
  }

  const formatTimestamp = (timestamp: string) => {
    try {
      const date = new Date(timestamp)
      return date.toLocaleString('en-US', {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    } catch {
      return timestamp
    }
  }

  const formatDeviation = (percent: number) => {
    return percent > 0 ? `+${percent.toFixed(0)}%` : `${percent.toFixed(0)}%`
  }

  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-lg font-semibold">Anomaly Timeline</h3>
        <div className="animate-pulse space-y-2">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-12 rounded bg-gray-200" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h3 className="mb-2 text-lg font-semibold text-red-900">Anomaly Timeline</h3>
        <p className="text-sm text-red-700">{error}</p>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <h3 className="mb-4 text-lg font-semibold">
        Anomaly Timeline ({anomalies.length})
      </h3>

      {anomalies.length === 0 ? (
        <p className="text-sm text-gray-500">No anomalies detected</p>
      ) : (
        <div className="space-y-3">
          {anomalies.map((anomaly) => (
            <div
              key={anomaly.id}
              className="flex items-start space-x-4 rounded-lg border border-gray-200 p-4 hover:bg-gray-50"
            >
              {/* Timeline indicator */}
              <div className="flex flex-col items-center pt-1">
                <div className={`h-3 w-3 rounded-full ${
                  anomaly.severity === 'critical' ? 'bg-red-600' :
                  anomaly.severity === 'high' ? 'bg-orange-600' :
                  anomaly.severity === 'medium' ? 'bg-yellow-600' :
                  'bg-blue-600'
                }`} />
                <div className="h-8 w-0.5 bg-gray-300" />
              </div>

              {/* Anomaly details */}
              <div className="flex-1">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">
                      {anomaly.metric} anomaly on {anomaly.rollout_id}
                    </p>
                    <p className="text-xs text-gray-500">
                      {anomaly.detection_method} • {formatTimestamp(anomaly.created_at)}
                    </p>
                  </div>
                  <span className={`inline-block rounded px-2 py-1 text-xs font-semibold ${getSeverityColor(anomaly.severity)}`}>
                    {anomaly.severity}
                  </span>
                </div>

                {/* Metric values */}
                <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                  <div>
                    <span className="text-gray-600">Current:</span>{' '}
                    <span className="font-mono font-semibold">{anomaly.value.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Baseline:</span>{' '}
                    <span className="font-mono font-semibold">{anomaly.baseline.toFixed(2)}</span>
                  </div>
                  <div>
                    <span className="text-gray-600">Deviation:</span>{' '}
                    <span className={`font-mono font-semibold ${getAnomalyScoreColor(anomaly.anomaly_score)}`}>
                      {formatDeviation(anomaly.deviation_percent)}
                    </span>
                  </div>
                </div>

                {/* Anomaly score */}
                <div className="mt-2 flex items-center space-x-2">
                  <div className="flex-1 rounded-full bg-gray-200">
                    <div
                      className="rounded-full bg-gradient-to-r from-blue-400 to-red-400 py-1"
                      style={{ width: `${anomaly.anomaly_score * 100}%` }}
                    />
                  </div>
                  <span className={`text-xs font-semibold ${getAnomalyScoreColor(anomaly.anomaly_score)}`}>
                    {(anomaly.anomaly_score * 100).toFixed(0)}%
                  </span>
                </div>

                {/* Status */}
                {anomaly.resolved_at && (
                  <p className="mt-2 text-xs text-green-600">✓ Resolved at {formatTimestamp(anomaly.resolved_at)}</p>
                )}
                {anomaly.acknowledged && !anomaly.resolved_at && (
                  <p className="mt-2 text-xs text-yellow-600">⚠ Acknowledged</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
