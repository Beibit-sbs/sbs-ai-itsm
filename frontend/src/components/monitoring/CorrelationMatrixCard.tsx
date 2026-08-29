/**
 * CorrelationMatrixCard - Displays metric correlation heatmap
 * Shows Pearson correlation coefficients between metrics for root cause analysis
 */

import { useMemo, type ReactNode } from 'react'
import { localizeTree } from '../../experience/LocalizedContent'
import { useTenantExperience } from '../../experience/TenantExperienceContext'

interface CorrelationMatrixCardProps {
  rolloutId: string
  correlationMatrix: Record<string, Record<string, number>>
  metricCount: number
  dataPoints: number
  isLoading?: boolean
  error?: string
}

export default function CorrelationMatrixCard({
  rolloutId,
  correlationMatrix,
  metricCount,
  dataPoints,
  isLoading = false,
  error,
}: CorrelationMatrixCardProps) {
  const { translate } = useTenantExperience()
  const localize = (node: ReactNode) => localizeTree(node, translate)
  const metrics = useMemo(() => {
    return Object.keys(correlationMatrix).sort()
  }, [correlationMatrix])

  const getCorrelationColor = (value: number) => {
    const absValue = Math.abs(value)
    if (absValue >= 0.8) return 'bg-red-500'
    if (absValue >= 0.6) return 'bg-orange-400'
    if (absValue >= 0.4) return 'bg-yellow-300'
    if (absValue >= 0.2) return 'bg-blue-300'
    return 'bg-gray-200'
  }

  const getCorrelationTextColor = (value: number) => {
    const absValue = Math.abs(value)
    if (absValue >= 0.8) return 'text-white'
    if (absValue >= 0.6) return 'text-white'
    return 'text-gray-700'
  }

  const getCorrelationLabel = (value: number) => {
    if (value > 0.5) return translate('Strong Positive')
    if (value > 0) return translate('Weak Positive')
    if (value < -0.5) return translate('Strong Negative')
    if (value < 0) return translate('Weak Negative')
    return translate('No Correlation')
  }

  const getMetricLabel = (metric: string) => {
    const labels: Record<string, string> = {
      error_rate: 'Error Rate',
      latency_p99: 'Latency P99',
      throughput: 'Throughput',
      cpu: 'CPU',
      memory: 'Memory',
    }
    return translate(labels[metric] || metric)
  }

  if (isLoading) {
    return localize(
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-lg font-semibold">Metric Correlation Matrix</h3>
        <div className="animate-pulse space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-8 rounded bg-gray-200" />
          ))}
        </div>
      </div>
    )
  }

  if (error) {
    return localize(
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h3 className="mb-2 text-lg font-semibold text-red-900">Metric Correlation Matrix</h3>
        <p className="text-sm text-red-700">{error}</p>
      </div>
    )
  }

  return localize(
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">Metric Correlation Matrix</h3>
        <span className="text-xs text-gray-500">
          {metricCount} metrics • {dataPoints} data points
        </span>
      </div>

      {metricCount === 0 ? (
        <p className="text-sm text-gray-500">No correlation data available</p>
      ) : (
        <div className="space-y-4">
          {/* Heatmap Matrix */}
          <div className="overflow-x-auto">
            <table className="text-xs">
              <thead>
                <tr>
                  <th className="px-2 py-1 text-left" />
                  {metrics.map((metric) => (
                    <th key={metric} className="px-2 py-1 text-center">
                      {getMetricLabel(metric).slice(0, 6)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {metrics.map((metric1) => (
                  <tr key={metric1}>
                    <td className="px-2 py-1 text-right font-medium">
                      {getMetricLabel(metric1).slice(0, 6)}
                    </td>
                    {metrics.map((metric2) => {
                      const value = correlationMatrix[metric1]?.[metric2] ?? 0
                      return (
                        <td
                          key={`${metric1}-${metric2}`}
                          className={`${getCorrelationColor(value)} ${getCorrelationTextColor(value)} relative px-2 py-1 text-center font-semibold`}
                          title={`${getMetricLabel(metric1)} ${translate('vs')} ${getMetricLabel(metric2)}: ${value.toFixed(2)} - ${getCorrelationLabel(value)}`}
                        >
                          {value.toFixed(2)}
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Legend */}
          <div className="border-t pt-4">
            <p className="mb-2 text-xs font-semibold text-gray-700">Correlation Strength:</p>
            <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-3">
              <div className="flex items-center space-x-2">
                <div className="h-3 w-3 rounded bg-red-500" />
                <span>Strong (±0.8-1.0)</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="h-3 w-3 rounded bg-orange-400" />
                <span>Moderate (±0.6-0.8)</span>
              </div>
              <div className="flex items-center space-x-2">
                <div className="h-3 w-3 rounded bg-yellow-300" />
                <span>Weak (±0.4-0.6)</span>
              </div>
            </div>
          </div>

          {/* Interpretation Help */}
          <div className="rounded bg-blue-50 p-3 text-xs text-blue-900">
            <p className="font-semibold">Interpretation:</p>
            <p className="mt-1">
              • Positive values (red) = metrics move together (e.g., CPU ↑ → Error Rate ↑)
            </p>
            <p>• Negative values (blue) = inverse relationship (e.g., Throughput ↓ → Errors ↑)</p>
            <p>• Use for root cause analysis: high error correlations suggest the cause</p>
          </div>
        </div>
      )}
    </div>
  )
}
