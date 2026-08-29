import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import {
  archiveKnowledgeArticle,
  createKnowledgeCategory,
  createKnowledgeArticle,
  fetchKnowledgeArticle,
  fetchKnowledgeArticlesPage,
  fetchKnowledgeCategories,
  publishKnowledgeArticle,
  submitKnowledgeFeedback,
  updateKnowledgeArticle,
  type CreateKnowledgeArticleRequest,
  type KnowledgeArticle,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const subnavItems = ['Статьи', 'Категории', 'Черновики', 'Использование', 'Feedback', 'AI Suggestions'] as const

type SubnavKey = (typeof subnavItems)[number]
type DetailTab = 'Обзор' | 'Контент' | 'Связанные заявки' | 'Использование' | 'Feedback'

type ArticleForm = {
  title: string
  summary: string
  content: string
  category_id: string
  visibility: string
  status: string
  tags: string
}

const emptyForm: ArticleForm = {
  title: '',
  summary: '',
  content: '',
  category_id: '',
  visibility: 'internal',
  status: 'draft',
  tags: '',
}

export default function KnowledgePage() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const permissions = new Set(session?.user.permissions ?? [])

  const canCreate = permissions.has('knowledge.create')
  const canUpdate = permissions.has('knowledge.update')
  const canPublish = permissions.has('knowledge.publish')
  const canArchive = permissions.has('knowledge.archive')
  const canFeedback = permissions.has('knowledge.feedback')

  const [activeSubnav, setActiveSubnav] = useState<SubnavKey>('Статьи')
  const [detailTab, setDetailTab] = useState<DetailTab>('Обзор')
  const [selectedArticleId, setSelectedArticleId] = useState<string | null>(
    () => searchParams.get('article_id'),
  )
  const [editingArticle, setEditingArticle] = useState<KnowledgeArticle | null>(null)
  const [isFormOpen, setIsFormOpen] = useState(false)
  const [form, setForm] = useState<ArticleForm>(emptyForm)
  const [categoryForm, setCategoryForm] = useState({
    code: '',
    name: '',
    description: '',
  })

  const [q, setQ] = useState('')
  const [categoryId, setCategoryId] = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [visibilityFilter, setVisibilityFilter] = useState('ALL')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)

  function openArticle(articleId: string) {
    setSelectedArticleId(articleId)
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.set('article_id', articleId)
      return next
    }, { replace: true })
  }

  function closeArticle() {
    setSelectedArticleId(null)
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      next.delete('article_id')
      return next
    }, { replace: true })
  }

  const formDialogRef = useDialogFocusTrap<HTMLDivElement>(
    isFormOpen,
    () => setIsFormOpen(false),
  )
  const detailDialogRef = useDialogFocusTrap<HTMLDivElement>(
    Boolean(selectedArticleId),
    closeArticle,
  )

  useEffect(() => {
    const linkedArticleId = searchParams.get('article_id')
    if (linkedArticleId && linkedArticleId !== selectedArticleId) {
      setSelectedArticleId(linkedArticleId)
    }
  }, [searchParams, selectedArticleId])

  useEffect(() => {
    setPage(1)
  }, [q, categoryId, statusFilter, visibilityFilter, pageSize])

  const categoriesQuery = useQuery({
    queryKey: ['knowledge-categories', session?.access_token],
    queryFn: () => fetchKnowledgeCategories(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const articlesPageQuery = useQuery({
    queryKey: ['knowledge-articles-page', session?.access_token, q, categoryId, statusFilter, visibilityFilter, page, pageSize, activeSubnav],
    queryFn: () =>
      fetchKnowledgeArticlesPage(session?.access_token ?? '', {
        q: q || undefined,
        category_id: categoryId !== 'ALL' ? categoryId : undefined,
        status: activeSubnav === 'Черновики' ? 'draft' : statusFilter,
        visibility: visibilityFilter,
        page,
        page_size: pageSize,
        sort_by: activeSubnav === 'Использование' ? 'view_count' : 'updated_at',
        sort_dir: 'desc',
      }),
    enabled: Boolean(session?.access_token),
  })

  const articleQuery = useQuery({
    queryKey: ['knowledge-article', session?.access_token, selectedArticleId],
    queryFn: () => fetchKnowledgeArticle(session?.access_token ?? '', selectedArticleId ?? ''),
    enabled: Boolean(session?.access_token && selectedArticleId),
  })
  const categoryMutation = useMutation({
    mutationFn: () => createKnowledgeCategory(session?.access_token ?? '', categoryForm),
    onSuccess: async (category) => {
      setCategoryForm({ code: '', name: '', description: '' })
      setForm((current) => ({ ...current, category_id: current.category_id || category.id }))
      await queryClient.invalidateQueries({ queryKey: ['knowledge-categories'] })
    },
  })

  const createMutation = useMutation({
    mutationFn: async (payload: CreateKnowledgeArticleRequest) => {
      if (!session?.access_token) throw new Error('No session')
      return createKnowledgeArticle(session.access_token, payload)
    },
    onSuccess: async (article) => {
      setIsFormOpen(false)
      setForm(emptyForm)
      openArticle(article.id)
      await queryClient.invalidateQueries({ queryKey: ['knowledge-articles-page'] })
    },
  })

  const updateMutation = useMutation({
    mutationFn: async (payload: { articleId: string; body: Partial<CreateKnowledgeArticleRequest> }) => {
      if (!session?.access_token) throw new Error('No session')
      return updateKnowledgeArticle(session.access_token, payload.articleId, payload.body)
    },
    onSuccess: async (article) => {
      setIsFormOpen(false)
      setEditingArticle(null)
      setForm(emptyForm)
      openArticle(article.id)
      await queryClient.invalidateQueries({ queryKey: ['knowledge-articles-page'] })
      await queryClient.invalidateQueries({ queryKey: ['knowledge-article'] })
    },
  })

  const publishMutation = useMutation({
    mutationFn: async (articleId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return publishKnowledgeArticle(session.access_token, articleId)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['knowledge-articles-page'] })
      await queryClient.invalidateQueries({ queryKey: ['knowledge-article'] })
    },
  })

  const archiveMutation = useMutation({
    mutationFn: async (articleId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return archiveKnowledgeArticle(session.access_token, articleId)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['knowledge-articles-page'] })
      await queryClient.invalidateQueries({ queryKey: ['knowledge-article'] })
    },
  })

  const feedbackMutation = useMutation({
    mutationFn: async (payload: { articleId: string; isHelpful: boolean }) => {
      if (!session?.access_token) throw new Error('No session')
      return submitKnowledgeFeedback(session.access_token, payload.articleId, { is_helpful: payload.isHelpful })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['knowledge-articles-page'] })
      await queryClient.invalidateQueries({ queryKey: ['knowledge-article'] })
    },
  })

  const categories = categoriesQuery.data ?? []
  const articlePage = articlesPageQuery.data
  const articles = articlePage?.items ?? []
  const selectedArticle = articleQuery.data
  const total = articlePage?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const usageTop = useMemo(() => [...articles].sort((a, b) => (b.view_count ?? 0) - (a.view_count ?? 0)).slice(0, 10), [articles])

  return (
    <AppShell title="База знаний" subtitle="Инструкции, решения, статьи и база типовых инцидентов для ИТ-службы.">
      <nav className="module-subnav" aria-label="Knowledge subnav">
        {subnavItems.map((item) => (
          <button key={item} type="button" className={`module-subnav-tab ${activeSubnav === item ? 'active' : ''}`} onClick={() => setActiveSubnav(item)}>
            {translate(item)}
          </button>
        ))}
      </nav>

      <section className="foundation-card tickets-toolbar" style={{ marginTop: 14 }}>
        <div className="tickets-toolbar-group" style={{ gridTemplateColumns: 'repeat(6, minmax(0, 1fr))' }}>
          <label className="inline-field">
            <span>Поиск</span>
            <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="Заголовок, summary, теги" />
          </label>
          <label className="inline-field">
            <span>Категория</span>
            <select value={categoryId} onChange={(event) => setCategoryId(event.target.value)}>
              <option value="ALL">Все</option>
              {categories.map((item) => (
                <option key={item.id} value={item.id}>{item.name}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Статус</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="ALL">Все</option>
              <option value="draft">draft</option>
              <option value="published">published</option>
              <option value="archived">archived</option>
            </select>
          </label>
          <label className="inline-field">
            <span>Видимость</span>
            <select value={visibilityFilter} onChange={(event) => setVisibilityFilter(event.target.value)}>
              <option value="ALL">Все</option>
              <option value="internal">internal</option>
              <option value="public">public</option>
            </select>
          </label>
          <label className="inline-field">
            <span>На страницу</span>
            <select value={String(pageSize)} onChange={(event) => setPageSize(Number(event.target.value))}>
              <option value="10">10</option>
              <option value="20">20</option>
              <option value="50">50</option>
            </select>
          </label>
          <div className="inline-field">
            <span>Всего</span>
            <strong>{total}</strong>
          </div>
        </div>
        <button
          type="button"
          className="ghost-button tickets-create-button"
          disabled={!canCreate}
          title={!canCreate ? 'Нет прав knowledge.create' : undefined}
          onClick={() => {
            setEditingArticle(null)
            setForm({ ...emptyForm, category_id: categories[0]?.id ?? '' })
            setIsFormOpen(true)
          }}
        >
          Создать статью
        </button>
      </section>

      {activeSubnav === 'Категории' ? (
        <section className="section-card" style={{ marginTop: 14 }}>
          <header className="section-header">
            <h3 className="section-title">Категории</h3>
            <p className="section-subtitle">Справочник категорий базы знаний.</p>
          </header>
          {canCreate ? (
            <form
              className="knowledge-category-form"
              onSubmit={(event) => {
                event.preventDefault()
                categoryMutation.mutate()
              }}
            >
              <label>
                <span>Код</span>
                <input
                  required
                  value={categoryForm.code}
                  onChange={(event) => setCategoryForm((current) => ({ ...current, code: event.target.value }))}
                  placeholder="ACCESS"
                />
              </label>
              <label>
                <span>Название</span>
                <input
                  required
                  value={categoryForm.name}
                  onChange={(event) => setCategoryForm((current) => ({ ...current, name: event.target.value }))}
                  placeholder="Доступ и учётные записи"
                />
              </label>
              <label>
                <span>Описание</span>
                <input
                  value={categoryForm.description}
                  onChange={(event) => setCategoryForm((current) => ({ ...current, description: event.target.value }))}
                  placeholder="Инструкции по доступам и ролям"
                />
              </label>
              <button type="submit" disabled={categoryMutation.isPending}>
                {categoryMutation.isPending ? 'Создаём…' : 'Создать категорию'}
              </button>
            </form>
          ) : null}
          {categoryMutation.isError ? (
            <p className="error-message" role="alert">
              {categoryMutation.error instanceof Error ? categoryMutation.error.message : 'Не удалось создать категорию.'}
            </p>
          ) : null}
          <div className="activity-list">
            {categories.map((item) => (
              <article key={item.id} className="activity-item">
                <header><strong>{item.name}</strong><span>{item.code}</span></header>
                <p>{item.description ?? 'Описание отсутствует.'}</p>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      {activeSubnav === 'AI Suggestions' ? (
        <section className="section-card" style={{ marginTop: 14 }}>
          <header className="section-header">
            <h3 className="section-title">AI Suggestions</h3>
            <p className="section-subtitle">Для действий с AI рекомендациями используйте страницу Copilot и раздел AI/Knowledge в заявке.</p>
          </header>
        </section>
      ) : null}

      {activeSubnav !== 'Категории' && activeSubnav !== 'AI Suggestions' ? (
        <section className="ticket-table-shell" style={{ marginTop: 14 }}>
          {articlesPageQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка статей...</p> : null}
          {articlesPageQuery.isError ? <p className="error-message">Не удалось получить статьи.</p> : null}
          {!articlesPageQuery.isPending && !articlesPageQuery.isError ? (
            <>
              <div className="ticket-table-wrap">
                <table className="ticket-table">
                  <thead>
                    <tr>
                      <th>Title</th>
                      <th>Категория</th>
                      <th>Status</th>
                      <th>Visibility</th>
                      <th>Tags</th>
                      <th>Views</th>
                      <th>Helpful</th>
                      <th>Updated</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {articles.length === 0 ? (
                      <tr>
                        <td colSpan={9}><p className="state-panel state-panel-empty">Статьи не найдены по текущим фильтрам.</p></td>
                      </tr>
                    ) : null}
                    {articles.map((article) => (
                      <tr key={article.id}>
                        <td>
                          <strong>{article.title}</strong>
                          <p className="table-subtext">{article.summary}</p>
                        </td>
                        <td>{article.category_name ?? '—'}</td>
                        <td>{translate(article.status)}</td>
                        <td>{translate(article.visibility)}</td>
                        <td>{article.tags.join(', ') || '—'}</td>
                        <td>{article.view_count ?? 0}</td>
                        <td>{article.helpful_count} / {article.not_helpful_count}</td>
                        <td>{formatDateTime(article.updated_at)}</td>
                        <td>
                          <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
                            <button type="button" className="ghost-button row-action" onClick={() => { openArticle(article.id); setDetailTab('Обзор') }}>Детали</button>
                            <button
                              type="button"
                              className="ghost-button row-action"
                              disabled={!canUpdate}
                              title={!canUpdate ? 'Нет прав knowledge.update' : undefined}
                              onClick={() => {
                                setEditingArticle(article)
                                setForm({
                                  title: article.title,
                                  summary: article.summary,
                                  content: article.content,
                                  category_id: article.category_id,
                                  visibility: article.visibility,
                                  status: article.status,
                                  tags: article.tags.join(', '),
                                })
                                setIsFormOpen(true)
                              }}
                            >
                              Редактировать
                            </button>
                            <button
                              type="button"
                              className="ghost-button row-action"
                              disabled={!canPublish || article.status === 'published' || publishMutation.isPending}
                              title={!canPublish ? 'Нет прав knowledge.publish' : undefined}
                              onClick={() => publishMutation.mutate(article.id)}
                            >
                              Опубликовать
                            </button>
                            <button
                              type="button"
                              className="ghost-button row-action"
                              disabled={!canArchive || article.status === 'archived' || archiveMutation.isPending}
                              title={!canArchive ? 'Нет прав knowledge.archive' : undefined}
                              onClick={() => archiveMutation.mutate(article.id)}
                            >
                              Архивировать
                            </button>
                            <button
                              type="button"
                              className="ghost-button row-action"
                              disabled={!canFeedback || feedbackMutation.isPending}
                              title={!canFeedback ? 'Нет прав knowledge.feedback' : undefined}
                              onClick={() => {
                                openArticle(article.id)
                                setDetailTab('Feedback')
                              }}
                            >
                              Feedback
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="table-pagination">
                <p className="muted">Показано {articles.length} из {total}</p>
                <div className="analytics-actions">
                  <button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Назад</button>
                  <span className="muted">Страница {page} / {totalPages}</span>
                  <button type="button" className="ghost-button" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>Вперед</button>
                </div>
              </div>

              {activeSubnav === 'Использование' ? (
                <section className="foundation-card" style={{ marginTop: 14 }}>
                  <h3>Топ статей по просмотрам</h3>
                  <div className="activity-list">
                    {usageTop.map((item) => (
                      <article className="activity-item" key={item.id}>
                        <header><strong>{item.title}</strong><span>{item.view_count ?? 0} views</span></header>
                        <p>Last used: {formatDateTime(item.last_used_at)}</p>
                      </article>
                    ))}
                  </div>
                </section>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}

      {isFormOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsFormOpen(false)}>
          <div
            ref={formDialogRef}
            className="modal-card modal-card-large"
            role="dialog"
            aria-modal="true"
            aria-labelledby="knowledge-form-dialog-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">{editingArticle ? 'РЕДАКТИРОВАНИЕ' : 'НОВАЯ СТАТЬЯ'}</p>
                <h2 id="knowledge-form-dialog-title">{editingArticle ? 'Редактировать статью' : 'Создать статью'}</h2>
              </div>
              <button type="button" className="ghost-button" onClick={() => setIsFormOpen(false)}>Закрыть</button>
            </div>
            <form
              className="modal-form"
              onSubmit={(event) => {
                event.preventDefault()
                const body: CreateKnowledgeArticleRequest = {
                  title: form.title,
                  summary: form.summary,
                  content: form.content,
                  category_id: form.category_id || categories[0]?.id || '',
                  visibility: form.visibility,
                  status: canPublish ? form.status : 'draft',
                  tags: form.tags.split(',').map((item) => item.trim()).filter(Boolean),
                }
                if (editingArticle) {
                  updateMutation.mutate({ articleId: editingArticle.id, body })
                } else {
                  createMutation.mutate(body)
                }
              }}
            >
              <div className="form-grid">
                <label><span>Title</span><input required value={form.title} onChange={(event) => setForm((state) => ({ ...state, title: event.target.value }))} /></label>
                <label>
                  <span>Category</span>
                  <select value={form.category_id} onChange={(event) => setForm((state) => ({ ...state, category_id: event.target.value }))}>
                    <option value="">Выберите категорию</option>
                    {categories.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
                  </select>
                </label>
                <label>
                  <span>Visibility</span>
                  <select value={form.visibility} onChange={(event) => setForm((state) => ({ ...state, visibility: event.target.value }))}>
                    <option value="internal">internal</option>
                    <option value="public">public</option>
                  </select>
                </label>
                <label>
                  <span>Status</span>
                  <select value={form.status} disabled={!canPublish} onChange={(event) => setForm((state) => ({ ...state, status: event.target.value }))}>
                    <option value="draft">draft</option>
                    <option value="published">published</option>
                  </select>
                </label>
                <label><span>Tags</span><input value={form.tags} onChange={(event) => setForm((state) => ({ ...state, tags: event.target.value }))} placeholder="network, printer" /></label>
              </div>
              <label><span>Summary</span><textarea rows={3} value={form.summary} onChange={(event) => setForm((state) => ({ ...state, summary: event.target.value }))} /></label>
              <label><span>Content</span><textarea rows={8} value={form.content} onChange={(event) => setForm((state) => ({ ...state, content: event.target.value }))} /></label>
              <button type="submit" disabled={createMutation.isPending || updateMutation.isPending}>{createMutation.isPending || updateMutation.isPending ? 'Сохранение...' : 'Сохранить'}</button>
            </form>
          </div>
        </div>
      ) : null}

      {selectedArticleId ? (
        <div className="modal-backdrop" role="presentation" onClick={closeArticle}>
          <div
            ref={detailDialogRef}
            className="modal-card modal-card-xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="knowledge-detail-dialog-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">СТАТЬЯ</p>
                <h2 id="knowledge-detail-dialog-title">{selectedArticle?.article_number ?? 'Загрузка...'}</h2>
                <p className="modal-subtitle">{selectedArticle?.title ?? ''}</p>
              </div>
              <button type="button" className="ghost-button" onClick={closeArticle}>Закрыть</button>
            </div>

            <section className="module-subnav">
              {(['Обзор', 'Контент', 'Связанные заявки', 'Использование', 'Feedback'] as const).map((tab) => (
                <button key={tab} type="button" className={`module-subnav-tab ${detailTab === tab ? 'active' : ''}`} onClick={() => setDetailTab(tab)}>{translate(tab)}</button>
              ))}
            </section>

            {articleQuery.isPending ? <p className="state-panel state-panel-loading" role="status">Загрузка статьи...</p> : null}
            {articleQuery.isError ? <p className="error-message" role="alert">Не удалось загрузить статью.</p> : null}

            {selectedArticle ? (
              <section className="ticket-detail-panel" style={{ marginTop: 12 }}>
                {detailTab === 'Обзор' ? (
                  <div className="detail-fields">
                    <div><span>Категория</span><strong>{selectedArticle.category_name ?? '—'}</strong></div>
                    <div><span>Status</span><strong>{translate(selectedArticle.status)}</strong></div>
                    <div><span>Visibility</span><strong>{translate(selectedArticle.visibility)}</strong></div>
                    <div><span>Views</span><strong>{selectedArticle.view_count ?? 0}</strong></div>
                    <div><span>Helpful</span><strong>{selectedArticle.helpful_count}</strong></div>
                    <div><span>Not helpful</span><strong>{selectedArticle.not_helpful_count}</strong></div>
                    <div><span>Updated</span><strong>{formatDateTime(selectedArticle.updated_at)}</strong></div>
                    <div><span>Published</span><strong>{formatDateTime(selectedArticle.published_at)}</strong></div>
                  </div>
                ) : null}

                {detailTab === 'Контент' ? (
                  <>
                    <h3>{selectedArticle.summary}</h3>
                    <p>{selectedArticle.content}</p>
                  </>
                ) : null}

                {detailTab === 'Связанные заявки' ? (
                  <div className="detail-fields">
                    <div><span>Source ticket</span><strong>{selectedArticle.source_ticket_id ?? 'Не привязана'}</strong></div>
                    <div><span>Source asset</span><strong>{selectedArticle.source_asset_id ?? 'Не привязан'}</strong></div>
                  </div>
                ) : null}

                {detailTab === 'Использование' ? (
                  <div className="detail-fields">
                    <div><span>Views</span><strong>{selectedArticle.view_count ?? 0}</strong></div>
                    <div><span>Last used</span><strong>{formatDateTime(selectedArticle.last_used_at)}</strong></div>
                  </div>
                ) : null}

                {detailTab === 'Feedback' ? (
                  <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
                    <button
                      type="button"
                      disabled={!canFeedback || feedbackMutation.isPending}
                      title={!canFeedback ? 'Нет прав knowledge.feedback' : undefined}
                      onClick={() => feedbackMutation.mutate({ articleId: selectedArticle.id, isHelpful: true })}
                    >
                      Полезно
                    </button>
                    <button
                      type="button"
                      className="ghost-button"
                      disabled={!canFeedback || feedbackMutation.isPending}
                      title={!canFeedback ? 'Нет прав knowledge.feedback' : undefined}
                      onClick={() => feedbackMutation.mutate({ articleId: selectedArticle.id, isHelpful: false })}
                    >
                      Не полезно
                    </button>
                  </div>
                ) : null}
              </section>
            ) : null}
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}
