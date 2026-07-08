import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addTicketComment,
  analyzeTicketWithAi,
  createArticleFromTicket,
  createTicket,
  fetchAiSuggestions,
  fetchAssets,
  fetchTicket,
  fetchTicketAutomationSuggestions,
  fetchTicketHistory,
  fetchTicketsPage,
  patchTicket,
  type Ticket,
  type TicketDetail,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'

const statusOptions = [
  { value: 'NEW', label: 'Новая' },
  { value: 'TRIAGED', label: 'Оттриажена' },
  { value: 'ASSIGNED', label: 'Назначена' },
  { value: 'IN_PROGRESS', label: 'В работе' },
  { value: 'WAITING_USER', label: 'Ожидаем пользователя' },
  { value: 'RESOLVED', label: 'Решена' },
  { value: 'CLOSED', label: 'Закрыта' },
  { value: 'REOPENED', label: 'Переоткрыта' },
]

const priorityOptions = [
  { value: 'LOW', label: 'Low' },
  { value: 'MEDIUM', label: 'Medium' },
  { value: 'HIGH', label: 'High' },
  { value: 'CRITICAL', label: 'Critical' },
]

const categoryOptions = [
  { value: 'NETWORK_INTERNET', label: 'Сеть / Интернет' },
  { value: 'HARDWARE_WORKSTATION', label: 'Рабочее место' },
  { value: 'PRINTING', label: 'Печать' },
  { value: 'ACCESS_PLATONUS', label: 'Доступы / Platonus' },
  { value: 'ACCESS_MOODLE', label: 'Доступы / Moodle' },
  { value: 'SOFTWARE_INSTALL', label: 'Установка ПО' },
  { value: 'ACCOUNT_PASSWORD', label: 'Пароли / Учетные записи' },
  { value: 'MAIL', label: 'Почта' },
  { value: 'AV_PROJECTOR', label: 'Проектор / Презентации' },
  { value: 'NETWORK_WIFI', label: 'Сеть / Wi‑Fi' },
  { value: 'PROCUREMENT', label: 'Закупка / Новый ноутбук' },
  { value: 'SECURITY_PHISHING', label: 'Безопасность / Фишинг' },
]

type TicketFormState = {
  title: string
  description: string
  requester_name: string
  requester_email: string
  department: string
  location: string
  category: string
  priority: string
  assignee_name: string
  asset_id: string
}

const emptyTicketForm: TicketFormState = {
  title: '',
  description: '',
  requester_name: '',
  requester_email: '',
  department: 'Service Desk',
  location: '',
  category: 'NETWORK_INTERNET',
  priority: 'MEDIUM',
  assignee_name: '',
  asset_id: '',
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function minutesToLabel(minutes: number | null) {
  if (minutes == null) return '—'
  if (minutes < 60) return `${minutes} мин`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest === 0 ? `${hours} ч` : `${hours} ч ${rest} мин`
}

function isClosedStatus(status: string) {
  return ['RESOLVED', 'CLOSED'].includes(status)
}

function aiCategoryToTicketCategory(value: string): string | undefined {
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
  return map[value]
}

function TicketBadge({ label, color }: { label: string; color: string }) {
  return (
    <span className="inline-pill" style={{ color, borderColor: `${color}55`, backgroundColor: `${color}18` }}>
      {label}
    </span>
  )
}

function toTicketDetailFallback(ticket: Ticket): TicketDetail {
  return {
    ...ticket,
    comments: [],
    history_count: 0,
  }
}

export default function TicketsPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [priorityFilter, setPriorityFilter] = useState('ALL')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<TicketFormState>(emptyTicketForm)
  const [detailStatus, setDetailStatus] = useState('NEW')
  const [detailAssignee, setDetailAssignee] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const [notificationHint, setNotificationHint] = useState<string | null>(null)

  useEffect(() => {
    if (!selectedTicketId && !isCreateOpen) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (selectedTicketId) {
        setSelectedTicketId(null)
        return
      }
      if (isCreateOpen) {
        setIsCreateOpen(false)
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectedTicketId, isCreateOpen])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim())
      setPage(1)
    }, 300)
    return () => window.clearTimeout(timer)
  }, [search])

  const ticketsQuery = useQuery({
    queryKey: ['tickets', session?.access_token, debouncedSearch, statusFilter, priorityFilter, page, pageSize],
    queryFn: () =>
      fetchTicketsPage(session?.access_token ?? '', {
        q: debouncedSearch || undefined,
        status: statusFilter,
        priority: priorityFilter,
        page,
        page_size: pageSize,
      }),
    enabled: Boolean(session?.access_token),
  })

  const assetsQuery = useQuery({
    queryKey: ['assets', session?.access_token],
    queryFn: () => fetchAssets(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const selectedTicketQuery = useQuery({
    queryKey: ['ticket', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicket(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const ticketHistoryQuery = useQuery({
    queryKey: ['ticket-history', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketHistory(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const aiSuggestionsQuery = useQuery({
    queryKey: ['ticket-ai-suggestions', session?.access_token, selectedTicketId],
    queryFn: () => fetchAiSuggestions(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const automationSuggestionsQuery = useQuery({
    queryKey: ['ticket-automation-suggestions', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketAutomationSuggestions(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  useEffect(() => {
    if (!selectedTicketQuery.data) return
    setDetailStatus(selectedTicketQuery.data.status)
    setDetailAssignee(selectedTicketQuery.data.assignee_name ?? '')
  }, [selectedTicketQuery.data])

  const createMutation = useMutation({
    mutationFn: async (payload: TicketFormState) => {
      if (!session?.access_token) throw new Error('No session')
      return createTicket(session.access_token, {
        title: payload.title,
        description: payload.description || null,
        requester_name: payload.requester_name,
        requester_email: payload.requester_email,
        department: payload.department,
        location: payload.location,
        category: payload.category,
        priority: payload.priority,
        assignee_name: payload.assignee_name || null,
        asset_id: payload.asset_id || null,
      })
    },
    onSuccess: async (ticket) => {
      setIsCreateOpen(false)
      setCreateForm(emptyTicketForm)
      setNotificationHint('Создано уведомление: заявка создана.')
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
      setSelectedTicketId(ticket.id)
    },
  })

  const updateMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; status: string; assignee_name: string; category?: string; priority?: string }) => {
      if (!session?.access_token) throw new Error('No session')
      return patchTicket(session.access_token, payload.ticketId, {
        status: payload.status,
        assignee_name: payload.assignee_name || null,
        category: payload.category,
        priority: payload.priority,
      })
    },
    onSuccess: async (ticket) => {
      setNotificationHint('Создано уведомление об изменениях заявки.')
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, ticket.id] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, ticket.id] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
  })

  const commentMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; body: string }) => {
      if (!session?.access_token) throw new Error('No session')
      return addTicketComment(session.access_token, payload.ticketId, { body: payload.body })
    },
    onSuccess: async (_, variables) => {
      setCommentBody('')
      setNotificationHint('Создано уведомление о новом комментарии.')
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
  })

  const aiAnalyzeMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; text: string }) => {
      if (!session?.access_token) throw new Error('No session')
      return analyzeTicketWithAi(session.access_token, { ticket_id: payload.ticketId, input_text: payload.text })
    },
    onSuccess: async (_, variables) => {
      setNotificationHint('AI рекомендация готова: создано уведомление.')
      await queryClient.invalidateQueries({ queryKey: ['ticket-ai-suggestions', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
  })

  const createArticleMutation = useMutation({
    mutationFn: async (ticketId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return createArticleFromTicket(session.access_token, ticketId)
    },
  })

  const tickets = ticketsQuery.data?.items ?? []
  const totalTickets = ticketsQuery.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(totalTickets / pageSize))
  const assets = assetsQuery.data ?? []

  useEffect(() => {
    if (page > totalPages) {
      setPage(totalPages)
    }
  }, [page, totalPages])

  const filteredTickets = useMemo(() => tickets, [tickets])

  const openCount = tickets.filter((ticket) => !isClosedStatus(ticket.status)).length
  const overdueCount = tickets.filter((ticket) => {
    if (!ticket.sla_due_at || isClosedStatus(ticket.status)) return false
    return new Date(ticket.sla_due_at).getTime() < Date.now()
  }).length
  const criticalCount = tickets.filter((ticket) => ticket.priority === 'CRITICAL' && !isClosedStatus(ticket.status)).length
  const todayCount = tickets.filter((ticket) => new Date(ticket.created_at).toDateString() === new Date().toDateString()).length
  const responseValues = tickets.map((ticket) => ticket.response_minutes ?? 0).filter((value) => value > 0)
  const avgResponse = responseValues.length === 0 ? null : Math.round(responseValues.reduce((sum, value) => sum + value, 0) / responseValues.length)

  const workload = useMemo(() => {
    const map = new Map<string, number>()
    tickets
      .filter((ticket) => !isClosedStatus(ticket.status))
      .forEach((ticket) => {
        const assignee = ticket.assignee_name || 'Не назначен'
        map.set(assignee, (map.get(assignee) ?? 0) + 1)
      })
    return Array.from(map.entries())
      .map(([assignee, count]) => ({ assignee, count }))
      .sort((left, right) => right.count - left.count)
      .slice(0, 5)
  }, [tickets])

  const topCategories = useMemo(() => {
    const map = new Map<string, number>()
    tickets.forEach((ticket) => {
      map.set(ticket.category_label, (map.get(ticket.category_label) ?? 0) + 1)
    })
    return Array.from(map.entries())
      .map(([category, count]) => ({ category, count }))
      .sort((left, right) => right.count - left.count)
      .slice(0, 5)
  }, [tickets])

  const selectedTableTicket = selectedTicketId ? tickets.find((item) => item.id === selectedTicketId) ?? null : null
  const detail = selectedTicketQuery.data ?? (selectedTableTicket ? toTicketDetailFallback(selectedTableTicket) : null)
  const history = ticketHistoryQuery.data ?? []
  const suggestions = aiSuggestionsQuery.data ?? []
  const latestSuggestion = suggestions[0] ?? null
  const automationSuggestions = automationSuggestionsQuery.data

  return (
    <AppShell title="Заявки" subtitle="Service Desk для Demo Tenant уже работает как полноценный demo-ready workflow.">
      <section className="foundation-card">
        <div>
          <p className="eyebrow">SERVICE DESK</p>
          <h2>Очередь обращений</h2>
          <p>
            Таблица, фильтры, карточка заявки, история и комментарии доступны прямо здесь. Это уже рабочий demo flow, а не статичный shell.
          </p>
        </div>
        <div className="status-column">
          <HealthBadge />
          <div className="status-list">
            <span>✓ Table workflow</span>
            <span>✓ Status and assignee actions</span>
            <span>✓ Comment and history timeline</span>
          </div>
        </div>
      </section>

      {notificationHint ? (
        <section className="foundation-card ticket-notification-banner">
          <div>
            <p className="eyebrow">NOTIFICATION EVENT</p>
            <h2>Уведомление создано</h2>
            <p>{notificationHint}</p>
          </div>
          <button type="button" className="ghost-button" onClick={() => setNotificationHint(null)}>
            Скрыть
          </button>
        </section>
      ) : null}

      <section className="metric-grid tickets-metrics">
        <article className="metric-card">
          <span>Открытых заявок</span>
          <strong>{ticketsQuery.isPending ? '…' : openCount}</strong>
          <p>Все заявки, кроме закрытых и решённых.</p>
        </article>
        <article className="metric-card">
          <span>Просрочено SLA</span>
          <strong>{ticketsQuery.isPending ? '…' : overdueCount}</strong>
          <p>Те, что уже вышли за срок реакции или решения.</p>
        </article>
        <article className="metric-card">
          <span>Критичных</span>
          <strong>{ticketsQuery.isPending ? '…' : criticalCount}</strong>
          <p>Высокий приоритет без закрытых заявок.</p>
        </article>
        <article className="metric-card">
          <span>Среднее время реакции</span>
          <strong>{ticketsQuery.isPending ? '…' : avgResponse == null ? '—' : `${avgResponse}м`}</strong>
          <p>Считается по seeded response history.</p>
        </article>
        <article className="metric-card">
          <span>Заявки за сегодня</span>
          <strong>{ticketsQuery.isPending ? '…' : todayCount}</strong>
          <p>Создано в текущую дату.</p>
        </article>
        <article className="metric-card">
          <span>Исполнителей в работе</span>
          <strong>{ticketsQuery.isPending ? '…' : workload.length}</strong>
          <p>Нагрузка текущих assignee.</p>
        </article>
      </section>

      <section className="foundation-card dashboard-split">
        <div>
          <p className="eyebrow">TOP CATEGORIES</p>
          <h2>Топ категорий обращений</h2>
          <div className="mini-bars">
            {topCategories.map((item) => (
              <div className="mini-bar-row" key={item.category}>
                <span>{item.category}</span>
                <div className="mini-bar-track">
                  <div className="mini-bar-fill" style={{ width: `${Math.max(14, (item.count / Math.max(1, tickets.length)) * 100)}%` }} />
                </div>
                <strong>{item.count}</strong>
              </div>
            ))}
          </div>
        </div>
        <div className="status-column">
          <p className="eyebrow">WORKLOAD</p>
          <div className="workload-list">
            {workload.map((item) => (
              <article className="workload-card" key={item.assignee}>
                <span>{item.assignee}</span>
                <strong>{item.count}</strong>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="foundation-card tickets-toolbar">
        <div className="tickets-toolbar-group">
          <label className="inline-field">
            <span>Поиск</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="№ заявки, тема, заявитель, отдел..." />
          </label>
          <label className="inline-field">
            <span>Статус</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="ALL">Все статусы</option>
              {statusOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Приоритет</span>
            <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
              <option value="ALL">Все приоритеты</option>
              {priorityOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>На страницу</span>
            <select
              value={String(pageSize)}
              onChange={(event) => {
                setPageSize(Number(event.target.value))
                setPage(1)
              }}
            >
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </label>
        </div>
        <button type="button" className="ghost-button tickets-create-button" onClick={() => setIsCreateOpen(true)}>
          Создать заявку
        </button>
      </section>

      <section className="ticket-table-shell">
        {ticketsQuery.isPending ? (
          <p className="muted">Загрузка заявок…</p>
        ) : ticketsQuery.isError ? (
          <p className="error-message">Не удалось получить список заявок.</p>
        ) : (
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead>
                <tr>
                  <th>№</th>
                  <th>Тема</th>
                  <th>Заявитель</th>
                  <th>Отдел</th>
                  <th>Категория</th>
                  <th>Приоритет</th>
                  <th>Статус</th>
                  <th>Исполнитель</th>
                  <th>Актив</th>
                  <th>SLA</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {filteredTickets.map((ticket) => {
                  const overdue = ticket.sla_due_at ? new Date(ticket.sla_due_at).getTime() < Date.now() && !isClosedStatus(ticket.status) : false
                  return (
                    <tr key={ticket.id} className={overdue ? 'row-overdue' : ''}>
                      <td>{ticket.ticket_number}</td>
                      <td>
                        <strong>{ticket.title}</strong>
                        <p className="table-subtext">{ticket.location}</p>
                      </td>
                      <td>
                        {ticket.requester_name}
                        <p className="table-subtext">{ticket.requester_email}</p>
                      </td>
                      <td>{ticket.department}</td>
                      <td>
                        <TicketBadge label={ticket.category_label} color={ticket.category_color} />
                      </td>
                      <td>
                        <TicketBadge label={ticket.priority_label} color={ticket.priority_color} />
                      </td>
                      <td>
                        <TicketBadge label={ticket.status_label} color={ticket.status_color} />
                      </td>
                      <td>{ticket.assignee_name ?? 'Не назначен'}</td>
                      <td>
                        <div className="ticket-asset-cell">
                          <strong>{ticket.asset_tag ?? 'Без актива'}</strong>
                          <p className="table-subtext">{ticket.asset_name ?? ticket.asset_type ?? 'Не привязан'}</p>
                        </div>
                      </td>
                      <td>
                        <div className="ticket-sla-cell">
                          <span>{formatDateTime(ticket.sla_due_at)}</span>
                          {overdue ? <small>Просрочено</small> : <small>{ticket.sla_status ?? minutesToLabel(ticket.response_minutes)}</small>}
                        </div>
                      </td>
                      <td>
                        <button type="button" className="ghost-button row-action" onClick={() => setSelectedTicketId(ticket.id)}>
                          Открыть
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        {!ticketsQuery.isPending && !ticketsQuery.isError ? (
          <div className="analytics-actions">
            <p className="muted">Показано {tickets.length} из {totalTickets}</p>
            <div className="analytics-actions">
              <button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                Назад
              </button>
              <span className="muted">Страница {page} / {totalPages}</span>
              <button type="button" className="ghost-button" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>
                Вперёд
              </button>
            </div>
          </div>
        ) : null}
      </section>

      {isCreateOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsCreateOpen(false)}>
          <div className="modal-card modal-card-large" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <p className="eyebrow">НОВАЯ ЗАЯВКА</p>
                <h2>Создать заявку</h2>
              </div>
              <button type="button" className="ghost-button" onClick={() => setIsCreateOpen(false)}>
                Закрыть
              </button>
            </div>
            <form
              className="modal-form"
              onSubmit={(event) => {
                event.preventDefault()
                createMutation.mutate(createForm)
              }}
            >
              <div className="form-grid">
                <label>
                  <span>Тема</span>
                  <input value={createForm.title} onChange={(event) => setCreateForm((state) => ({ ...state, title: event.target.value }))} />
                </label>
                <label>
                  <span>Заявитель</span>
                  <input
                    value={createForm.requester_name}
                    onChange={(event) => setCreateForm((state) => ({ ...state, requester_name: event.target.value }))}
                  />
                </label>
                <label>
                  <span>Почта заявителя</span>
                  <input
                    value={createForm.requester_email}
                    onChange={(event) => setCreateForm((state) => ({ ...state, requester_email: event.target.value }))}
                  />
                </label>
                <label>
                  <span>Отдел</span>
                  <input value={createForm.department} onChange={(event) => setCreateForm((state) => ({ ...state, department: event.target.value }))} />
                </label>
                <label>
                  <span>Локация</span>
                  <input value={createForm.location} onChange={(event) => setCreateForm((state) => ({ ...state, location: event.target.value }))} />
                </label>
                <label>
                  <span>Категория</span>
                  <select value={createForm.category} onChange={(event) => setCreateForm((state) => ({ ...state, category: event.target.value }))}>
                    {categoryOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Приоритет</span>
                  <select value={createForm.priority} onChange={(event) => setCreateForm((state) => ({ ...state, priority: event.target.value }))}>
                    {priorityOptions.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Исполнитель</span>
                  <input
                    value={createForm.assignee_name}
                    onChange={(event) => setCreateForm((state) => ({ ...state, assignee_name: event.target.value }))}
                  />
                </label>
                <label>
                  <span>Актив</span>
                  <select value={createForm.asset_id} onChange={(event) => setCreateForm((state) => ({ ...state, asset_id: event.target.value }))}>
                    <option value="">Без привязки</option>
                    {assets.map((asset) => (
                      <option key={asset.id} value={asset.id}>
                        {asset.asset_tag} · {asset.name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                <span>Описание</span>
                <textarea
                  value={createForm.description}
                  onChange={(event) => setCreateForm((state) => ({ ...state, description: event.target.value }))}
                  rows={4}
                />
              </label>
              <button type="submit" disabled={createMutation.isPending}>
                {createMutation.isPending ? 'Создание…' : 'Создать заявку'}
              </button>
            </form>
          </div>
        </div>
      ) : null}

      {selectedTicketId ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setSelectedTicketId(null)}>
          <div className="modal-card modal-card-xl" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <p className="eyebrow">КАРТОЧКА ЗАЯВКИ</p>
                <h2>{detail?.ticket_number ?? 'Загрузка...'}</h2>
                <p className="modal-subtitle">{detail?.title ?? 'Получаем карточку заявки...'}</p>
              </div>
              <button type="button" className="ghost-button" onClick={() => setSelectedTicketId(null)}>
                Закрыть
              </button>
            </div>

            {selectedTicketQuery.isPending && !detail ? <p className="muted">Загрузка карточки заявки…</p> : null}
            {selectedTicketQuery.isError && !detail ? <p className="error-message">Не удалось загрузить карточку заявки.</p> : null}

            {detail ? (
              <>
                {selectedTicketQuery.isError ? <p className="error-message">Детальная API-карточка недоступна. Показаны данные из таблицы.</p> : null}

            <div className="ticket-detail-grid">
              <section className="ticket-detail-panel">
                <h3>Информация</h3>
                <div className="detail-fields">
                  <div><span>Заявитель</span><strong>{detail.requester_name}</strong></div>
                  <div><span>Почта</span><strong>{detail.requester_email}</strong></div>
                  <div><span>Отдел</span><strong>{detail.department}</strong></div>
                  <div><span>Локация</span><strong>{detail.location}</strong></div>
                  <div><span>Категория</span><strong>{detail.category_label}</strong></div>
                  <div><span>Приоритет</span><strong>{detail.priority_label}</strong></div>
                  <div><span>Актив</span><strong>{detail.asset_tag ?? 'Без актива'}</strong></div>
                  <div><span>Тип актива</span><strong>{detail.asset_name ?? detail.asset_type ?? '—'}</strong></div>
                  <div><span>SLA статус</span><strong>{detail.sla_status ?? '—'}</strong></div>
                  <div><span>Создана</span><strong>{formatDateTime(detail.created_at)}</strong></div>
                  <div><span>SLA due</span><strong>{formatDateTime(detail.sla_due_at)}</strong></div>
                  <div><span>Response due</span><strong>{formatDateTime(detail.response_due_at)}</strong></div>
                  <div><span>Resolution due</span><strong>{formatDateTime(detail.resolution_due_at)}</strong></div>
                </div>
                <p className="ticket-description">{detail.description ?? 'Описание отсутствует'}</p>
              </section>

              <section className="ticket-detail-panel">
                <h3>Управление</h3>
                <div className="form-stack">
                  <label>
                    <span>Статус</span>
                    <select value={detailStatus} onChange={(event) => setDetailStatus(event.target.value)}>
                      {statusOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Исполнитель</span>
                    <input value={detailAssignee} onChange={(event) => setDetailAssignee(event.target.value)} />
                  </label>
                  <button
                    type="button"
                    onClick={() =>
                      updateMutation.mutate({
                        ticketId: detail.id,
                        status: detailStatus,
                        assignee_name: detailAssignee,
                      })
                    }
                    disabled={updateMutation.isPending}
                  >
                    {updateMutation.isPending ? 'Сохранение…' : 'Сохранить изменения'}
                  </button>
                </div>

                <div className="comment-box">
                  <h4>Комментарий</h4>
                  <textarea value={commentBody} onChange={(event) => setCommentBody(event.target.value)} rows={4} placeholder="Добавить рабочий комментарий…" />
                  <button type="button" onClick={() => commentMutation.mutate({ ticketId: detail.id, body: commentBody })} disabled={!commentBody.trim() || commentMutation.isPending}>
                    {commentMutation.isPending ? 'Отправка…' : 'Добавить комментарий'}
                  </button>
                </div>

                <div className="comment-box">
                  <h4>AI-рекомендации</h4>
                  {latestSuggestion ? (
                    <div className="activity-list">
                      <article className="activity-item">
                        <header>
                          <strong>{latestSuggestion.recommended_category}</strong>
                          <span>{latestSuggestion.confidence}</span>
                        </header>
                        <p>{latestSuggestion.summary}</p>
                        <small>{latestSuggestion.possible_cause}</small>
                        <small>{latestSuggestion.suggested_solution}</small>
                      </article>
                      <article className="activity-item">
                        <header>
                          <strong>Предложенные статьи</strong>
                        </header>
                        <ul>
                          {latestSuggestion.related_articles.length === 0 ? <li>Не найдено</li> : latestSuggestion.related_articles.map((item) => <li key={item.id}>{item.article_number} · {item.title}</li>)}
                        </ul>
                      </article>
                    </div>
                  ) : (
                    <p className="muted">Рекомендаций пока нет.</p>
                  )}

                  <button
                    type="button"
                    onClick={() => aiAnalyzeMutation.mutate({ ticketId: detail.id, text: `${detail.title}. ${detail.description ?? ''}` })}
                    disabled={aiAnalyzeMutation.isPending}
                  >
                    {aiAnalyzeMutation.isPending ? 'Анализ...' : 'Сгенерировать AI-рекомендацию'}
                  </button>

                  {latestSuggestion ? (
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() =>
                        updateMutation.mutate({
                          ticketId: detail.id,
                          status: detailStatus,
                          assignee_name: latestSuggestion.recommended_assignee,
                          category: aiCategoryToTicketCategory(latestSuggestion.recommended_category),
                          priority: latestSuggestion.recommended_priority,
                        })
                      }
                    >
                      Применить рекомендацию
                    </button>
                  ) : null}

                  <button
                    type="button"
                    className="ghost-button"
                    onClick={() => createArticleMutation.mutate(detail.id)}
                    disabled={createArticleMutation.isPending}
                  >
                    {createArticleMutation.isPending ? 'Создание...' : 'Создать статью из решенной заявки'}
                  </button>
                </div>

                <div className="comment-box">
                  <h4>Automation / Runbook suggestions</h4>
                  {automationSuggestionsQuery.isPending ? <p className="muted">Подбираем runbooks и правила…</p> : null}
                  {automationSuggestionsQuery.isError ? <p className="error-message">Не удалось получить automation suggestions.</p> : null}
                  {!automationSuggestionsQuery.isPending && !automationSuggestionsQuery.isError ? (
                    <>
                      <div className="activity-list">
                        {(automationSuggestions?.suggested_runbooks ?? []).map((item) => (
                          <article className="activity-item" key={item.id}>
                            <header>
                              <strong>{item.title}</strong>
                              <span>{item.severity}</span>
                            </header>
                            <p>{item.category}</p>
                            <small>{item.estimated_minutes} min</small>
                          </article>
                        ))}
                      </div>
                      {automationSuggestions?.matched_rules?.length ? (
                        <pre className="analytics-export-preview">{JSON.stringify(automationSuggestions.matched_rules, null, 2)}</pre>
                      ) : (
                        <p className="muted">Совпадающие automation rules не найдены.</p>
                      )}
                    </>
                  ) : null}
                </div>
              </section>
            </div>

            <section className="ticket-detail-panel activity-panel">
              <div className="activity-columns">
                <div>
                  <h3>Комментарии</h3>
                  <div className="activity-list">
                    {(detail.comments ?? []).length === 0 ? (
                      <p className="muted">Комментариев пока нет.</p>
                    ) : (
                      (detail.comments ?? []).map((comment) => (
                        <article className="activity-item" key={comment.id}>
                          <header>
                            <strong>{comment.author_name}</strong>
                            <span>{formatDateTime(comment.created_at)}</span>
                          </header>
                          <p>{comment.body}</p>
                        </article>
                      ))
                    )}
                  </div>
                </div>
                <div>
                  <h3>История</h3>
                  <div className="activity-list">
                    {ticketHistoryQuery.isPending ? (
                      <p className="muted">Загрузка истории…</p>
                    ) : history.length === 0 ? (
                      <p className="muted">История пока пуста.</p>
                    ) : (
                      history.map((item) => (
                        <article className="activity-item" key={item.id}>
                          <header>
                            <strong>{item.actor_name}</strong>
                            <span>{formatDateTime(item.created_at)}</span>
                          </header>
                          <p>{item.message}</p>
                        </article>
                      ))
                    )}
                  </div>
                </div>
              </div>
            </section>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}