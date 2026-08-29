import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  askAiRag,
  fetchAiRagDashboard,
  fetchAiRagMeta,
  synchronizeAiRag,
  type AiRagAnswer,
  type AiRagSourceType,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const SOURCE_LABELS: Record<AiRagSourceType, string> = {
  knowledge: 'База знаний',
  ticket: 'Решённые заявки',
  problem: 'Проблемы / KEDB',
  change: 'Изменения',
  asset: 'Проверенные активы',
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Неизвестная ошибка'
}

export default function RagAssistantPanel() {
  const { session } = useAuth()
  const { translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const canUse = Boolean(
    isRoot || session?.user.permissions.includes('ai.rag.use'),
  )
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [question, setQuestion] = useState('')
  const [sourceTypes, setSourceTypes] = useState<AiRagSourceType[]>([])
  const [answer, setAnswer] = useState<AiRagAnswer | null>(null)

  const metaQuery = useQuery({
    queryKey: ['ai-rag-meta', token],
    queryFn: () => fetchAiRagMeta(token),
    enabled: Boolean(token && canUse),
    staleTime: 60_000,
  })

  useEffect(() => {
    if (!metaQuery.data || sourceTypes.length > 0) return
    setSourceTypes(metaQuery.data.allowed_source_types)
  }, [metaQuery.data, sourceTypes.length])

  const effectiveTenantId = isRoot ? tenantId.trim() : session?.user.tenant_id
  const canLoadTenantData = Boolean(effectiveTenantId)
  const dashboardQuery = useQuery({
    queryKey: ['ai-rag-dashboard', token, effectiveTenantId],
    queryFn: () => fetchAiRagDashboard(token, effectiveTenantId),
    enabled: Boolean(
      token
      && canUse
      && canLoadTenantData
      && (
        isRoot
        || session?.user.permissions.includes('ai.rag.read')
      ),
    ),
    staleTime: 20_000,
  })

  const askMutation = useMutation({
    mutationFn: () => {
      if (!token) throw new Error('Нет активной сессии')
      if (!effectiveTenantId) throw new Error('Укажите tenant ID')
      if (question.trim().length < 3) {
        throw new Error('Сформулируйте вопрос минимум из трёх символов')
      }
      if (sourceTypes.length === 0) {
        throw new Error('Выберите хотя бы один разрешённый источник')
      }
      return askAiRag(token, {
        tenant_id: isRoot ? effectiveTenantId : undefined,
        query: question.trim(),
        source_types: sourceTypes,
        limit: 6,
        minimum_score: 0.12,
      })
    },
    onSuccess: (result) => {
      setAnswer(result)
      void queryClient.invalidateQueries({
        queryKey: ['ai-rag-dashboard', token, effectiveTenantId],
      })
    },
  })

  const syncMutation = useMutation({
    mutationFn: () => {
      if (!token) throw new Error('Нет активной сессии')
      if (!effectiveTenantId) throw new Error('Укажите tenant ID')
      const syncSources = metaQuery.data?.allowed_source_types ?? []
      if (syncSources.length === 0) {
        throw new Error('Нет разрешённых источников для индексации')
      }
      return synchronizeAiRag(token, {
        tenant_id: isRoot ? effectiveTenantId : undefined,
        source_types: syncSources,
      })
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ['ai-rag-dashboard', token, effectiveTenantId],
      })
    },
  })

  const groundedRate = useMemo(() => {
    const data = dashboardQuery.data
    if (!data?.total_queries) return 0
    return Math.round((data.grounded_queries / data.total_queries) * 100)
  }, [dashboardQuery.data])

  if (!canUse) {
    return (
      <LocalizedContent>
      <section className="rag-assistant rag-assistant-locked">
        <p className="eyebrow">PERMISSION-AWARE AI</p>
        <h2>Корпоративный ассистент недоступен</h2>
        <p>Для этой роли не назначено право <code>ai.rag.use</code>.</p>
      </section>
      </LocalizedContent>
    )
  }

  return (
    <LocalizedContent>
    <section className="rag-assistant">
      <div className="rag-assistant-heading">
        <div>
          <p className="eyebrow">PERMISSION-AWARE RAG</p>
          <h2>Корпоративный ITSM-ассистент</h2>
          <p>
            Ответы строятся только по опубликованным и актуальным объектам,
            которые разрешены вашей роли. Перед выдачей система повторно
            проверяет tenant, права и доступ к исходному объекту.
          </p>
        </div>
        <div className="rag-privacy-badges" aria-label="Контроли безопасности">
          <span>Live ACL</span>
          <span>PII redaction</span>
          <span>Injection guard</span>
          <span>No raw logs</span>
        </div>
      </div>

      {isRoot ? (
        <label className="inline-field rag-tenant-field">
          <span>Tenant ID для изолированного контекста</span>
          <input
            value={tenantId}
            onChange={(event) => {
              setTenantId(event.target.value)
              setAnswer(null)
            }}
            placeholder="UUID организации"
          />
        </label>
      ) : null}

      <div className="rag-workspace">
        <article className="rag-question-card">
          <label className="inline-field">
            <span>Вопрос по ITSM-контексту</span>
            <textarea
              rows={5}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Например: как решали похожие сбои VPN и какой workaround подтверждён?"
            />
          </label>

          <fieldset className="rag-source-picker">
            <legend>Разрешённые источники</legend>
            {(metaQuery.data?.allowed_source_types ?? []).map((sourceType) => (
              <label key={sourceType}>
                <input
                  type="checkbox"
                  checked={sourceTypes.includes(sourceType)}
                  onChange={(event) => {
                    setSourceTypes((current) => (
                      event.target.checked
                        ? [...current, sourceType]
                        : current.filter((item) => item !== sourceType)
                    ))
                  }}
                />
                <span>{translate(SOURCE_LABELS[sourceType])}</span>
              </label>
            ))}
          </fieldset>

          <div className="analytics-actions rag-actions">
            <button
              type="button"
              disabled={askMutation.isPending || !canLoadTenantData}
              onClick={() => askMutation.mutate()}
            >
              {askMutation.isPending ? 'Проверка источников…' : 'Получить подтверждённый ответ'}
            </button>
            {metaQuery.data?.can_manage ? (
              <button
                type="button"
                className="ghost-button"
                disabled={syncMutation.isPending || !canLoadTenantData}
                onClick={() => syncMutation.mutate()}
              >
                {syncMutation.isPending ? 'Синхронизация…' : 'Обновить индекс'}
              </button>
            ) : null}
          </div>

          {metaQuery.isPending ? <p className="loading-state">Проверка AI-политик…</p> : null}
          {metaQuery.isError ? <p className="error-message">{errorMessage(metaQuery.error)}</p> : null}
          {askMutation.isError ? <p className="error-message">{errorMessage(askMutation.error)}</p> : null}
          {syncMutation.isError ? <p className="error-message">{errorMessage(syncMutation.error)}</p> : null}
          {syncMutation.isSuccess ? (
            <p className="loading-state">
              Индекс обновлён: {syncMutation.data.indexed} новых, {syncMutation.data.updated} изменённых,
              {' '}{syncMutation.data.deleted} удалённых источников.
            </p>
          ) : null}
        </article>

        <article className="rag-answer-card">
          <div className="rag-answer-header">
            <div>
              <p className="eyebrow">GROUNDED ANSWER</p>
              <h3>{answer ? (answer.grounded ? 'Подтверждённый ответ' : 'Недостаточно данных') : 'Ожидает вопроса'}</h3>
            </div>
            {answer ? (
              <span className={answer.grounded ? 'rag-grounded' : 'rag-ungrounded'}>
                {answer.grounded ? 'Grounded' : 'No evidence'}
              </span>
            ) : null}
          </div>

          {answer ? (
            <>
              {answer.provider_mock && answer.fallback_used ? (
                <p className="state-panel state-panel-warning">
                  Внешний provider не дал подтверждённый ответ; показан локальный extractive fallback по разрешённым источникам.
                </p>
              ) : answer.provider_mock ? (
                <p className="state-panel state-panel-warning">
                  Локальная AI-симуляция: ответ собран из разрешённых источников без вызова внешнего LLM.
                </p>
              ) : (
                <p className="state-panel state-panel-neutral">
                  Ответ получен от внешнего provider и подтверждён указанными ниже источниками.
                </p>
              )}
              <p className="rag-answer-text">{answer.answer}</p>
              <div className="rag-answer-meta">
                <span>requested {answer.requested_provider} · effective {answer.provider}</span>
                <span>{answer.model} · {answer.execution_mode}</span>
                <span>{answer.latency_ms} ms</span>
                <span>{answer.citations.length} цитат</span>
              </div>
              <div className="rag-citations">
                {answer.citations.map((citation) => (
                  <a
                    className="rag-citation"
                    href={citation.url_path}
                    key={`${citation.source_type}:${citation.source_id}`}
                  >
                    <span>{citation.citation_id} · {translate(SOURCE_LABELS[citation.source_type])}</span>
                    <strong>{citation.source_key} · {citation.title}</strong>
                    <p>{citation.excerpt}</p>
                    <small>
                      relevance {Math.round(citation.score * 100)}% · source {citation.source_updated_at.slice(0, 10)}
                    </small>
                  </a>
                ))}
              </div>
              {(answer.permission_denied_count > 0
                || answer.stale_count > 0
                || answer.unsafe_source_count > 0) ? (
                  <p className="rag-filter-note">
                    Исключено политиками: ACL {answer.permission_denied_count},
                    устаревших {answer.stale_count}, небезопасных {answer.unsafe_source_count}.
                  </p>
                ) : null}
            </>
          ) : (
            <p className="empty-state">
              Здесь появится ответ вместе с кликабельными доказательствами.
              Без разрешённых источников Copilot не будет додумывать факты.
            </p>
          )}
        </article>
      </div>

      <div className="rag-health-strip">
        <div><span>Документы</span><strong>{dashboardQuery.data?.active_documents ?? '—'}</strong></div>
        <div><span>Grounded rate</span><strong>{dashboardQuery.data ? `${groundedRate}%` : '—'}</strong></div>
        <div><span>Stale blocked</span><strong>{dashboardQuery.data?.stale_sources_blocked ?? '—'}</strong></div>
        <div><span>ACL denied</span><strong>{dashboardQuery.data?.permission_denials ?? '—'}</strong></div>
        <div><span>Injection blocked</span><strong>{dashboardQuery.data?.injection_attempts ?? '—'}</strong></div>
        <div>
          <span>Последняя индексация</span>
          <strong>
            {dashboardQuery.data?.latest_ingestion
              ? dashboardQuery.data.latest_ingestion.status
              : 'не запускалась'}
          </strong>
        </div>
      </div>
    </section>
    </LocalizedContent>
  )
}
