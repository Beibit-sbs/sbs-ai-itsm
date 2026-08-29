import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  createSavedSearchView,
  deleteSavedSearchView,
  fetchSavedSearchViews,
  runGlobalSearch,
  type GlobalSearchEntityType,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import type { UiMessageKey } from '../i18n/catalog'

const entityTypes: Array<{
  code: GlobalSearchEntityType
  labelKey: UiMessageKey
}> = [
  { code: 'ticket', labelKey: 'search.entity.ticket' },
  { code: 'request', labelKey: 'search.entity.request' },
  { code: 'knowledge', labelKey: 'search.entity.knowledge' },
  { code: 'asset', labelKey: 'search.entity.asset' },
  { code: 'change', labelKey: 'search.entity.change' },
  { code: 'problem', labelKey: 'search.entity.problem' },
  { code: 'user', labelKey: 'search.entity.user' },
]

const entityLabels = Object.fromEntries(
  entityTypes.map((item) => [item.code, item.labelKey]),
) as Record<GlobalSearchEntityType, UiMessageKey>

const defaultTypes = entityTypes.map((item) => item.code)

function isEditableTarget(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false
  return (
    target.isContentEditable
    || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName)
  )
}

export default function GlobalSearchPalette() {
  const { session } = useAuth()
  const { t } = useTenantExperience()
  const token = session?.access_token ?? ''
  const permissions = session?.user.permissions ?? []
  const canSearch =
    session?.user.role === 'saas_root' || permissions.includes('search.use')
  const canShare =
    session?.user.role === 'saas_root'
    || permissions.includes('search.views.share')
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [debouncedQuery, setDebouncedQuery] = useState('')
  const [selectedTypes, setSelectedTypes] =
    useState<GlobalSearchEntityType[]>(defaultTypes)
  const [activeIndex, setActiveIndex] = useState(0)
  const [showSave, setShowSave] = useState(false)
  const [viewName, setViewName] = useState('')
  const [shareView, setShareView] = useState(false)
  const [shareRoles, setShareRoles] = useState(
    'it_manager,it_agent,requester',
  )
  const dialogRef = useDialogFocusTrap<HTMLElement>(
    open,
    () => {
      setOpen(false)
      setShowSave(false)
    },
    inputRef,
  )

  useEffect(() => {
    const handleGlobalShortcut = (event: KeyboardEvent) => {
      const commandShortcut =
        (event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k'
      const slashShortcut =
        event.key === '/' && !isEditableTarget(event.target)
      if (!canSearch || (!commandShortcut && !slashShortcut)) return
      event.preventDefault()
      setOpen(true)
    }
    window.addEventListener('keydown', handleGlobalShortcut)
    return () => window.removeEventListener('keydown', handleGlobalShortcut)
  }, [canSearch])

  useEffect(() => {
    const timer = window.setTimeout(
      () => setDebouncedQuery(query.trim()),
      220,
    )
    return () => window.clearTimeout(timer)
  }, [query])

  const searchQuery = useQuery({
    queryKey: ['global-search', token, debouncedQuery, selectedTypes],
    queryFn: () =>
      runGlobalSearch(token, {
        q: debouncedQuery,
        types: selectedTypes,
      }),
    enabled:
      open
      && canSearch
      && Boolean(token)
      && debouncedQuery.length >= 2
      && selectedTypes.length > 0,
    staleTime: 15_000,
  })

  const viewsQuery = useQuery({
    queryKey: ['saved-search-views', token],
    queryFn: () => fetchSavedSearchViews(token),
    enabled: open && canSearch && Boolean(token),
  })

  const saveMutation = useMutation({
    mutationFn: () =>
      createSavedSearchView(token, {
        name: viewName.trim(),
        query: { q: query.trim(), types: selectedTypes },
        is_shared: canShare && shareView,
        shared_role_codes:
          canShare && shareView
            ? shareRoles
                .split(',')
                .map((item) => item.trim())
                .filter(Boolean)
            : [],
      }),
    onSuccess: async () => {
      setViewName('')
      setShowSave(false)
      await queryClient.invalidateQueries({
        queryKey: ['saved-search-views', token],
      })
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (viewId: string) => deleteSavedSearchView(token, viewId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['saved-search-views', token],
      })
    },
  })

  const results = searchQuery.data?.items ?? []
  const safeActiveIndex = results.length
    ? Math.min(activeIndex, results.length - 1)
    : 0

  useEffect(() => {
    setActiveIndex(0)
  }, [debouncedQuery, selectedTypes])

  const selectedTypeSet = useMemo(
    () => new Set(selectedTypes),
    [selectedTypes],
  )

  if (!canSearch) return null

  const close = () => {
    setOpen(false)
    setShowSave(false)
  }

  const openResult = (href: string) => {
    close()
    navigate(href)
  }

  const handleInputKeyDown = (
    event: ReactKeyboardEvent<HTMLInputElement>,
  ) => {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
      return
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setActiveIndex((current) =>
        results.length ? (current + 1) % results.length : 0,
      )
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      setActiveIndex((current) =>
        results.length
          ? (current - 1 + results.length) % results.length
          : 0,
      )
      return
    }
    if (event.key === 'Enter' && results[safeActiveIndex]) {
      event.preventDefault()
      openResult(results[safeActiveIndex].href)
    }
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        className="global-search-trigger"
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
      >
        <span>{t('search.trigger')}</span>
        <kbd>Ctrl K</kbd>
      </button>

      {open ? (
        <div
          className="global-search-backdrop"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) close()
          }}
        >
          <section
            ref={dialogRef}
            className="global-search-palette"
            role="dialog"
            aria-modal="true"
            aria-labelledby="global-search-title"
            tabIndex={-1}
          >
            <header className="global-search-header">
              <div>
                <p className="eyebrow">{t('search.eyebrow')}</p>
                <h2 id="global-search-title">{t('search.title')}</h2>
              </div>
              <button
                type="button"
                className="ghost-button"
                onClick={close}
                aria-label={t('search.close')}
              >
                Esc
              </button>
            </header>

            <input
              ref={inputRef}
              className="global-search-input"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={handleInputKeyDown}
              placeholder={t('search.placeholder')}
              aria-label={t('search.query')}
              aria-controls="global-search-results"
              aria-activedescendant={
                results[safeActiveIndex]
                  ? `global-result-${results[safeActiveIndex].entity_type}-${results[safeActiveIndex].id}`
                  : undefined
              }
            />

            <div
              className="global-search-types"
              aria-label={t('search.entityTypes')}
            >
              {entityTypes.map((item) => (
                <button
                  key={item.code}
                  type="button"
                  className={
                    selectedTypeSet.has(item.code) ? 'active' : undefined
                  }
                  aria-pressed={selectedTypeSet.has(item.code)}
                  onClick={() => {
                    setSelectedTypes((current) =>
                      current.includes(item.code)
                        ? current.filter((value) => value !== item.code)
                        : [...current, item.code],
                    )
                  }}
                >
                  {t(item.labelKey)}
                </button>
              ))}
            </div>

            {(viewsQuery.data ?? []).length ? (
              <div className="global-search-views">
                <span>{t('search.saved')}</span>
                {(viewsQuery.data ?? []).map((view) => (
                  <div key={view.id} className="global-search-view">
                    <button
                      type="button"
                      onClick={() => {
                        setQuery(view.query.q)
                        setSelectedTypes(view.query.types)
                      }}
                    >
                      {view.name}
                      {view.is_shared ? ` · ${t('search.team')}` : ''}
                    </button>
                    {view.is_owner ? (
                      <button
                        type="button"
                        aria-label={t('search.delete', { name: view.name })}
                        onClick={() => deleteMutation.mutate(view.id)}
                      >
                        ×
                      </button>
                    ) : null}
                  </div>
                ))}
              </div>
            ) : null}

            <div
              id="global-search-results"
              className="global-search-results"
              role="listbox"
              aria-label={t('search.results')}
            >
              {debouncedQuery.length < 2 ? (
                <div className="global-search-empty">
                  {t('search.minChars')}
                </div>
              ) : null}
              {selectedTypes.length === 0 ? (
                <div className="global-search-empty">
                  {t('search.chooseType')}
                </div>
              ) : null}
              {searchQuery.isLoading ? (
                <div className="global-search-empty" role="status">{t('search.searching')}</div>
              ) : null}
              {searchQuery.isError ? (
                <div className="global-search-empty error-text" role="alert">
                  {t('search.unavailable')}
                </div>
              ) : null}
              {!searchQuery.isLoading
              && debouncedQuery.length >= 2
              && selectedTypes.length > 0
              && results.length === 0 ? (
                <div className="global-search-empty">
                  {t('search.noResults')}
                </div>
              ) : null}
              {results.map((result, index) => (
                <button
                  id={`global-result-${result.entity_type}-${result.id}`}
                  key={`${result.entity_type}-${result.id}`}
                  type="button"
                  role="option"
                  aria-selected={index === safeActiveIndex}
                  className={
                    index === safeActiveIndex
                      ? 'global-search-result active'
                      : 'global-search-result'
                  }
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => openResult(result.href)}
                >
                  <span className="global-search-result-type">
                    {t(entityLabels[result.entity_type])}
                  </span>
                  <strong>{result.identifier}</strong>
                  <span className="global-search-result-title">
                    {result.title}
                  </span>
                  <small>
                    {[result.subtitle, result.status]
                      .filter(Boolean)
                      .join(' · ')}
                  </small>
                </button>
              ))}
            </div>

            <footer className="global-search-footer">
              <span>
                {searchQuery.data
                  ? t('search.stats', {
                      count: searchQuery.data.total,
                      duration: searchQuery.data.duration_ms,
                    })
                  : t('search.keyboardHelp')}
              </span>
              {query.trim().length >= 2 ? (
                <button
                  type="button"
                  className="ghost-button"
                  onClick={() => setShowSave((current) => !current)}
                >
                  {t('search.saveView')}
                </button>
              ) : null}
            </footer>

            {showSave ? (
              <form
                className="global-search-save"
                onSubmit={(event) => {
                  event.preventDefault()
                  if (viewName.trim()) saveMutation.mutate()
                }}
              >
                <label>
                  <span>{t('search.name')}</span>
                  <input
                    value={viewName}
                    onChange={(event) => setViewName(event.target.value)}
                    maxLength={160}
                    required
                  />
                </label>
                {canShare ? (
                  <>
                    <label className="global-search-share-toggle">
                      <input
                        type="checkbox"
                        checked={shareView}
                        onChange={(event) =>
                          setShareView(event.target.checked)}
                      />
                      <span>{t('search.teamView')}</span>
                    </label>
                    {shareView ? (
                      <label>
                        <span>{t('search.roles')}</span>
                        <input
                          value={shareRoles}
                          onChange={(event) =>
                            setShareRoles(event.target.value)}
                        />
                      </label>
                    ) : null}
                  </>
                ) : null}
                <button
                  type="submit"
                  disabled={
                    saveMutation.isPending
                    || !viewName.trim()
                    || selectedTypes.length === 0
                  }
                >
                  {saveMutation.isPending ? t('search.saving') : t('common.save')}
                </button>
                {saveMutation.isError ? (
                  <span className="error-text" role="alert">
                    {t('search.saveError')}
                  </span>
                ) : null}
              </form>
            ) : null}
          </section>
        </div>
      ) : null}
    </>
  )
}
