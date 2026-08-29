import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createLocalizedContentVariant,
  decideLocalizedContentVariant,
  fetchLocalizedContentSources,
  fetchLocalizedContentVariants,
  fetchTenants,
  submitLocalizedContentVariant,
  updateLocalizedContentVariant,
  type LocalizedContentSource,
  type LocalizedContentVariant,
  type LocalizedResourceType,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const resourceLabels: Record<LocalizedResourceType, string> = {
  KNOWLEDGE_ARTICLE: 'Статьи базы знаний',
  NOTIFICATION_TEMPLATE: 'Шаблоны уведомлений',
}

const statusLabels: Record<LocalizedContentVariant['status'], string> = {
  DRAFT: 'Черновик',
  IN_REVIEW: 'На согласовании',
  PUBLISHED: 'Опубликован',
  REJECTED: 'Отклонён',
  RETIRED: 'Архивная версия',
}

const fieldLabels: Record<string, string> = {
  title: 'Заголовок',
  summary: 'Краткое описание',
  content: 'Содержание',
  name: 'Название шаблона',
  subject_template: 'Тема сообщения',
  body_template: 'Текст сообщения',
}

function fieldsFor(resourceType: LocalizedResourceType) {
  return resourceType === 'KNOWLEDGE_ARTICLE'
    ? ['title', 'summary', 'content']
    : ['name', 'subject_template', 'body_template']
}

function statusClass(status: LocalizedContentVariant['status']) {
  if (status === 'PUBLISHED') return 'badge badge-positive'
  if (status === 'REJECTED') return 'badge badge-danger'
  if (status === 'IN_REVIEW') return 'badge badge-warning'
  return 'badge'
}

function sourceDraft(source: LocalizedContentSource | undefined) {
  return source ? { ...source.payload } : {}
}

export default function LocalizedContentPanel() {
  const { session } = useAuth()
  const { formatDateTime, t, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const canRead = isRoot || permissions.has('tenant.translations.read')
  const canManage = isRoot || permissions.has('tenant.translations.manage')
  const canPublish = isRoot || permissions.has('tenant.translations.publish')
  const [selectedTenantId, setSelectedTenantId] = useState(
    session?.user.tenant_id ?? '',
  )
  const tenantId = isRoot
    ? selectedTenantId || null
    : session?.user.tenant_id ?? null
  const [resourceType, setResourceType] = useState<LocalizedResourceType>(
    'KNOWLEDGE_ARTICLE',
  )
  const [locale, setLocale] = useState('kk-KZ')
  const [sourceId, setSourceId] = useState('')
  const [variantId, setVariantId] = useState('')
  const [newVersionMode, setNewVersionMode] = useState(false)
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [submissionNote, setSubmissionNote] = useState('')
  const [reviewComment, setReviewComment] = useState('')
  const [feedback, setFeedback] = useState<{
    kind: 'success' | 'error'
    message: string
  } | null>(null)

  const tenantsQuery = useQuery({
    queryKey: ['localized-content-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot && canRead),
  })
  const sourcesQuery = useQuery({
    queryKey: ['localized-content-sources', token, tenantId, resourceType],
    queryFn: () => fetchLocalizedContentSources(token, resourceType, tenantId),
    enabled: Boolean(token && tenantId && canRead),
  })
  const variantsQuery = useQuery({
    queryKey: [
      'localized-content-variants',
      token,
      tenantId,
      resourceType,
      sourceId,
      locale,
    ],
    queryFn: () => fetchLocalizedContentVariants(token, {
      tenant_id: tenantId,
      resource_type: resourceType,
      resource_id: sourceId,
      locale,
    }),
    enabled: Boolean(token && tenantId && sourceId && canRead),
  })

  const source = useMemo(
    () => (sourcesQuery.data ?? []).find((item) => item.id === sourceId),
    [sourceId, sourcesQuery.data],
  )
  const variant = useMemo(
    () => (variantsQuery.data ?? []).find((item) => item.id === variantId),
    [variantId, variantsQuery.data],
  )

  useEffect(() => {
    if (!isRoot || selectedTenantId || !(tenantsQuery.data ?? []).length) return
    setSelectedTenantId(tenantsQuery.data?.[0]?.id ?? '')
  }, [isRoot, selectedTenantId, tenantsQuery.data])

  useEffect(() => {
    const sources = sourcesQuery.data ?? []
    if (sources.some((item) => item.id === sourceId)) return
    setSourceId(sources[0]?.id ?? '')
    setVariantId('')
    setNewVersionMode(false)
  }, [sourceId, sourcesQuery.data])

  useEffect(() => {
    if (newVersionMode) return
    const variants = variantsQuery.data ?? []
    if (variants.some((item) => item.id === variantId)) return
    setVariantId(variants[0]?.id ?? '')
  }, [newVersionMode, variantId, variantsQuery.data])

  useEffect(() => {
    if (newVersionMode) {
      setDraft(sourceDraft(source))
      return
    }
    setDraft(variant ? { ...variant.payload } : sourceDraft(source))
  }, [newVersionMode, source, variant])

  const refreshVariants = async () => {
    await queryClient.invalidateQueries({
      queryKey: ['localized-content-variants', token, tenantId, resourceType],
    })
  }
  const selectResult = async (
    result: LocalizedContentVariant,
    message: string,
  ) => {
    setNewVersionMode(false)
    setVariantId(result.id)
    setDraft({ ...result.payload })
    setSubmissionNote('')
    setReviewComment('')
    await refreshVariants()
    setFeedback({ kind: 'success', message })
  }
  const mutationError = (error: unknown, fallback: string) => {
    setFeedback({
      kind: 'error',
      message: error instanceof Error ? error.message : fallback,
    })
  }

  const createMutation = useMutation({
    mutationFn: () => {
      if (!tenantId || !source) throw new Error('Выберите организацию и источник.')
      return createLocalizedContentVariant(token, {
        tenant_id: isRoot ? tenantId : undefined,
        resource_type: resourceType,
        resource_id: source.id,
        locale,
        payload: draft,
      })
    },
    onSuccess: (result) => selectResult(
      result,
      t('localizedContent.createdDraft', { version: result.version }),
    ),
    onError: (error) => mutationError(error, 'Не удалось создать перевод.'),
  })
  const saveMutation = useMutation({
    mutationFn: () => {
      if (!variant) throw new Error('Выберите черновик.')
      return updateLocalizedContentVariant(
        token,
        variant.id,
        variant.revision,
        draft,
        isRoot ? tenantId : undefined,
      )
    },
    onSuccess: (result) => selectResult(
      result,
      t('localizedContent.savedDraft', {
        version: result.version,
        revision: result.revision,
      }),
    ),
    onError: (error) => mutationError(error, 'Не удалось сохранить черновик.'),
  })
  const submitMutation = useMutation({
    mutationFn: () => {
      if (!variant) throw new Error('Выберите черновик.')
      return submitLocalizedContentVariant(
        token,
        variant.id,
        variant.revision,
        submissionNote,
        isRoot ? tenantId : undefined,
      )
    },
    onSuccess: (result) => selectResult(
      result,
      t('localizedContent.submitted', { version: result.version }),
    ),
    onError: (error) => mutationError(error, 'Не удалось отправить на согласование.'),
  })
  const decisionMutation = useMutation({
    mutationFn: (decision: 'APPROVE' | 'REJECT') => {
      if (!variant) throw new Error('Выберите версию на согласовании.')
      return decideLocalizedContentVariant(
        token,
        variant.id,
        variant.revision,
        decision,
        reviewComment,
        isRoot ? tenantId : undefined,
      )
    },
    onSuccess: (result) => selectResult(
      result,
      result.status === 'PUBLISHED'
        ? t('localizedContent.published', { version: result.version })
        : t('localizedContent.rejected', { version: result.version }),
    ),
    onError: (error) => mutationError(error, 'Не удалось принять решение.'),
  })

  if (!canRead) return null

  const busy = (
    createMutation.isPending
    || saveMutation.isPending
    || submitMutation.isPending
    || decisionMutation.isPending
  )
  const editable = Boolean(
    variant
    && canManage
    && ['DRAFT', 'REJECTED'].includes(variant.status),
  )
  const ownReview = (
    variant?.created_by_id === session?.user.id
    || variant?.updated_by_id === session?.user.id
  )
  const reviewable = Boolean(
    variant
    && variant.status === 'IN_REVIEW'
    && canPublish
    && !ownReview
    && variant.source_current
    && variant.integrity_valid,
  )

  return (
    <LocalizedContent>
    <section className="foundation-card admin-panel localized-content-panel">
      <header className="localized-content-header">
        <div>
          <p className="eyebrow">CONTROLLED LOCALIZATION</p>
          <h2>Переводы контента и уведомлений</h2>
          <p>
            Версионирование, независимое согласование, контроль целостности и
            автоматический fallback на исходный текст при устаревании перевода.
          </p>
        </div>
        <div className="localized-content-evidence">
          <span>Four-eyes</span>
          <strong>ENFORCED</strong>
          <small>source + payload SHA-256</small>
        </div>
      </header>

      <div className="localized-content-filters">
        {isRoot ? (
          <label>
            <span>Организация</span>
            <select
              value={selectedTenantId}
              onChange={(event) => {
                setSelectedTenantId(event.target.value)
                setSourceId('')
                setVariantId('')
                setFeedback(null)
              }}
            >
              <option value="">Выберите tenant</option>
              {(tenantsQuery.data ?? []).map((tenant) => (
                <option key={tenant.id} value={tenant.id}>{tenant.name}</option>
              ))}
            </select>
          </label>
        ) : null}
        <label>
          <span>Тип контента</span>
          <select
            value={resourceType}
            onChange={(event) => {
              setResourceType(event.target.value as LocalizedResourceType)
              setSourceId('')
              setVariantId('')
              setNewVersionMode(false)
              setFeedback(null)
            }}
          >
            {(Object.keys(resourceLabels) as LocalizedResourceType[]).map((key) => (
              <option key={key} value={key}>{translate(resourceLabels[key])}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Язык перевода</span>
          <select
            value={locale}
            onChange={(event) => {
              setLocale(event.target.value)
              setVariantId('')
              setNewVersionMode(false)
              setFeedback(null)
            }}
          >
            <option value="kk-KZ">Казахский (kk-KZ)</option>
            <option value="en-US">Английский (en-US)</option>
            <option value="ru-RU">Русский (ru-RU)</option>
          </select>
        </label>
        <label className="localized-source-select">
          <span>Исходный материал</span>
          <select
            value={sourceId}
            onChange={(event) => {
              setSourceId(event.target.value)
              setVariantId('')
              setNewVersionMode(false)
              setFeedback(null)
            }}
            disabled={!tenantId || sourcesQuery.isPending}
          >
            <option value="">Выберите источник</option>
            {(sourcesQuery.data ?? []).map((item) => (
              <option key={item.id} value={item.id}>
                {item.code} · {item.label}{item.inherited ? ' · GLOBAL' : ''}
              </option>
            ))}
          </select>
        </label>
      </div>

      {sourcesQuery.isPending ? (
        <p className="state-panel state-panel-loading" role="status">
          Загрузка доступных источников…
        </p>
      ) : null}
      {sourcesQuery.isError ? (
        <div className="state-panel state-panel-error" role="alert">
          <p>
            {sourcesQuery.error instanceof Error
              ? sourcesQuery.error.message
              : 'Не удалось загрузить источники.'}
          </p>
          <button type="button" onClick={() => sourcesQuery.refetch()}>
            Повторить
          </button>
        </div>
      ) : null}
      {feedback ? (
        <div
          className={feedback.kind === 'error' ? 'error-banner' : 'success-banner'}
          role={feedback.kind === 'error' ? 'alert' : 'status'}
        >
          {feedback.message}
        </div>
      ) : null}

      {source ? (
        <div className="localized-content-workspace">
          <section className="localized-content-editor">
            <header>
              <div>
                <h3>
                  {newVersionMode
                    ? 'Новая управляемая версия'
                    : variant
                      ? t('localizedContent.version', { version: variant.version })
                      : 'Первая версия перевода'}
                </h3>
                <p className="muted">
                  Источник: {source.code} ·{' '}
                  <code>{source.source_sha256.slice(0, 12)}</code>
                </p>
              </div>
              {variant && !newVersionMode ? (
                <span className={statusClass(variant.status)}>
                  {translate(statusLabels[variant.status])}
                </span>
              ) : null}
            </header>

            {variant && (!variant.integrity_valid || !variant.source_current) ? (
              <div className="warning-banner" role="alert">
                {!variant.integrity_valid
                  ? 'Нарушена целостность payload. Публикация заблокирована.'
                  : 'Исходный материал изменился. Эта версия устарела; система использует исходный текст.'}
              </div>
            ) : null}
            {resourceType === 'NOTIFICATION_TEMPLATE' ? (
              <p className="localized-placeholder-rule">
                Плейсхолдеры вида <code>{'{{ticket_number}}'}</code> должны
                полностью совпадать с исходным шаблоном.
              </p>
            ) : null}

            <form
              onSubmit={(event) => {
                event.preventDefault()
                setFeedback(null)
                if (newVersionMode || !variant) createMutation.mutate()
                else saveMutation.mutate()
              }}
            >
              {fieldsFor(resourceType).map((field) => (
                <label key={field}>
                  <span>{translate(fieldLabels[field])}</span>
                  {field === 'content' || field === 'body_template' ? (
                    <textarea
                      value={draft[field] ?? ''}
                      minLength={2}
                      maxLength={field === 'content' ? 100_000 : 20_000}
                      rows={field === 'content' ? 14 : 9}
                      disabled={!canManage || (!newVersionMode && variant != null && !editable)}
                      onChange={(event) => setDraft({
                        ...draft,
                        [field]: event.target.value,
                      })}
                    />
                  ) : (
                    <input
                      value={draft[field] ?? ''}
                      minLength={2}
                      maxLength={field.includes('subject') || field === 'title' ? 255 : 5_000}
                      disabled={!canManage || (!newVersionMode && variant != null && !editable)}
                      onChange={(event) => setDraft({
                        ...draft,
                        [field]: event.target.value,
                      })}
                    />
                  )}
                </label>
              ))}
              <div className="localized-content-actions">
                <button
                  type="submit"
                  disabled={
                    busy
                    || !canManage
                    || Boolean(variant && !newVersionMode && !editable)
                  }
                >
                  {newVersionMode || !variant ? 'Создать черновик' : 'Сохранить черновик'}
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={!canManage || busy}
                  onClick={() => {
                    setNewVersionMode(true)
                    setVariantId('')
                    setDraft(sourceDraft(source))
                    setFeedback(null)
                  }}
                >
                  Новая версия
                </button>
              </div>
            </form>

            {variant && variant.status === 'DRAFT' && !newVersionMode ? (
              <section className="localized-content-gate">
                <label>
                  <span>Примечание для согласующего</span>
                  <textarea
                    value={submissionNote}
                    minLength={5}
                    maxLength={500}
                    rows={3}
                    disabled={!canManage}
                    onChange={(event) => setSubmissionNote(event.target.value)}
                  />
                </label>
                <button
                  type="button"
                  disabled={
                    busy
                    || !canManage
                    || submissionNote.trim().length < 5
                    || !variant.integrity_valid
                    || !variant.source_current
                  }
                  onClick={() => submitMutation.mutate()}
                >
                  Передать на согласование
                </button>
              </section>
            ) : null}

            {variant && variant.status === 'IN_REVIEW' && !newVersionMode ? (
              <section className="localized-content-gate">
                {ownReview ? (
                  <p className="warning-banner" role="status">
                    Автор не может согласовать собственную версию. Требуется
                    другой пользователь с правом публикации.
                  </p>
                ) : null}
                <label>
                  <span>Комментарий согласующего</span>
                  <textarea
                    value={reviewComment}
                    minLength={5}
                    maxLength={1_000}
                    rows={3}
                    disabled={!canPublish || ownReview}
                    onChange={(event) => setReviewComment(event.target.value)}
                  />
                </label>
                <div className="localized-content-actions">
                  <button
                    type="button"
                    disabled={busy || !reviewable || reviewComment.trim().length < 5}
                    onClick={() => decisionMutation.mutate('APPROVE')}
                  >
                    Согласовать и опубликовать
                  </button>
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={busy || !reviewable || reviewComment.trim().length < 5}
                    onClick={() => decisionMutation.mutate('REJECT')}
                  >
                    Отклонить
                  </button>
                </div>
              </section>
            ) : null}
          </section>

          <aside className="localized-content-history">
            <header>
              <h3>История версий</h3>
              {variantsQuery.isFetching ? <span role="status">Обновление…</span> : null}
            </header>
            {(variantsQuery.data ?? []).length === 0 ? (
              <p className="empty-state">
                Для выбранного языка ещё нет управляемых версий.
              </p>
            ) : (
              <ol>
                {(variantsQuery.data ?? []).map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className={item.id === variantId ? 'active' : ''}
                      onClick={() => {
                        setNewVersionMode(false)
                        setVariantId(item.id)
                        setFeedback(null)
                      }}
                    >
                      <span>
                        <strong>v{item.version}</strong>
                        <span className={statusClass(item.status)}>
                          {translate(statusLabels[item.status])}
                        </span>
                      </span>
                      <small>
                        revision {item.revision} · {formatDateTime(item.updated_at)}
                      </small>
                      <small>
                        payload <code>{item.payload_sha256.slice(0, 10)}</code>
                      </small>
                      <small>
                        source {item.source_current ? 'CURRENT' : 'STALE'} ·
                        integrity {item.integrity_valid ? 'VALID' : 'INVALID'}
                      </small>
                    </button>
                  </li>
                ))}
              </ol>
            )}
          </aside>
        </div>
      ) : !sourcesQuery.isPending && tenantId ? (
        <p className="state-panel state-panel-empty">
          Для выбранного типа нет доступных исходных материалов.
        </p>
      ) : null}
    </section>
    </LocalizedContent>
  )
}
