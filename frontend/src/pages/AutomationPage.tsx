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
  retryAutomationExecution,
  patchRunbookExecution,
  startRunbookExecution,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'

const tabs = [
  { key: 'overview', label: 'Overview' },
  { key: 'rules', label: 'Rules' },
  { key: 'executions', label: 'Executions' },
  { key: 'runbooks', label: 'Runbooks' },
  { key: 'approvals', label: 'Approvals' },
  { key: 'templates', label: 'Templates / Examples' },
] as const

type TabKey = (typeof tabs)[number]['key']

function formatDateTime(value: string | null) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export default function AutomationPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [activeTab, setActiveTab] = useState<TabKey>('overview')
  const [selectedRuleId, setSelectedRuleId] = useState<string>('')
  const [selectedRunId, setSelectedRunId] = useState<string>('')
  const [selectedExecutionId, setSelectedExecutionId] = useState<string>('')
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

  const retryExecutionMutation = useMutation({
    mutationFn: async (executionId: string) => retryAutomationExecution(token, executionId),
    onSuccess: async () => {
      setActionError('')
      await queryClient.invalidateQueries({ queryKey: ['automation-runs'] })
      await queryClient.invalidateQueries({ queryKey: ['automation-overview'] })
    },
    onError: (error) => setActionError(error instanceof Error ? error.message : 'Retry failed'),
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
    <AppShell title="Автоматизация" subtitle="Правила, runbooks, approvals и журнал исполнения автоматических процессов ITSM.">
      <nav className="module-subnav" aria-label="Automation navigation">
        {tabs.map((tab) => (
          <button key={tab.key} type="button" className={`module-subnav-tab ${activeTab === tab.key ? 'active' : ''}`} onClick={() => setActiveTab(tab.key)}>
            {tab.label}
          </button>
        ))}
      </nav>

      {actionError ? <p className="error-state">{actionError}</p> : null}

      <section className="module-content">
      {activeTab === 'overview' ? (
        <>
          <section className="module-overview-grid">
            <article className="metric-card"><span>Активные правила</span><strong>{overviewQuery.data?.active_rules ?? 0}</strong><p>Доступные правила автоматизации.</p></article>
            <article className="metric-card"><span>Прогонов сегодня</span><strong>{overviewQuery.data?.runs_today ?? 0}</strong><p>Все прогоны за текущий день.</p></article>
            <article className="metric-card"><span>Ошибки</span><strong>{overviewQuery.data?.failed_runs ?? 0}</strong><p>Ошибки и прогоны с ошибками.</p></article>
            <article className="metric-card"><span>Успешность</span><strong>{`${overviewQuery.data?.automation_success_rate ?? 0}%`}</strong><p>Эффективность исполнения.</p></article>
          </section>

          <section className="foundation-card dashboard-split">
            <div>
              <p className="eyebrow">WORKFLOW AUTOMATION</p>
              <h2>Обзор автоматизации</h2>
              <div className="mini-bars">
                <div className="mini-bar-row"><span>Pending approvals</span><strong>{overviewQuery.data?.pending_approvals ?? 0}</strong></div>
                <div className="mini-bar-row"><span>Runbooks</span><strong>{overviewQuery.data?.runbooks_available ?? 0}</strong></div>
                <div className="mini-bar-row"><span>Исполнения</span><strong>{(executionsQuery.data ?? []).length}</strong></div>
              </div>
            </div>
            <div>
              <p className="eyebrow">ПОСЛЕДНИЕ ПРОГОНЫ</p>
              <div className="activity-list">
                {(runsQuery.data ?? []).slice(0, 6).map((run) => (
                  <article className="activity-item" key={run.id}>
                    <header><strong>{run.trigger_type}</strong><span>{run.status === 'with-errors' ? 'с ошибками' : run.status}</span></header>
                    <small>{formatDateTime(run.started_at)}</small>
                  </article>
                ))}
                {!runsQuery.isPending && (runsQuery.data ?? []).length === 0 ? <p className="empty-state">Данных пока нет. Запустите тестовый прогон правила.</p> : null}
              </div>
            </div>
          </section>
        </>
      ) : null}

      {activeTab === 'rules' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Правила автоматизации</h3><p className="section-subtitle">Управление активностью и приоритетом правил.</p></header>
          <div className="analytics-actions" style={{ marginBottom: 12 }}>
            <select value={selectedRuleId} onChange={(event) => setSelectedRuleId(event.target.value)}>
              <option value="">Выберите правило</option>
              {(rulesQuery.data ?? []).map((rule) => <option key={rule.id} value={rule.id}>{rule.name}</option>)}
            </select>
            <button type="button" onClick={() => selectedRuleId && dryRunMutation.mutate(selectedRuleId)} disabled={!selectedRuleId || dryRunMutation.isPending}>Dry-run</button>
            <button type="button" onClick={() => selectedRuleId && manualRunMutation.mutate(selectedRuleId)} disabled={!selectedRuleId || manualRunMutation.isPending}>Manual run</button>
          </div>
          <div className="ticket-table-wrap">
          <table className="ticket-table">
            <thead><tr><th>Правило</th><th>Триггер</th><th>Приоритет</th><th>Статус</th><th>Действие</th></tr></thead>
            <tbody>
              {rulesQuery.isPending ? <tr><td colSpan={5}><p className="state-panel state-panel-loading">Загрузка правил…</p></td></tr> : null}
              {!rulesQuery.isPending && (rulesQuery.data ?? []).length === 0 ? <tr><td colSpan={5}><p className="state-panel state-panel-empty">Правила автоматизации отсутствуют.</p></td></tr> : null}
              {(rulesQuery.data ?? []).map((rule) => (
                <tr key={rule.id}>
                  <td><strong>{rule.name}</strong><p className="table-subtext">{rule.code}</p></td>
                  <td>{rule.trigger_type}</td>
                  <td>{rule.priority}</td>
                  <td>{rule.is_active ? 'Активный' : 'Неактивный'}</td>
                  <td>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => {
                        const nextActive = !rule.is_active
                        const confirmed = window.confirm(nextActive ? 'Включить правило автоматизации?' : 'Отключить правило автоматизации?')
                        if (!confirmed) return
                        patchRuleMutation.mutate({ ruleId: rule.id, isActive: nextActive })
                      }}
                      disabled={patchRuleMutation.isPending}
                    >
                      {rule.is_active ? 'Отключить' : 'Включить'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </section>
      ) : null}

      {activeTab === 'runbooks' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Runbooks / инструкции</h3><p className="section-subtitle">Наборы шагов для регламентных операций.</p></header>
          <div className="ticket-table-wrap">
          <table className="ticket-table">
            <thead><tr><th>Runbook</th><th>Категория</th><th>Критичность</th><th>Оценка</th></tr></thead>
            <tbody>
              {(runbooksQuery.data ?? []).map((runbook) => (
                <tr key={runbook.id}>
                  <td><strong>{runbook.title}</strong><p className="table-subtext">{runbook.code}</p></td>
                  <td>{runbook.category}</td>
                  <td>{runbook.severity}</td>
                  <td>{runbook.estimated_minutes} мин</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </section>
      ) : null}

      {activeTab === 'executions' ? (
        <section className="section-card dashboard-split">
          <div>
            <p className="eyebrow">EXECUTIONS</p>
            <h2>Исполнения и retry</h2>
            <label>
              <span>Runbook</span>
              <select value={selectedRunbookId} onChange={(event) => setSelectedRunbookId(event.target.value)}>
                <option value="">Выберите runbook</option>
                {(runbooksQuery.data ?? []).map((runbook) => <option key={runbook.id} value={runbook.id}>{runbook.title}</option>)}
              </select>
            </label>
            <label>
              <span>Заявка (опционально)</span>
              <select value={selectedTicketId} onChange={(event) => setSelectedTicketId(event.target.value)}>
                <option value="">Без тикета</option>
                {(ticketsQuery.data ?? []).map((ticket) => <option key={ticket.id} value={ticket.id}>{ticket.ticket_number} · {ticket.title}</option>)}
              </select>
            </label>
            <button type="button" onClick={() => startExecutionMutation.mutate()} disabled={!selectedRunbookId || startExecutionMutation.isPending}>Запустить исполнение</button>
            <label>
              <span>Execution detail</span>
              <select value={selectedRunId} onChange={(event) => setSelectedRunId(event.target.value)}>
                <option value="">Выберите execution</option>
                {(runsQuery.data ?? []).map((run) => <option key={run.id} value={run.id}>{run.id}</option>)}
              </select>
            </label>
            <pre className="analytics-export-preview">{JSON.stringify(logsQuery.data ?? [], null, 2)}</pre>
          </div>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>ID</th><th>Status</th><th>Step</th><th>Action</th></tr></thead>
              <tbody>
                {executionsQuery.isPending ? <tr><td colSpan={4}><p className="state-panel state-panel-loading">Загрузка исполнений…</p></td></tr> : null}
                {!executionsQuery.isPending && (executionsQuery.data ?? []).length === 0 ? <tr><td colSpan={4}><p className="state-panel state-panel-empty">Исполнения runbooks пока отсутствуют.</p></td></tr> : null}
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
                          disabled={updateExecutionMutation.isPending}
                        >
                          Следующий шаг
                        </button>
                        <button
                          className="ghost-button"
                          type="button"
                          onClick={() => {
                            const confirmed = window.confirm('Отметить исполнение как completed?')
                            if (!confirmed) return
                            updateExecutionMutation.mutate({ executionId: execution.id, status: 'completed' })
                          }}
                          disabled={updateExecutionMutation.isPending}
                        >
                          Завершить
                        </button>
                        <button
                          className="ghost-button"
                          type="button"
                          onClick={() => setSelectedRunId(execution.id)}
                        >
                          Детали
                        </button>
                        <button
                          className="ghost-button"
                          type="button"
                          onClick={() => retryExecutionMutation.mutate(execution.id)}
                          disabled={retryExecutionMutation.isPending || (execution.status !== 'failed' && execution.status !== 'skipped')}
                        >
                          Retry
                        </button>
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
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Согласования</h3><p className="section-subtitle">Запросы подтверждения для контролируемых действий.</p></header>
          <div className="ticket-table-wrap">
          <table className="ticket-table">
            <thead><tr><th>Название</th><th>Статус</th><th>Инициатор</th><th>Решение</th></tr></thead>
            <tbody>
              {approvalsQuery.isPending ? <tr><td colSpan={4}><p className="state-panel state-panel-loading">Загрузка согласований…</p></td></tr> : null}
              {!approvalsQuery.isPending && (approvalsQuery.data ?? []).length === 0 ? <tr><td colSpan={4}><p className="state-panel state-panel-empty">Запросы согласования отсутствуют.</p></td></tr> : null}
              {(approvalsQuery.data ?? []).map((approval) => (
                <tr key={approval.id}>
                  <td>{approval.title}</td>
                  <td>{approval.status}</td>
                  <td>{approval.requested_by}</td>
                  <td>
                    <div className="analytics-actions">
                      <button
                        type="button"
                        onClick={() => {
                          const confirmed = window.confirm('Подтвердить APPROVED для этой заявки?')
                          if (!confirmed) return
                          decideApprovalMutation.mutate({ approvalId: approval.id, decision: 'APPROVED' })
                        }}
                        disabled={decideApprovalMutation.isPending}
                      >
                        Подтвердить
                      </button>
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => {
                          const confirmed = window.confirm('Подтвердить REJECTED для этой заявки?')
                          if (!confirmed) return
                          decideApprovalMutation.mutate({ approvalId: approval.id, decision: 'REJECTED' })
                        }}
                        disabled={decideApprovalMutation.isPending}
                      >
                        Отклонить
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </section>
      ) : null}

      {activeTab === 'templates' ? (
        <section className="section-card dashboard-split">
          <div>
            <p className="eyebrow">TEMPLATES</p>
            <h2>Templates / Examples</h2>
            <div className="activity-list">
              <article className="activity-item"><header><strong>SLA breach escalation</strong><span>template</span></header></article>
              <article className="activity-item"><header><strong>Auto-assign ticket by category</strong><span>template</span></header></article>
              <article className="activity-item"><header><strong>Notify manager on critical ticket</strong><span>template</span></header></article>
              <article className="activity-item"><header><strong>Request asset verification</strong><span>template</span></header></article>
              <article className="activity-item"><header><strong>Security high risk review</strong><span>template</span></header></article>
            </div>
          </div>
          <div>
            <p className="eyebrow">EXAMPLE PAYLOAD</p>
            <pre className="analytics-export-preview">{JSON.stringify({
              trigger_type: 'ticket_sla_breached',
              conditions: { all: [{ path: 'ticket.priority', operator: 'eq', value: 'CRITICAL' }] },
              actions: [{ type: 'create_manager_notification' }, { type: 'escalate_ticket' }, { type: 'require_admin_review' }],
            }, null, 2)}</pre>
          </div>
        </section>
      ) : null}
      </section>
    </AppShell>
  )
}
