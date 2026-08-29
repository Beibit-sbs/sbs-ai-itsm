/**
 * SystemHealthCard - Displays overall system health summary
 * Shows active rollouts, health score, alert counts, and anomalies
 */

import type { ReactNode } from 'react'
import { localizeTree } from '../../experience/LocalizedContent'
import { useTenantExperience } from '../../experience/TenantExperienceContext'

interface SystemHealthProps {
  activeRollouts: number
  avgHealthScore: number
  healthStatus: 'healthy' | 'degraded' | 'critical' | 'unknown'
  activeAlerts: number
  criticalAlerts: number
  unresolved_anomalies: number
  systemStatus: 'operational' | 'degraded' | 'critical'
}

export default function SystemHealthCard({
  activeRollouts,
  avgHealthScore,
  healthStatus,
  activeAlerts,
  criticalAlerts,
  unresolved_anomalies,
  systemStatus,
}: SystemHealthProps) {
  const { translate } = useTenantExperience()
  const localize = (node: ReactNode) => localizeTree(node, translate)
  const getHealthColor = (status: string) => {
    switch (status) {
      case 'healthy':
        return 'bg-green-50 border-green-200'
      case 'degraded':
        return 'bg-yellow-50 border-yellow-200'
      case 'critical':
        return 'bg-red-50 border-red-200'
      default:
        return 'bg-gray-50 border-gray-200'
    }
  }

  const getHealthTextColor = (status: string) => {
    switch (status) {
      case 'healthy':
        return 'text-green-700'
      case 'degraded':
        return 'text-yellow-700'
      case 'critical':
        return 'text-red-700'
      default:
        return 'text-gray-700'
    }
  }

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'operational':
        return translate('✓ Operational')
      case 'degraded':
        return translate('⚠ Degraded')
      case 'critical':
        return translate('✕ Critical')
      default:
        return status
    }
  }

  return localize(
    <div className={`rounded-lg border-2 p-6 ${getHealthColor(healthStatus)}`}>
      <h2 className="mb-4 text-2xl font-bold">System Health Overview</h2>
      
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div className="rounded bg-white p-4">
          <p className="text-sm text-gray-600">Active Rollouts</p>
          <p className="mt-2 text-3xl font-bold text-gray-900">{activeRollouts}</p>
        </div>
        
        <div className="rounded bg-white p-4">
          <p className="text-sm text-gray-600">Health Score</p>
          <p className={`mt-2 text-3xl font-bold ${getHealthTextColor(healthStatus)}`}>
            {(avgHealthScore * 100).toFixed(0)}%
          </p>
        </div>
        
        <div className="rounded bg-white p-4">
          <p className="text-sm text-gray-600">Active Alerts</p>
          <p className="mt-2 text-3xl font-bold text-orange-600">{activeAlerts}</p>
          {criticalAlerts > 0 && (
            <p className="mt-1 text-xs text-red-600">{criticalAlerts} critical</p>
          )}
        </div>
        
        <div className="rounded bg-white p-4">
          <p className="text-sm text-gray-600">Unresolved Anomalies</p>
          <p className="mt-2 text-3xl font-bold text-red-600">{unresolved_anomalies}</p>
        </div>
      </div>
      
      <div className="mt-4 flex items-center justify-between border-t pt-4">
        <p className="text-sm font-medium text-gray-700">System Status:</p>
        <span className={`rounded-full px-4 py-1 text-sm font-semibold ${
          systemStatus === 'operational' ? 'bg-green-100 text-green-800' :
          systemStatus === 'degraded' ? 'bg-yellow-100 text-yellow-800' :
          'bg-red-100 text-red-800'
        }`}>
          {getStatusBadge(systemStatus)}
        </span>
      </div>
    </div>
  )
}
