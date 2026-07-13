import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  addTicketComment,
  analyzeTicket,
  attachArticleToTicket,
  assignTicket,
  createArticleFromTicket,
  createTicket,
  fetchAdminUsers,
  fetchAiSuggestions,
  fetchAssets,
  fetchTicket,
  fetchTicketHistory,
  fetchTicketKnowledge,
  fetchTicketsPage,
  transitionTicket,
  useArticleForTicket,
  type CreateTicketRequest,
  type Ticket,
  type TicketDetail,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'

type QueueKey = 'all' | 'mine' | 'unassigned' | 'critical' | 'sla_breached' | 'due_today' | 'created_by_me' | 'closed'
type TicketTab = 'overview' | 'comments' | 'history' | 'sla' | 'asset' | 'ai'
type TicketSortBy = 'updated_at' | 'created_at' | 'priority' | 'status' | 'sla_due_at' | 'ticket_number'
type TicketSortDir = 'asc' | 'desc'

type TicketFilterPreset = {
  id: string
  name: string
  queue: QueueKey
  statusFilter: string
  priorityFilter: string
  categoryFilter: string
  assigneeFilter: string
  sortBy: TicketSortBy
  sortDir: TicketSortDir
  pageSize: number
}

type ActionFeedback = {
  kind: 'success' | 'error'
  message: string
}

type BulkActionResult = {
  updatedCount: number
  skippedCount: number
  errors: string[]
}

type RequesterTemplate = {
  id: string
  label: string
  category: string
  priority: string
  title: string
  description: string
  summary: string
  requiredFields: Array<'location' | 'requester_contact' | 'description'>
}

type TicketTimelineItem = {
  id: string
  title: string
  timestamp: string | null
  note: string
  tone: 'info' | 'success' | 'warning' | 'danger'
}

type TicketFormState = {
  title: string
  description: string
  category: string
  priority: string
  department: string
  location: string
  requester_id: string
  requester_name: string
  requester_email: string
  requester_contact: string
  assignee_id: string
  asset_id: string
}

const queueOptions: Array<{ value: QueueKey; label: string }> = [
  { value: 'all', label: 'Все' },
  { value: 'mine', label: 'Моя очередь' },
  { value: 'unassigned', label: 'Неназначенные' },
  { value: 'critical', label: 'Критичные' },
  { value: 'sla_breached', label: 'SLA просрочено' },
  { value: 'due_today', label: 'На сегодня' },
  { value: 'created_by_me', label: 'Созданные мной' },
  { value: 'closed', label: 'Закрытые' },
]

const statusOptions = [
  { value: 'ALL', label: 'Все статусы' },
  { value: 'NEW', label: 'Новая' },
  { value: 'TRIAGE', label: 'Разбор' },
  { value: 'ASSIGNED', label: 'Назначена' },
  { value: 'IN_PROGRESS', label: 'В работе' },
  { value: 'WAITING_USER', label: 'Ожидает пользователя' },
  { value: 'WAITING_VENDOR', label: 'Ожидает поставщика' },
  { value: 'RESOLVED', label: 'Решена' },
  { value: 'CLOSED', label: 'Закрыта' },
  { value: 'REOPENED', label: 'Переоткрыта' },
  { value: 'CANCELLED', label: 'Отменена' },
]

const transitionOptions = statusOptions.filter((item) => item.value !== 'ALL')

const priorityOptions = [
  { value: 'ALL', label: 'Все приоритеты' },
  { value: 'LOW', label: 'Низкий' },
  { value: 'MEDIUM', label: 'Средний' },
  { value: 'HIGH', label: 'Высокий' },
  { value: 'CRITICAL', label: 'Критичный' },
]

const categoryOptions = [
  { value: 'ALL', label: 'Все категории' },
  { value: 'NETWORK_INTERNET', label: 'Сеть / Интернет' },
  { value: 'HARDWARE_WORKSTATION', label: 'Рабочее место' },
  { value: 'PRINTING', label: 'Печать' },
  { value: 'ACCESS_PLATONUS', label: 'Доступы / Platonus' },
  { value: 'ACCESS_MOODLE', label: 'Доступы / Moodle' },
  { value: 'SOFTWARE_INSTALL', label: 'Установка ПО' },
  { value: 'ACCOUNT_PASSWORD', label: 'Пароли / Учетные записи' },
  { value: 'MAIL', label: 'Почта' },
  { value: 'AV_PROJECTOR', label: 'Проектор / Презентации' },
  { value: 'NETWORK_WIFI', label: 'Сеть / Wi-Fi' },
  { value: 'PROCUREMENT', label: 'Закупка / Новый ноутбук' },
  { value: 'SECURITY_PHISHING', label: 'Безопасность / Фишинг' },
]

const emptyTicketForm: TicketFormState = {
  title: '',
  description: '',
  category: 'NETWORK_INTERNET',
  priority: 'MEDIUM',
  department: 'Service Desk',
  location: '',
  requester_id: '',
  requester_name: '',
  requester_email: '',
  requester_contact: '',
  assignee_id: '',
  asset_id: '',
}

const requesterTemplates: RequesterTemplate[] = [
  {
    id: 'internet',
    label: 'Интернет / Wi-Fi',
    category: 'NETWORK_WIFI',
    priority: 'HIGH',
    title: 'Нет доступа к интернету',
    description: 'Опишите, где и когда пропал доступ: корпус, кабинет/зона, устройство, вид ошибки.',
    summary: 'Сбои Wi-Fi, отсутствие IP, нестабильный интернет в кабинете или зоне.',
    requiredFields: ['location', 'description'],
  },
  {
    id: 'account',
    label: 'Доступ / Пароль',
    category: 'ACCOUNT_PASSWORD',
    priority: 'HIGH',
    title: 'Проблема с доступом к учетной записи',
    description: 'Укажите систему, логин и текст ошибки. Если была смена устройства или телефона, добавьте это в описание.',
    summary: 'Проблемы входа, блокировки аккаунта, восстановление пароля.',
    requiredFields: ['requester_contact', 'description'],
  },
  {
    id: 'mail',
    label: 'Почта',
    category: 'MAIL',
    priority: 'MEDIUM',
    title: 'Не работает корпоративная почта',
    description: 'Опишите проблему: отправка, получение, синхронизация или авторизация.',
    summary: 'Не отправляются/не приходят письма, ошибки синхронизации.',
    requiredFields: ['description'],
  },
  {
    id: 'software',
    label: 'Установка ПО',
    category: 'SOFTWARE_INSTALL',
    priority: 'LOW',
    title: 'Запрос на установку программного обеспечения',
    description: 'Укажите название ПО, версию, цель использования и срок, когда доступ должен быть предоставлен.',
    summary: 'Установка или обновление рабочего ПО по запросу пользователя.',
    requiredFields: ['location', 'description'],
  },
]

const requesterFieldLabels: Record<'location' | 'requester_contact' | 'description', string> = {
  location: 'Локация',
  requester_contact: 'Контакт заявителя',
  description: 'Описание',
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function slaBadgeLabel(value: string | null) {
  if (value === 'BREACHED') return 'Просрочено'
  if (value === 'RISK' || value === 'WARNING') return 'Риск'
  return 'Норма'
}

function priorityLabel(value: string) {
  const item = priorityOptions.find((option) => option.value === value)
  return item ? item.label : value
}

function statusLabel(value: string) {
  const item = statusOptions.find((option) => option.value === value)
  return item ? item.label : value
}

function toDetailFallback(ticket: Ticket): TicketDetail {
  return { ...ticket, comments: [], history_count: 0 }
}

function canUseInternalComment(role: string) {
  return role !== 'requester'
}

function canManageAssignments(role: string) {
  return ['saas_root', 'organization_admin', 'it_manager'].includes(role)
}

function canTakeTicket(role: string) {
  return role === 'it_agent'
}

function canCreateArticleFromTicket(role: string) {
  return ['saas_root', 'organization_admin', 'it_manager', 'it_agent'].includes(role)
}

function canQuickAssignToMe(role: string, assigneeId: string | null, assigneeName: string | null) {
  return role === 'it_agent' && !assigneeId && !(assigneeName || '').trim()
}

function canQuickStart(role: string, status: string, assigneeId: string | null, assigneeName: string | null, currentUserId: string | undefined, currentUserName: string | undefined) {
  if (role === 'requester') return false
  if (!['ASSIGNED', 'TRIAGE', 'REOPENED'].includes(status)) return false
  if (role === 'it_agent') {
    return assigneeId === currentUserId || Boolean(currentUserName && assigneeName?.toLowerCase() === currentUserName.toLowerCase())
  }
  return true
}

function canQuickResolve(role: string, status: string, assigneeId: string | null, assigneeName: string | null, currentUserId: string | undefined, currentUserName: string | undefined) {
  if (role === 'requester') return false
  if (!['IN_PROGRESS', 'WAITING_USER', 'WAITING_VENDOR'].includes(status)) return false
  if (role === 'it_agent') {
    return assigneeId === currentUserId || Boolean(currentUserName && assigneeName?.toLowerCase() === currentUserName.toLowerCase())
  }
  return true
}

function canRequesterAccept(status: string) {
  return status === 'RESOLVED'
}

function canRequesterReopen(status: string) {
  return status === 'RESOLVED' || status === 'CLOSED'
}

function formatMinutes(value: number | null | undefined) {
  if (value == null) return '—'
  if (value < 60) return `${value} мин`
  const hours = Math.floor(value / 60)
  const minutes = value % 60
  return minutes > 0 ? `${hours} ч ${minutes} мин` : `${hours} ч`
}

export default function TicketsPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const role = session?.user.role ?? 'guest'
  const isRequester = role === 'requester'
  const isStaff = role !== 'requester'
  const presetStorageKey = `tickets-presets:${session?.user.id ?? 'anonymous'}`

  const [queue, setQueue] = useState<QueueKey>('all')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [priorityFilter, setPriorityFilter] = useState('ALL')
  const [categoryFilter, setCategoryFilter] = useState('ALL')
  const [assigneeFilter, setAssigneeFilter] = useState('ALL')
  const [sortBy, setSortBy] = useState<TicketSortBy>('sla_due_at')
  const [sortDir, setSortDir] = useState<TicketSortDir>('asc')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)
  const [selectedTicketIds, setSelectedTicketIds] = useState<string[]>([])
  const [bulkStatus, setBulkStatus] = useState('IN_PROGRESS')
  const [bulkAssigneeId, setBulkAssigneeId] = useState('')
  const [bulkComment, setBulkComment] = useState('Массовая операция оператора')
  const [isBulkPreviewOpen, setIsBulkPreviewOpen] = useState(false)
  const [presets, setPresets] = useState<TicketFilterPreset[]>([])
  const [presetName, setPresetName] = useState('')
  const [activePresetId, setActivePresetId] = useState('')
  const [actionFeedback, setActionFeedback] = useState<ActionFeedback | null>(null)
  const [createValidationError, setCreateValidationError] = useState<string | null>(null)

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<TicketFormState>(emptyTicketForm)

  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TicketTab>('overview')
  const [transitionStatus, setTransitionStatus] = useState('IN_PROGRESS')
  const [transitionComment, setTransitionComment] = useState('')
  const [requesterDecisionComment, setRequesterDecisionComment] = useState('')
  const [assignComment, setAssignComment] = useState('')
  const [assignUserId, setAssignUserId] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const [commentInternal, setCommentInternal] = useState(false)

  const selectedRequesterTemplate = useMemo(
    () => requesterTemplates.find((template) => template.category === createForm.category) ?? null,
    [createForm.category]
  )

  const requesterRequiredFields = useMemo(() => {
    if (!selectedRequesterTemplate) return ['description'] as Array<'location' | 'requester_contact' | 'description'>
    return selectedRequesterTemplate.requiredFields
  }, [selectedRequesterTemplate])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim())
      setPage(1)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [search])

  useEffect(() => {
    setPage(1)
  }, [queue, statusFilter, priorityFilter, categoryFilter, assigneeFilter, sortBy, sortDir, pageSize])

  useEffect(() => {
    if (!isRequester) return
    setQueue((current) => {
      if (current === 'all' || current === 'mine' || current === 'unassigned' || current === 'critical' || current === 'sla_breached' || current === 'due_today') {
        return 'created_by_me'
      }
      return current
    })
  }, [isRequester])

  useEffect(() => {
    setSelectedTicketIds([])
  }, [queue, debouncedSearch, statusFilter, priorityFilter, categoryFilter, assigneeFilter, sortBy, sortDir, page, pageSize])

  useEffect(() => {
    if (!actionFeedback) return
    const timer = window.setTimeout(() => setActionFeedback(null), 5000)
    return () => window.clearTimeout(timer)
  }, [actionFeedback])

  useEffect(() => {
    if (!session?.user?.id) {
      setPresets([])
      return
    }
    const raw = window.localStorage.getItem(presetStorageKey)
    if (!raw) {
      setPresets([])
      return
    }
    try {
      const parsed = JSON.parse(raw) as TicketFilterPreset[]
      setPresets(Array.isArray(parsed) ? parsed : [])
    } catch {
      setPresets([])
    }
  }, [presetStorageKey, session?.user?.id])

  useEffect(() => {
    if (!session?.user?.id) return
    window.localStorage.setItem(presetStorageKey, JSON.stringify(presets))
  }, [presetStorageKey, presets, session?.user?.id])

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
    if (!session?.user) return
    if (!isCreateOpen) return
    setCreateValidationError(null)
    if (isRequester) {
      setCreateForm((state) => ({
        ...state,
        requester_id: session.user.id,
        requester_name: session.user.full_name,
        requester_email: session.user.email,
        assignee_id: '',
      }))
    }
  }, [isCreateOpen, isRequester, session?.user])

  const ticketsQuery = useQuery({
    queryKey: ['tickets', session?.access_token, queue, debouncedSearch, statusFilter, priorityFilter, categoryFilter, assigneeFilter, sortBy, sortDir, page, pageSize],
    queryFn: () =>
      fetchTicketsPage(session?.access_token ?? '', {
        queue,
        q: debouncedSearch || undefined,
        status: statusFilter,
        priority: priorityFilter,
        category: categoryFilter,
        assignee_name: assigneeFilter,
        sort_by: sortBy,
        sort_dir: sortDir,
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

  const usersQuery = useQuery({
    queryKey: ['admin-users', session?.access_token],
    queryFn: () => fetchAdminUsers(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && canManageAssignments(role),
  })

  const selectedTicketQuery = useQuery({
    queryKey: ['ticket', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicket(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const historyQuery = useQuery({
    queryKey: ['ticket-history', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketHistory(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const aiSuggestionsQuery = useQuery({
    queryKey: ['ticket-ai', session?.access_token, selectedTicketId],
    queryFn: () => fetchAiSuggestions(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const ticketKnowledgeQuery = useQuery({
    queryKey: ['ticket-knowledge', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketKnowledge(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const createMutation = useMutation({
    mutationFn: async (payload: TicketFormState) => {
      const request: CreateTicketRequest = {
        title: payload.title,
        description: payload.description || null,
        category: payload.category,
        priority: payload.priority,
        department: payload.department,
        location: payload.location || null,
        requester_id: payload.requester_id || null,
        requester_name: payload.requester_name,
        requester_email: payload.requester_email,
        requester_contact: payload.requester_contact || null,
        assignee_id: payload.assignee_id || null,
        asset_id: payload.asset_id || null,
      }
      return createTicket(session?.access_token ?? '', request)
    },
    onSuccess: async (ticket) => {
      setIsCreateOpen(false)
      setCreateForm(emptyTicketForm)
      setSelectedTicketId(ticket.id)
      setActionFeedback({ kind: 'success', message: `Заявка ${ticket.ticket_number ?? ''} создана.`.trim() })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Не удалось создать заявку.' })
    },
  })

  const transitionMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; status: string; comment?: string; is_internal?: boolean }) =>
      transitionTicket(session?.access_token ?? '', payload.ticketId, {
        status: payload.status,
        comment: payload.comment,
        is_internal: payload.is_internal,
      }),
    onSuccess: async (ticket) => {
      setTransitionComment('')
      setActionFeedback({ kind: 'success', message: `Статус заявки ${ticket.ticket_number ?? ''} обновлен.`.trim() })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, ticket.id] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, ticket.id] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Не удалось изменить статус.' })
    },
  })

  const assignMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; assignee_id?: string | null; comment?: string }) =>
      assignTicket(session?.access_token ?? '', payload.ticketId, payload),
    onSuccess: async (ticket) => {
      setAssignComment('')
      setActionFeedback({ kind: 'success', message: `Исполнитель по заявке ${ticket.ticket_number ?? ''} обновлен.`.trim() })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, ticket.id] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, ticket.id] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Не удалось назначить исполнителя.' })
    },
  })

  const commentMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; body: string; is_internal: boolean }) =>
      addTicketComment(session?.access_token ?? '', payload.ticketId, payload),
    onSuccess: async (_, variables) => {
      setCommentBody('')
      setCommentInternal(false)
      setActionFeedback({ kind: 'success', message: 'Комментарий добавлен.' })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Не удалось добавить комментарий.' })
    },
  })

  const bulkMutation = useMutation({
    mutationFn: async (payload: { ticketIds: string[]; status?: string; assigneeId?: string; comment?: string }): Promise<BulkActionResult> => {
      const token = session?.access_token ?? ''
      let updatedCount = 0
      let skippedCount = 0
      const errors: string[] = []

      for (const ticketId of payload.ticketIds) {
        try {
          if (payload.assigneeId) {
            await assignTicket(token, ticketId, {
              assignee_id: payload.assigneeId,
              comment: payload.comment || undefined,
            })
          }
          if (payload.status) {
            await transitionTicket(token, ticketId, {
              status: payload.status,
              comment: payload.comment || undefined,
              is_internal: isStaff,
            })
          }
          updatedCount += 1
        } catch (error) {
          skippedCount += 1
          errors.push(error instanceof Error ? error.message : `Ошибка по заявке ${ticketId}`)
        }
      }

      return { updatedCount, skippedCount, errors }
    },
    onSuccess: async (result) => {
      setSelectedTicketIds([])
      setIsBulkPreviewOpen(false)
      if (result.skippedCount === 0) {
        setActionFeedback({ kind: 'success', message: `Массовая операция завершена: обновлено ${result.updatedCount}.` })
      } else {
        const firstError = result.errors[0] ? ` Первая ошибка: ${result.errors[0]}` : ''
        setActionFeedback({ kind: 'error', message: `Массовая операция завершена частично: обновлено ${result.updatedCount}, пропущено ${result.skippedCount}.${firstError}` })
      }
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Не удалось выполнить массовую операцию.' })
    },
  })

  const aiMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; text: string }) =>
      analyzeTicket(session?.access_token ?? '', { ticket_id: payload.ticketId, input_text: payload.text }),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ['ticket-ai', session?.access_token, variables.ticketId] })
    },
  })

  const articleMutation = useMutation({
    mutationFn: async (ticketId: string) => createArticleFromTicket(session?.access_token ?? '', ticketId),
  })

  const attachArticleMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; articleId: string; confidence: number | null }) =>
      attachArticleToTicket(session?.access_token ?? '', payload.ticketId, {
        article_id: payload.articleId,
        link_type: 'ai_suggestion',
        confidence: payload.confidence,
        comment: 'Attached from ticket AI tab',
      }),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ['ticket-knowledge', session?.access_token, variables.ticketId] })
    },
  })

  const useArticleMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; articleId: string }) => useArticleForTicket(session?.access_token ?? '', payload.ticketId, payload.articleId),
  })

  const tickets = ticketsQuery.data?.items ?? []
  const total = ticketsQuery.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const assets = assetsQuery.data ?? []
  const users = usersQuery.data ?? []
  const allPageTicketIds = useMemo(() => tickets.map((ticket) => ticket.id), [tickets])
  const allPageSelected = allPageTicketIds.length > 0 && allPageTicketIds.every((id) => selectedTicketIds.includes(id))

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const selectedTableTicket = selectedTicketId ? tickets.find((item) => item.id === selectedTicketId) ?? null : null
  const detail = selectedTicketQuery.data ?? (selectedTableTicket ? toDetailFallback(selectedTableTicket) : null)

  const timelineItems = useMemo<TicketTimelineItem[]>(() => {
    if (!detail) return []

    const items: TicketTimelineItem[] = [
      {
        id: 'created',
        title: 'Заявка создана',
        timestamp: detail.created_at,
        note: `Создана пользователем ${detail.requester_name}`,
        tone: 'info',
      },
    ]

    if (detail.response_due_at) {
      let note = `Дедлайн первой реакции: ${formatDateTime(detail.response_due_at)}`
      let tone: TicketTimelineItem['tone'] = 'info'
      if (detail.is_response_breached) {
        note = `SLA первой реакции нарушен. Фактическое время реакции: ${formatMinutes(detail.response_minutes)}`
        tone = 'danger'
      } else if (detail.response_minutes != null) {
        note = `Первая реакция выполнена за ${formatMinutes(detail.response_minutes)}`
        tone = 'success'
      }
      items.push({
        id: 'response-sla',
        title: 'SLA первой реакции',
        timestamp: detail.response_due_at,
        note,
        tone,
      })
    }

    if (detail.resolution_due_at) {
      const resolutionDone = detail.resolved_at || detail.closed_at
      let note = `Дедлайн решения: ${formatDateTime(detail.resolution_due_at)}`
      let tone: TicketTimelineItem['tone'] = 'info'
      if (detail.is_resolution_breached && !resolutionDone) {
        note = 'SLA решения нарушен. Требуется срочное действие команды.'
        tone = 'danger'
      } else if (resolutionDone) {
        note = `Решение зафиксировано: ${formatDateTime(detail.resolved_at ?? detail.closed_at)}`
        tone = detail.is_resolution_breached ? 'warning' : 'success'
      }
      items.push({
        id: 'resolution-sla',
        title: 'SLA решения',
        timestamp: detail.resolution_due_at,
        note,
        tone,
      })
    }

    if (detail.resolved_at) {
      items.push({
        id: 'resolved',
        title: 'Решение предложено',
        timestamp: detail.resolved_at,
        note: 'Заявка переведена в статус Решена.',
        tone: 'success',
      })
    }

    if (detail.closed_at) {
      items.push({
        id: 'closed',
        title: 'Заявка закрыта',
        timestamp: detail.closed_at,
        note: 'Решение подтверждено и обращение закрыто.',
        tone: 'success',
      })
    }

    if (detail.reopened_at) {
      items.push({
        id: 'reopened',
        title: 'Заявка переоткрыта',
        timestamp: detail.reopened_at,
        note: 'Проблема не устранена полностью, заявка возвращена в работу.',
        tone: 'warning',
      })
    }

    let waitingUserAt: string | null = null
    const history = historyQuery.data ?? []
    for (let index = history.length - 1; index >= 0; index -= 1) {
      const item = history[index]
      if (item.event_type !== 'status_changed') continue
      if ((item.new_value ?? '').toUpperCase() !== 'WAITING_USER') continue
      waitingUserAt = item.created_at
      break
    }
    if (detail.status === 'WAITING_USER' || waitingUserAt) {
      items.push({
        id: 'waiting-user',
        title: 'Ожидается ответ пользователя',
        timestamp: waitingUserAt,
        note: 'Нужно подтвердить результат или уточнить детали в комментариях.',
        tone: 'warning',
      })
    }

    return items.sort((a, b) => {
      const left = a.timestamp ? new Date(a.timestamp).getTime() : 0
      const right = b.timestamp ? new Date(b.timestamp).getTime() : 0
      return right - left
    })
  }, [detail, historyQuery.data])

  useEffect(() => {
    if (!detail) return
    setTransitionStatus(detail.status)
    setAssignUserId(detail.assignee_id ?? '')
    setRequesterDecisionComment('')
  }, [detail?.id, detail?.status, detail?.assignee_id])

  const assigneeOptions = useMemo(() => {
    const values = new Set<string>()
    tickets.forEach((ticket) => {
      if (ticket.assignee_name) values.add(ticket.assignee_name)
    })
    return Array.from(values).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [tickets])

  const selectedTicketsPreview = useMemo(
    () => tickets.filter((ticket) => selectedTicketIds.includes(ticket.id)),
    [tickets, selectedTicketIds]
  )

  const bulkAssigneeName = useMemo(() => {
    if (!bulkAssigneeId) return 'Без назначения'
    return users.find((user) => user.id === bulkAssigneeId)?.full_name ?? 'Выбранный исполнитель'
  }, [bulkAssigneeId, users])

  const triageStats = useMemo(() => {
    const overdue = tickets.filter((ticket) => ticket.sla_badge === 'BREACHED').length
    const dueToday = tickets.filter((ticket) => {
      const dueAt = ticket.resolution_due_at ?? ticket.sla_due_at
      if (!dueAt) return false
      const due = new Date(dueAt)
      const now = new Date()
      return due.getFullYear() === now.getFullYear() && due.getMonth() === now.getMonth() && due.getDate() === now.getDate() && !['CLOSED', 'RESOLVED', 'CANCELLED'].includes(ticket.status)
    }).length
    const unassigned = tickets.filter((ticket) => !ticket.assignee_id && !ticket.assignee_name).length
    const critical = tickets.filter((ticket) => ticket.priority === 'CRITICAL').length
    return { overdue, dueToday, unassigned, critical }
  }, [tickets])

  const requesterStats = useMemo(() => {
    const isClosed = (status: string) => ['RESOLVED', 'CLOSED', 'CANCELLED'].includes(status)
    const open = tickets.filter((ticket) => !isClosed(ticket.status)).length
    const waitingUser = tickets.filter((ticket) => ticket.status === 'WAITING_USER').length
    const resolved = tickets.filter((ticket) => ticket.status === 'RESOLVED').length
    const overdue = tickets.filter((ticket) => ticket.sla_badge === 'BREACHED' && !isClosed(ticket.status)).length
    return { open, waitingUser, resolved, overdue }
  }, [tickets])

  const applyRequesterTemplate = (template: RequesterTemplate) => {
    setCreateValidationError(null)
    setCreateForm((state) => ({
      ...state,
      category: template.category,
      priority: template.priority,
      title: template.title,
      description: template.description,
      department: state.department || 'Service Desk',
      requester_contact: state.requester_contact,
    }))
    setIsCreateOpen(true)
  }

  const validateRequesterCreateForm = (payload: TicketFormState) => {
    const missing: Array<'location' | 'requester_contact' | 'description'> = []
    for (const field of requesterRequiredFields) {
      const value = payload[field]
      if (!value || !value.trim()) {
        missing.push(field)
      }
    }
    return missing
  }

  const toggleTicketSelection = (ticketId: string) => {
    setSelectedTicketIds((current) =>
      current.includes(ticketId) ? current.filter((id) => id !== ticketId) : [...current, ticketId]
    )
  }

  const toggleSelectPage = () => {
    setSelectedTicketIds((current) => {
      if (allPageSelected) {
        return current.filter((id) => !allPageTicketIds.includes(id))
      }
      const next = new Set([...current, ...allPageTicketIds])
      return Array.from(next)
    })
  }

  const savePreset = () => {
    const name = presetName.trim()
    if (!name) return
    const preset: TicketFilterPreset = {
      id: String(Date.now()),
      name,
      queue,
      statusFilter,
      priorityFilter,
      categoryFilter,
      assigneeFilter,
      sortBy,
      sortDir,
      pageSize,
    }
    setPresets((current) => [...current, preset])
    setPresetName('')
    setActivePresetId(preset.id)
  }

  const applyPreset = (presetId: string) => {
    setActivePresetId(presetId)
    const preset = presets.find((item) => item.id === presetId)
    if (!preset) return
    setQueue(preset.queue)
    setStatusFilter(preset.statusFilter)
    setPriorityFilter(preset.priorityFilter)
    setCategoryFilter(preset.categoryFilter)
    setAssigneeFilter(preset.assigneeFilter)
    setSortBy(preset.sortBy)
    setSortDir(preset.sortDir)
    setPageSize(preset.pageSize)
    setPage(1)
  }

  const removeActivePreset = () => {
    if (!activePresetId) return
    setPresets((current) => current.filter((item) => item.id !== activePresetId))
    setActivePresetId('')
  }

  const applyKpiFilter = (filter: 'overdue' | 'dueToday' | 'unassigned' | 'critical') => {
    setPage(1)
    if (filter === 'overdue') {
      setQueue('sla_breached')
      return
    }
    if (filter === 'dueToday') {
      setQueue('due_today')
      return
    }
    if (filter === 'unassigned') {
      setQueue('unassigned')
      return
    }
    setQueue('critical')
  }

  return (
    <AppShell
      title="Заявки"
      subtitle="Service Desk, обращения пользователей, статусы, комментарии, SLA и история действий."
    >
      <section className="foundation-card">
        <div>
          <p className="eyebrow">SERVICE DESK</p>
          <h2>{isRequester ? 'Мои обращения в ИТ-службу' : 'Рабочий центр ИТ-службы'}</h2>
          <p>
            {isRequester
              ? 'Создавайте обращения по шаблонам, отслеживайте статусы и отвечайте в комментариях по своим заявкам.'
              : 'Очереди, управление статусами, назначение исполнителей, комментарии и аудит действий в одном экране.'}
          </p>
        </div>
        <button type="button" className="ghost-button" onClick={() => setIsCreateOpen(true)}>
          {isRequester ? 'Создать обращение' : 'Создать заявку'}
        </button>
      </section>

      {isRequester ? (
        <section className="foundation-card" style={{ marginTop: 12 }}>
          <div>
            <p className="eyebrow">REQUESTER QUICK START</p>
            <h3 style={{ margin: '6px 0 8px' }}>Быстрые шаблоны обращения</h3>
            <p className="muted" style={{ margin: 0 }}>Выберите тип проблемы, и форма создания откроется уже заполненной.</p>
          </div>
          <div className="analytics-actions" style={{ marginTop: 12, justifyContent: 'flex-start', flexWrap: 'wrap' }}>
            {requesterTemplates.map((template) => (
              <button key={template.id} type="button" className="ghost-button" onClick={() => applyRequesterTemplate(template)}>
                {template.label}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {actionFeedback ? (
        <section
          className="foundation-card"
          style={{ marginTop: 12, borderColor: actionFeedback.kind === 'success' ? '#15803d' : '#b42318', background: actionFeedback.kind === 'success' ? '#f0fdf4' : '#fef2f2' }}
        >
          <p style={{ margin: 0, color: actionFeedback.kind === 'success' ? '#166534' : '#b42318', fontWeight: 600 }}>
            {actionFeedback.message}
          </p>
        </section>
      ) : null}

      <section className="module-subnav" style={{ marginTop: 18 }}>
        {(isRequester ? queueOptions.filter((item) => ['created_by_me', 'closed'].includes(item.value)) : queueOptions).map((item) => (
          <button
            key={item.value}
            type="button"
            className={`module-subnav-tab ${queue === item.value ? 'active' : ''}`}
            onClick={() => setQueue(item.value)}
          >
            {item.label}
          </button>
        ))}
      </section>

      <section className="foundation-card tickets-toolbar" style={{ marginTop: 14 }}>
        <div className="tickets-toolbar-group" style={{ gridTemplateColumns: isRequester ? 'repeat(6, minmax(0, 1fr))' : 'repeat(8, minmax(0, 1fr))' }}>
          <label className="inline-field">
            <span>Поиск</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Номер, тема, заявитель" />
          </label>
          <label className="inline-field">
            <span>Статус</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              {statusOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Приоритет</span>
            <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
              {priorityOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Категория</span>
            <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
              {categoryOptions.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </label>
          {!isRequester ? (
            <label className="inline-field">
              <span>Исполнитель</span>
              <select value={assigneeFilter} onChange={(event) => setAssigneeFilter(event.target.value)}>
                <option value="ALL">Все</option>
                {assigneeOptions.map((value) => (
                  <option key={value} value={value}>{value}</option>
                ))}
              </select>
            </label>
          ) : null}
          <label className="inline-field">
            <span>Сортировать по</span>
            <select value={sortBy} onChange={(event) => setSortBy(event.target.value as TicketSortBy)}>
              <option value="updated_at">Обновлено</option>
              <option value="created_at">Создано</option>
              <option value="priority">Приоритет</option>
              <option value="status">Статус</option>
              <option value="sla_due_at">SLA дедлайн</option>
              <option value="ticket_number">Номер</option>
            </select>
          </label>
          <label className="inline-field">
            <span>Порядок</span>
            <select value={sortDir} onChange={(event) => setSortDir(event.target.value as TicketSortDir)}>
              <option value="desc">Сначала новые</option>
              <option value="asc">Сначала старые</option>
            </select>
          </label>
          <label className="inline-field">
            <span>На страницу</span>
            <select value={String(pageSize)} onChange={(event) => setPageSize(Number(event.target.value))}>
              <option value="25">25</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
          </label>
        </div>
      </section>

      {!isRequester ? (
        <section className="foundation-card tickets-toolbar" style={{ marginTop: 12 }}>
          <div className="tickets-toolbar-group" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
            <label className="inline-field">
              <span>Пресет</span>
              <select value={activePresetId} onChange={(event) => applyPreset(event.target.value)}>
                <option value="">Без пресета</option>
                {presets.map((preset) => (
                  <option key={preset.id} value={preset.id}>{preset.name}</option>
                ))}
              </select>
            </label>
            <label className="inline-field">
              <span>Сохранить пресет</span>
              <input value={presetName} onChange={(event) => setPresetName(event.target.value)} placeholder="Например: Ночные SLA" />
            </label>
            <div className="analytics-actions" style={{ alignItems: 'end' }}>
              <button type="button" className="ghost-button" onClick={savePreset} disabled={!presetName.trim()}>
                Сохранить
              </button>
              <button type="button" className="ghost-button" onClick={removeActivePreset} disabled={!activePresetId}>
                Удалить
              </button>
            </div>
            <div className="inline-field">
              <span>Выбрано заявок</span>
              <strong>{selectedTicketIds.length}</strong>
            </div>
          </div>
        </section>
      ) : null}

      {isStaff ? (
        <section className="foundation-card tickets-toolbar" style={{ marginTop: 12 }}>
          <div className="tickets-toolbar-group" style={{ gridTemplateColumns: canManageAssignments(role) ? 'repeat(4, minmax(0, 1fr))' : 'repeat(3, minmax(0, 1fr))' }}>
            <label className="inline-field">
              <span>Массовый статус</span>
              <select value={bulkStatus} onChange={(event) => setBulkStatus(event.target.value)}>
                {transitionOptions.filter((item) => item.value !== 'ALL').map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            {canManageAssignments(role) ? (
              <label className="inline-field">
                <span>Массовое назначение</span>
                <select value={bulkAssigneeId} onChange={(event) => setBulkAssigneeId(event.target.value)}>
                  <option value="">Без назначения</option>
                  {users.map((user) => (
                    <option key={user.id} value={user.id}>{user.full_name}</option>
                  ))}
                </select>
              </label>
            ) : null}
            <label className="inline-field">
              <span>Комментарий операции</span>
              <input value={bulkComment} onChange={(event) => setBulkComment(event.target.value)} />
            </label>
            <div className="analytics-actions" style={{ alignItems: 'end' }}>
              <button
                type="button"
                className="ghost-button"
                disabled={selectedTicketIds.length === 0 || bulkMutation.isPending}
                onClick={() => setIsBulkPreviewOpen(true)}
              >
                Предпросмотр и подтверждение
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {isBulkPreviewOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsBulkPreviewOpen(false)}>
          <div className="modal-card modal-card-large" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <p className="eyebrow">BULK PREVIEW</p>
                <h2>Подтверждение массового действия</h2>
                <p className="modal-subtitle">Проверь список заявок и параметры операции перед применением.</p>
              </div>
              <button type="button" className="ghost-button" onClick={() => setIsBulkPreviewOpen(false)}>Закрыть</button>
            </div>

            <section className="foundation-card" style={{ marginBottom: 12 }}>
              <div className="detail-fields">
                <div><span>Количество заявок</span><strong>{selectedTicketsPreview.length}</strong></div>
                <div><span>Новый статус</span><strong>{statusLabel(bulkStatus)}</strong></div>
                <div><span>Назначение</span><strong>{bulkAssigneeName}</strong></div>
                <div><span>Комментарий</span><strong>{bulkComment || '—'}</strong></div>
              </div>
            </section>

            <section className="ticket-table-wrap" style={{ maxHeight: 320, overflow: 'auto' }}>
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Номер</th>
                    <th>Тема</th>
                    <th>Текущий статус</th>
                    <th>Приоритет</th>
                    <th>Исполнитель</th>
                  </tr>
                </thead>
                <tbody>
                  {selectedTicketsPreview.map((ticket) => (
                    <tr key={ticket.id}>
                      <td>{ticket.ticket_number ?? '—'}</td>
                      <td>{ticket.title}</td>
                      <td>{statusLabel(ticket.status)}</td>
                      <td>{priorityLabel(ticket.priority)}</td>
                      <td>{ticket.assignee_name ?? 'Не назначен'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <div className="analytics-actions" style={{ marginTop: 16, justifyContent: 'flex-end' }}>
              <button type="button" className="ghost-button" onClick={() => setIsBulkPreviewOpen(false)}>
                Отмена
              </button>
              <button
                type="button"
                disabled={selectedTicketIds.length === 0 || bulkMutation.isPending}
                onClick={() =>
                  bulkMutation.mutate({
                    ticketIds: selectedTicketIds,
                    status: bulkStatus,
                    assigneeId: canManageAssignments(role) ? bulkAssigneeId || undefined : undefined,
                    comment: bulkComment || undefined,
                  })
                }
              >
                {bulkMutation.isPending ? 'Применение...' : 'Подтвердить массовое действие'}
              </button>
            </div>
          </div>
        </div>
      ) : null}

      <section className="foundation-card" style={{ marginTop: 12 }}>
        {isRequester ? (
          <div className="tickets-toolbar-group" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
            <div className="inline-field" style={{ minHeight: 82 }}>
              <span>Открытые</span>
              <strong>{requesterStats.open}</strong>
            </div>
            <div className="inline-field" style={{ minHeight: 82 }}>
              <span>Ожидают моего ответа</span>
              <strong style={{ color: requesterStats.waitingUser > 0 ? '#b54708' : undefined }}>{requesterStats.waitingUser}</strong>
            </div>
            <div className="inline-field" style={{ minHeight: 82 }}>
              <span>Решенные</span>
              <strong>{requesterStats.resolved}</strong>
            </div>
            <div className="inline-field" style={{ minHeight: 82 }}>
              <span>Просроченные</span>
              <strong style={{ color: requesterStats.overdue > 0 ? '#b42318' : undefined }}>{requesterStats.overdue}</strong>
            </div>
          </div>
        ) : (
          <div className="tickets-toolbar-group" style={{ gridTemplateColumns: 'repeat(4, minmax(0, 1fr))' }}>
            <button type="button" className="inline-field ghost-button" style={{ textAlign: 'left', display: 'block', minHeight: 82 }} onClick={() => applyKpiFilter('overdue')}>
              <span>SLA просрочено</span>
              <strong style={{ color: triageStats.overdue > 0 ? '#b42318' : undefined }}>{triageStats.overdue}</strong>
            </button>
            <button type="button" className="inline-field ghost-button" style={{ textAlign: 'left', display: 'block', minHeight: 82 }} onClick={() => applyKpiFilter('dueToday')}>
              <span>На сегодня</span>
              <strong style={{ color: triageStats.dueToday > 0 ? '#b54708' : undefined }}>{triageStats.dueToday}</strong>
            </button>
            <button type="button" className="inline-field ghost-button" style={{ textAlign: 'left', display: 'block', minHeight: 82 }} onClick={() => applyKpiFilter('unassigned')}>
              <span>Неназначенные</span>
              <strong>{triageStats.unassigned}</strong>
            </button>
            <button type="button" className="inline-field ghost-button" style={{ textAlign: 'left', display: 'block', minHeight: 82 }} onClick={() => applyKpiFilter('critical')}>
              <span>Критичные</span>
              <strong style={{ color: triageStats.critical > 0 ? '#b42318' : undefined }}>{triageStats.critical}</strong>
            </button>
          </div>
        )}
      </section>

      <section className="ticket-table-shell">
        {ticketsQuery.isPending ? <p className="muted">Загрузка заявок...</p> : null}
        {ticketsQuery.isError ? <p className="error-message">Не удалось загрузить список заявок.</p> : null}
        {!ticketsQuery.isPending && !ticketsQuery.isError ? (
          <>
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    {!isRequester ? (
                      <th>
                        <input type="checkbox" checked={allPageSelected} onChange={toggleSelectPage} aria-label="Выбрать все на странице" />
                      </th>
                    ) : null}
                    <th>Номер</th>
                    <th>Тема</th>
                    <th>Статус</th>
                    <th>Приоритет</th>
                    <th>Категория</th>
                    <th>Заявитель</th>
                    <th>Исполнитель</th>
                    <th>SLA</th>
                    <th>Обновлено</th>
                    <th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {tickets.map((ticket) => (
                    <tr key={ticket.id} className={ticket.sla_badge === 'BREACHED' ? 'row-overdue' : ''}>
                      {!isRequester ? (
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedTicketIds.includes(ticket.id)}
                            onChange={() => toggleTicketSelection(ticket.id)}
                            aria-label={`Выбрать заявку ${ticket.ticket_number ?? ticket.id}`}
                          />
                        </td>
                      ) : null}
                      <td>{ticket.ticket_number ?? '—'}</td>
                      <td>
                        <strong>{ticket.title}</strong>
                        <p className="table-subtext">{ticket.location}</p>
                      </td>
                      <td>{statusLabel(ticket.status)}</td>
                      <td>{priorityLabel(ticket.priority)}</td>
                      <td>{ticket.category_label}</td>
                      <td>
                        {ticket.requester_name}
                        <p className="table-subtext">{ticket.requester_email}</p>
                      </td>
                      <td>{ticket.assignee_name ?? 'Не назначен'}</td>
                      <td>
                        <div className="ticket-sla-cell">
                          <strong>{slaBadgeLabel(ticket.sla_badge)}</strong>
                          <small>{formatDateTime(ticket.resolution_due_at ?? ticket.sla_due_at)}</small>
                        </div>
                      </td>
                      <td>{formatDateTime(ticket.updated_at)}</td>
                      <td>
                        <div className="analytics-actions" style={{ justifyContent: 'flex-start', flexWrap: 'wrap' }}>
                          {!isRequester && canQuickAssignToMe(role, ticket.assignee_id, ticket.assignee_name) ? (
                            <button
                              type="button"
                              className="ghost-button row-action"
                              onClick={() => assignMutation.mutate({ ticketId: ticket.id, comment: 'Взял в работу' })}
                              disabled={assignMutation.isPending}
                            >
                              Взять
                            </button>
                          ) : null}
                          {!isRequester && canQuickStart(role, ticket.status, ticket.assignee_id, ticket.assignee_name, session?.user.id, session?.user.full_name) ? (
                            <button
                              type="button"
                              className="ghost-button row-action"
                              onClick={() => transitionMutation.mutate({ ticketId: ticket.id, status: 'IN_PROGRESS', comment: 'Переведено в работу', is_internal: isStaff })}
                              disabled={transitionMutation.isPending}
                            >
                              Старт
                            </button>
                          ) : null}
                          {!isRequester && canQuickResolve(role, ticket.status, ticket.assignee_id, ticket.assignee_name, session?.user.id, session?.user.full_name) ? (
                            <button
                              type="button"
                              className="ghost-button row-action"
                              onClick={() => transitionMutation.mutate({ ticketId: ticket.id, status: 'RESOLVED', comment: 'Решено оператором', is_internal: isStaff })}
                              disabled={transitionMutation.isPending}
                            >
                              Решить
                            </button>
                          ) : null}
                          <button type="button" className="ghost-button row-action" onClick={() => setSelectedTicketId(ticket.id)}>
                            Открыть
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-pagination">
              <p className="muted">Показано {tickets.length} из {total}</p>
              <div className="analytics-actions">
                <button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Назад</button>
                <span className="muted">Страница {page} / {totalPages}</span>
                <button type="button" className="ghost-button" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>Вперед</button>
              </div>
            </div>
          </>
        ) : null}
      </section>

      {isCreateOpen ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsCreateOpen(false)}>
          <div className="modal-card modal-card-large" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <p className="eyebrow">НОВАЯ ЗАЯВКА</p>
                <h2>Создание обращения</h2>
              </div>
              <button type="button" className="ghost-button" onClick={() => setIsCreateOpen(false)}>Закрыть</button>
            </div>

            <form
              className="modal-form"
              onSubmit={(event) => {
                event.preventDefault()
                if (isRequester) {
                  const missingFields = validateRequesterCreateForm(createForm)
                  if (missingFields.length > 0) {
                    const requiredLabels = missingFields.map((field) => requesterFieldLabels[field]).join(', ')
                    setCreateValidationError(`Заполните обязательные поля: ${requiredLabels}.`)
                    return
                  }
                }
                setCreateValidationError(null)
                createMutation.mutate(createForm)
              }}
            >
              {isRequester ? (
                <section className="foundation-card" style={{ marginBottom: 12, gridTemplateColumns: '1fr', gap: 12 }}>
                  <div>
                    <p className="eyebrow">SERVICE CATALOG</p>
                    <h3 style={{ margin: '4px 0 8px' }}>Выберите тип услуги</h3>
                    <p className="muted" style={{ margin: 0 }}>Категория задает обязательные поля и ускоряет обработку обращения.</p>
                  </div>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 10 }}>
                    {requesterTemplates.map((template) => {
                      const active = createForm.category === template.category
                      return (
                        <button
                          key={template.id}
                          type="button"
                          className="ghost-button"
                          style={{
                            textAlign: 'left',
                            display: 'grid',
                            gap: 6,
                            borderColor: active ? '#40a8ff' : undefined,
                            background: active ? '#17344e' : undefined,
                          }}
                          onClick={() => applyRequesterTemplate(template)}
                        >
                          <strong>{template.label}</strong>
                          <span className="muted" style={{ fontSize: '.82rem' }}>{template.summary}</span>
                          <small className="muted">Обязательно: {template.requiredFields.map((field) => requesterFieldLabels[field]).join(', ')}</small>
                        </button>
                      )
                    })}
                  </div>
                </section>
              ) : null}

              {isRequester ? (
                <section className="foundation-card" style={{ marginBottom: 12, gridTemplateColumns: '1fr', gap: 10 }}>
                  <div className="detail-fields" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
                    <div><span>Каталог</span><strong>{selectedRequesterTemplate?.label ?? 'Общий запрос'}</strong></div>
                    <div><span>Обязательные поля</span><strong>{requesterRequiredFields.map((field) => requesterFieldLabels[field]).join(', ')}</strong></div>
                    <div><span>SLA приоритет</span><strong>{priorityLabel(createForm.priority)}</strong></div>
                  </div>
                </section>
              ) : null}

              {createValidationError ? <p className="error-message">{createValidationError}</p> : null}

              <div className="form-grid">
                <label>
                  <span>Тема</span>
                  <input required value={createForm.title} onChange={(event) => setCreateForm((state) => ({ ...state, title: event.target.value }))} />
                </label>
                <label>
                  <span>Категория</span>
                  <select value={createForm.category} onChange={(event) => setCreateForm((state) => ({ ...state, category: event.target.value }))}>
                    {categoryOptions.filter((item) => item.value !== 'ALL').map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Приоритет</span>
                  <select value={createForm.priority} onChange={(event) => setCreateForm((state) => ({ ...state, priority: event.target.value }))}>
                    {priorityOptions.filter((item) => item.value !== 'ALL').map((option) => (
                      <option key={option.value} value={option.value}>{option.label}</option>
                    ))}
                  </select>
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
                  <span>Контакт заявителя</span>
                  <input value={createForm.requester_contact} onChange={(event) => setCreateForm((state) => ({ ...state, requester_contact: event.target.value }))} />
                </label>
                {isRequester ? (
                  <>
                    <label>
                      <span>Заявитель</span>
                      <input value={createForm.requester_name} disabled />
                    </label>
                    <label>
                      <span>Email</span>
                      <input value={createForm.requester_email} disabled />
                    </label>
                  </>
                ) : (
                  <>
                    <label>
                      <span>Заявитель</span>
                      <select value={createForm.requester_id} onChange={(event) => {
                        const user = users.find((item) => item.id === event.target.value)
                        setCreateForm((state) => ({
                          ...state,
                          requester_id: event.target.value,
                          requester_name: user?.full_name ?? '',
                          requester_email: user?.email ?? '',
                        }))
                      }}>
                        <option value="">Выбрать</option>
                        {users.map((user) => (
                          <option key={user.id} value={user.id}>{user.full_name} · {user.email}</option>
                        ))}
                      </select>
                    </label>
                    <label>
                      <span>Исполнитель</span>
                      <select value={createForm.assignee_id} onChange={(event) => setCreateForm((state) => ({ ...state, assignee_id: event.target.value }))}>
                        <option value="">Не назначать</option>
                        {users.filter((user) => ['IT Manager', 'Network Agent', 'Support Agent'].some((name) => user.full_name.includes(name))).map((user) => (
                          <option key={user.id} value={user.id}>{user.full_name}</option>
                        ))}
                      </select>
                    </label>
                  </>
                )}
                <label>
                  <span>Актив</span>
                  <select value={createForm.asset_id} onChange={(event) => setCreateForm((state) => ({ ...state, asset_id: event.target.value }))}>
                    <option value="">Не привязан</option>
                    {assets.map((asset) => (
                      <option key={asset.id} value={asset.id}>{asset.asset_tag} · {asset.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <label>
                <span>Описание</span>
                <textarea value={createForm.description} onChange={(event) => setCreateForm((state) => ({ ...state, description: event.target.value }))} rows={5} />
              </label>
              <button type="submit" disabled={createMutation.isPending}>{createMutation.isPending ? 'Создание...' : 'Создать заявку'}</button>
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
                <p className="modal-subtitle">{detail?.title ?? ''}</p>
              </div>
              <button type="button" className="ghost-button" onClick={() => setSelectedTicketId(null)}>Закрыть</button>
            </div>

            {selectedTicketQuery.isPending && !detail ? <p className="muted">Загрузка...</p> : null}
            {selectedTicketQuery.isError && !detail ? <p className="error-message">Не удалось получить детали заявки.</p> : null}

            {detail ? (
              <>
                <section className="foundation-card" style={{ marginBottom: 14, gridTemplateColumns: '1fr auto' }}>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <span className="inline-pill">{statusLabel(detail.status)}</span>
                    <span className="inline-pill">{priorityLabel(detail.priority)}</span>
                    <span className="inline-pill">SLA: {slaBadgeLabel(detail.sla_badge)}</span>
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    {!isRequester && canTakeTicket(role) ? (
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => assignMutation.mutate({ ticketId: detail.id, comment: 'Взял в работу' })}
                        disabled={assignMutation.isPending}
                      >
                        Взять в работу
                      </button>
                    ) : null}
                    {!isRequester && canManageAssignments(role) ? (
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => assignMutation.mutate({ ticketId: detail.id, assignee_id: assignUserId || null, comment: assignComment || undefined })}
                        disabled={assignMutation.isPending}
                      >
                        Назначить
                      </button>
                    ) : null}
                    {!isRequester ? (
                      <>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => transitionMutation.mutate({ ticketId: detail.id, status: transitionStatus, comment: transitionComment, is_internal: isStaff })}
                          disabled={transitionMutation.isPending}
                        >
                          Сменить статус
                        </button>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => transitionMutation.mutate({ ticketId: detail.id, status: 'CLOSED', comment: 'Закрыто оператором' })}
                          disabled={transitionMutation.isPending}
                        >
                          Закрыть
                        </button>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => transitionMutation.mutate({ ticketId: detail.id, status: 'REOPENED', comment: 'Переоткрытие по запросу' })}
                          disabled={transitionMutation.isPending}
                        >
                          Переоткрыть
                        </button>
                      </>
                    ) : null}
                  </div>
                </section>

                <section className="module-subnav">
                  <button type="button" className={`module-subnav-tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Обзор</button>
                  <button type="button" className={`module-subnav-tab ${activeTab === 'comments' ? 'active' : ''}`} onClick={() => setActiveTab('comments')}>Комментарии</button>
                  <button type="button" className={`module-subnav-tab ${activeTab === 'history' ? 'active' : ''}`} onClick={() => setActiveTab('history')}>История</button>
                  <button type="button" className={`module-subnav-tab ${activeTab === 'sla' ? 'active' : ''}`} onClick={() => setActiveTab('sla')}>SLA</button>
                  <button type="button" className={`module-subnav-tab ${activeTab === 'asset' ? 'active' : ''}`} onClick={() => setActiveTab('asset')}>Актив</button>
                  <button type="button" className={`module-subnav-tab ${activeTab === 'ai' ? 'active' : ''}`} onClick={() => setActiveTab('ai')}>AI</button>
                </section>

                <section className="ticket-detail-panel" style={{ marginTop: 12 }}>
                  <h3>Таймлайн SLA и статусов</h3>
                  {isRequester && detail.status === 'WAITING_USER' ? (
                    <div
                      style={{
                        border: '1px solid #b54708',
                        background: '#2f210c',
                        borderRadius: 12,
                        padding: 12,
                        marginBottom: 12,
                      }}
                    >
                      <p style={{ margin: 0, color: '#fbcf93', fontWeight: 700 }}>Требуется ваш ответ по заявке</p>
                      <p style={{ margin: '6px 0 10px', color: '#f4d8b5' }}>Подтвердите результат или уточните детали в комментариях, чтобы команда продолжила работу.</p>
                      <button type="button" className="ghost-button" onClick={() => setActiveTab('comments')}>
                        Перейти к комментариям
                      </button>
                    </div>
                  ) : null}
                  <div className="activity-list">
                    {timelineItems.map((item) => (
                      <article
                        className="activity-item"
                        key={item.id}
                        style={{
                          borderColor:
                            item.tone === 'danger'
                              ? '#b42318'
                              : item.tone === 'warning'
                                ? '#b54708'
                                : item.tone === 'success'
                                  ? '#15803d'
                                  : '#2a445f',
                        }}
                      >
                        <header>
                          <strong>{item.title}</strong>
                          <span>{formatDateTime(item.timestamp)}</span>
                        </header>
                        <p>{item.note}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="ticket-detail-panel" style={{ marginTop: 12 }}>
                  {activeTab === 'overview' ? (
                    <div className="detail-fields">
                      <div><span>Заявитель</span><strong>{detail.requester_name}</strong></div>
                      <div><span>Email</span><strong>{detail.requester_email}</strong></div>
                      <div><span>Категория</span><strong>{detail.category_label}</strong></div>
                      <div><span>Приоритет</span><strong>{priorityLabel(detail.priority)}</strong></div>
                      <div><span>Исполнитель</span><strong>{detail.assignee_name ?? 'Не назначен'}</strong></div>
                      <div><span>Отдел</span><strong>{detail.department}</strong></div>
                      <div><span>Локация</span><strong>{detail.location}</strong></div>
                      <div><span>Обновлено</span><strong>{formatDateTime(detail.updated_at)}</strong></div>
                    </div>
                  ) : null}

                  {activeTab === 'comments' ? (
                    <div className="activity-columns" style={{ gridTemplateColumns: '1fr' }}>
                      <div className="comment-box">
                        <h4>Добавить комментарий</h4>
                        <textarea value={commentBody} onChange={(event) => setCommentBody(event.target.value)} rows={4} />
                        {canUseInternalComment(role) ? (
                          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                            <input type="checkbox" checked={commentInternal} onChange={(event) => setCommentInternal(event.target.checked)} />
                            Внутренний комментарий
                          </label>
                        ) : null}
                        <button
                          type="button"
                          onClick={() => commentMutation.mutate({ ticketId: detail.id, body: commentBody, is_internal: commentInternal && canUseInternalComment(role) })}
                          disabled={!commentBody.trim() || commentMutation.isPending}
                        >
                          {commentMutation.isPending ? 'Отправка...' : 'Добавить комментарий'}
                        </button>
                      </div>
                      <div className="activity-list">
                        {detail.comments.length === 0 ? <p className="muted">Комментариев пока нет.</p> : null}
                        {detail.comments.map((item) => (
                          <article className="activity-item" key={item.id}>
                            <header>
                              <strong>{item.author_name}</strong>
                              <span>{formatDateTime(item.created_at)}</span>
                            </header>
                            <p>{item.body}</p>
                            <small>{item.is_internal ? 'Внутренний' : 'Публичный'}</small>
                          </article>
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {activeTab === 'history' ? (
                    <div className="activity-list">
                      {historyQuery.isPending ? <p className="muted">Загрузка истории...</p> : null}
                      {!historyQuery.isPending && (historyQuery.data ?? []).length === 0 ? <p className="muted">История пока пуста.</p> : null}
                      {(historyQuery.data ?? []).map((item) => (
                        <article className="activity-item" key={item.id}>
                          <header>
                            <strong>{item.actor_name}</strong>
                            <span>{formatDateTime(item.created_at)}</span>
                          </header>
                          <p>{item.message}</p>
                        </article>
                      ))}
                    </div>
                  ) : null}

                  {activeTab === 'sla' ? (
                    <div className="detail-fields">
                      <div><span>SLA badge</span><strong>{slaBadgeLabel(detail.sla_badge)}</strong></div>
                      <div><span>Response due</span><strong>{formatDateTime(detail.response_due_at)}</strong></div>
                      <div><span>Resolution due</span><strong>{formatDateTime(detail.resolution_due_at)}</strong></div>
                      <div><span>Response remaining</span><strong>{detail.response_remaining_minutes ?? '—'} мин</strong></div>
                      <div><span>Resolution remaining</span><strong>{detail.resolution_remaining_minutes ?? '—'} мин</strong></div>
                      <div><span>Breached</span><strong>{detail.is_resolution_breached || detail.is_response_breached ? 'Да' : 'Нет'}</strong></div>
                    </div>
                  ) : null}

                  {activeTab === 'asset' ? (
                    <div className="detail-fields">
                      <div><span>Asset tag</span><strong>{detail.asset_tag ?? 'Не привязан'}</strong></div>
                      <div><span>Asset name</span><strong>{detail.asset_name ?? '—'}</strong></div>
                      <div><span>Тип</span><strong>{detail.asset_type ?? '—'}</strong></div>
                    </div>
                  ) : null}

                  {activeTab === 'ai' ? (
                    <div className="activity-list">
                      <button
                        type="button"
                        onClick={() => aiMutation.mutate({ ticketId: detail.id, text: `${detail.title}. ${detail.description ?? ''}` })}
                        disabled={aiMutation.isPending}
                      >
                        {aiMutation.isPending ? 'Анализ...' : 'Сгенерировать AI рекомендации'}
                      </button>
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => articleMutation.mutate(detail.id)}
                        disabled={articleMutation.isPending || !canCreateArticleFromTicket(role) || !['RESOLVED', 'CLOSED'].includes(detail.status)}
                        title={!canCreateArticleFromTicket(role) ? 'Доступно только staff/manager/admin' : !['RESOLVED', 'CLOSED'].includes(detail.status) ? 'Доступно только для RESOLVED/CLOSED' : undefined}
                      >
                        {articleMutation.isPending ? 'Создание...' : 'Создать статью из заявки'}
                      </button>
                      <h4>Прикрепленные статьи</h4>
                      {ticketKnowledgeQuery.isPending ? <p className="muted">Загрузка связанных статей...</p> : null}
                      {!ticketKnowledgeQuery.isPending && (ticketKnowledgeQuery.data ?? []).length === 0 ? <p className="muted">Связанных статей пока нет.</p> : null}
                      {(ticketKnowledgeQuery.data ?? []).map((link) => (
                        <article className="activity-item" key={link.id}>
                          <header>
                            <strong>{link.article_number} · {link.article_title}</strong>
                            <span>{link.link_type}</span>
                          </header>
                          <p>Linked by: {link.linked_by_name ?? '—'}</p>
                          <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() => useArticleMutation.mutate({ ticketId: detail.id, articleId: link.article_id })}
                              disabled={useArticleMutation.isPending}
                            >
                              Использовать для решения
                            </button>
                          </div>
                        </article>
                      ))}

                      <h4>Suggested articles</h4>
                      {(aiSuggestionsQuery.data ?? []).map((item) => (
                        <article className="activity-item" key={item.id}>
                          <header>
                            <strong>{item.recommended_category}</strong>
                            <span>{item.confidence}</span>
                          </header>
                          <p>{item.summary}</p>
                          <small>{item.suggested_solution}</small>
                          {item.recommended_article_id ? (
                            <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
                              <button
                                type="button"
                                className="ghost-button"
                                disabled={attachArticleMutation.isPending || !isStaff}
                                title={!isStaff ? 'Недостаточно прав для привязки статьи' : undefined}
                                onClick={() =>
                                  attachArticleMutation.mutate({
                                    ticketId: detail.id,
                                    articleId: item.recommended_article_id ?? '',
                                    confidence: item.confidence_value ?? null,
                                  })
                                }
                              >
                                Прикрепить статью
                              </button>
                              <button
                                type="button"
                                className="ghost-button"
                                disabled={useArticleMutation.isPending}
                                onClick={() => useArticleMutation.mutate({ ticketId: detail.id, articleId: item.recommended_article_id ?? '' })}
                              >
                                Использовать для решения
                              </button>
                            </div>
                          ) : (
                            <p className="muted">Нет article_id для привязки.</p>
                          )}
                        </article>
                      ))}
                    </div>
                  ) : null}
                </section>

                {!isRequester ? (
                  <section className="ticket-detail-panel" style={{ marginTop: 12 }}>
                    <h3>Операции</h3>
                    <div className="form-grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
                      <label>
                        <span>Новый статус</span>
                        <select value={transitionStatus} onChange={(event) => setTransitionStatus(event.target.value)}>
                          {transitionOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                        </select>
                      </label>
                      {canManageAssignments(role) ? (
                        <label>
                          <span>Назначить на</span>
                          <select value={assignUserId} onChange={(event) => setAssignUserId(event.target.value)}>
                            <option value="">Выбрать исполнителя</option>
                            {users.map((user) => (
                              <option key={user.id} value={user.id}>{user.full_name} · {user.email}</option>
                            ))}
                          </select>
                        </label>
                      ) : (
                        <div />
                      )}
                      <label>
                        <span>Комментарий к действию</span>
                        <input value={assignComment} onChange={(event) => setAssignComment(event.target.value)} />
                      </label>
                    </div>
                    <label>
                      <span>Комментарий к смене статуса</span>
                      <textarea value={transitionComment} onChange={(event) => setTransitionComment(event.target.value)} rows={3} />
                    </label>
                  </section>
                ) : null}

                {isRequester && (canRequesterAccept(detail.status) || canRequesterReopen(detail.status)) ? (
                  <section className="ticket-detail-panel" style={{ marginTop: 12 }}>
                    <h3>Подтверждение решения</h3>
                    <p className="muted" style={{ marginTop: 0 }}>
                      Если проблема решена, подтвердите закрытие. Если осталась, опишите причину и переоткройте заявку.
                    </p>
                    <label>
                      <span>Комментарий пользователя</span>
                      <textarea
                        value={requesterDecisionComment}
                        onChange={(event) => setRequesterDecisionComment(event.target.value)}
                        rows={3}
                        placeholder="Например: проблема воспроизводится при подключении из кабинета 401"
                      />
                    </label>
                    <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
                      {canRequesterAccept(detail.status) ? (
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() =>
                            transitionMutation.mutate({
                              ticketId: detail.id,
                              status: 'CLOSED',
                              comment: requesterDecisionComment.trim() || 'Пользователь подтвердил решение',
                              is_internal: false,
                            })
                          }
                          disabled={transitionMutation.isPending}
                        >
                          Подтвердить и закрыть
                        </button>
                      ) : null}
                      {canRequesterReopen(detail.status) ? (
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() =>
                            transitionMutation.mutate({
                              ticketId: detail.id,
                              status: 'REOPENED',
                              comment: requesterDecisionComment.trim(),
                              is_internal: false,
                            })
                          }
                          disabled={transitionMutation.isPending || !requesterDecisionComment.trim()}
                        >
                          Переоткрыть
                        </button>
                      ) : null}
                    </div>
                  </section>
                ) : null}
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </AppShell>
  )
}
