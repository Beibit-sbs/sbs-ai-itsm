import { useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { analyzeTicketWithAi, createKnowledgeArticle, createTicket, fetchKnowledgeCategories, type AiSuggestion } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'

function suggestionToTicketCategory(category: string): string {
  const map: Record<string, string> = {
    'Сеть и интернет': 'NETWORK_INTERNET',
    Принтеры: 'PRINTING',
    'Доступы и учетные записи': 'ACCOUNT_PASSWORD',
    'Информационные системы': 'ACCESS_PLATONUS',
    'Корпоративная почта': 'MAIL',
    'Информационная безопасность': 'SECURITY_PHISHING',
    Оборудование: 'HARDWARE_WORKSTATION',
    'Аудиторное оборудование': 'AV_PROJECTOR',
  }
  return map[category] ?? 'SOFTWARE_INSTALL'
}

export default function CopilotPage() {
  const { session } = useAuth()
  const [description, setDescription] = useState('')
  const [result, setResult] = useState<AiSuggestion | null>(null)
  const [actionHint, setActionHint] = useState<string | null>(null)

  const analyzeMutation = useMutation({
    mutationFn: async (text: string) => {
      if (!session?.access_token) throw new Error('No session')
      return analyzeTicketWithAi(session.access_token, { input_text: text })
    },
    onSuccess: (payload) => {
      setActionHint(null)
      setResult(payload)
    },
  })

  const createTicketMutation = useMutation({
    mutationFn: async (payload: AiSuggestion) => {
      if (!session?.access_token) throw new Error('No session')
      return createTicket(session.access_token, {
        title: payload.summary,
        description: `${payload.possible_cause}\n\n${payload.suggested_solution}`,
        requester_name: 'AI Copilot',
        requester_email: 'copilot@sbs.local',
        department: 'Service Desk',
        location: 'AI Desk',
        category: suggestionToTicketCategory(payload.recommended_category),
        priority: payload.recommended_priority,
        assignee_name: payload.recommended_assignee,
      })
    },
    onSuccess: () => {
      setActionHint('Черновик заявки успешно создан на основе AI-анализа.')
    },
  })

  const createArticleMutation = useMutation({
    mutationFn: async (payload: AiSuggestion) => {
      if (!session?.access_token) throw new Error('No session')
      const categories = await fetchKnowledgeCategories(session.access_token)
      const categoryId = categories.find((item) => item.name === payload.recommended_category)?.id ?? categories[0]?.id
      if (!categoryId) throw new Error('Knowledge category is unavailable')

      return createKnowledgeArticle(session.access_token, {
        title: `AI: ${payload.summary}`,
        summary: payload.possible_cause,
        content: payload.suggested_solution,
        category_id: categoryId,
        ticket_category: suggestionToTicketCategory(payload.recommended_category),
        asset_type: payload.recommended_asset_type,
        tags: ['ai', 'mockai', 'copilot'],
        status: 'draft',
        visibility: 'internal',
      })
    },
    onSuccess: () => {
      setActionHint('Черновик статьи базы знаний успешно создан.')
    },
  })

  return (
    <AppShell title="AI Copilot" subtitle="AI-анализ обращений, рекомендации, похожие заявки и статьи базы знаний.">

      <section className="copilot-layout">
        <article className="copilot-panel">
          <p className="eyebrow">ВХОДНЫЕ ДАННЫЕ</p>
          <h2>Описание проблемы</h2>
          <textarea
            rows={8}
            value={description}
            onChange={(event) => setDescription(event.target.value)}
            placeholder="Например: в кабинете 1113 пропал интернет и не пингуется шлюз"
          />
          <button
            type="button"
            onClick={() => analyzeMutation.mutate(description.trim() || 'не работает интернет в кабинете 1113')}
            disabled={analyzeMutation.isPending}
          >
            {analyzeMutation.isPending ? 'Анализ...' : 'Проанализировать'}
          </button>
          {analyzeMutation.isError ? <p className="error-state">Не удалось выполнить AI-анализ. Повторите запрос.</p> : null}
        </article>

        <article className="copilot-panel">
          <p className="eyebrow">РЕЗУЛЬТАТ AI-АНАЛИЗА</p>
          <h2>Результат анализа</h2>
          {result ? (
            <div className="copilot-result">
              <div className="result-card"><span>Краткое резюме</span><strong>{result.summary}</strong></div>
              <div className="result-card"><span>Категория</span><strong>{result.recommended_category}</strong></div>
              <div className="result-card"><span>Приоритет</span><strong>{result.recommended_priority}</strong></div>
              <div className="result-card"><span>Возможная причина</span><strong>{result.possible_cause}</strong></div>
              <div className="result-card"><span>Рекомендуемое решение</span><strong>{result.suggested_solution}</strong></div>
              <div className="result-card"><span>Исполнитель</span><strong>{result.recommended_assignee}</strong></div>
              <div className="result-card"><span>Тип актива</span><strong>{result.recommended_asset_type ?? '—'}</strong></div>
              <div className="result-card"><span>Уверенность AI</span><strong>{result.confidence}</strong></div>

              <div className="result-card result-card-wide">
                <span>Подходящие статьи базы знаний</span>
                <ul>
                  {result.related_articles.length === 0 ? <li>Не найдено</li> : result.related_articles.map((item) => <li key={item.id}>{item.article_number} · {item.title}</li>)}
                </ul>
              </div>

              <div className="result-card result-card-wide">
                <span>Похожие инциденты</span>
                <ul>
                  {result.similar_tickets.length === 0 ? <li>Не найдено</li> : result.similar_tickets.map((item) => <li key={item.id}>{item.ticket_number ?? item.id} · {item.title}</li>)}
                </ul>
              </div>

              <div className="result-card result-card-wide">
                <span>Следующие действия</span>
                <ul>
                  {result.next_actions.map((item) => (
                    <li key={item}>{item}</li>
                  ))}
                </ul>
              </div>

              <div className="form-stack">
                <button
                  type="button"
                  disabled={createTicketMutation.isPending || createArticleMutation.isPending}
                  onClick={() => {
                    const confirmed = window.confirm('Создать заявку из текущего AI-анализа?')
                    if (!confirmed) return
                    createTicketMutation.mutate(result)
                  }}
                >
                  {createTicketMutation.isPending ? 'Создание заявки...' : 'Создать заявку из анализа'}
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={createArticleMutation.isPending || createTicketMutation.isPending}
                  onClick={() => {
                    const confirmed = window.confirm('Создать статью базы знаний из текущего AI-анализа?')
                    if (!confirmed) return
                    createArticleMutation.mutate(result)
                  }}
                >
                  {createArticleMutation.isPending ? 'Создание статьи...' : 'Создать статью из решения'}
                </button>
              </div>

              {createTicketMutation.isError ? <p className="error-message">Не удалось создать заявку из AI-анализа.</p> : null}
              {createArticleMutation.isError ? <p className="error-message">Не удалось создать статью из AI-анализа.</p> : null}
              {actionHint ? <p className="loading-state">{actionHint}</p> : null}
            </div>
          ) : (
            <p className="empty-state">Данных пока нет. Нажмите «Проанализировать», чтобы получить рекомендации AI Copilot.</p>
          )}
        </article>
      </section>
    </AppShell>
  )
}
