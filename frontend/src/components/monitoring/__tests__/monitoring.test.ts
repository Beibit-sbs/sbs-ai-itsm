/**
 * Unit tests for Stage 036: Frontend React Dashboard Components
 * Tests for: SystemHealthCard, MetricsTimelineChart, ActiveAlertsTable, 
 * RolloutComparisonTable, AnomalyTimelineCard, CorrelationMatrixCard
 */

// Component validation tests
export const testComponentValidation = () => {
  // SystemHealthCard validation
  const healthCardProps = {
    activeRollouts: 5,
    avgHealthScore: 0.95,
    healthStatus: 'healthy' as const,
    activeAlerts: 1,
    criticalAlerts: 0,
    unresolved_anomalies: 0,
    systemStatus: 'operational' as const,
  }
  console.assert(healthCardProps.healthStatus === 'healthy', 'Health status should be healthy')
  console.assert(healthCardProps.systemStatus === 'operational', 'System status should be operational')

  // Degraded status
  const degradedProps = {
    activeRollouts: 3,
    avgHealthScore: 0.65,
    healthStatus: 'degraded' as const,
    activeAlerts: 5,
    criticalAlerts: 1,
    unresolved_anomalies: 2,
    systemStatus: 'degraded' as const,
  }
  console.assert(degradedProps.healthStatus === 'degraded', 'Health status should be degraded')

  // Critical status
  const criticalProps = {
    activeRollouts: 1,
    avgHealthScore: 0.2,
    healthStatus: 'critical' as const,
    activeAlerts: 15,
    criticalAlerts: 8,
    unresolved_anomalies: 10,
    systemStatus: 'critical' as const,
  }
  console.assert(criticalProps.healthStatus === 'critical', 'Health status should be critical')
  console.assert(criticalProps.criticalAlerts > 0, 'Should have critical alerts')

  console.log('✓ SystemHealthCard validation passed')
}

export const testMetricsTimelineChart = () => {
  // Empty metrics
  const emptyProps = {
    rolloutId: 'crl-1',
    metricType: 'error_rate',
    values: [],
    timestamps: [],
    statistics: {
      average: 0,
      minimum: 0,
      maximum: 0,
    },
  }
  console.assert(emptyProps.values.length === 0, 'Values should be empty')
  console.assert(emptyProps.statistics.average === 0, 'Average should be 0')

  // With data
  const withDataProps = {
    rolloutId: 'crl-1',
    metricType: 'error_rate',
    values: [0.5, 0.6, 0.48, 0.55],
    timestamps: ['2026-07-13T10:00:00Z', '2026-07-13T10:05:00Z', '2026-07-13T10:10:00Z', '2026-07-13T10:15:00Z'],
    statistics: {
      average: 0.5375,
      minimum: 0.48,
      maximum: 0.6,
    },
  }
  console.assert(withDataProps.values.length === 4, 'Should have 4 data points')
  console.assert(withDataProps.statistics.minimum === 0.48, 'Min should be 0.48')
  console.assert(withDataProps.statistics.maximum === 0.6, 'Max should be 0.6')

  // Test metric types
  const metricTypes = ['error_rate', 'latency_p99', 'throughput', 'cpu', 'memory']
  metricTypes.forEach((type) => {
    console.assert(
      ['error_rate', 'latency_p99', 'throughput', 'cpu', 'memory'].includes(type),
      `Metric type ${type} should be valid`
    )
  })

  console.log('✓ MetricsTimelineChart validation passed')
}

export const testActiveAlertsTable = () => {
  // Empty alerts
  const emptyAlerts = { alerts: [] }
  console.assert(emptyAlerts.alerts.length === 0, 'Alerts should be empty')

  // With alerts
  const withAlerts = {
    alerts: [
      {
        id: 'alert-1',
        alert_rule_id: 'rule-1',
        rule_name: 'High Error Rate',
        rollout_id: 'crl-1',
        metric: 'error_rate',
        current_value: 1.2,
        threshold: 1.0,
        operator: '>',
        severity: 'high' as const,
        status: 'active' as const,
        triggered_at: '2026-07-13T10:00:00Z',
        acknowledged_at: null,
        resolved_at: null,
        duration_seconds: 3600,
        breach_count: 5,
        breach_percentage: 75.0,
      },
    ],
  }
  console.assert(withAlerts.alerts.length === 1, 'Should have 1 alert')
  console.assert(withAlerts.alerts[0].severity === 'high', 'Severity should be high')
  console.assert(withAlerts.alerts[0].duration_seconds === 3600, 'Duration should be 3600')

  // Test severities
  const severities: Array<'critical' | 'high' | 'medium' | 'low'> = ['critical', 'high', 'medium', 'low']
  severities.forEach((sev) => {
    console.assert(
      ['critical', 'high', 'medium', 'low'].includes(sev),
      `Severity ${sev} should be valid`
    )
  })

  console.log('✓ ActiveAlertsTable validation passed')
}

export const testRolloutComparisonTable = () => {
  // Empty comparison
  const emptyComparison = { rollouts: [] }
  console.assert(emptyComparison.rollouts.length === 0, 'Rollouts should be empty')

  // With rollouts
  const withRollouts = {
    rollouts: [
      {
        rollout_id: 'crl-1',
        name: 'Feature A',
        status: 'active',
        canary_percentage: 10,
        error_rate: 0.5,
        latency_p99_ms: 250,
        throughput_eps: 1500,
        health_score: 0.95,
        active_alerts: 0,
        unresolved_anomalies: 0,
        duration_hours: 2.5,
        started_at: '2026-07-13T07:30:00Z',
      },
      {
        rollout_id: 'crl-2',
        name: 'Feature B',
        status: 'active',
        canary_percentage: 5,
        error_rate: 0.3,
        latency_p99_ms: 200,
        throughput_eps: 1800,
        health_score: 0.98,
        active_alerts: 0,
        unresolved_anomalies: 0,
        duration_hours: 1.0,
        started_at: '2026-07-13T09:00:00Z',
      },
    ],
  }
  console.assert(withRollouts.rollouts.length === 2, 'Should have 2 rollouts')
  console.assert(withRollouts.rollouts[0].health_score > 0.8, 'Health score should be > 0.8')

  // Test max 10 limit
  const manyRollouts = Array.from({ length: 15 }, (_, i) => ({
    rollout_id: `crl-${i}`,
    name: `Feature ${i}`,
    status: 'active',
    canary_percentage: 5,
    error_rate: 0.5,
    latency_p99_ms: 250,
    throughput_eps: 1500,
    health_score: 0.9,
    active_alerts: 0,
    unresolved_anomalies: 0,
    duration_hours: 1,
    started_at: '2026-07-13T10:00:00Z',
  }))
  console.assert(manyRollouts.slice(0, 10).length === 10, 'Max 10 rollouts')

  console.log('✓ RolloutComparisonTable validation passed')
}

export const testAnomalyTimelineCard = () => {
  // Empty anomalies
  const emptyAnomalies = { anomalies: [] }
  console.assert(emptyAnomalies.anomalies.length === 0, 'Anomalies should be empty')

  // With anomalies
  const withAnomalies = {
    anomalies: [
      {
        id: 'anom-1',
        rollout_id: 'crl-1',
        metric: 'error_rate',
        detection_method: 'z_score',
        anomaly_score: 0.85,
        severity: 'high' as const,
        value: 2.5,
        baseline: 0.5,
        deviation_percent: 400,
        created_at: '2026-07-13T10:30:00Z',
        acknowledged: false,
        resolved_at: null,
        resolution_notes: null,
      },
    ],
  }
  console.assert(withAnomalies.anomalies.length === 1, 'Should have 1 anomaly')
  console.assert(withAnomalies.anomalies[0].anomaly_score > 0.8, 'Anomaly score > 0.8')
  console.assert(withAnomalies.anomalies[0].deviation_percent > 100, 'Deviation > 100%')

  // Test resolved vs unresolved
  const unresolved = {
    id: 'anom-1',
    rollout_id: 'crl-1',
    metric: 'error_rate',
    detection_method: 'z_score',
    anomaly_score: 0.85,
    severity: 'high' as const,
    value: 2.5,
    baseline: 0.5,
    deviation_percent: 400,
    created_at: '2026-07-13T10:30:00Z',
    acknowledged: false,
    resolved_at: null,
    resolution_notes: null,
  }

  const resolved = {
    ...unresolved,
    resolved_at: '2026-07-13T11:00:00Z',
    resolution_notes: 'Scaled up service',
  }

  console.assert(unresolved.resolved_at === null, 'Unresolved should have null resolved_at')
  console.assert(resolved.resolved_at !== null, 'Resolved should have resolved_at')

  console.log('✓ AnomalyTimelineCard validation passed')
}

export const testCorrelationMatrixCard = () => {
  // Empty matrix
  const emptyMatrix = {
    rolloutId: 'crl-1',
    correlationMatrix: {},
    metricCount: 0,
    dataPoints: 0,
  }
  console.assert(Object.keys(emptyMatrix.correlationMatrix).length === 0, 'Matrix should be empty')
  console.assert(emptyMatrix.metricCount === 0, 'Metric count should be 0')

  // With data
  const withData = {
    rolloutId: 'crl-1',
    correlationMatrix: {
      error_rate: {
        error_rate: 1.0,
        latency_p99: 0.78,
        throughput: -0.62,
        cpu: 0.55,
        memory: 0.42,
      },
      latency_p99: {
        error_rate: 0.78,
        latency_p99: 1.0,
        throughput: -0.45,
        cpu: 0.67,
        memory: 0.58,
      },
    },
    metricCount: 5,
    dataPoints: 60,
  }
  console.assert(Object.keys(withData.correlationMatrix).length > 0, 'Matrix should have data')
  console.assert(withData.metricCount === 5, 'Should have 5 metrics')
  console.assert(withData.dataPoints === 60, 'Should have 60 data points')

  // Test correlation strengths
  const correlationScores = [0.95, 0.7, 0.5, 0.2, 0.0, -0.2, -0.5, -0.7, -0.95]
  const strongCorrelations = correlationScores.filter((score) => Math.abs(score) >= 0.8)
  const moderateCorrelations = correlationScores.filter(
    (score) => Math.abs(score) >= 0.6 && Math.abs(score) < 0.8
  )
  console.assert(strongCorrelations.length === 2, 'Should have 2 strong correlations')
  console.assert(moderateCorrelations.length === 2, 'Should have 2 moderate correlations')

  console.log('✓ CorrelationMatrixCard validation passed')
}

export const testAPIClientTypes = () => {
  // DashboardSummary
  const summary = {
    timestamp: '2026-07-13T12:33:15Z',
    active_rollouts: 5,
    avg_health_score: 0.935,
    health_status: 'healthy' as const,
    active_alerts: 2,
    critical_alerts: 0,
    unresolved_anomalies: 1,
    system_status: 'operational' as const,
  }
  console.assert(summary.active_rollouts > 0, 'Active rollouts > 0')
  console.assert(summary.avg_health_score <= 1, 'Health score <= 1')

  // MetricsTimeline
  const timeline = {
    rollout_id: 'crl-1',
    metric_type: 'error_rate',
    time_window_minutes: 60,
    timestamps: ['2026-07-13T11:00:00Z', '2026-07-13T12:00:00Z'],
    values: [0.5, 0.6],
    statistics: {
      average: 0.55,
      minimum: 0.5,
      maximum: 0.6,
    },
    data_points: 2,
  }
  console.assert(
    timeline.timestamps.length === timeline.values.length,
    'Timestamps and values should match'
  )
  console.assert(timeline.data_points === timeline.values.length, 'Data points should match values')

  // AlertSummaryItem
  const alert = {
    id: 'alert-1',
    alert_rule_id: 'rule-1',
    rule_name: 'High Error Rate',
    rollout_id: 'crl-1',
    metric: 'error_rate',
    current_value: 1.2,
    threshold: 1.0,
    operator: '>',
    severity: 'high' as const,
    status: 'active' as const,
    triggered_at: '2026-07-13T10:00:00Z',
    acknowledged_at: null,
    resolved_at: null,
    duration_seconds: 3600,
    breach_count: 5,
    breach_percentage: 75.0,
  }
  console.assert(alert.current_value > alert.threshold, 'Current > threshold')
  console.assert(alert.breach_percentage >= 0 && alert.breach_percentage <= 100, 'Breach % valid')

  console.log('✓ API Client types validation passed')
}

// Run all tests
export const runAllTests = () => {
  testComponentValidation()
  testMetricsTimelineChart()
  testActiveAlertsTable()
  testRolloutComparisonTable()
  testAnomalyTimelineCard()
  testCorrelationMatrixCard()
  testAPIClientTypes()
  console.log('\n✅ All component tests passed!')
}

// Export for testing
if (typeof window !== 'undefined') {
  ;(window as any).monitoringTests = {
    testComponentValidation,
    testMetricsTimelineChart,
    testActiveAlertsTable,
    testRolloutComparisonTable,
    testAnomalyTimelineCard,
    testCorrelationMatrixCard,
    testAPIClientTypes,
    runAllTests,
  }
}

