import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  acceptAiSuggestion,
  analyzeTicket,
  attachArticleToTicket,
  fetchAiProviderStatus,
  rejectAiSuggestion,
  fetchTicketsPage,
  patchTicket,
  type AiSuggestion,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { canAccessPath } from '../auth/accessControl'
import AppShell from '../components/AppShell'
import RagAssistantPanel from '../components/RagAssistantPanel'
import AiGovernancePanel from '../components/AiGovernancePanel'
import AiRuntimeControlsPanel from '../components/AiRuntimeControlsPanel'
import AiActionsPanel from '../components/AiActionsPanel'
import { useTenantExperience } from '../experience/TenantExperienceContext'

export default function CopilotPage() {
  const { session } = useAuth()
  const { translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const permissions = new Set(session?.user.permissions ?? [])
  const root = session?.user.role === 'saas_root'
  const hasPermission = (permission: string) => root || permissions.has(permission)

  const canAnalyze = hasPermission('ai.use')
  const canAccept = hasPermission('ai.accept_suggestion')
  const canReject = hasPermission('ai.reject_suggestion')
  const canAttach = hasPermission('knowledge.attach')
  const canApplyTicketUpdate = hasPermission('tickets.update')
  const canReadTickets = Boolean(session?.user && canAccessPath(session.user, '/tickets'))
  const canReadProviderStatus = [
    'admin.settings.read',
    'admin.users.read',
    'security.audit.read',
    'ai.use',
    'ai.rag.use',
    'ai.actions.read',
  ].some(hasPermission)
  const hasAiPermission = canAnalyze
    || canAccept
    || canReject
    || hasPermission('ai.rag.use')
    || hasPermission('ai.governance.read')
    || hasPermission('ai.runtime.read')
    || hasPermission('ai.actions.read')

  const [ticketId, setTicketId] = useState('')
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [assetId, setAssetId] = useState('')
  const [decisionNote, setDecisionNote] = useState('')
  const [result, setResult] = useState<AiSuggestion | null>(null)
  const [actionHint, setActionHint] = useState<string | null>(null)

  const ticketsQuery = useQuery({
    queryKey: ['copilot-ticket-options', session?.access_token],
    queryFn: () => fetchTicketsPage(session?.access_token ?? '', { page: 1, page_size: 100 }),
    enabled: Boolean(session?.access_token) && canReadTickets,
  })

  const aiProviderQuery = useQuery({
    queryKey: ['ai-provider-status', session?.access_token],
    queryFn: () => fetchAiProviderStatus(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && canReadProviderStatus,
    refetchInterval: 60000,
    refetchIntervalInBackground: false,
  })

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      const text = [title, description, assetId ? `asset:${assetId}` : ''].filter(Boolean).join('. ').trim() || description.trim()
      return analyzeTicket(session.access_token, { ticket_id: ticketId || undefined, input_text: text || translate('Нужен анализ инцидента') })
    },
    onSuccess: (payload) => {
      setResult(payload)
      setActionHint(
        payload.provider_mock
          ? 'Локальная симуляция завершена; внешний AI не подтвердил результат.'
          : `${translate('Рекомендация получена от')} ${payload.provider ?? translate('внешнего AI')}.`,
      )
      if (payload.ticket_id) {
        void queryClient.invalidateQueries({ queryKey: ['ticket-ai', session?.access_token, payload.ticket_id] })
      }
    },
  })

  const acceptMutation = useMutation({
    mutationFn: async (suggestionId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return acceptAiSuggestion(session.access_token, suggestionId, { rationale: decisionNote || null })
    },
    onSuccess: () => setActionHint('Suggestion принят.'),
  })

  const rejectMutation = useMutation({
    mutationFn: async (suggestionId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return rejectAiSuggestion(session.access_token, suggestionId, { rationale: decisionNote || null })
    },
    onSuccess: () => setActionHint('Suggestion отклонен.'),
  })

  const attachMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; articleId: string }) => {
      if (!session?.access_token) throw new Error('No session')
      return attachArticleToTicket(session.access_token, payload.ticketId, {
        article_id: payload.articleId,
        link_type: 'ai_suggestion',
        confidence: result?.confidence_value ?? null,
        comment: 'Attached from Copilot suggestion',
      })
    },
    onSuccess: (_, variables) => {
      setActionHint('Статья прикреплена к заявке.')
      void queryClient.invalidateQueries({ queryKey: ['ticket-knowledge', session?.access_token, variables.ticketId] })
    },
  })

  const applySuggestionMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      if (!result?.ticket_id) throw new Error('AI результат не связан с заявкой')
      return patchTicket(session.access_token, result.ticket_id, {
        category: result.recommended_category,
        priority: result.recommended_priority,
      })
    },
    onSuccess: async () => {
      setActionHint('AI рекомендации применены к заявке (категория и приоритет).')
      if (result?.ticket_id) {
        await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, result.ticket_id] })
        await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      }
    },
  })

  const selectedTicket = useMemo(() => ticketsQuery.data?.items.find((item) => item.id === ticketId) ?? null, [ticketsQuery.data?.items, ticketId])

  const aiStageLabel = useMemo(() => {
    if (!hasAiPermission) return 'AI ограничен текущей ролью'
    if (aiProviderQuery.data?.execution_mode === 'LOCAL_SIMULATION') return 'Локальная AI-симуляция'
    if (aiProviderQuery.data?.execution_mode === 'FALLBACK_UNCONFIGURED') return 'Внешний AI не настроен · local fallback'
    if (aiProviderQuery.data?.execution_mode === 'EXTERNAL_CONFIGURED') return `${translate('Настроен:')} ${aiProviderQuery.data.active_provider}`
    return 'AI provider недоступен'
  }, [aiProviderQuery.data?.active_provider, aiProviderQuery.data?.execution_mode, hasAiPermission, translate])

  const nextActions = result?.next_actions ?? []

  const attachDisabledReason = !result?.ticket_id || !result?.recommended_article_id
    ? 'Нужно, чтобы в результате были ticket_id и recommended_article_id'
    : !canAttach
      ? 'Нет прав knowledge.attach'
      : ''

  return (
    <AppShell title="AI Copilot" subtitle="Permission-aware ответы с доказательствами и управляемый AI-анализ заявок.">
      <RagAssistantPanel />
      <AiGovernancePanel />
      <AiRuntimeControlsPanel />
      <AiActionsPanel />

      <section className="foundation-card" style={{ marginTop: 6 }}>
        <div>
          <p className="eyebrow">AI CONTROL TOWER</p>
          <h2>Интеллектуальный контур ИТ-операций</h2>
          <p>
            Copilot подключен к рабочему потоку заявок: анализирует инциденты, предлагает решения, связывает статьи и помогает быстрее закрывать обращения.
          </p>
        </div>
        <div className="status-column">
          <span className="unread-pill">{aiStageLabel}</span>
          <span className="muted">
            {aiProviderQuery.isPending
              ? 'Проверка AI провайдера...'
              : aiProviderQuery.isError
                ? 'Статус провайдера временно недоступен'
                : `${aiProviderQuery.data?.model ?? translate('model n/a')} ${translate('· timeout')} ${aiProviderQuery.data?.request_timeout_seconds ?? translate('n/a')}${translate('s')}`}
          </span>
        </div>
      </section>

      <section className="copilot-layout">
        <article className="copilot-panel">
          <p className="eyebrow">ANALYZE</p>
          <h2>Параметры анализа</h2>

          {canReadTickets ? <label className="inline-field" style={{ marginBottom: 10 }}>
            <span>Выбрать заявку (опционально)</span>
            <select value={ticketId} onChange={(event) => setTicketId(event.target.value)}>
              <option value="">Manual режим</option>
              {(ticketsQuery.data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>{item.ticket_number ?? item.id} · {item.title}</option>
              ))}
            </select>
          </label> : null}

          <label className="inline-field" style={{ marginBottom: 10 }}>
            <span>Ручной заголовок</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Краткий заголовок" />
          </label>

          <label className="inline-field" style={{ marginBottom: 10 }}>
            <span>Ручное описание</span>
            <textarea rows={5} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Описание инцидента" />
          </label>

          <label className="inline-field" style={{ marginBottom: 10 }}>
            <span>asset_id (опционально)</span>
            <input value={assetId} onChange={(event) => setAssetId(event.target.value)} placeholder="asset uuid" />
          </label>

          <button type="button" disabled={!canAnalyze || analyzeMutation.isPending} title={!canAnalyze ? 'Нет прав ai.use' : undefined} onClick={() => analyzeMutation.mutate()}>
            {analyzeMutation.isPending ? 'Анализ...' : 'Проанализировать заявку'}
          </button>

          {selectedTicket ? <p className="loading-state">Контекст: {selectedTicket.ticket_number ?? selectedTicket.id} · {selectedTicket.title}</p> : null}
          {analyzeMutation.isError ? <p className="error-message">Не удалось выполнить analyze.</p> : null}
        </article>

        <article className="copilot-panel">
          <p className="eyebrow">RESULT</p>
          <h2>Результат AI</h2>

          {!result ? <p className="empty-state">Пока нет результатов. Запустите analyze.</p> : null}

          {result ? (
            <div className="copilot-result">
              {result.provider_mock && result.fallback_used ? (
                <div className="alert alert-warning result-card-wide">Использован fallback вместо запрошенного provider. Результат требует ручной проверки.</div>
              ) : result.provider_mock ? (
                <div className="alert alert-warning result-card-wide">Результат создан локальными правилами; внешний LLM не использовался. Проверьте рекомендацию вручную перед применением.</div>
              ) : (
                <div className="alert alert-info result-card-wide">Результат получен от настроенного внешнего provider; это рекомендация, а не автоматическое решение.</div>
              )}
              <div className="result-card"><span>Запрошенный provider</span><strong>{result.requested_provider ?? 'unknown'}</strong></div>
              <div className="result-card"><span>Провайдер</span><strong>{result.provider ?? 'unknown'}{result.model ? ` · ${result.model}` : ''}</strong></div>
              <div className="result-card"><span>Режим выполнения</span><strong>{result.execution_mode ?? 'UNKNOWN'}</strong></div>
              <div className="result-card"><span>Предложенная категория</span><strong>{result.recommended_category}</strong></div>
              <div className="result-card"><span>Предложенный приоритет</span><strong>{result.recommended_priority}</strong></div>
              <div className="result-card"><span>Уверенность</span><strong>{result.confidence}</strong></div>
              <div className="result-card"><span>Обоснование</span><strong>{result.rationale ?? 'rule_based_local_mock'}</strong></div>
              <div className="result-card result-card-wide"><span>Шаги решения</span><strong>{result.suggested_solution}</strong></div>

              <div className="result-card result-card-wide">
                <span>Следующие действия AI</span>
                <ul>
                  {nextActions.length === 0 ? <li>Нет дополнительных шагов</li> : nextActions.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </div>

              <div className="result-card result-card-wide">
                <span>Предложенные статьи</span>
                <ul>
                  {result.related_articles.length === 0 ? <li>Нет подходящих статей</li> : result.related_articles.map((item) => <li key={item.id}>{item.article_number} · {item.title}</li>)}
                </ul>
              </div>

              <div className="result-card result-card-wide">
                <span>Похожие заявки</span>
                <ul>
                  {result.similar_tickets.length === 0 ? <li>Нет похожих тикетов</li> : result.similar_tickets.map((item) => <li key={item.id}>{item.ticket_number ?? item.id} · {item.title}</li>)}
                </ul>
              </div>

              <label className="inline-field">
                <span>Комментарий к decision</span>
                <input value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} placeholder="Необязательное обоснование" />
              </label>

              <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={!canApplyTicketUpdate || !result.ticket_id || applySuggestionMutation.isPending}
                  title={!canApplyTicketUpdate ? 'Нет прав tickets.update' : undefined}
                  onClick={() => applySuggestionMutation.mutate()}
                >
                  {applySuggestionMutation.isPending ? 'Применение...' : 'Применить категорию и приоритет к заявке'}
                </button>
                <button
                  type="button"
                  disabled={!canAccept || !result.id || acceptMutation.isPending}
                  title={!canAccept ? 'Нет прав ai.accept_suggestion' : undefined}
                  onClick={() => acceptMutation.mutate(result.id)}
                >
                  Принять suggestion
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={!canReject || !result.id || rejectMutation.isPending}
                  title={!canReject ? 'Нет прав ai.reject_suggestion' : undefined}
                  onClick={() => rejectMutation.mutate(result.id)}
                >
                  Отклонить suggestion
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={Boolean(attachDisabledReason) || attachMutation.isPending}
                  title={attachDisabledReason || undefined}
                  onClick={() => {
                    if (!result.ticket_id || !result.recommended_article_id) return
                    attachMutation.mutate({ ticketId: result.ticket_id, articleId: result.recommended_article_id })
                  }}
                >
                  Прикрепить статью к заявке
                </button>
              </div>

              {actionHint ? <p className="loading-state">{actionHint}</p> : null}
              {acceptMutation.isError || rejectMutation.isError || attachMutation.isError || applySuggestionMutation.isError ? <p className="error-message">Одна из операций завершилась ошибкой.</p> : null}
            </div>
          ) : null}
        </article>
      </section>
    </AppShell>
  )
}
