/**
 * MetricsTimelineChart - Displays time-series metrics as a line chart
 * Shows metric values over time with statistics (min, max, avg)
 */

import { useMemo, type ReactNode } from 'react'
import { localizeTree } from '../../experience/LocalizedContent'
import { useTenantExperience } from '../../experience/TenantExperienceContext'

interface MetricsTimelineProps {
  rolloutId: string
  metricType: string
  values: number[]
  timestamps: string[]
  statistics: {
    average: number
    minimum: number
    maximum: number
  }
  isLoading?: boolean
  error?: string
}

export default function MetricsTimelineChart({
  rolloutId,
  metricType,
  values,
  timestamps,
  statistics,
  isLoading = false,
  error,
}: MetricsTimelineProps) {
  const { formatDateTime, translate } = useTenantExperience()
  const localize = (node: ReactNode) => localizeTree(node, translate)
  const getMetricLabel = (type: string) => {
    switch (type) {
      case 'error_rate':
        return translate('Error Rate')
      case 'latency_p99':
        return translate('Latency (P99)')
      case 'throughput':
        return translate('Throughput')
      case 'cpu':
        return translate('CPU Usage')
      case 'memory':
        return translate('Memory Usage')
      default:
        return type
    }
  }

  const getMetricUnit = (type: string) => {
    switch (type) {
      case 'error_rate':
        return '%'
      case 'latency_p99':
        return translate('ms')
      case 'throughput':
        return translate('req/s')
      case 'cpu':
      case 'memory':
        return '%'
      default:
        return ''
    }
  }

  const chartData = useMemo(() => {
    if (values.length === 0) return null

    const minVal = Math.min(...values)
    const maxVal = Math.max(...values)
    const range = maxVal - minVal || 1
    const chartHeight = 200

    return values.map((value, idx) => ({
      height: ((value - minVal) / range) * chartHeight,
      value,
      timestamp: timestamps[idx] || '',
    }))
  }, [values, timestamps])

  if (isLoading) {
    return localize(
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-lg font-semibold">{getMetricLabel(metricType)}</h3>
        <div className="animate-pulse space-y-2">
          <div className="h-40 rounded bg-gray-200" />
        </div>
      </div>
    )
  }

  if (error) {
    return localize(
      <div className="rounded-lg border border-red-200 bg-red-50 p-6">
        <h3 className="mb-2 text-lg font-semibold text-red-900">{getMetricLabel(metricType)}</h3>
        <p className="text-sm text-red-700">{error}</p>
      </div>
    )
  }

  if (!chartData || chartData.length === 0) {
    return localize(
      <div className="rounded-lg border border-gray-200 bg-white p-6">
        <h3 className="mb-4 text-lg font-semibold">{getMetricLabel(metricType)}</h3>
        <p className="text-sm text-gray-500">No data available</p>
      </div>
    )
  }

  return localize(
    <div className="rounded-lg border border-gray-200 bg-white p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg font-semibold">{getMetricLabel(metricType)}</h3>
        <span className="text-xs text-gray-500">Rollout: {rolloutId}</span>
      </div>

      {/* Mini Chart */}
      <div className="mb-4 flex items-end space-x-1" style={{ height: '200px' }}>
        {chartData.map((point, idx) => (
          <div
            key={idx}
            className="flex-1 rounded-t bg-blue-400 hover:bg-blue-600"
            style={{ height: `${Math.max(point.height, 2)}px` }}
            title={`${point.value.toFixed(2)} ${translate('at')} ${formatDateTime(point.timestamp)}`}
          />
        ))}
      </div>

      {/* Statistics */}
      <div className="grid grid-cols-3 gap-4 border-t pt-4">
        <div>
          <p className="text-xs text-gray-600">Minimum</p>
          <p className="font-mono font-semibold">
            {statistics.minimum.toFixed(2)}{getMetricUnit(metricType)}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-600">Average</p>
          <p className="font-mono font-semibold">
            {statistics.average.toFixed(2)}{getMetricUnit(metricType)}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-600">Maximum</p>
          <p className="font-mono font-semibold">
            {statistics.maximum.toFixed(2)}{getMetricUnit(metricType)}
          </p>
        </div>
      </div>
    </div>
  )
}
