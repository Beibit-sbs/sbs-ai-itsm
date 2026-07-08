import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import {
  decideApprovalRequest,
  dryRunAutomationRule,
  fetchApprovalRequests,
  fetchAutomationOverview,
  fetchAutomationRules,
  fetchAutomationRunLogs,
  fetchAutomationRuns,
  fetchRunbookExecutions,
  fetchRunbooks,
  fetchTickets,
  fetchTicketAutomationSuggestions,
  manualRunAutomationRule,
  patchAutomationRule,
  patchRunbookExecution,
  startRunbookExecution,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'

const tabs = [
  { key: 'rules', label: 'Правила' },
  { key: 'dryrun', label: 'Dry Run' },
  { key: 'runs', label: 'Прогоны' },
  { key: 'logs', label: 'Логи действий' },
  { key: 'runbooks', label: 'Runbooks' },
  { key: 'executions', label: 'Исполнения' },
  { key: 'approvals', label: 'Approval' },
  { key: 'suggestions', label: 'Suggestions' },
] as const

type TabKey = (typeof tabs)[number]['key']

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export default function AutomationPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabKey>('rules')
  const [selectedRuleId, setSelectedRuleId] = useState<string>('')
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [selectedRunbookId, setSelectedRunbookId] = useState<string>('')
  const [selectedTicketId, setSelectedTicketId] = useState<string>('')
  const [dryRunResult, setDryRunResult] = useState<string>('')
  const [manualRunResult, setManualRunResult] = useState<string>('')
  const [actionError, setActionError] = useState<string>('')

  const token = session?.access_token ?? ''

  const overviewQuery = useQuery({
    queryKey: ['automation-overview', token],
    queryFn: () => fetchAutomationOverview(token),
    enabled: Boolean(token),
  })
  const rulesQuery = useQuery({
    queryKey: ['automation-rules', token],
    queryFn: () => fetchAutomationRules(token),
    enabled: Boolean(token),
  })
  const runsQuery = useQuery({
    queryKey: ['automation-runs', token],
    queryFn: () => fetchAutomationRuns(token),
    enabled: Boolean(token),
  })
  const runbooksQuery = useQuery({
    queryKey: ['automation-runbooks', token],
    queryFn: () => fetchRunbooks(token),
    enabled: Boolean(token),
  })
  const executionsQuery = useQuery({
    queryKey: ['automation-executions', token],
    queryFn: () => fetchRunbookExecutions(token),
    enabled: Boolean(token),
  })
  const approvalsQuery = useQuery({
    queryKey: ['automation-approvals', token],
    queryFn: () => fetchApprovalRequests(token),
    enabled: Boolean(token),
  })
  const ticketsQuery = useQuery({
    queryKey: ['automation-tickets', token],
    queryFn: () => fetchTickets(token),
    enabled: Boolean(token),
  })
  const logsQuery = useQuery({
    queryKey: ['automation-run-logs', token, selectedRunId],
    queryFn: () => fetchAutomationRunLogs(token, selectedRunId),
    enabled: Boolean(token && selectedRunId),
  })
  const suggestionQuery = useQuery({
    queryKey: ['automation-suggestion', token, selectedTicketId],
    queryFn: () => fetchTicketAutomationSuggestions(token, selectedTicketId),
    enabled: Boolean(token && selectedTicketId),
  })

  const patchRuleMutation = useMutation({
    mutationFn: async (payload: { ruleId: string; isActive: boolean }) => patchAutomationRule(token, payload.ruleId, { is_active: payload.isActive }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['automation-rules'] })
      await queryClient.invalidateQueries({ queryKey: ['automation-overview'] })
    },
  })

  const dryRunMutation = useMutation({
    mutationFn: async (ruleId: string) => dryRunAutomationRule(token, ruleId, { trigger_type: 'manual_run', context: { entity_type: 'manual', entity_id: 'ui-dry-run' } }),
    onSuccess: (data) => {
      setActionError('')
      setDryRunResult(JSON.stringify(data, null, 2))
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Dry Run failed'),
  })

  const manualRunMutation = useMutation({
    mutationFn: async (ruleId: string) => manualRunAutomationRule(token, ruleId, { trigger_type: 'manual_run', context: { entity_type: 'manual', entity_id: 'ui-manual-run' } }),
    onSuccess: async (data) => {
      setActionError('')
      setManualRunResult(JSON.stringify(data, null, 2))
      await queryClient.invalidateQueries({ queryKey: ['automation-runs'] })
      await queryClient.invalidateQueries({ queryKey: ['automation-overview'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Manual Run failed'),
  })

  const startExecutionMutation = useMutation({
    mutationFn: async () => startRunbookExecution(token, selectedRunbookId, { ticket_id: selectedTicketId || null }),
    onSuccess: async () => {
      setActionError('')
      await queryClient.invalidateQueries({ queryKey: ['automation-executions'] })
      await queryClient.invalidateQueries({ queryKey: ['automation-overview'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Start execution failed'),
  })

  const updateExecutionMutation = useMutation({
    mutationFn: async (payload: { executionId: string; status?: string; current_step?: number }) =>
      patchRunbookExecution(token, payload.executionId, { status: payload.status, current_step: payload.current_step }),
    onSuccess: async () => {
      setActionError('')
      await queryClient.invalidateQueries({ queryKey: ['automation-executions'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Execution update failed'),
  })

  const decideApprovalMutation = useMutation({
    mutationFn: async (payload: { approvalId: string; decision: 'APPROVED' | 'REJECTED' }) => decideApprovalRequest(token, payload.approvalId, { decision: payload.decision }),
    onSuccess: async () => {
      setActionError('')
      await queryClient.invalidateQueries({ queryKey: ['automation-approvals'] })
      await queryClient.invalidateQueries({ queryKey: ['automation-overview'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Approval action failed'),
  })

  const runOptions = useMemo(() => runsQuery.data ?? [], [runsQuery.data])

  return (
    <AppShell title="Автоматизация" subtitle="WORKFLOW-AUTOMATION-001: правила, триггеры, runbooks, approval и demo-safe исполнение.">
      <section className="metric-grid dashboard-metrics">
        <article className="metric-card"><span>Активные правила</span><strong>{overviewQuery.data?.active_rules ?? 0}</strong><p>Доступные правила автоматизации.</p></article>
        <article className="metric-card"><span>Прогонов сегодня</span><strong>{overviewQuery.data?.runs_today ?? 0}</strong><p>Все automation-runs за текущий день.</p></article>
        <article className="metric-card"><span>Ошибки</span><strong>{overviewQuery.data?.failed_runs ?? 0}</strong><p>Failed/with-errors прогоны.</p></article>
        <article className="metric-card"><span>Success rate</span><strong>{`${overviewQuery.data?.automation_success_rate ?? 0}%`}</strong><p>Эффективность demo-safe выполнения.</p></article>
      </section>

      <section className="foundation-card admin-panel">
        <div>
          <p className="eyebrow">WORKFLOW AUTOMATION</p>
          <h2>Правила, runbooks и approval flow</h2>
        </div>
        <div className="notification-tabs">
          {tabs.map((tab) => (
            <button key={tab.key} type="button" className={activeTab === tab.key ? 'admin-tab-active' : 'ghost-button'} onClick={() => setActiveTab(tab.key)}>
              {tab.label}
            </button>
          ))}
        </div>
      </section>

      {actionError ? <section className="foundation-card"><p className="error-message">{actionError}</p></section> : null}

      {activeTab === 'rules' ? (
        <section className="ticket-table-wrap admin-panel">
          <table className="ticket-table">
            <thead><tr><th>Rule</th><th>Trigger</th><th>Priority</th><th>Status</th><th>Action</th></tr></thead>
            <tbody>
              {(rulesQuery.data ?? []).map((rule) => (
                <tr key={rule.id}>
                  <td><strong>{rule.name}</strong><p className="table-subtext">{rule.code}</p></td>
                  <td>{rule.trigger_type}</td>
                  <td>{rule.priority}</td>
                  <td>{rule.is_active ? 'ACTIVE' : 'INACTIVE'}</td>
                  <td>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => patchRuleMutation.mutate({ ruleId: rule.id, isActive: !rule.is_active })}
                    >
                      {rule.is_active ? 'Disable' : 'Enable'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {activeTab === 'dryrun' ? (
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">DRY RUN / MANUAL RUN</p>
            <h2>Проверка правил без side effects</h2>
            <label>
              <span>Rule</span>
              <select value={selectedRuleId} onChange={(event) => setSelectedRuleId(event.target.value)}>
                <option value="">Выберите правило</option>
                {(rulesQuery.data ?? []).map((rule) => <option key={rule.id} value={rule.id}>{rule.name}</option>)}
              </select>
            </label>
            <div className="analytics-actions">
              <button type="button" onClick={() => selectedRuleId && dryRunMutation.mutate(selectedRuleId)} disabled={!selectedRuleId || dryRunMutation.isPending}>Dry Run</button>
              <button type="button" onClick={() => selectedRuleId && manualRunMutation.mutate(selectedRuleId)} disabled={!selectedRuleId || manualRunMutation.isPending}>Manual Run</button>
            </div>
          </div>
          <div>
            <p className="eyebrow">RESULTS</p>
            <pre className="analytics-export-preview">{dryRunResult || manualRunResult || 'Результат dry-run/manual-run появится здесь.'}</pre>
          </div>
        </section>
      ) : null}

      {activeTab === 'runs' ? (
        <section className="ticket-table-wrap admin-panel">
          <table className="ticket-table">
            <thead><tr><th>Run</th><th>Trigger</th><th>Status</th><th>Started</th><th>Finished</th></tr></thead>
            <tbody>
              {(runsQuery.data ?? []).map((run) => (
                <tr key={run.id}>
                  <td>{run.id}</td>
                  <td>{run.trigger_type}</td>
                  <td>{run.status}</td>
                  <td>{formatDateTime(run.started_at)}</td>
                  <td>{formatDateTime(run.finished_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {activeTab === 'logs' ? (
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">ACTION LOGS</p>
            <h2>Логи действий по прогону</h2>
            <label>
              <span>Run</span>
              <select value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)}>
                <option value="">Выберите прогон</option>
                {runOptions.map((run) => <option key={run.id} value={run.id}>{run.id} · {run.status}</option>)}
              </select>
            </label>
          </div>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Action</th><th>Status</th><th>Created</th><th>Error</th></tr></thead>
              <tbody>
                {(logsQuery.data ?? []).map((log) => (
                  <tr key={log.id}>
                    <td>{log.action_type}</td>
                    <td>{log.status}</td>
                    <td>{formatDateTime(log.created_at)}</td>
                    <td>{log.error_message ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeTab === 'runbooks' ? (
        <section className="ticket-table-wrap admin-panel">
          <table className="ticket-table">
            <thead><tr><th>Runbook</th><th>Category</th><th>Severity</th><th>ETA</th></tr></thead>
            <tbody>
              {(runbooksQuery.data ?? []).map((runbook) => (
                <tr key={runbook.id}>
                  <td><strong>{runbook.title}</strong><p className="table-subtext">{runbook.code}</p></td>
                  <td>{runbook.category}</td>
                  <td>{runbook.severity}</td>
                  <td>{runbook.estimated_minutes} min</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {activeTab === 'executions' ? (
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">START EXECUTION</p>
            <h2>Запуск runbook исполнения</h2>
            <label>
              <span>Runbook</span>
              <select value={selectedRunbookId} onChange={(event) => setSelectedRunbookId(event.target.value)}>
                <option value="">Выберите runbook</option>
                {(runbooksQuery.data ?? []).map((runbook) => <option key={runbook.id} value={runbook.id}>{runbook.title}</option>)}
              </select>
            </label>
            <label>
              <span>Ticket (optional)</span>
              <select value={selectedTicketId} onChange={(event) => setSelectedTicketId(event.target.value)}>
                <option value="">Без тикета</option>
                {(ticketsQuery.data ?? []).map((ticket) => <option key={ticket.id} value={ticket.id}>{ticket.ticket_number} · {ticket.title}</option>)}
              </select>
            </label>
            <button type="button" onClick={() => startExecutionMutation.mutate()} disabled={!selectedRunbookId || startExecutionMutation.isPending}>Start Execution</button>
          </div>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>ID</th><th>Status</th><th>Step</th><th>Action</th></tr></thead>
              <tbody>
                {(executionsQuery.data ?? []).map((execution) => (
                  <tr key={execution.id}>
                    <td>{execution.id}</td>
                    <td>{execution.status}</td>
                    <td>{execution.current_step}</td>
                    <td>
                      <div className="analytics-actions">
                        <button
                          className="ghost-button"
                          type="button"
                          onClick={() => updateExecutionMutation.mutate({ executionId: execution.id, current_step: execution.current_step + 1 })}
                        >
                          Update Step
                        </button>
                        <button className="ghost-button" type="button" onClick={() => updateExecutionMutation.mutate({ executionId: execution.id, status: 'completed' })}>Mark Completed</button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeTab === 'approvals' ? (
        <section className="ticket-table-wrap admin-panel">
          <table className="ticket-table">
            <thead><tr><th>Title</th><th>Status</th><th>Requested By</th><th>Decision</th></tr></thead>
            <tbody>
              {(approvalsQuery.data ?? []).map((approval) => (
                <tr key={approval.id}>
                  <td>{approval.title}</td>
                  <td>{approval.status}</td>
                  <td>{approval.requested_by}</td>
                  <td>
                    <div className="analytics-actions">
                      <button type="button" onClick={() => decideApprovalMutation.mutate({ approvalId: approval.id, decision: 'APPROVED' })}>Approve</button>
                      <button type="button" className="ghost-button" onClick={() => decideApprovalMutation.mutate({ approvalId: approval.id, decision: 'REJECTED' })}>Reject</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}

      {activeTab === 'suggestions' ? (
        <section className="foundation-card dashboard-split admin-panel">
          <div>
            <p className="eyebrow">SUGGESTIONS</p>
            <h2>Рекомендованные runbooks для тикета</h2>
            <label>
              <span>Ticket</span>
              <select value={selectedTicketId} onChange={(event) => setSelectedTicketId(event.target.value)}>
                <option value="">Выберите тикет</option>
                {(ticketsQuery.data ?? []).map((ticket) => <option key={ticket.id} value={ticket.id}>{ticket.ticket_number} · {ticket.title}</option>)}
              </select>
            </label>
          </div>
          <div>
            <p className="eyebrow">RUNBOOKS</p>
            <div className="activity-list">
              {(suggestionQuery.data?.suggested_runbooks ?? []).map((item) => (
                <article className="activity-item" key={item.id}>
                  <header><strong>{item.title}</strong><span>{item.severity}</span></header>
                  <p>{item.category} · {item.estimated_minutes} min</p>
                </article>
              ))}
            </div>
            <p className="eyebrow analytics-subsection">MATCHED RULES</p>
            <pre className="analytics-export-preview">{JSON.stringify(suggestionQuery.data?.matched_rules ?? [], null, 2)}</pre>
          </div>
        </section>
      ) : null}
    </AppShell>
  )
}
