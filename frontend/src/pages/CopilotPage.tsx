import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  acceptAiSuggestion,
  analyzeTicket,
  attachArticleToTicket,
  rejectAiSuggestion,
  fetchTicketsPage,
  type AiSuggestion,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'

export default function CopilotPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const permissions = new Set(session?.user.permissions ?? [])

  const canAnalyze = permissions.has('ai.use')
  const canAccept = permissions.has('ai.accept_suggestion')
  const canReject = permissions.has('ai.reject_suggestion')
  const canAttach = permissions.has('knowledge.attach')

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
    enabled: Boolean(session?.access_token),
  })

  const analyzeMutation = useMutation({
    mutationFn: async () => {
      if (!session?.access_token) throw new Error('No session')
      const text = [title, description, assetId ? `asset:${assetId}` : ''].filter(Boolean).join('. ').trim() || description.trim()
      return analyzeTicket(session.access_token, { ticket_id: ticketId || undefined, input_text: text || 'Нужен анализ инцидента' })
    },
    onSuccess: (payload) => {
      setResult(payload)
      setActionHint('AI анализ успешно выполнен (mock-safe).')
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

  const selectedTicket = useMemo(() => ticketsQuery.data?.items.find((item) => item.id === ticketId) ?? null, [ticketsQuery.data?.items, ticketId])

  const attachDisabledReason = !result?.ticket_id || !result?.recommended_article_id
    ? 'Нужно, чтобы в результате были ticket_id и recommended_article_id'
    : !canAttach
      ? 'Нет прав knowledge.attach'
      : ''

  return (
    <AppShell title="AI Copilot" subtitle="Mock-safe AI-анализ заявок, решения и действия по suggestion lifecycle.">
      <section className="copilot-layout">
        <article className="copilot-panel">
          <p className="eyebrow">ANALYZE</p>
          <h2>Параметры анализа</h2>

          <label className="inline-field" style={{ marginBottom: 10 }}>
            <span>Выбрать заявку (опционально)</span>
            <select value={ticketId} onChange={(event) => setTicketId(event.target.value)}>
              <option value="">Manual режим</option>
              {(ticketsQuery.data?.items ?? []).map((item) => (
                <option key={item.id} value={item.id}>{item.ticket_number ?? item.id} · {item.title}</option>
              ))}
            </select>
          </label>

          <label className="inline-field" style={{ marginBottom: 10 }}>
            <span>Manual title</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Краткий заголовок" />
          </label>

          <label className="inline-field" style={{ marginBottom: 10 }}>
            <span>Manual description</span>
            <textarea rows={5} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Описание инцидента" />
          </label>

          <label className="inline-field" style={{ marginBottom: 10 }}>
            <span>asset_id (опционально)</span>
            <input value={assetId} onChange={(event) => setAssetId(event.target.value)} placeholder="asset uuid" />
          </label>

          <button type="button" disabled={!canAnalyze || analyzeMutation.isPending} title={!canAnalyze ? 'Нет прав ai.use' : undefined} onClick={() => analyzeMutation.mutate()}>
            {analyzeMutation.isPending ? 'Анализ...' : 'Analyze ticket'}
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
              <div className="result-card"><span>Suggested category</span><strong>{result.recommended_category}</strong></div>
              <div className="result-card"><span>Suggested priority</span><strong>{result.recommended_priority}</strong></div>
              <div className="result-card"><span>Confidence</span><strong>{result.confidence}</strong></div>
              <div className="result-card"><span>Rationale</span><strong>{result.rationale ?? 'rule_based_local_mock'}</strong></div>
              <div className="result-card result-card-wide"><span>Resolution steps</span><strong>{result.suggested_solution}</strong></div>

              <div className="result-card result-card-wide">
                <span>Suggested articles</span>
                <ul>
                  {result.related_articles.length === 0 ? <li>Нет подходящих статей</li> : result.related_articles.map((item) => <li key={item.id}>{item.article_number} · {item.title}</li>)}
                </ul>
              </div>

              <div className="result-card result-card-wide">
                <span>Similar tickets</span>
                <ul>
                  {result.similar_tickets.length === 0 ? <li>Нет похожих тикетов</li> : result.similar_tickets.map((item) => <li key={item.id}>{item.ticket_number ?? item.id} · {item.title}</li>)}
                </ul>
              </div>

              <label className="inline-field">
                <span>Комментарий к decision</span>
                <input value={decisionNote} onChange={(event) => setDecisionNote(event.target.value)} placeholder="optional rationale" />
              </label>

              <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
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
              {acceptMutation.isError || rejectMutation.isError || attachMutation.isError ? <p className="error-message">Одна из операций завершилась ошибкой.</p> : null}
            </div>
          ) : null}
        </article>
      </section>
    </AppShell>
  )
}
