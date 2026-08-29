import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  confirmCatalogKnowledgeDeflection,
  fetchCatalogKnowledgeSuggestions,
  type CatalogItem,
} from '../api/client'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

type Props = {
  accessToken: string
  item: CatalogItem
  enabled: boolean
  onResolved: (articleTitle: string) => void
}

export default function CatalogKnowledgeDeflection({
  accessToken,
  item,
  enabled,
  onResolved,
}: Props) {
  const { t } = useTenantExperience()
  const suggestionsQuery = useQuery({
    queryKey: ['catalog-knowledge-suggestions', accessToken, item.id],
    queryFn: () => fetchCatalogKnowledgeSuggestions(accessToken, item.id),
    enabled: Boolean(accessToken && enabled),
    staleTime: 60_000,
  })
  const resolvedMutation = useMutation({
    mutationFn: (articleId: string) =>
      confirmCatalogKnowledgeDeflection(accessToken, item.id, articleId),
    onSuccess: (_result, articleId) => {
      const article = suggestionsQuery.data?.find((entry) => entry.id === articleId)
      onResolved(article?.title ?? t('catalog.deflection.fallbackArticle'))
    },
  })

  if (!enabled) return null
  if (suggestionsQuery.isPending) {
    return (
      <LocalizedContent>
      <section className="catalog-deflection-panel" aria-live="polite">
        <strong>Проверяем базу знаний…</strong>
        <span>Ищем инструкцию, которая может решить вопрос без заявки.</span>
      </section>
      </LocalizedContent>
    )
  }
  if (suggestionsQuery.isError || !suggestionsQuery.data?.length) return null

  return (
    <LocalizedContent>
    <section className="catalog-deflection-panel" aria-labelledby="catalog-deflection-title">
      <header>
        <div>
          <p className="eyebrow">KNOWLEDGE DEFLECTION</p>
          <h3 id="catalog-deflection-title">Возможно, заявка не нужна</h3>
          <p>Сначала проверьте короткие инструкции. Если они не подходят, форма заказа остаётся ниже.</p>
        </div>
        <span>{suggestionsQuery.data.length} подсказки</span>
      </header>
      <div className="catalog-deflection-list">
        {suggestionsQuery.data.map((article) => (
          <article key={article.id}>
            <div className="catalog-deflection-meta">
              <span>{article.article_number}</span>
              <span>{article.category_name ?? 'База знаний'}</span>
              <span>Полезно: {article.helpful_count}</span>
            </div>
            <h4>{article.title}</h4>
            <p>{article.summary}</p>
            <details>
              <summary>Показать инструкцию</summary>
              <p>{article.content_preview}</p>
            </details>
            <footer>
              <Link
                className="ghost-button catalog-deflection-link"
                to={`/knowledge?article_id=${encodeURIComponent(article.id)}`}
              >
                Открыть статью
              </Link>
              <button
                type="button"
                disabled={resolvedMutation.isPending}
                onClick={() => resolvedMutation.mutate(article.id)}
              >
                Инструкция помогла — заявка не нужна
              </button>
            </footer>
          </article>
        ))}
      </div>
      {resolvedMutation.isError ? (
        <p className="catalog-runtime-error" role="alert">
          Не удалось зафиксировать результат. Вы всё равно можете открыть статью или создать заявку.
        </p>
      ) : null}
    </section>
    </LocalizedContent>
  )
}
