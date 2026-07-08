import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addKnowledgeFeedback,
  createKnowledgeArticle,
  fetchKnowledgeArticle,
  fetchKnowledgeArticles,
  fetchKnowledgeCategories,
  searchKnowledge,
  type CreateKnowledgeArticleRequest,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

type ArticleFormState = {
  title: string
  summary: string
  content: string
  category_id: string
  ticket_category: string
  asset_type: string
  tags: string
}

const emptyForm: ArticleFormState = {
  title: '',
  summary: '',
  content: '',
  category_id: '',
  ticket_category: '',
  asset_type: '',
  tags: '',
}

export default function KnowledgePage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('ALL')
  const [tagFilter, setTagFilter] = useState('')
  const [selectedArticleId, setSelectedArticleId] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [form, setForm] = useState<ArticleFormState>(emptyForm)

  const categoriesQuery = useQuery({
    queryKey: ['knowledge-categories', session?.access_token],
    queryFn: () => fetchKnowledgeCategories(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const articlesQuery = useQuery({
    queryKey: ['knowledge-articles', session?.access_token],
    queryFn: () => fetchKnowledgeArticles(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const searchQuery = useQuery({
    queryKey: ['knowledge-search', session?.access_token, search],
    queryFn: () => searchKnowledge(session?.access_token ?? '', search),
    enabled: Boolean(session?.access_token && search.trim().length > 1),
  })

  const articleQuery = useQuery({
    queryKey: ['knowledge-article', session?.access_token, selectedArticleId],
    queryFn: () => fetchKnowledgeArticle(session?.access_token ?? '', selectedArticleId ?? ''),
    enabled: Boolean(session?.access_token && selectedArticleId),
  })

  const createMutation = useMutation({
    mutationFn: async (payload: CreateKnowledgeArticleRequest) => {
      if (!session?.access_token) throw new Error('No session')
      return createKnowledgeArticle(session.access_token, payload)
    },
    onSuccess: async (article) => {
      setIsCreateOpen(false)
      setForm(emptyForm)
      setSelectedArticleId(article.id)
      await queryClient.invalidateQueries({ queryKey: ['knowledge-articles'] })
      await queryClient.invalidateQueries({ queryKey: ['knowledge-search'] })
    },
  })

  const feedbackMutation = useMutation({
    mutationFn: async (payload: { articleId: string; isHelpful: boolean }) => {
      if (!session?.access_token) throw new Error('No session')
      return addKnowledgeFeedback(session.access_token, payload.articleId, { is_helpful: payload.isHelpful })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['knowledge-articles'] })
      await queryClient.invalidateQueries({ queryKey: ['knowledge-article', session?.access_token, selectedArticleId] })
      await queryClient.invalidateQueries({ queryKey: ['knowledge-search'] })
    },
  })

  const categories = categoriesQuery.data ?? []
  const allArticles = search.trim().length > 1 ? (searchQuery.data ?? []) : (articlesQuery.data ?? [])

  const filteredArticles = useMemo(() => {
    return allArticles.filter((article) => {
      const categoryMatch = categoryFilter === 'ALL' || article.category_id === categoryFilter
      const tagMatch = !tagFilter.trim() || article.tags.some((tag) => tag.toLowerCase().includes(tagFilter.trim().toLowerCase()))
      return categoryMatch && tagMatch
    })
  }, [allArticles, categoryFilter, tagFilter])

  const selectedArticle = articleQuery.data
  const publishedCount = allArticles.filter((article) => article.status === 'published').length
  const topHelpful = [...allArticles]
    .sort((left, right) => right.helpful_count - left.helpful_count)
    .slice(0, 5)

  return (
    <AppShell title="База знаний" subtitle="Типовые решения, связи с категориями заявок и активами, и обратная связь от команды.">
      <section className="foundation-card">
        <div>
          <p className="eyebrow">KNOWLEDGE BASE</p>
          <h2>Операционная база решений</h2>
          <p>Экран объединяет поиск, фильтры, карточку статьи и feedback, чтобы команда быстрее решала типовые инциденты.</p>
        </div>
        <div className="status-column">
          <HealthBadge />
          <div className="status-list">
            <span>✓ Search and filters</span>
            <span>✓ Article feedback</span>
            <span>✓ Ticket and asset links</span>
          </div>
        </div>
      </section>

      <section className="metric-grid">
        <article className="metric-card">
          <span>Всего статей</span>
          <strong>{articlesQuery.isPending ? '…' : allArticles.length}</strong>
          <p>База инструкций для операторов и инженеров.</p>
        </article>
        <article className="metric-card">
          <span>Опубликовано</span>
          <strong>{articlesQuery.isPending ? '…' : publishedCount}</strong>
          <p>Статьи со статусом published.</p>
        </article>
        <article className="metric-card">
          <span>Категорий</span>
          <strong>{categoriesQuery.isPending ? '…' : categories.length}</strong>
          <p>Темы базы знаний по направлениям.</p>
        </article>
        <article className="metric-card">
          <span>Статус API</span>
          <strong>{articlesQuery.isError ? 'Ошибка' : 'OK'}</strong>
          <p>{articlesQuery.isError ? 'Не удалось загрузить статьи.' : 'Сервис базы знаний доступен.'}</p>
        </article>
      </section>

      <section className="foundation-card tickets-toolbar">
        <div className="tickets-toolbar-group">
          <label className="inline-field">
            <span>Поиск</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Название, summary, тег..." />
          </label>
          <label className="inline-field">
            <span>Категория</span>
            <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
              <option value="ALL">Все категории</option>
              {categories.map((category) => (
                <option key={category.id} value={category.id}>
                  {category.name}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Тег</span>
            <input value={tagFilter} onChange={(event) => setTagFilter(event.target.value)} placeholder="network, printer, security" />
          </label>
        </div>
        <button type="button" className="ghost-button tickets-create-button" onClick={() => setIsCreateOpen(true)}>
          Создать статью
        </button>
      </section>

      <section className="asset-list-shell">
        {articlesQuery.isPending ? (
          <p className="muted">Загрузка базы знаний…</p>
        ) : articlesQuery.isError ? (
          <p className="error-message">Не удалось получить статьи.</p>
        ) : (
          <div className="asset-table-layout">
            <div className="asset-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>№</th>
                    <th>Статья</th>
                    <th>Категория</th>
                    <th>Теги</th>
                    <th>Статус</th>
                    <th>Полезно</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredArticles.map((article) => (
                    <tr key={article.id} className={selectedArticleId === article.id ? 'row-selected' : ''}>
                      <td>{article.article_number}</td>
                      <td>
                        <strong>{article.title}</strong>
                        <p className="table-subtext">{article.summary}</p>
                      </td>
                      <td>{article.category_name ?? '—'}</td>
                      <td>{article.tags.slice(0, 3).join(', ') || '—'}</td>
                      <td>{article.status}</td>
                      <td>{article.helpful_count} / {article.not_helpful_count}</td>
                      <td>
                        <button type="button" className="ghost-button row-action" onClick={() => setSelectedArticleId(article.id)}>
                          Открыть
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <aside className="asset-detail-panel">
              {!selectedArticle ? (
                <p className="muted">Выберите статью, чтобы увидеть подробности.</p>
              ) : (
                <>
                  <p className="eyebrow">КАРТОЧКА СТАТЬИ</p>
                  <h3>{selectedArticle.title}</h3>
                  <p className="asset-description">{selectedArticle.summary}</p>
                  <p>{selectedArticle.content}</p>
                  <div className="detail-fields">
                    <div><span>Категория</span><strong>{selectedArticle.category_name ?? '—'}</strong></div>
                    <div><span>Ticket category</span><strong>{selectedArticle.ticket_category ?? '—'}</strong></div>
                    <div><span>Asset type</span><strong>{selectedArticle.asset_type ?? '—'}</strong></div>
                    <div><span>Теги</span><strong>{selectedArticle.tags.join(', ') || '—'}</strong></div>
                    <div><span>Автор</span><strong>{selectedArticle.author_name}</strong></div>
                    <div><span>Публикация</span><strong>{formatDate(selectedArticle.published_at)}</strong></div>
                  </div>
                  <div className="status-list">
                    <span>👍 Helpful: {selectedArticle.helpful_count}</span>
                    <span>👎 Not helpful: {selectedArticle.not_helpful_count}</span>
                  </div>
                  <div className="form-stack">
                    <button type="button" onClick={() => feedbackMutation.mutate({ articleId: selectedArticle.id, isHelpful: true })}>Полезно</button>
                    <button type="button" className="ghost-button" onClick={() => feedbackMutation.mutate({ articleId: selectedArticle.id, isHelpful: false })}>Не полезно</button>
                  </div>
                </>
              )}
            </aside>
          </div>
        )}
      </section>

      <section className="foundation-card dashboard-split">
        <div>
          <p className="eyebrow">TOP ARTICLES</p>
          <h2>Лидеры по полезности</h2>
          <div className="mini-bars">
            {topHelpful.map((article) => (
              <div className="mini-bar-row" key={article.id}>
                <span>{article.article_number}</span>
                <div className="mini-bar-track">
                  <div className="mini-bar-fill" style={{ width: `${Math.max(12, article.helpful_count * 10)}%` }} />
                </div>
                <strong>{article.helpful_count}</strong>
              </div>
            ))}
          </div>
        </div>
      </section>

      {isCreateOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsCreateOpen(false)}>
          <div className="modal-card modal-card-large" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <p className="eyebrow">НОВАЯ СТАТЬЯ</p>
                <h2>Создать статью базы знаний</h2>
              </div>
              <button type="button" className="ghost-button" onClick={() => setIsCreateOpen(false)}>Закрыть</button>
            </div>
            <form
              className="modal-form"
              onSubmit={(event) => {
                event.preventDefault()
                createMutation.mutate({
                  title: form.title,
                  summary: form.summary,
                  content: form.content,
                  category_id: form.category_id || categories[0]?.id || '',
                  ticket_category: form.ticket_category || null,
                  asset_type: form.asset_type || null,
                  tags: form.tags.split(',').map((item) => item.trim()).filter(Boolean),
                  status: 'draft',
                  visibility: 'internal',
                })
              }}
            >
              <div className="form-grid">
                <label>
                  <span>Название</span>
                  <input value={form.title} onChange={(event) => setForm((state) => ({ ...state, title: event.target.value }))} />
                </label>
                <label>
                  <span>Категория</span>
                  <select value={form.category_id} onChange={(event) => setForm((state) => ({ ...state, category_id: event.target.value }))}>
                    <option value="">Выберите</option>
                    {categories.map((category) => (
                      <option key={category.id} value={category.id}>{category.name}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Ticket category</span>
                  <input value={form.ticket_category} onChange={(event) => setForm((state) => ({ ...state, ticket_category: event.target.value }))} />
                </label>
                <label>
                  <span>Asset type</span>
                  <input value={form.asset_type} onChange={(event) => setForm((state) => ({ ...state, asset_type: event.target.value }))} />
                </label>
                <label>
                  <span>Теги (через запятую)</span>
                  <input value={form.tags} onChange={(event) => setForm((state) => ({ ...state, tags: event.target.value }))} />
                </label>
              </div>
              <label>
                <span>Кратко</span>
                <textarea rows={2} value={form.summary} onChange={(event) => setForm((state) => ({ ...state, summary: event.target.value }))} />
              </label>
              <label>
                <span>Решение</span>
                <textarea rows={6} value={form.content} onChange={(event) => setForm((state) => ({ ...state, content: event.target.value }))} />
              </label>
              <button type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? 'Сохранение…' : 'Создать статью'}</button>
            </form>
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}
