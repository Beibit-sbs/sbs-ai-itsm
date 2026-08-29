import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createCatalogCategory,
  createCatalogItem,
  createCatalogService,
  createServiceOffering,
  fetchCatalogCategories,
  fetchCatalogForm,
  fetchCatalogItemHistory,
  fetchCatalogItems,
  recordCatalogItemView,
  setCatalogItemFavorite,
  fetchCatalogServices,
  fetchCatalogSummary,
  fetchServiceOfferings,
  transitionCatalogItem,
  type CatalogItem,
  type CatalogLifecycle,
  type CreateCatalogItemRequest,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'
import CatalogFormDesigner from '../components/CatalogFormDesigner'
import CatalogKnowledgeDeflection from '../components/CatalogKnowledgeDeflection'
import CatalogRequestForm from '../components/CatalogRequestForm'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const lifecycleLabels: Record<string, string> = {
  DRAFT: 'Черновик',
  IN_REVIEW: 'На проверке',
  PUBLISHED: 'Опубликовано',
  RETIRED: 'Выведено',
}

const lifecycleOptions = ['ALL', 'DRAFT', 'IN_REVIEW', 'PUBLISHED', 'RETIRED']

type ItemForm = {
  category_id: string
  service_id: string
  offering_id: string
  code: string
  name: string
  short_description: string
  description: string
  support_group: string
  expected_delivery_hours: number
  approval_required: boolean
  entitlement_roles: string
  entitlement_departments: string
  entitlement_locations: string
  entitlement_cost_centers: string
  unit_cost_major: number
  currency: string
  cost_type: CatalogItem['cost_type']
  risk_level: CatalogItem['risk_level']
  approval_cost_threshold_major: number
  approval_minimum_risk: '' | CatalogItem['risk_level']
  approver_roles: string
  sla_target_hours: number
  ola_hours: number
  sla_calendar: '24X7' | 'WEEKDAYS_8X5'
}

const emptyItemForm: ItemForm = {
  category_id: '',
  service_id: '',
  offering_id: '',
  code: '',
  name: '',
  short_description: '',
  description: '',
  support_group: 'Service Desk',
  expected_delivery_hours: 8,
  approval_required: false,
  entitlement_roles: '',
  entitlement_departments: '',
  entitlement_locations: '',
  entitlement_cost_centers: '',
  unit_cost_major: 0,
  currency: 'KZT',
  cost_type: 'ONE_TIME',
  risk_level: 'LOW',
  approval_cost_threshold_major: 0,
  approval_minimum_risk: '',
  approver_roles: 'organization_admin, it_manager',
  sla_target_hours: 8,
  ola_hours: 6,
  sla_calendar: '24X7',
}

function can(session: ReturnType<typeof useAuth>['session'], permission: string) {
  return session?.user.role === 'saas_root' || Boolean(session?.user.permissions.includes(permission))
}

function csv(value: string) {
  return value.split(',').map((entry) => entry.trim()).filter(Boolean)
}

function hasPolicyDrivenApproval(item: CatalogItem) {
  const policyDriven = Boolean(
    Number(item.approval_policy.cost_threshold_minor ?? 0)
    || item.approval_policy.minimum_risk
    || item.approval_policy.always,
  )
  return policyDriven
}

export default function CatalogPage() {
  const { session } = useAuth()
  const { formatCurrency, formatDateTime, t, translate } = useTenantExperience()
  const money = (minor: number, currency: string) =>
    minor ? formatCurrency(minor / 100, currency) : t('catalog.noCharge')
  const duration = (minutes: number) => {
    if (minutes < 60) return t('catalog.minutesShortValue', { count: minutes })
    const hours = Math.round((minutes / 60) * 10) / 10
    if (hours < 24) return t('requests.hoursShort', { count: hours })
    return t('catalog.daysShortValue', {
      count: Math.round((hours / 24) * 10) / 10,
    })
  }
  const approvalLabel = (item: CatalogItem) => {
    if (item.approval_required) return t('catalog.always')
    if (hasPolicyDrivenApproval(item)) return t('catalog.policyDrivenApproval')
    return t('catalog.notRequired')
  }
  const costTypeLabel = (value: CatalogItem['cost_type']) => {
    if (value === 'NO_CHARGE') return t('catalog.noCharge')
    if (value === 'ONE_TIME') return t('catalog.costOnce')
    if (value === 'MONTHLY') return t('catalog.costMonthly')
    return t('catalog.costAnnual')
  }
  const token = session?.access_token ?? ''
  const queryClient = useQueryClient()
  const canManage = can(session, 'catalog.manage')
  const canPublish = can(session, 'catalog.publish')
  const [mode, setMode] = useState<'browse' | 'manage'>('browse')
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [personalFilter, setPersonalFilter] = useState<'ALL' | 'FAVORITES'>('ALL')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [orderMode, setOrderMode] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [categoryForm, setCategoryForm] = useState({ code: '', name: '', description: '' })
  const [serviceForm, setServiceForm] = useState({ category_id: '', code: '', name: '', description: '', support_group: 'Service Desk' })
  const [offeringForm, setOfferingForm] = useState({ service_id: '', code: '', name: '', description: '', support_group: 'Service Desk', expected_hours: 8 })
  const [itemForm, setItemForm] = useState<ItemForm>(emptyItemForm)
  const closeButtonRef = useRef<HTMLButtonElement>(null)
  const detailDialogRef = useDialogFocusTrap<HTMLElement>(
    Boolean(selectedId),
    closeSelected,
    closeButtonRef,
  )

  const summaryQuery = useQuery({
    queryKey: ['catalog-summary', token],
    queryFn: () => fetchCatalogSummary(token),
    enabled: Boolean(token),
  })
  const categoriesQuery = useQuery({
    queryKey: ['catalog-categories', token],
    queryFn: () => fetchCatalogCategories(token),
    enabled: Boolean(token),
  })
  const servicesQuery = useQuery({
    queryKey: ['catalog-services', token],
    queryFn: () => fetchCatalogServices(token),
    enabled: Boolean(token),
  })
  const offeringsQuery = useQuery({
    queryKey: ['catalog-offerings', token],
    queryFn: () => fetchServiceOfferings(token),
    enabled: Boolean(token),
  })
  const itemsQuery = useQuery({
    queryKey: ['catalog-items', token, search, categoryFilter, statusFilter, canManage],
    queryFn: () => fetchCatalogItems(token, {
      search: search.trim() || undefined,
      category_id: categoryFilter === 'ALL' ? undefined : categoryFilter,
      lifecycle_status: canManage ? statusFilter : undefined,
    }),
    enabled: Boolean(token),
  })
  const historyQuery = useQuery({
    queryKey: ['catalog-history', token, selectedId],
    queryFn: () => fetchCatalogItemHistory(token, selectedId ?? ''),
    enabled: Boolean(token && selectedId && canManage),
  })
  const publishedFormQuery = useQuery({
    queryKey: ['catalog-form', token, selectedId, 'published'],
    queryFn: () => fetchCatalogForm(token, selectedId ?? '', 'published'),
    enabled: Boolean(token && selectedId),
  })

  const categories = categoriesQuery.data ?? []
  const services = servicesQuery.data ?? []
  const offerings = offeringsQuery.data ?? []
  const items = itemsQuery.data ?? []
  const selected = items.find((item) => item.id === selectedId) ?? null
  const visibleItems = useMemo(
    () => personalFilter === 'FAVORITES'
      ? items.filter((item) => item.is_favorite)
      : items,
    [items, personalFilter],
  )
  const favoriteItems = useMemo(
    () => items.filter((item) => item.is_favorite).slice(0, 6),
    [items],
  )
  const recentItems = useMemo(
    () => items
      .filter((item) => item.last_requested_at || item.last_viewed_at)
      .sort((left, right) => {
        const leftAt = left.last_requested_at ?? left.last_viewed_at ?? ''
        const rightAt = right.last_requested_at ?? right.last_viewed_at ?? ''
        return rightAt.localeCompare(leftAt)
      })
      .slice(0, 6),
    [items],
  )
  const filteredServices = useMemo(
    () => services.filter((service) => service.category_id === itemForm.category_id),
    [services, itemForm.category_id],
  )
  const filteredOfferings = useMemo(
    () => offerings.filter((offering) => offering.service_id === itemForm.service_id),
    [offerings, itemForm.service_id],
  )

  useEffect(() => {
    if (!itemForm.category_id && categories[0]) {
      setItemForm((current) => ({ ...current, category_id: categories[0].id }))
    }
    if (!serviceForm.category_id && categories[0]) {
      setServiceForm((current) => ({ ...current, category_id: categories[0].id }))
    }
  }, [categories, itemForm.category_id, serviceForm.category_id])

  useEffect(() => {
    if (!itemForm.service_id && filteredServices[0]) {
      setItemForm((current) => ({ ...current, service_id: filteredServices[0].id, offering_id: '' }))
    }
  }, [filteredServices, itemForm.service_id])

  useEffect(() => {
    if (!offeringForm.service_id && services[0]) {
      setOfferingForm((current) => ({ ...current, service_id: services[0].id }))
    }
  }, [services, offeringForm.service_id])

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['catalog-summary'] }),
      queryClient.invalidateQueries({ queryKey: ['catalog-categories'] }),
      queryClient.invalidateQueries({ queryKey: ['catalog-services'] }),
      queryClient.invalidateQueries({ queryKey: ['catalog-offerings'] }),
      queryClient.invalidateQueries({ queryKey: ['catalog-items'] }),
      queryClient.invalidateQueries({ queryKey: ['catalog-history'] }),
    ])
  }

  function mutationError(error: unknown) {
    setActionError(error instanceof Error ? error.message : t('catalog.operationFailed'))
    setNotice(null)
  }

  const categoryMutation = useMutation({
    mutationFn: () => createCatalogCategory(token, categoryForm),
    onSuccess: async (category) => {
      setCategoryForm({ code: '', name: '', description: '' })
      setNotice(t('catalog.categoryCreated', { title: category.name }))
      setActionError(null)
      await refresh()
    },
    onError: mutationError,
  })
  const serviceMutation = useMutation({
    mutationFn: () => createCatalogService(token, serviceForm),
    onSuccess: async (service) => {
      setServiceForm((current) => ({ ...current, code: '', name: '', description: '' }))
      setNotice(t('catalog.serviceCreated', { title: service.name }))
      setActionError(null)
      await refresh()
    },
    onError: mutationError,
  })
  const offeringMutation = useMutation({
    mutationFn: () => createServiceOffering(token, {
      service_id: offeringForm.service_id,
      code: offeringForm.code,
      name: offeringForm.name,
      description: offeringForm.description,
      support_group: offeringForm.support_group,
      expected_fulfillment_minutes: offeringForm.expected_hours * 60,
    }),
    onSuccess: async (offering) => {
      setOfferingForm((current) => ({ ...current, code: '', name: '', description: '' }))
      setNotice(t('catalog.offeringCreated', { title: offering.name }))
      setActionError(null)
      await refresh()
    },
    onError: mutationError,
  })
  const itemMutation = useMutation({
    mutationFn: () => {
      const roles = csv(itemForm.entitlement_roles)
      const departments = csv(itemForm.entitlement_departments)
      const locations = csv(itemForm.entitlement_locations)
      const costCenters = csv(itemForm.entitlement_cost_centers)
      const approverRoles = csv(itemForm.approver_roles)
      const entitlementRules = {
        ...(roles.length ? { roles } : {}),
        ...(departments.length ? { departments } : {}),
        ...(locations.length ? { locations } : {}),
        ...(costCenters.length ? { cost_centers: costCenters } : {}),
        match: 'ALL',
      }
      const payload: CreateCatalogItemRequest = {
        category_id: itemForm.category_id,
        service_id: itemForm.service_id,
        offering_id: itemForm.offering_id || null,
        code: itemForm.code,
        name: itemForm.name,
        short_description: itemForm.short_description,
        description: itemForm.description,
        owner_user_id: session?.user.id ?? null,
        support_group: itemForm.support_group,
        expected_delivery_minutes: itemForm.expected_delivery_hours * 60,
        approval_required: itemForm.approval_required,
        entitlement_rules: Object.keys(entitlementRules).length > 1 ? entitlementRules : {},
        unit_cost_minor: Math.round(itemForm.unit_cost_major * 100),
        currency: itemForm.currency.toUpperCase(),
        cost_type: itemForm.unit_cost_major > 0 ? itemForm.cost_type : 'NO_CHARGE',
        risk_level: itemForm.risk_level,
        approval_policy: {
          cost_threshold_minor: Math.round(itemForm.approval_cost_threshold_major * 100),
          minimum_risk: itemForm.approval_minimum_risk || null,
          approver_roles: approverRoles,
          mode: 'SEQUENTIAL',
          due_minutes: 1440,
        },
        sla_policy: {
          target_minutes: Math.round(itemForm.sla_target_hours * 60),
          ola_minutes: Math.round(itemForm.ola_hours * 60),
          calendar_code: itemForm.sla_calendar,
          warning_percent: 80,
          pause_on_waiting: true,
          escalation_minutes: [0, 60, 240],
        },
      }
      return createCatalogItem(token, payload)
    },
    onSuccess: async (item) => {
      setItemForm((current) => ({
        ...emptyItemForm,
        category_id: current.category_id,
        service_id: current.service_id,
        offering_id: current.offering_id,
      }))
      setSelectedId(item.id)
      setNotice(t('catalog.itemDraftCreated', { title: item.name }))
      setActionError(null)
      await refresh()
    },
    onError: mutationError,
  })
  const transitionMutation = useMutation({
    mutationFn: ({ item, target }: { item: CatalogItem; target: CatalogLifecycle }) => transitionCatalogItem(
      token,
      item.id,
      {
        expected_version: item.version,
        target_status: target,
        reason: `Изменение статуса через консоль каталога: ${lifecycleLabels[target]}`,
      },
    ),
    onSuccess: async (item) => {
      setNotice(t('catalog.lifecycleChanged', {
        title: item.name,
        status: t(item.lifecycle_status === 'DRAFT'
          ? 'catalog.draft'
          : item.lifecycle_status === 'IN_REVIEW'
            ? 'catalog.inReview'
            : item.lifecycle_status === 'PUBLISHED'
              ? 'catalog.published'
              : 'catalog.retired'),
      }))
      setActionError(null)
      await refresh()
    },
    onError: mutationError,
  })
  const viewMutation = useMutation({
    mutationFn: (item: CatalogItem) => recordCatalogItemView(token, item.id),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['catalog-items'] })
    },
  })
  const favoriteMutation = useMutation({
    mutationFn: (item: CatalogItem) => setCatalogItemFavorite(token, item.id, !item.is_favorite),
    onSuccess: async (preference) => {
      setNotice(t(preference.is_favorite ? 'catalog.favoriteAdded' : 'catalog.favoriteRemoved'))
      setActionError(null)
      await queryClient.invalidateQueries({ queryKey: ['catalog-items'] })
    },
    onError: mutationError,
  })

  function nextActions(item: CatalogItem): CatalogLifecycle[] {
    if (!canManage) return []
    if (item.lifecycle_status === 'DRAFT') return ['IN_REVIEW']
    if (item.lifecycle_status === 'IN_REVIEW') return canPublish ? ['DRAFT', 'PUBLISHED'] : ['DRAFT']
    if (item.lifecycle_status === 'PUBLISHED' && canPublish) return ['RETIRED']
    return []
  }

  const summary = summaryQuery.data
  function closeSelected() {
    setSelectedId(null)
    setOrderMode(false)
  }

  function openItem(item: CatalogItem, shouldOrder: boolean) {
    setSelectedId(item.id)
    setOrderMode(shouldOrder)
    viewMutation.mutate(item)
  }

  return (
    <AppShell
      title="Каталог услуг"
      subtitle="Управляемая витрина ИТ-услуг: владельцы, сроки, согласования и контролируемая публикация."
    >
      <QueryFailureNotice
        title="Часть данных Service Catalog недоступна."
        sources={[
          { label: 'оперативная сводка', query: summaryQuery },
          { label: 'категории', query: categoriesQuery },
          { label: 'сервисы', query: servicesQuery },
          { label: 'offerings', query: offeringsQuery },
          { label: 'элементы каталога', query: itemsQuery },
          { label: 'история', query: historyQuery },
          { label: 'опубликованная форма', query: publishedFormQuery },
        ]}
      />
      <section className="catalog-summary-grid" aria-label="Сводка каталога">
        <article><span>Опубликовано</span><strong>{summary?.published_items ?? 0}</strong></article>
        <article><span>На проверке</span><strong>{summary?.review_items ?? 0}</strong></article>
        <article><span>Черновики</span><strong>{summary?.draft_items ?? 0}</strong></article>
        <article><span>Услуги / предложения</span><strong>{summary?.services ?? 0} / {summary?.offerings ?? 0}</strong></article>
      </section>

      <div className="catalog-mode-switch">
        <button type="button" aria-pressed={mode === 'browse'} className={mode === 'browse' ? 'active' : ''} onClick={() => setMode('browse')}>
          Витрина услуг
        </button>
        {canManage ? (
          <button type="button" aria-pressed={mode === 'manage'} className={mode === 'manage' ? 'active' : ''} onClick={() => setMode('manage')}>
            Управление каталогом
          </button>
        ) : null}
      </div>

      {notice ? <div className="success-banner" role="status" aria-live="polite">{notice}</div> : null}
      {actionError ? <div className="error-banner" role="alert">{actionError}</div> : null}

      {mode === 'browse' ? (
        <>
          <section className="catalog-toolbar foundation-card">
            <label>
              <span>Поиск</span>
              <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="VPN, доступ, оборудование…" />
            </label>
            <label>
              <span>Категория</span>
              <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
                <option value="ALL">Все категории</option>
                {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
              </select>
            </label>
            <label>
              <span>Персональная витрина</span>
              <select value={personalFilter} onChange={(event) => setPersonalFilter(event.target.value as 'ALL' | 'FAVORITES')}>
                <option value="ALL">Все услуги</option>
                <option value="FAVORITES">Только избранное</option>
              </select>
            </label>
            {canManage ? (
              <label>
                <span>Lifecycle</span>
                <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
                  {lifecycleOptions.map((status) => <option key={status} value={status}>{status === 'ALL' ? 'Все статусы' : translate(lifecycleLabels[status])}</option>)}
                </select>
              </label>
            ) : null}
          </section>

          {favoriteItems.length || recentItems.length ? (
            <section className="catalog-personalized foundation-card" aria-label="Персональная витрина">
              {favoriteItems.length ? (
                <div>
                  <header><strong>Избранное</strong><span>{favoriteItems.length}</span></header>
                  <div className="catalog-quick-links">
                    {favoriteItems.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => openItem(item, false)}
                      >
                        <span aria-hidden="true">★</span>{item.name}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
              {recentItems.length ? (
                <div>
                  <header><strong>Недавно использовали</strong><span>{recentItems.length}</span></header>
                  <div className="catalog-quick-links">
                    {recentItems.map((item) => (
                      <button
                        key={item.id}
                        type="button"
                        onClick={() => openItem(item, false)}
                      >
                        <span aria-hidden="true">↻</span>{item.name}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </section>
          ) : null}

          {itemsQuery.isPending ? <p className="state-panel" role="status">Загрузка каталога…</p> : null}
          {itemsQuery.isError ? <p className="state-panel state-panel-error" role="alert">Не удалось загрузить каталог.</p> : null}
          {!itemsQuery.isPending && !itemsQuery.isError && visibleItems.length === 0 ? (
            <section className="state-panel state-panel-empty">
              <h3>{personalFilter === 'FAVORITES' ? 'В избранном пока пусто' : 'Каталог пока пуст'}</h3>
              <p>{personalFilter === 'FAVORITES' ? 'Нажмите звезду на нужной услуге — она появится здесь.' : canManage ? 'Перейдите в управление и создайте первую услугу.' : 'Опубликованные услуги ещё не добавлены.'}</p>
            </section>
          ) : null}
          <section className="catalog-card-grid">
            {visibleItems.map((item) => (
              <article className="catalog-item-card" key={item.id}>
                <header>
                  <span>{item.category_name}</span>
                  <div className="catalog-card-actions">
                    <button
                      type="button"
                      className={`catalog-favorite-button ${item.is_favorite ? 'active' : ''}`}
                      aria-label={`${item.is_favorite ? 'Удалить из избранного' : 'Добавить в избранное'}: ${item.name}`}
                      aria-pressed={item.is_favorite}
                      disabled={favoriteMutation.isPending}
                      onClick={() => favoriteMutation.mutate(item)}
                    >
                      <span aria-hidden="true">{item.is_favorite ? '★' : '☆'}</span>
                    </button>
                    <strong className={`catalog-status status-${item.lifecycle_status.toLowerCase()}`}>
                      {translate(lifecycleLabels[item.lifecycle_status])}
                    </strong>
                  </div>
                </header>
                <div className="catalog-card-code">{item.code}</div>
                <h3>{item.name}</h3>
                <p>{item.short_description}</p>
                <dl>
                  <div><dt>Срок</dt><dd>{duration(item.expected_delivery_minutes)}</dd></div>
                  <div><dt>Исполнитель</dt><dd>{item.support_group ?? 'Не назначен'}</dd></div>
                  <div><dt>Стоимость</dt><dd>{money(item.unit_cost_minor, item.currency)}</dd></div>
                  <div><dt>Риск</dt><dd>{translate(item.risk_level)}</dd></div>
                  <div><dt>Согласование</dt><dd>{approvalLabel(item)}</dd></div>
                </dl>
                <footer>
                  <button
                    type="button"
                    className="ghost-button"
                    aria-label={t('catalog.detailsFor', { title: item.name })}
                    onClick={() => openItem(item, false)}
                  >
                    Подробнее
                  </button>
                  {item.lifecycle_status === 'PUBLISHED' ? (
                    <button
                      type="button"
                      className="primary-link-button"
                      aria-label={t('catalog.createFor', { title: item.name })}
                      onClick={() => openItem(item, true)}
                    >
                      Создать заявку
                    </button>
                  ) : null}
                </footer>
              </article>
            ))}
          </section>
        </>
      ) : null}

      {mode === 'manage' && canManage ? (
        <section className="catalog-management">
          <article className="foundation-card catalog-taxonomy-panel">
            <header>
              <p className="eyebrow">TAXONOMY</p>
              <h2>Структура каталога</h2>
              <p className="muted">Категория → услуга → предложение → позиция каталога.</p>
            </header>
            <div className="catalog-taxonomy-forms">
              <form onSubmit={(event) => { event.preventDefault(); categoryMutation.mutate() }}>
                <h3>1. Категория</h3>
                <input required value={categoryForm.code} onChange={(event) => setCategoryForm({ ...categoryForm, code: event.target.value })} placeholder="ACCESS" />
                <input required value={categoryForm.name} onChange={(event) => setCategoryForm({ ...categoryForm, name: event.target.value })} placeholder="Доступы и учётные записи" />
                <textarea value={categoryForm.description} onChange={(event) => setCategoryForm({ ...categoryForm, description: event.target.value })} placeholder="Назначение категории" />
                <button type="submit" disabled={categoryMutation.isPending}>Создать категорию</button>
              </form>
              <form onSubmit={(event) => { event.preventDefault(); serviceMutation.mutate() }}>
                <h3>2. Услуга</h3>
                <select required value={serviceForm.category_id} onChange={(event) => setServiceForm({ ...serviceForm, category_id: event.target.value })}>
                  <option value="">Выберите категорию</option>
                  {categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}
                </select>
                <input required value={serviceForm.code} onChange={(event) => setServiceForm({ ...serviceForm, code: event.target.value })} placeholder="IDENTITY_ACCESS" />
                <input required value={serviceForm.name} onChange={(event) => setServiceForm({ ...serviceForm, name: event.target.value })} placeholder="Управление доступом" />
                <input value={serviceForm.support_group} onChange={(event) => setServiceForm({ ...serviceForm, support_group: event.target.value })} placeholder="Service Desk" />
                <button type="submit" disabled={serviceMutation.isPending || !serviceForm.category_id}>Создать услугу</button>
              </form>
              <form onSubmit={(event) => { event.preventDefault(); offeringMutation.mutate() }}>
                <h3>3. Предложение</h3>
                <select required value={offeringForm.service_id} onChange={(event) => setOfferingForm({ ...offeringForm, service_id: event.target.value })}>
                  <option value="">Выберите услугу</option>
                  {services.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}
                </select>
                <input required value={offeringForm.code} onChange={(event) => setOfferingForm({ ...offeringForm, code: event.target.value })} placeholder="STANDARD_ACCESS" />
                <input required value={offeringForm.name} onChange={(event) => setOfferingForm({ ...offeringForm, name: event.target.value })} placeholder="Стандартный доступ" />
                <label><span>Срок, часов</span><input type="number" min={1} value={offeringForm.expected_hours} onChange={(event) => setOfferingForm({ ...offeringForm, expected_hours: Number(event.target.value) })} /></label>
                <button type="submit" disabled={offeringMutation.isPending || !offeringForm.service_id}>Создать предложение</button>
              </form>
            </div>
          </article>

          <article className="foundation-card catalog-item-editor">
            <header>
              <p className="eyebrow">CATALOG ITEM</p>
              <h2>Новая позиция каталога</h2>
              <p className="muted">После создания позиция остаётся черновиком и проходит отдельную публикацию.</p>
            </header>
            <form onSubmit={(event) => { event.preventDefault(); itemMutation.mutate() }}>
              <div className="catalog-form-grid">
                <label><span>Категория</span><select required value={itemForm.category_id} onChange={(event) => setItemForm({ ...itemForm, category_id: event.target.value, service_id: '', offering_id: '' })}>{categories.map((category) => <option key={category.id} value={category.id}>{category.name}</option>)}</select></label>
                <label><span>Услуга</span><select required value={itemForm.service_id} onChange={(event) => setItemForm({ ...itemForm, service_id: event.target.value, offering_id: '' })}>{filteredServices.map((service) => <option key={service.id} value={service.id}>{service.name}</option>)}</select></label>
                <label><span>Предложение</span><select value={itemForm.offering_id} onChange={(event) => setItemForm({ ...itemForm, offering_id: event.target.value })}><option value="">Без предложения</option>{filteredOfferings.map((offering) => <option key={offering.id} value={offering.id}>{offering.name}</option>)}</select></label>
                <label><span>Код</span><input required value={itemForm.code} onChange={(event) => setItemForm({ ...itemForm, code: event.target.value })} placeholder="REQ_VPN_ACCESS" /></label>
                <label className="catalog-wide"><span>Название</span><input required value={itemForm.name} onChange={(event) => setItemForm({ ...itemForm, name: event.target.value })} placeholder="Корпоративный VPN-доступ" /></label>
                <label className="catalog-wide"><span>Краткое описание</span><input required value={itemForm.short_description} onChange={(event) => setItemForm({ ...itemForm, short_description: event.target.value })} /></label>
                <label className="catalog-wide"><span>Полное описание</span><textarea required value={itemForm.description} onChange={(event) => setItemForm({ ...itemForm, description: event.target.value })} /></label>
                <label><span>Группа поддержки</span><input required value={itemForm.support_group} onChange={(event) => setItemForm({ ...itemForm, support_group: event.target.value })} /></label>
                <label><span>Срок, часов</span><input type="number" min={1} value={itemForm.expected_delivery_hours} onChange={(event) => setItemForm({ ...itemForm, expected_delivery_hours: Number(event.target.value) })} /></label>
                <label><span>Разрешённые роли</span><input value={itemForm.entitlement_roles} onChange={(event) => setItemForm({ ...itemForm, entitlement_roles: event.target.value })} placeholder="requester, it_agent" /></label>
                <label><span>Разрешённые отделы</span><input value={itemForm.entitlement_departments} onChange={(event) => setItemForm({ ...itemForm, entitlement_departments: event.target.value })} placeholder="Finance, HR" /></label>
                <label><span>Разрешённые локации</span><input value={itemForm.entitlement_locations} onChange={(event) => setItemForm({ ...itemForm, entitlement_locations: event.target.value })} placeholder="HQ, Branch-1" /></label>
                <label><span>Разрешённые cost center</span><input value={itemForm.entitlement_cost_centers} onChange={(event) => setItemForm({ ...itemForm, entitlement_cost_centers: event.target.value })} placeholder="CC-100, CC-200" /></label>
                <label><span>Стоимость за единицу</span><input type="number" min={0} step="0.01" value={itemForm.unit_cost_major} onChange={(event) => setItemForm({ ...itemForm, unit_cost_major: Number(event.target.value) })} /></label>
                <label><span>Валюта</span><input required minLength={3} maxLength={3} value={itemForm.currency} onChange={(event) => setItemForm({ ...itemForm, currency: event.target.value.toUpperCase() })} /></label>
                <label><span>Модель стоимости</span><select value={itemForm.cost_type} onChange={(event) => setItemForm({ ...itemForm, cost_type: event.target.value as CatalogItem['cost_type'] })}><option value="NO_CHARGE">Без оплаты</option><option value="ONE_TIME">Разово</option><option value="MONTHLY">Ежемесячно</option><option value="ANNUAL">Ежегодно</option></select></label>
                <label><span>Риск услуги</span><select value={itemForm.risk_level} onChange={(event) => setItemForm({ ...itemForm, risk_level: event.target.value as CatalogItem['risk_level'] })}><option value="LOW">LOW</option><option value="MEDIUM">MEDIUM</option><option value="HIGH">HIGH</option><option value="CRITICAL">CRITICAL</option></select></label>
                <label><span>Согласование от суммы</span><input type="number" min={0} step="0.01" value={itemForm.approval_cost_threshold_major} onChange={(event) => setItemForm({ ...itemForm, approval_cost_threshold_major: Number(event.target.value) })} /></label>
                <label><span>Согласование от риска</span><select value={itemForm.approval_minimum_risk} onChange={(event) => setItemForm({ ...itemForm, approval_minimum_risk: event.target.value as ItemForm['approval_minimum_risk'] })}><option value="">Не использовать</option><option value="LOW">LOW</option><option value="MEDIUM">MEDIUM</option><option value="HIGH">HIGH</option><option value="CRITICAL">CRITICAL</option></select></label>
                <label><span>Роли согласующих</span><input value={itemForm.approver_roles} onChange={(event) => setItemForm({ ...itemForm, approver_roles: event.target.value })} placeholder="organization_admin, it_manager" /></label>
                <label><span>SLA, часов</span><input type="number" min={0.1} step={0.1} value={itemForm.sla_target_hours} onChange={(event) => setItemForm({ ...itemForm, sla_target_hours: Number(event.target.value) })} /></label>
                <label><span>OLA, часов</span><input type="number" min={0.1} step={0.1} max={itemForm.sla_target_hours} value={itemForm.ola_hours} onChange={(event) => setItemForm({ ...itemForm, ola_hours: Number(event.target.value) })} /></label>
                <label><span>Календарь</span><select value={itemForm.sla_calendar} onChange={(event) => setItemForm({ ...itemForm, sla_calendar: event.target.value as ItemForm['sla_calendar'] })}><option value="24X7">24×7</option><option value="WEEKDAYS_8X5">Будни 09:00–17:00 UTC</option></select></label>
                <label className="catalog-checkbox"><input type="checkbox" checked={itemForm.approval_required} onChange={(event) => setItemForm({ ...itemForm, approval_required: event.target.checked })} /><span>Требуется согласование</span></label>
              </div>
              <button type="submit" disabled={itemMutation.isPending || !itemForm.service_id}>Создать черновик</button>
            </form>
          </article>
        </section>
      ) : null}

      {selected ? (
        <div className="modal-backdrop" role="presentation" onMouseDown={closeSelected}>
          <aside
            ref={detailDialogRef}
            className="modal catalog-detail-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="catalog-detail-title"
            tabIndex={-1}
            onMouseDown={(event) => event.stopPropagation()}
          >
            <header className="modal-header">
              <div>
                <p className="eyebrow">{selected.code} · v{selected.version}</p>
                <h2 id="catalog-detail-title">{selected.name}</h2>
              </div>
              <button
                ref={closeButtonRef}
                type="button"
                className="ghost-button"
                aria-label={t('catalog.closeCard', { title: selected.name })}
                onClick={closeSelected}
              >
                Закрыть
              </button>
            </header>
            <p className="catalog-detail-description">{selected.description}</p>
            <div className="detail-fields">
              <div><span>Lifecycle</span><strong>{translate(lifecycleLabels[selected.lifecycle_status])}</strong></div>
              <div><span>Категория</span><strong>{selected.category_name}</strong></div>
              <div><span>Услуга</span><strong>{selected.service_name}</strong></div>
              <div><span>Предложение</span><strong>{selected.offering_name ?? '—'}</strong></div>
              <div><span>Группа</span><strong>{selected.support_group ?? '—'}</strong></div>
              <div><span>Ожидаемый срок</span><strong>{duration(selected.expected_delivery_minutes)}</strong></div>
              <div><span>Стоимость</span><strong>{money(selected.unit_cost_minor, selected.currency)}</strong></div>
              <div><span>Модель стоимости</span><strong>{costTypeLabel(selected.cost_type)}</strong></div>
              <div><span>Риск</span><strong>{translate(selected.risk_level)}</strong></div>
              <div><span>Согласование</span><strong>{approvalLabel(selected)}</strong></div>
              <div><span>SLA</span><strong>{duration(Number(selected.sla_policy.target_minutes ?? selected.expected_delivery_minutes))}</strong></div>
              <div><span>OLA</span><strong>{duration(Number(selected.sla_policy.ola_minutes ?? selected.expected_delivery_minutes))}</strong></div>
            </div>
            {canManage ? (
              <section className="catalog-governance-summary">
                <h3>Governance policy</h3>
                <p><strong>Entitlements:</strong> {Object.keys(selected.entitlement_rules).length ? JSON.stringify(selected.entitlement_rules) : 'для всех пользователей организации'}</p>
                <p><strong>Approval:</strong> {JSON.stringify(selected.approval_policy)}</p>
                <p><strong>SLA:</strong> {JSON.stringify(selected.sla_policy)}</p>
              </section>
            ) : null}
            {nextActions(selected).length ? (
              <section className="catalog-lifecycle-actions">
                <h3>Lifecycle</h3>
                {nextActions(selected).map((target) => (
                  <button key={target} type="button" onClick={() => transitionMutation.mutate({ item: selected, target })} disabled={transitionMutation.isPending}>
                    {target === 'IN_REVIEW' ? 'Передать на проверку' : target === 'PUBLISHED' ? 'Опубликовать' : target === 'DRAFT' ? 'Вернуть в черновик' : 'Вывести из каталога'}
                  </button>
                ))}
              </section>
            ) : null}
            {canManage ? (
              <CatalogFormDesigner
                accessToken={token}
                itemId={selected.id}
                canPublish={canPublish}
                onNotice={(message) => { setNotice(message); setActionError(null) }}
                onError={(message) => { setActionError(message); setNotice(null) }}
              />
            ) : null}
            {canManage ? (
              <section className="catalog-history">
                <h3>Неизменяемая история</h3>
                {historyQuery.isPending ? <p className="muted">Загрузка…</p> : null}
                {(historyQuery.data ?? []).map((entry) => (
                  <article key={entry.id}>
                    <strong>{translate(entry.action)}</strong>
                    <span>v{entry.version} · {entry.actor_name}</span>
                    <small>{formatDateTime(entry.created_at)}</small>
                    {entry.reason ? <p>{entry.reason}</p> : null}
                  </article>
                ))}
              </section>
            ) : null}
            {selected.lifecycle_status === 'PUBLISHED' ? (
              orderMode ? (
                <>
                  <CatalogKnowledgeDeflection
                    accessToken={token}
                    item={selected}
                    enabled={orderMode}
                    onResolved={(articleTitle) => {
                      setNotice(t('catalog.deflectionResolved', { title: articleTitle }))
                      setActionError(null)
                      closeSelected()
                    }}
                  />
                  {publishedFormQuery.isPending ? (
                    <p className="state-panel">Загрузка формы заказа…</p>
                  ) : publishedFormQuery.data ? (
                    <CatalogRequestForm
                      accessToken={token}
                      item={selected}
                      form={publishedFormQuery.data}
                    />
                  ) : (
                    <div className="catalog-legacy-order">
                      <p>
                        Форма заказа временно недоступна. Обновите карточку или
                        обратитесь к владельцу услуги — запрос не будет ошибочно
                        создан как инцидент.
                      </p>
                    </div>
                  )}
                </>
              ) : (
                <button type="button" className="primary-link-button catalog-order-button" onClick={() => setOrderMode(true)}>
                  Создать заявку по услуге
                </button>
              )
            ) : null}
          </aside>
        </div>
      ) : null}
    </AppShell>
  )
}
