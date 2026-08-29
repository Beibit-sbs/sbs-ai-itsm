import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  type AiActionProposal,
  type AiActionType,
  createAiActionProposal,
  decideAiActionProposal,
  executeAiActionProposal,
  fetchAiActionMeta,
  fetchAiActionProposals,
  rollbackAiActionProposal,
  updateAiActionPolicy,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import QueryFailureNotice from './QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const ACTION_LABELS: Record<AiActionType, string> = {
  'ticket.update': 'Изменить категорию/приоритет заявки',
  'ticket.classify': 'Применить AI-классификацию заявки',
  'knowledge.draft': 'Создать черновик статьи',
  'runbook.draft': 'Создать неактивный черновик runbook',
}

const PARAMETER_EXAMPLES: Record<AiActionType, Record<string, unknown>> = {
  'ticket.update': { priority: 'HIGH', category: 'Network' },
  'ticket.classify': { priority: 'MEDIUM', category: 'Software' },
  'knowledge.draft': {
    title: 'Диагностика сетевого доступа',
    summary: 'Проверенный порядок первичной диагностики.',
    content: 'Пошаговая инструкция с условиями эскалации.',
    category_id: 'UUID категории базы знаний',
    tags: ['network', 'diagnostics'],
  },
  'runbook.draft': {
    code: 'network.diagnostics',
    title: 'Диагностика сети',
    category: 'network',
    severity: 'HIGH',
    steps: [
      {
        title: 'Проверить состояние',
        instruction: 'Зафиксировать симптомы и метрики.',
      },
    ],
    estimated_minutes: 15,
  },
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Неизвестная ошибка'
}

function shortHash(value: string | null) {
  return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : '—'
}

export default function AiActionsPanel() {
  const { session } = useAuth()
  const { formatDateTime } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const permissions = useMemo(
    () => new Set(session?.user.permissions ?? []),
    [session?.user.permissions],
  )
  const isRoot = session?.user.role === 'saas_root'
  const canRead = isRoot || permissions.has('ai.actions.read')
  const canManage = isRoot || permissions.has('ai.actions.manage')
  const canPropose = isRoot || permissions.has('ai.actions.propose')
  const canApprove = isRoot || permissions.has('ai.actions.approve')
  const canExecute = isRoot || permissions.has('ai.actions.execute')
  const canRollback = isRoot || permissions.has('ai.actions.rollback')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const scope = isRoot ? tenantId.trim() : session?.user.tenant_id
  const [enabled, setEnabled] = useState(true)
  const [fourEyes, setFourEyes] = useState(true)
  const [ttlMinutes, setTtlMinutes] = useState(1440)
  const [allowedActions, setAllowedActions] = useState<AiActionType[]>([])
  const [actionType, setActionType] =
    useState<AiActionType>('ticket.classify')
  const [targetId, setTargetId] = useState('')
  const [parameters, setParameters] = useState(
    JSON.stringify(PARAMETER_EXAMPLES['ticket.classify'], null, 2),
  )
  const [rationale, setRationale] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState(
    `ui-${Date.now().toString(36)}-proposal`,
  )
  const [notice, setNotice] = useState('')

  const meta = useQuery({
    queryKey: ['ai-actions-meta', token, scope],
    queryFn: () => fetchAiActionMeta(token, scope),
    enabled: Boolean(token && canRead && scope),
    refetchInterval: 30_000,
  })
  const proposals = useQuery({
    queryKey: ['ai-actions-proposals', token, scope],
    queryFn: () => fetchAiActionProposals(token, scope),
    enabled: Boolean(token && canRead && scope),
    refetchInterval: 30_000,
  })

  useEffect(() => {
    if (!meta.data) return
    setEnabled(meta.data.policy?.enabled ?? true)
    setFourEyes(meta.data.policy?.independent_approval_for_high_risk ?? true)
    setTtlMinutes(meta.data.policy?.proposal_ttl_minutes ?? 1440)
    setAllowedActions(
      meta.data.policy?.allowed_actions ?? meta.data.server_action_allowlist,
    )
  }, [meta.data])

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['ai-actions-meta'] }),
      queryClient.invalidateQueries({ queryKey: ['ai-actions-proposals'] }),
    ])
  }

  const policyMutation = useMutation({
    mutationFn: () =>
      updateAiActionPolicy(token, {
        tenant_id: isRoot ? scope : undefined,
        expected_revision: meta.data?.policy?.revision ?? 0,
        enabled,
        allowed_actions: allowedActions,
        independent_approval_for_high_risk: fourEyes,
        proposal_ttl_minutes: ttlMinutes,
      }),
    onSuccess: async () => {
      setNotice(
        'Политика сохранена. Серверный allowlist действует до выполнения действия.',
      )
      await refresh()
    },
  })
  const createMutation = useMutation({
    mutationFn: () => {
      const parsed = JSON.parse(parameters) as unknown
      if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') {
        throw new Error('Параметры должны быть JSON-объектом.')
      }
      return createAiActionProposal(token, {
        tenant_id: isRoot ? scope : undefined,
        idempotency_key: idempotencyKey,
        action_type: actionType,
        target_id: targetId.trim() || undefined,
        parameters: parsed as Record<string, unknown>,
        citations: [],
        rationale,
      })
    },
    onSuccess: async () => {
      setNotice(
        'Предложение создано. До независимого approval состояние системы не изменится.',
      )
      setIdempotencyKey(`ui-${Date.now().toString(36)}-proposal`)
      await refresh()
    },
  })
  const decisionMutation = useMutation({
    mutationFn: ({
      proposal,
      decision,
    }: {
      proposal: AiActionProposal
      decision: 'APPROVED' | 'REJECTED'
    }) =>
      decideAiActionProposal(
        token,
        proposal.id,
        decision,
        decision === 'APPROVED'
          ? 'Проверены параметры, evidence и ожидаемое влияние'
          : 'Предложение отклонено оператором',
      ),
    onSuccess: refresh,
  })
  const executeMutation = useMutation({
    mutationFn: (proposal: AiActionProposal) =>
      executeAiActionProposal(token, proposal.id),
    onSuccess: async () => {
      setNotice(
        'Действие выполнено фиксированным server handler. Before/after hash сохранены.',
      )
      await refresh()
    },
  })
  const rollbackMutation = useMutation({
    mutationFn: (proposal: AiActionProposal) =>
      rollbackAiActionProposal(
        token,
        proposal.id,
        'Operator rollback from guarded AI control center',
      ),
    onSuccess: async () => {
      setNotice('Rollback выполнен после проверки live-state.')
      await refresh()
    },
  })

  if (!canRead) return null
  const error =
    meta.error ??
    proposals.error ??
    policyMutation.error ??
    createMutation.error ??
    decisionMutation.error ??
    executeMutation.error ??
    rollbackMutation.error

  const changeAction = (next: AiActionType) => {
    setActionType(next)
    setParameters(JSON.stringify(PARAMETER_EXAMPLES[next], null, 2))
    if (!next.startsWith('ticket.')) setTargetId('')
  }

  return (
    <LocalizedContent>
    <section className="ai-actions-panel">
      <QueryFailureNotice
        title="Часть данных AI Actions недоступна."
        sources={[
          { label: 'action catalog', query: meta },
          { label: 'proposals', query: proposals },
        ]}
      />
      <div className="rag-assistant-heading">
        <div>
          <p className="eyebrow">GUARDED AI ACTIONS</p>
          <h2>Предложения, approval, выполнение и rollback</h2>
          <p>
            AI не получает произвольных tools. Он может подготовить только строго
            типизированное предложение; сервер повторно проверяет tenant, права,
            allowlist, параметры и live fingerprint объекта.
          </p>
        </div>
        <div className="rag-privacy-badges">
          <span>Server allowlist</span>
          <span>Four eyes</span>
          <span>Idempotency</span>
          <span>State hash</span>
        </div>
      </div>

      {isRoot ? (
        <label className="inline-field">
          <span>Tenant ID</span>
          <input
            value={tenantId}
            onChange={(event) => setTenantId(event.target.value)}
            placeholder="UUID организации"
          />
        </label>
      ) : null}

      <div className="ai-actions-counts">
        {(
          [
            'PROPOSED',
            'APPROVED',
            'EXECUTED',
            'FAILED',
            'ROLLED_BACK',
          ] as const
        ).map((status) => (
          <article key={status}>
            <span>{status}</span>
            <strong>{meta.data?.counts[status] ?? 0}</strong>
          </article>
        ))}
      </div>

      <div className="ai-actions-workspace">
        <article className="copilot-panel">
          <p className="eyebrow">TENANT ACTION POLICY</p>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
            />
            <span>Guarded actions включены</span>
          </label>
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={fourEyes}
              onChange={(event) => setFourEyes(event.target.checked)}
            />
            <span>Независимый approval для HIGH risk</span>
          </label>
          <label className="inline-field">
            <span>Срок действия предложения, минут</span>
            <input
              type="number"
              min={5}
              max={10080}
              value={ttlMinutes}
              onChange={(event) => setTtlMinutes(Number(event.target.value))}
            />
          </label>
          <div className="ai-action-allowlist">
            {(meta.data?.server_action_allowlist ?? []).map((action) => (
              <label className="checkbox-row" key={action}>
                <input
                  type="checkbox"
                  checked={allowedActions.includes(action)}
                  onChange={(event) =>
                    setAllowedActions((current) =>
                      event.target.checked
                        ? [...new Set([...current, action])]
                        : current.filter((item) => item !== action),
                    )
                  }
                />
                <span>{ACTION_LABELS[action]}</span>
              </label>
            ))}
          </div>
          {canManage ? (
            <button
              type="button"
              onClick={() => policyMutation.mutate()}
              disabled={
                !scope || !allowedActions.length || policyMutation.isPending
              }
            >
              Сохранить policy
            </button>
          ) : null}
        </article>

        <article className="copilot-panel">
          <p className="eyebrow">NEW PROPOSAL</p>
          <label className="inline-field">
            <span>Действие</span>
            <select
              value={actionType}
              onChange={(event) =>
                changeAction(event.target.value as AiActionType)
              }
            >
              {(
                meta.data?.server_action_allowlist ??
                (Object.keys(ACTION_LABELS) as AiActionType[])
              ).map((action) => (
                <option key={action} value={action}>
                  {ACTION_LABELS[action]}
                </option>
              ))}
            </select>
          </label>
          {actionType.startsWith('ticket.') ? (
            <label className="inline-field">
              <span>Ticket UUID</span>
              <input
                value={targetId}
                onChange={(event) => setTargetId(event.target.value)}
                placeholder="Обязателен для ticket actions"
              />
            </label>
          ) : null}
          <label className="inline-field">
            <span>Schema-validated parameters JSON</span>
            <textarea
              rows={9}
              value={parameters}
              onChange={(event) => setParameters(event.target.value)}
            />
          </label>
          <label className="inline-field">
            <span>Обоснование</span>
            <textarea
              rows={3}
              value={rationale}
              onChange={(event) => setRationale(event.target.value)}
              placeholder="Почему действие нужно выполнить и какие evidence проверены"
            />
          </label>
          <label className="inline-field">
            <span>Idempotency key</span>
            <input
              value={idempotencyKey}
              onChange={(event) => setIdempotencyKey(event.target.value)}
            />
          </label>
          {canPropose ? (
            <button
              type="button"
              onClick={() => createMutation.mutate()}
              disabled={
                !scope ||
                rationale.trim().length < 3 ||
                (actionType.startsWith('ticket.') && !targetId.trim()) ||
                createMutation.isPending
              }
            >
              Создать предложение
            </button>
          ) : null}
        </article>
      </div>

      <div className="ai-action-list">
        {(proposals.data ?? []).map((proposal) => (
          <article className="ai-action-card" key={proposal.id}>
            <div className="ai-action-card-heading">
              <div>
                <span
                  className={`status-badge status-${proposal.status.toLowerCase()}`}
                >
                  {proposal.status}
                </span>
                <strong>{proposal.proposal_number}</strong>
                <small>
                  {ACTION_LABELS[proposal.action_type]} · risk{' '}
                  {proposal.risk_level}
                </small>
              </div>
              <small>до {formatDateTime(proposal.expires_at, { dateStyle: 'short', timeStyle: 'short' })}</small>
            </div>
            <p>{proposal.rationale}</p>
            <div className="ai-action-evidence">
              <span>
                Target{' '}
                <strong>
                  {proposal.target_id ?? 'создаётся при execute'}
                </strong>
              </span>
              <span>
                Parameters SHA-256{' '}
                <code>{shortHash(proposal.parameters_sha256)}</code>
              </span>
              <span>
                Fingerprint{' '}
                <code>{shortHash(proposal.target_fingerprint)}</code>
              </span>
              <span>
                Citations <strong>{proposal.citation_evidence.length}</strong>
              </span>
            </div>
            <details>
              <summary>Проверенные параметры</summary>
              <pre>{JSON.stringify(proposal.parameters, null, 2)}</pre>
            </details>
            <div className="button-row">
              {proposal.status === 'PROPOSED' && canApprove ? (
                <>
                  <button
                    type="button"
                    onClick={() =>
                      decisionMutation.mutate({
                        proposal,
                        decision: 'APPROVED',
                      })
                    }
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() =>
                      decisionMutation.mutate({
                        proposal,
                        decision: 'REJECTED',
                      })
                    }
                  >
                    Reject
                  </button>
                </>
              ) : null}
              {proposal.status === 'APPROVED' && canExecute ? (
                <button
                  type="button"
                  onClick={() => executeMutation.mutate(proposal)}
                >
                  Execute
                </button>
              ) : null}
              {proposal.status === 'EXECUTED' && canRollback ? (
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => rollbackMutation.mutate(proposal)}
                >
                  Safe rollback
                </button>
              ) : null}
            </div>
            {proposal.error_code ? (
              <p className="error-message">{proposal.error_code}</p>
            ) : null}
          </article>
        ))}
        {!proposals.isLoading && !proposals.data?.length ? (
          <p className="empty-state">
            Предложений пока нет. Без proposal и approval система ничего не
            изменяет.
          </p>
        ) : null}
      </div>
      {notice ? <p className="loading-state">{notice}</p> : null}
      {error ? <p className="error-message">{errorText(error)}</p> : null}
    </section>
    </LocalizedContent>
  )
}
