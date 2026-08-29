import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import {
  addTicketParticipant,
  addTicketComment,
  analyzeTicket,
  attachArticleToTicket,
  assignTicket,
  createArticleFromTicket,
  createTicket,
  dismissTicketDuplicateCandidate,
  executeTicketBulkAction,
  fetchAdminUsers,
  fetchAiSuggestions,
  fetchAssets,
  fetchKnownErrors,
  fetchTicket,
  fetchTicketDuplicateCandidates,
  fetchTicketHistory,
  fetchTicketKnowledge,
  fetchTicketParticipantCandidates,
  fetchTicketParticipants,
  fetchTicketRequesterCandidates,
  fetchTicketsPage,
  previewTicketBulkAction,
  mergeTicket,
  removeTicketParticipant,
  transitionTicket,
  splitTicket,
  updateTicketParticipant,
  useArticleForTicket,
  watchTicket,
  type CreateTicketRequest,
  type Ticket,
  type TicketBulkPreview,
  type TicketDetail,
  type TicketDuplicateCandidate,
  type TicketHistory,
  type TicketParticipant,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import CMDBImpactPanel from '../components/CMDBImpactPanel'
import EntityCustomFieldsPanel from '../components/EntityCustomFieldsPanel'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import type { UiMessageKey } from '../i18n/catalog'

type QueueKey = 'all' | 'mine' | 'unassigned' | 'critical' | 'sla_breached' | 'due_today' | 'created_by_me' | 'closed'
type TicketTab = 'overview' | 'comments' | 'participants' | 'duplicates' | 'history' | 'sla' | 'asset' | 'impact' | 'ai'
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

type OperatorReplyTemplate = {
  id: string
  label: string
  body: string
  statuses: string[]
}

type RequesterReopenReasonOption = {
  value: string
  label: string
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
  on_behalf_reason: string
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
  on_behalf_reason: '',
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

const operatorReplyTemplates: OperatorReplyTemplate[] = [
  {
    id: 'waiting-user-info',
    label: 'Запросить уточнение',
    body: 'Для продолжения работы нужны уточнения: укажите, пожалуйста, где и как воспроизводится проблема, и приложите скриншот ошибки при возможности.',
    statuses: ['WAITING_USER', 'IN_PROGRESS', 'ASSIGNED'],
  },
  {
    id: 'waiting-user-check',
    label: 'Попросить проверку решения',
    body: 'Мы внесли изменения. Пожалуйста, проверьте работу сервиса со своей стороны и сообщите результат в ответном комментарии.',
    statuses: ['WAITING_USER', 'RESOLVED'],
  },
  {
    id: 'waiting-user-timebox',
    label: 'Напомнить о сроке',
    body: 'Чтобы сохранить приоритет обработки, просим ответить по заявке в течение рабочего дня. При отсутствии ответа статус может быть закрыт с возможностью переоткрытия.',
    statuses: ['WAITING_USER'],
  },
  {
    id: 'waiting-user-security',
    label: 'Проверка безопасности',
    body: 'По правилам безопасности подтверждение должно быть выполнено владельцем учетной записи. Пожалуйста, подтвердите, что действия выполнены именно с вашей стороны.',
    statuses: ['WAITING_USER', 'SECURITY_PHISHING'],
  },
]

const requesterReopenReasonOptions: RequesterReopenReasonOption[] = [
  { value: 'still-broken', label: 'Проблема не устранена' },
  { value: 'intermittent', label: 'Проблема повторяется периодически' },
  { value: 'partial-fix', label: 'Решение частичное, часть функций не работает' },
  { value: 'wrong-scope', label: 'Решение не покрывает исходный запрос' },
  { value: 'other', label: 'Другая причина' },
]

const duplicateSignalMessageKeys = {
  very_similar_title: 'ticket.duplicates.signal.very_similar_title',
  similar_title: 'ticket.duplicates.signal.similar_title',
  same_requester: 'ticket.duplicates.signal.same_requester',
  same_category: 'ticket.duplicates.signal.same_category',
  same_asset: 'ticket.duplicates.signal.same_asset',
  similar_description: 'ticket.duplicates.signal.similar_description',
  created_within_24h: 'ticket.duplicates.signal.created_within_24h',
  created_within_7d: 'ticket.duplicates.signal.created_within_7d',
} as const

const ticketHistoryEventTypes = [
  'notification_created',
  'created',
  'created_on_behalf',
  'status_changed',
  'updated',
  'assigned',
  'comment_added',
  'ticket_participant_added',
  'ticket_participant_reactivated',
  'ticket_participant_removed',
  'duplicate_candidate_dismissed',
  'ticket_merged',
  'ticket_merge_received',
  'ticket_split',
  'created_from_split',
  'ai_guarded_action',
  'ai_guarded_action_rollback',
  'automation_escalation',
  'runbook_attached',
  'automation_note',
  'automation_comment',
  'workflow_comment',
  'workflow_field_update',
  'created_from_email',
  'email_reply_added',
  'event_correlated',
  'lifecycle_transition_rejected',
] as const

type TicketHistoryEventType = (typeof ticketHistoryEventTypes)[number]

const ticketHistoryEventLabelKeys: Record<TicketHistoryEventType, UiMessageKey> = {
  notification_created: 'ticket.history.event.notificationCreated',
  created: 'ticket.history.event.created',
  created_on_behalf: 'ticket.history.event.createdOnBehalf',
  status_changed: 'ticket.history.event.statusChanged',
  updated: 'ticket.history.event.updated',
  assigned: 'ticket.history.event.assigned',
  comment_added: 'ticket.history.event.commentAdded',
  ticket_participant_added: 'ticket.history.event.participantAdded',
  ticket_participant_reactivated: 'ticket.history.event.participantReactivated',
  ticket_participant_removed: 'ticket.history.event.participantRemoved',
  duplicate_candidate_dismissed: 'ticket.history.event.duplicateCandidateDismissed',
  ticket_merged: 'ticket.history.event.ticketMerged',
  ticket_merge_received: 'ticket.history.event.ticketMergeReceived',
  ticket_split: 'ticket.history.event.ticketSplit',
  created_from_split: 'ticket.history.event.createdFromSplit',
  ai_guarded_action: 'ticket.history.event.aiGuardedAction',
  ai_guarded_action_rollback: 'ticket.history.event.aiGuardedActionRollback',
  automation_escalation: 'ticket.history.event.automationEscalation',
  runbook_attached: 'ticket.history.event.runbookAttached',
  automation_note: 'ticket.history.event.automationNote',
  automation_comment: 'ticket.history.event.automationComment',
  workflow_comment: 'ticket.history.event.workflowComment',
  workflow_field_update: 'ticket.history.event.workflowFieldUpdate',
  created_from_email: 'ticket.history.event.createdFromEmail',
  email_reply_added: 'ticket.history.event.emailReplyAdded',
  event_correlated: 'ticket.history.event.eventCorrelated',
  lifecycle_transition_rejected: 'ticket.history.event.lifecycleTransitionRejected',
}

const ticketHistoryFieldLabelKeys: Record<string, UiMessageKey> = {
  title: 'ticket.history.field.title',
  description: 'ticket.history.field.description',
  requester: 'ticket.history.field.requester',
  requester_name: 'ticket.history.field.requester',
  requester_email: 'ticket.history.field.requesterEmail',
  department: 'ticket.history.field.department',
  location: 'ticket.history.field.location',
  category: 'ticket.history.field.category',
  priority: 'ticket.history.field.priority',
  assignee: 'ticket.history.field.assignee',
  assignee_id: 'ticket.history.field.assignee',
  assignee_name: 'ticket.history.field.assignee',
  sla_due_at: 'ticket.history.field.slaDueAt',
  asset_id: 'ticket.history.field.asset',
  status: 'ticket.history.field.status',
  comment: 'ticket.history.field.comment',
  notification: 'ticket.history.field.notification',
  participants: 'ticket.history.field.participants',
  duplicate_candidate: 'ticket.history.field.duplicateCandidate',
  merged_into_id: 'ticket.history.field.primaryTicket',
  merged_source_id: 'ticket.history.field.mergedTicket',
  child_ticket_id: 'ticket.history.field.childTicket',
  parent_ticket_id: 'ticket.history.field.parentTicket',
  runbook: 'ticket.history.field.runbook',
  note: 'ticket.history.field.note',
  source: 'ticket.history.field.source',
}

const ticketHistoryNotificationLabelKeys: Record<string, UiMessageKey> = {
  ticket_created: 'ticket.history.notification.ticketCreated',
  ticket_assigned: 'ticket.history.notification.ticketAssigned',
  ticket_comment_added: 'ticket.history.notification.commentAdded',
  ticket_status_changed: 'ticket.history.notification.statusChanged',
  ticket_resolved: 'ticket.history.notification.ticketResolved',
}

function isKnownTicketHistoryEvent(value: string): value is TicketHistoryEventType {
  return ticketHistoryEventTypes.includes(value as TicketHistoryEventType)
}

function TicketHistoryRawValue({ value }: { value: string }) {
  return <span>{value}</span>
}

function duplicateSignalMessageKey(signal: string) {
  return duplicateSignalMessageKeys[signal as keyof typeof duplicateSignalMessageKeys]
    ?? 'ticket.duplicates.signal.similar_title'
}

function slaBadgeLabel(value: string | null) {
  if (value === 'BREACHED') return 'Просрочено'
  if (value === 'RISK' || value === 'WARNING') return 'Риск'
  return 'В норме'
}

function aiSlaRiskLabel(ticket: Ticket) {
  if (ticket.sla_badge === 'BREACHED') return { label: 'Высокий', color: '#b42318' }

  const remaining = ticket.resolution_remaining_minutes ?? ticket.response_remaining_minutes
  if (remaining != null) {
    if (remaining <= 60) return { label: 'Высокий', color: '#b54708' }
    if (remaining <= 240) return { label: 'Средний', color: '#c05621' }
  }

  if (ticket.priority === 'CRITICAL' || ticket.priority === 'HIGH') {
    return { label: 'Средний', color: '#c05621' }
  }

  return { label: 'Низкий', color: '#15803d' }
}

function priorityLabel(value: string, translate: (source: string) => string) {
  const item = priorityOptions.find((option) => option.value === value)
  return item ? translate(item.label) : value
}

function statusLabel(value: string, translate: (source: string) => string) {
  const item = statusOptions.find((option) => option.value === value)
  return item ? translate(item.label) : value
}

function toDetailFallback(ticket: Ticket): TicketDetail {
  return { ...ticket, comments: [], history_count: 0 }
}

function canQuickAssignToMe(canSelfAssign: boolean, assigneeId: string | null, assigneeName: string | null) {
  return canSelfAssign && !assigneeId && !(assigneeName || '').trim()
}

function isAssignedToCurrent(assigneeId: string | null, assigneeName: string | null, currentUserId: string | undefined, currentUserName: string | undefined) {
  return assigneeId === currentUserId
    || Boolean(currentUserName && assigneeName?.toLowerCase() === currentUserName.toLowerCase())
}

function canQuickStart(restrictToAssigned: boolean, status: string, assigneeId: string | null, assigneeName: string | null, currentUserId: string | undefined, currentUserName: string | undefined) {
  if (status !== 'ASSIGNED') return false
  return !restrictToAssigned || isAssignedToCurrent(
    assigneeId,
    assigneeName,
    currentUserId,
    currentUserName,
  )
}

function canQuickResolve(restrictToAssigned: boolean, status: string, assigneeId: string | null, assigneeName: string | null, currentUserId: string | undefined, currentUserName: string | undefined) {
  if (status !== 'IN_PROGRESS') return false
  return !restrictToAssigned || isAssignedToCurrent(
    assigneeId,
    assigneeName,
    currentUserId,
    currentUserName,
  )
}

function canRequesterAccept(status: string) {
  return status === 'RESOLVED'
}

function canRequesterReopen(status: string) {
  return status === 'RESOLVED' || status === 'CLOSED'
}

function canHandoffToRequester(status: string) {
  return ['TRIAGE', 'ASSIGNED', 'IN_PROGRESS', 'WAITING_USER'].includes(status)
}

function requesterReopenReasonLabel(value: string) {
  const option = requesterReopenReasonOptions.find((item) => item.value === value)
  return option?.label ?? value
}

function governanceIdempotencyKey(prefix: string) {
  const randomPart = typeof window.crypto?.randomUUID === 'function'
    ? window.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`
  return `${prefix}-${randomPart}`
}

export default function TicketsPage() {
  const { session } = useAuth()
  const { t, translate, formatDateTime } = useTenantExperience()
  const formatMinutes = (value: number | null | undefined) => {
    if (value == null) return '—'
    if (value < 60) return t('ticket.duration.minutes', { count: value })
    const hours = Math.floor(value / 60)
    const minutes = value % 60
    return minutes > 0
      ? t('ticket.duration.hoursMinutes', { hours, minutes })
      : t('ticket.duration.hours', { count: hours })
  }
  const formatDurationSince = (value: string | null) => {
    if (!value) return '—'
    const diffMs = Math.max(0, Date.now() - new Date(value).getTime())
    const diffMinutes = Math.floor(diffMs / 60000)
    if (diffMinutes < 60) return t('ticket.duration.minutes', { count: diffMinutes })
    const diffHours = Math.floor(diffMinutes / 60)
    if (diffHours < 24) {
      const remMinutes = diffMinutes % 60
      return remMinutes > 0
        ? t('ticket.duration.hoursMinutes', { hours: diffHours, minutes: remMinutes })
        : t('ticket.duration.hours', { count: diffHours })
    }
    const diffDays = Math.floor(diffHours / 24)
    const remHours = diffHours % 24
    return remHours > 0
      ? t('ticket.duration.daysHours', { days: diffDays, hours: remHours })
      : t('ticket.duration.days', { count: diffDays })
  }
  const ticketHistoryMessage = (item: TicketHistory): ReactNode => {
    const historyValue = (
      value: string | null,
      fieldName: string | null = null,
    ): ReactNode => {
      if (!value) return t('ticket.history.valueNotSet')
      if (fieldName === 'status') return statusLabel(value, translate)
      if (fieldName === 'priority') return priorityLabel(value, translate)
      return <TicketHistoryRawValue value={value} />
    }
    const fieldLabel = (fieldName: string): ReactNode => {
      const key = ticketHistoryFieldLabelKeys[fieldName]
      return key ? t(key) : <TicketHistoryRawValue value={fieldName} />
    }
    const withValue = (
      label: string,
      value: string | null,
      fieldName: string | null = null,
    ): ReactNode => (
      value
        ? <>{label}: {historyValue(value, fieldName)}</>
        : label
    )
    const withChange = (
      label: string,
      fieldName: string | null,
      oldValue: string | null,
      newValue: string | null,
      showField = true,
    ): ReactNode => (
      <>
        {label}
        {showField && fieldName ? (
          <> · {t('ticket.history.fieldPrefix')}: {fieldLabel(fieldName)}</>
        ) : null}
        {oldValue ? (
          <> · {t('ticket.history.previousValue')}: {historyValue(oldValue, fieldName)}</>
        ) : null}
        {newValue ? (
          <> · {t('ticket.history.newValue')}: {historyValue(newValue, fieldName)}</>
        ) : null}
      </>
    )

    if (!isKnownTicketHistoryEvent(item.event_type)) {
      return (
        <>
          {t('ticket.history.event.unknown')}: <TicketHistoryRawValue value={item.event_type} />
        </>
      )
    }

    const eventType = item.event_type
    const eventLabel = t(ticketHistoryEventLabelKeys[eventType])
    switch (eventType) {
      case 'notification_created': {
        const notificationKey = item.new_value
          ? ticketHistoryNotificationLabelKeys[item.new_value]
          : null
        return withValue(
          eventLabel,
          notificationKey ? t(notificationKey) : item.new_value,
          notificationKey ? null : item.field_name,
        )
      }
      case 'created':
      case 'created_on_behalf':
      case 'runbook_attached':
      case 'automation_note':
      case 'automation_comment':
      case 'workflow_comment':
      case 'email_reply_added':
        return withValue(eventLabel, item.new_value, item.field_name)
      case 'status_changed': {
        const oldStatus = item.field_name === 'status' && item.old_value
          ? statusLabel(item.old_value, translate)
          : null
        const newStatus = item.field_name === 'status' && item.new_value
          ? statusLabel(item.new_value, translate)
          : null
        if (oldStatus && newStatus) {
          return t('ticket.history.statusChanged', { oldStatus, newStatus })
        }
        if (newStatus) return t('ticket.history.statusChangedTo', { newStatus })
        return t('ticket.history.statusChangedGeneric')
      }
      case 'updated':
      case 'ai_guarded_action':
      case 'ai_guarded_action_rollback':
      case 'workflow_field_update':
        return withChange(
          eventLabel,
          item.field_name,
          item.old_value,
          item.new_value,
        )
      case 'assigned':
      case 'automation_escalation':
        return withChange(
          eventLabel,
          item.field_name,
          item.old_value,
          item.new_value,
          false,
        )
      case 'comment_added':
        return withValue(eventLabel, item.new_value, 'comment')
      case 'ticket_participant_added':
      case 'ticket_participant_reactivated':
        return withValue(eventLabel, item.new_value, 'participants')
      case 'ticket_participant_removed':
      case 'duplicate_candidate_dismissed':
        return withValue(eventLabel, item.old_value, item.field_name)
      case 'ticket_merged':
      case 'ticket_merge_received':
      case 'ticket_split':
      case 'created_from_split':
        return withValue(eventLabel, item.new_value, item.field_name)
      case 'created_from_email':
      case 'event_correlated':
        return eventLabel
      case 'lifecycle_transition_rejected':
        return withChange(
          eventLabel,
          'status',
          item.old_value,
          item.new_value,
          false,
        )
      default: {
        const exhaustiveEvent: never = eventType
        return exhaustiveEvent
      }
    }
  }
  const [urlSearchParams, setUrlSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const permissions = new Set(session?.user.permissions ?? [])
  const role = session?.user.role ?? 'guest'
  const root = role === 'saas_root'
  const hasPermission = (permission: string) => root || permissions.has(permission)
  const canReadAllTickets = hasPermission('tickets.scope.all') || hasPermission('tickets.assign')
  const canReadAssignedTickets = hasPermission('tickets.scope.assigned') || hasPermission('tickets.self_assign')
  const canReadRequesterTickets = hasPermission('tickets.scope.requester')
  const isRequester = canReadRequesterTickets && !canReadAllTickets && !canReadAssignedTickets
  const restrictOperationsToAssigned = canReadAssignedTickets && !canReadAllTickets
  const canCreate = hasPermission('tickets.create')
  const canCreateOnBehalf = hasPermission('tickets.create.on_behalf')
  const canOperate = hasPermission('tickets.update')
  const canComment = hasPermission('tickets.comment')
  const canReadParticipants = hasPermission('tickets.participants.read')
  const canManageParticipants = hasPermission('tickets.participants.manage')
  const canWatchTicket = hasPermission('tickets.watch')
  const canReadDuplicates = hasPermission('tickets.duplicates.read')
  const canManageDuplicates = hasPermission('tickets.duplicates.manage')
  const canMergeTickets = hasPermission('tickets.merge')
  const canSplitTickets = hasPermission('tickets.split')
  const canUseInternalComment = canOperate && !isRequester
  const canManageAssignments = hasPermission('tickets.assign')
  const canSelfAssign = canOperate && (canManageAssignments || hasPermission('tickets.self_assign'))
  const canReadAdminUsers = hasPermission('admin.users.read')
  const canSelectAssignee = canManageAssignments && canReadAdminUsers
  const canBulkTickets = canOperate && hasPermission('tickets.bulk.execute')
  const canReadAssets = hasPermission('assets.read')
  const canReadKnownErrors = hasPermission('problems.read')
  const canViewAiSuggestions = hasPermission('ai.view_suggestions')
  const canUseAiAssist = hasPermission('ai.use')
  const canReadTicketKnowledge = hasPermission('knowledge.attach.read')
  const canAttachKnowledge = hasPermission('knowledge.attach')
  const canRecordKnowledgeUsage = hasPermission('knowledge.usage.write')
  const canCreateArticleFromTicket = hasPermission('knowledge.create_from_ticket')
  const canViewAiTab = canUseAiAssist || canViewAiSuggestions || canReadTicketKnowledge || canCreateArticleFromTicket
  const isStaff = canOperate
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
  const [bulkComment, setBulkComment] = useState('')
  const [isBulkPreviewOpen, setIsBulkPreviewOpen] = useState(false)
  const [bulkPlan, setBulkPlan] = useState<TicketBulkPreview | null>(null)
  const [bulkConfirmation, setBulkConfirmation] = useState('')
  const [presets, setPresets] = useState<TicketFilterPreset[]>([])
  const [presetName, setPresetName] = useState('')
  const [activePresetId, setActivePresetId] = useState('')
  const [actionFeedback, setActionFeedback] = useState<ActionFeedback | null>(null)
  const [createValidationError, setCreateValidationError] = useState<string | null>(null)

  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState<TicketFormState>(emptyTicketForm)

  const [selectedTicketId, setSelectedTicketId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<TicketTab>('overview')
  const [transitionStatus, setTransitionStatus] = useState('')
  const [transitionComment, setTransitionComment] = useState('')
  const [requesterDecisionComment, setRequesterDecisionComment] = useState('')
  const [requesterSatisfaction, setRequesterSatisfaction] = useState<number | null>(null)
  const [requesterReopenReason, setRequesterReopenReason] = useState('')
  const [assignComment, setAssignComment] = useState('')
  const [assignUserId, setAssignUserId] = useState('')
  const [commentBody, setCommentBody] = useState('')
  const [commentInternal, setCommentInternal] = useState(false)
  const [participantUserId, setParticipantUserId] = useState('')
  const [participantExternalName, setParticipantExternalName] = useState('')
  const [participantExternalEmail, setParticipantExternalEmail] = useState('')
  const [participantRole, setParticipantRole] = useState<TicketParticipant['participant_role']>('WATCHER')
  const [participantScope, setParticipantScope] = useState<TicketParticipant['notification_scope']>('PUBLIC_ONLY')
  const [participantNotifyInApp, setParticipantNotifyInApp] = useState(true)
  const [participantNotifyEmail, setParticipantNotifyEmail] = useState(false)
  const [participantReason, setParticipantReason] = useState('')
  const [selfParticipantScope, setSelfParticipantScope] = useState<TicketParticipant['notification_scope']>('PUBLIC_ONLY')
  const [selfParticipantNotifyInApp, setSelfParticipantNotifyInApp] = useState(true)
  const [selfParticipantNotifyEmail, setSelfParticipantNotifyEmail] = useState(false)
  const [governanceReason, setGovernanceReason] = useState('')
  const [splitTitle, setSplitTitle] = useState('')
  const [splitDescription, setSplitDescription] = useState('')
  const [splitReason, setSplitReason] = useState('')
  const [selectedOperatorTemplateId, setSelectedOperatorTemplateId] = useState('')
  const [aiCreateHint, setAiCreateHint] = useState<string | null>(null)
  const [aiCommentHint, setAiCommentHint] = useState<string | null>(null)
  const bulkConfirmationRef = useRef<HTMLInputElement>(null)
  const bulkDialogRef = useDialogFocusTrap<HTMLDivElement>(
    isBulkPreviewOpen && Boolean(bulkPlan),
    () => setIsBulkPreviewOpen(false),
    bulkConfirmationRef,
  )
  const createDialogRef = useDialogFocusTrap<HTMLDivElement>(
    isCreateOpen && canCreate,
    () => setIsCreateOpen(false),
  )
  const detailDialogRef = useDialogFocusTrap<HTMLDivElement>(
    Boolean(selectedTicketId),
    () => setSelectedTicketId(null),
  )

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
    setCreateForm((state) => state.requester_id ? state : ({
      ...state,
      requester_id: session.user.id,
      requester_name: session.user.full_name,
      requester_email: session.user.email,
      requester_contact: state.requester_contact,
      on_behalf_reason: '',
      assignee_id: isRequester ? '' : state.assignee_id,
    }))
  }, [isCreateOpen, isRequester, session?.user])

  useEffect(() => {
    const ticketId = urlSearchParams.get('ticket')
    if (!ticketId) return
    setSelectedTicketId(ticketId)
    const nextParams = new URLSearchParams(urlSearchParams)
    nextParams.delete('ticket')
    setUrlSearchParams(nextParams, { replace: true })
  }, [setUrlSearchParams, urlSearchParams])

  useEffect(() => {
    if (!canCreate || urlSearchParams.get('catalog') !== '1') return
    const catalogName = urlSearchParams.get('catalog_name')?.trim() ?? ''
    const catalogCode = urlSearchParams.get('catalog_code')?.trim() ?? ''
    const catalogDescription = urlSearchParams.get('catalog_description')?.trim() ?? ''
    setCreateForm((current) => ({
      ...current,
      title: catalogName || current.title,
      description: [
        catalogDescription,
        catalogCode ? `Позиция каталога: ${catalogCode}` : '',
      ].filter(Boolean).join('\n\n'),
      department: 'Service Catalog',
    }))
    setIsCreateOpen(true)
    setUrlSearchParams({}, { replace: true })
  }, [canCreate, setUrlSearchParams, urlSearchParams])

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
    enabled: Boolean(session?.access_token) && canReadAssets,
  })

  const usersQuery = useQuery({
    queryKey: ['admin-users', session?.access_token],
    queryFn: () => fetchAdminUsers(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && canSelectAssignee,
  })

  const requesterCandidatesQuery = useQuery({
    queryKey: ['ticket-requester-candidates', session?.access_token],
    queryFn: () => fetchTicketRequesterCandidates(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && canCreateOnBehalf && isCreateOpen,
  })

  const selectedTicketQuery = useQuery({
    queryKey: ['ticket', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicket(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const duplicateCandidatesQuery = useQuery({
    queryKey: ['ticket-duplicate-candidates', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketDuplicateCandidates(
      session?.access_token ?? '',
      selectedTicketId ?? '',
    ),
    enabled: Boolean(
      session?.access_token
      && selectedTicketId
      && canReadDuplicates
      && activeTab === 'duplicates'
    ),
  })

  const historyQuery = useQuery({
    queryKey: ['ticket-history', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketHistory(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId),
  })

  const participantsQuery = useQuery({
    queryKey: ['ticket-participants', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketParticipants(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId && canReadParticipants),
  })

  const participantCandidatesQuery = useQuery({
    queryKey: ['ticket-participant-candidates', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketParticipantCandidates(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId && canManageParticipants),
  })

  const aiSuggestionsQuery = useQuery({
    queryKey: ['ticket-ai', session?.access_token, selectedTicketId],
    queryFn: () => fetchAiSuggestions(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId && canViewAiSuggestions),
  })

  const ticketKnowledgeQuery = useQuery({
    queryKey: ['ticket-knowledge', session?.access_token, selectedTicketId],
    queryFn: () => fetchTicketKnowledge(session?.access_token ?? '', selectedTicketId ?? ''),
    enabled: Boolean(session?.access_token && selectedTicketId && canReadTicketKnowledge),
  })

  const ticketKnownErrorsQuery = useQuery({
    queryKey: ['ticket-known-errors', session?.access_token, selectedTicketId],
    queryFn: () => fetchKnownErrors(session?.access_token ?? '', { page: 1, page_size: 3 }),
    enabled: Boolean(session?.access_token && selectedTicketId && canReadKnownErrors),
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
        on_behalf_reason: payload.on_behalf_reason || null,
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
    mutationFn: async (payload: {
      ticketId: string
      status: string
      expectedVersion: number
      idempotencyKey: string
      comment?: string
      is_internal?: boolean
      satisfaction_score?: number
      reopen_reason?: string
    }) =>
      transitionTicket(session?.access_token ?? '', payload.ticketId, {
        status: payload.status,
        comment: payload.comment,
        is_internal: payload.is_internal,
        expected_version: payload.expectedVersion,
        idempotency_key: payload.idempotencyKey,
        satisfaction_score: payload.satisfaction_score,
        reopen_reason: payload.reopen_reason,
      }),
    onSuccess: async (ticket) => {
      setTransitionComment('')
      setRequesterDecisionComment('')
      setRequesterSatisfaction(null)
      setRequesterReopenReason('')
      setActionFeedback({ kind: 'success', message: `Статус заявки ${ticket.ticket_number ?? ''} обновлен.`.trim() })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, ticket.id] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, ticket.id] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: async (error, variables) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Не удалось изменить статус.' })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, variables.ticketId] })
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

  const dismissDuplicateMutation = useMutation({
    mutationFn: async (payload: {
      ticketId: string
      sourceVersion: number
      candidate: TicketDuplicateCandidate
      reason: string
      idempotencyKey: string
    }) => dismissTicketDuplicateCandidate(
      session?.access_token ?? '',
      payload.ticketId,
      payload.candidate.id,
      {
        expected_ticket_version: payload.sourceVersion,
        expected_candidate_version: payload.candidate.governance_version,
        reason: payload.reason,
        idempotency_key: payload.idempotencyKey,
      },
    ),
    onSuccess: async (_, variables) => {
      setGovernanceReason('')
      setActionFeedback({ kind: 'success', message: t('ticket.duplicates.dismissed') })
      await queryClient.invalidateQueries({ queryKey: ['ticket-duplicate-candidates'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, variables.ticketId] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('ticket.duplicates.failed') })
    },
  })

  const mergeTicketMutation = useMutation({
    mutationFn: async (payload: {
      ticketId: string
      sourceVersion: number
      candidate: TicketDuplicateCandidate
      reason: string
      idempotencyKey: string
    }) => mergeTicket(session?.access_token ?? '', payload.ticketId, {
      target_ticket_id: payload.candidate.id,
      expected_source_version: payload.sourceVersion,
      expected_target_version: payload.candidate.governance_version,
      reason: payload.reason,
      idempotency_key: payload.idempotencyKey,
    }),
    onSuccess: async (_, variables) => {
      setGovernanceReason('')
      setActiveTab('overview')
      setActionFeedback({ kind: 'success', message: t('ticket.duplicates.merged') })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-duplicate-candidates'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, variables.ticketId] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('ticket.duplicates.failed') })
    },
  })

  const splitTicketMutation = useMutation({
    mutationFn: async (payload: {
      ticketId: string
      sourceVersion: number
      title: string
      description: string
      reason: string
      idempotencyKey: string
    }) => splitTicket(session?.access_token ?? '', payload.ticketId, {
      title: payload.title,
      description: payload.description || null,
      expected_source_version: payload.sourceVersion,
      reason: payload.reason,
      idempotency_key: payload.idempotencyKey,
    }),
    onSuccess: async (result, variables) => {
      setSplitTitle('')
      setSplitDescription('')
      setSplitReason('')
      setActionFeedback({
        kind: 'success',
        message: t('ticket.duplicates.splitCreated', { id: result.target_ticket_id ?? '' }),
      })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, variables.ticketId] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('ticket.duplicates.failed') })
    },
  })

  const addParticipantMutation = useMutation({
    mutationFn: async (ticketId: string) => addTicketParticipant(
      session?.access_token ?? '',
      ticketId,
      {
        ...(participantUserId
          ? { user_id: participantUserId }
          : {
              display_name: participantExternalName.trim(),
              email: participantExternalEmail.trim(),
            }),
        participant_role: participantRole,
        notification_scope: participantScope,
        notify_in_app: participantUserId ? participantNotifyInApp : false,
        notify_email: participantNotifyEmail,
        reason: participantReason.trim(),
      },
    ),
    onSuccess: async (participant) => {
      setParticipantUserId('')
      setParticipantExternalName('')
      setParticipantExternalEmail('')
      setParticipantReason('')
      setActionFeedback({ kind: 'success', message: t('ticket.participants.added', { name: participant.display_name }) })
      await queryClient.invalidateQueries({ queryKey: ['ticket-participants', session?.access_token, participant.ticket_id] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, participant.ticket_id] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('ticket.participants.failed') })
    },
  })

  const watchTicketMutation = useMutation({
    mutationFn: async (ticketId: string) => watchTicket(session?.access_token ?? '', ticketId, {
      notification_scope: selfParticipantScope,
      notify_in_app: selfParticipantNotifyInApp,
      notify_email: selfParticipantNotifyEmail,
    }),
    onSuccess: async (participant) => {
      setActionFeedback({ kind: 'success', message: t('ticket.participants.saved') })
      await queryClient.invalidateQueries({ queryKey: ['ticket-participants', session?.access_token, participant.ticket_id] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('ticket.participants.failed') })
    },
  })

  const updateParticipantMutation = useMutation({
    mutationFn: async (payload: {
      participant: TicketParticipant
      changes: Partial<Pick<TicketParticipant, 'participant_role' | 'notification_scope' | 'notify_in_app' | 'notify_email'>>
    }) => updateTicketParticipant(
      session?.access_token ?? '',
      payload.participant.ticket_id,
      payload.participant.id,
      {
        expected_version: payload.participant.version_number,
        ...payload.changes,
        reason: participantReason.trim() || 'Ticket participant settings updated',
      },
    ),
    onSuccess: async (participant) => {
      setActionFeedback({ kind: 'success', message: t('ticket.participants.saved') })
      await queryClient.invalidateQueries({ queryKey: ['ticket-participants', session?.access_token, participant.ticket_id] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('ticket.participants.failed') })
    },
  })

  const removeParticipantMutation = useMutation({
    mutationFn: async (participant: TicketParticipant) => removeTicketParticipant(
      session?.access_token ?? '',
      participant.ticket_id,
      participant.id,
      participantReason.trim() || 'Ticket participant removed',
    ),
    onSuccess: async (participant) => {
      setActionFeedback({ kind: 'success', message: t('ticket.participants.removed') })
      await queryClient.invalidateQueries({ queryKey: ['ticket-participants', session?.access_token, participant.ticket_id] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, participant.ticket_id] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : t('ticket.participants.failed') })
    },
  })

  const handoffToRequesterMutation = useMutation({
    mutationFn: async (payload: {
      ticketId: string
      body: string
      shouldTransition: boolean
      expectedVersion: number
      idempotencyKey: string
    }) => {
      const token = session?.access_token ?? ''
      if (payload.shouldTransition) {
        return transitionTicket(token, payload.ticketId, {
          status: 'WAITING_USER',
          comment: payload.body,
          is_internal: false,
          expected_version: payload.expectedVersion,
          idempotency_key: payload.idempotencyKey,
        })
      }
      return addTicketComment(token, payload.ticketId, {
        body: payload.body,
        is_internal: false,
      })
    },
    onSuccess: async (_, variables) => {
      setCommentBody('')
      setCommentInternal(false)
      setActionFeedback({
        kind: 'success',
        message: variables.shouldTransition
          ? 'Запрос отправлен, заявка переведена в статус Ожидает пользователя.'
          : 'Запрос пользователю отправлен.',
      })
      await queryClient.invalidateQueries({ queryKey: ['ticket', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['ticket-history', session?.access_token, variables.ticketId] })
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: (error) => {
      setActionFeedback({ kind: 'error', message: error instanceof Error ? error.message : 'Не удалось передать запрос пользователю.' })
    },
  })

  const bulkPreviewMutation = useMutation({
    mutationFn: () =>
      previewTicketBulkAction(session?.access_token ?? '', {
        ticket_ids: selectedTicketIds,
        status: bulkStatus,
        assignee_id: canSelectAssignee
          ? bulkAssigneeId || null
          : null,
        comment: bulkComment || null,
      }),
    onSuccess: (plan) => {
      setBulkPlan(plan)
      setBulkConfirmation('')
      setIsBulkPreviewOpen(true)
    },
    onError: (error) => {
      setActionFeedback({
        kind: 'error',
        message:
          error instanceof Error
            ? error.message
            : 'Не удалось сформировать серверный preview массовой операции.',
      })
    },
  })

  const bulkExecuteMutation = useMutation({
    mutationFn: () => {
      if (!bulkPlan) throw new Error('Серверный preview отсутствует.')
      return executeTicketBulkAction(
        session?.access_token ?? '',
        bulkPlan.plan_id,
        {
          expected_revision: bulkPlan.revision,
          confirmation_phrase: bulkConfirmation,
        },
      )
    },
    onSuccess: async (result) => {
      setSelectedTicketIds([])
      setIsBulkPreviewOpen(false)
      setBulkPlan(null)
      setBulkConfirmation('')
      if (result.skipped_count === 0) {
        setActionFeedback({ kind: 'success', message: `Массовая операция завершена: обновлено ${result.updated_count}.` })
      } else {
        setActionFeedback({ kind: 'success', message: `Массовая операция завершена: обновлено ${result.updated_count}, исключено preview ${result.skipped_count}.` })
      }
      await queryClient.invalidateQueries({ queryKey: ['tickets'] })
      await queryClient.invalidateQueries({ queryKey: ['notifications-unread-count'] })
    },
    onError: (error) => {
      setActionFeedback({
        kind: 'error',
        message:
          error instanceof Error
            ? error.message
            : 'План устарел или не прошёл повторную серверную проверку.',
      })
    },
  })

  const aiMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; text: string }) =>
      analyzeTicket(session?.access_token ?? '', { ticket_id: payload.ticketId, input_text: payload.text }),
    onSuccess: async (_, variables) => {
      await queryClient.invalidateQueries({ queryKey: ['ticket-ai', session?.access_token, variables.ticketId] })
    },
  })

  const aiCreateAssistMutation = useMutation({
    mutationFn: async (payload: { inputText: string }) =>
      analyzeTicket(session?.access_token ?? '', { input_text: payload.inputText }),
    onSuccess: (suggestion) => {
      setCreateForm((state) => ({
        ...state,
        category: suggestion.recommended_category || state.category,
        priority: suggestion.recommended_priority || state.priority,
      }))
      setAiCreateHint(`AI предложил: категория ${suggestion.recommended_category}, приоритет ${suggestion.recommended_priority}.`)
    },
    onError: (error) => {
      setAiCreateHint(error instanceof Error ? error.message : 'Не удалось получить AI подсказку для формы.')
    },
  })

  const aiCommentDraftMutation = useMutation({
    mutationFn: async (payload: { ticketId: string; text: string }) =>
      analyzeTicket(session?.access_token ?? '', { ticket_id: payload.ticketId, input_text: payload.text }),
    onSuccess: (suggestion) => {
      const nextSteps = suggestion.next_actions.length > 0
        ? `\n\nДальнейшие шаги:\n${suggestion.next_actions.map((item) => `- ${item}`).join('\n')}`
        : ''
      setCommentBody(`Коллеги, предлагаем следующий план решения:\n${suggestion.suggested_solution}${nextSteps}`)
      setAiCommentHint(`AI-черновик сформирован (confidence ${suggestion.confidence}). Проверьте текст и отправьте.`)
    },
    onError: (error) => {
      setAiCommentHint(error instanceof Error ? error.message : 'Не удалось сформировать AI-черновик.')
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
  const requesterCandidates = requesterCandidatesQuery.data ?? []
  const isCreatingOnBehalf = Boolean(
    canCreateOnBehalf
    && createForm.requester_id
    && createForm.requester_id !== session?.user.id,
  )
  const creationChannelLabel = (channel: Ticket['creation_channel']) => {
    if (channel === 'SELF_SERVICE') return t('ticket.onBehalf.channel.SELF_SERVICE')
    if (channel === 'ON_BEHALF') return t('ticket.onBehalf.channel.ON_BEHALF')
    return t('ticket.onBehalf.channel.LEGACY')
  }
  const participants = participantsQuery.data ?? []
  const participantRoleLabels: Record<TicketParticipant['participant_role'], string> = {
    WATCHER: t('ticket.participants.role.WATCHER'),
    COLLABORATOR: t('ticket.participants.role.COLLABORATOR'),
    REQUESTER_REPRESENTATIVE: t('ticket.participants.role.REQUESTER_REPRESENTATIVE'),
  }
  const participantScopeLabels: Record<TicketParticipant['notification_scope'], string> = {
    ALL: t('ticket.participants.scope.ALL'),
    PUBLIC_ONLY: t('ticket.participants.scope.PUBLIC_ONLY'),
    STATUS_ONLY: t('ticket.participants.scope.STATUS_ONLY'),
    NONE: t('ticket.participants.scope.NONE'),
  }
  const ownParticipant = participants.find((item) => item.user_id === session?.user.id) ?? null
  const availableParticipantCandidates = useMemo(() => {
    const activeUserIds = new Set(participants.map((item) => item.user_id).filter(Boolean))
    return (participantCandidatesQuery.data ?? []).filter((item) => !activeUserIds.has(item.id))
  }, [participantCandidatesQuery.data, participants])
  const allPageTicketIds = useMemo(() => tickets.map((ticket) => ticket.id), [tickets])
  const allPageSelected = allPageTicketIds.length > 0 && allPageTicketIds.every((id) => selectedTicketIds.includes(id))

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const selectedTableTicket = selectedTicketId ? tickets.find((item) => item.id === selectedTicketId) ?? null : null
  const detail = selectedTicketQuery.data ?? (selectedTableTicket ? toDetailFallback(selectedTableTicket) : null)
  const canOperateDetail = Boolean(
    detail
    && canOperate
    && !isRequester
    && (
      !restrictOperationsToAssigned
      || isAssignedToCurrent(
        detail.assignee_id,
        detail.assignee_name,
        session?.user.id,
        session?.user.full_name,
      )
    ),
  )
  const availableTransitionOptions = useMemo(() => {
    if (!detail) return []
    const allowed = new Set(detail.allowed_transitions)
    return transitionOptions.filter((option) => allowed.has(option.value))
  }, [detail?.allowed_transitions])

  useEffect(() => {
    if (ownParticipant) {
      setSelfParticipantScope(ownParticipant.notification_scope)
      setSelfParticipantNotifyInApp(ownParticipant.notify_in_app)
      setSelfParticipantNotifyEmail(ownParticipant.notify_email)
      return
    }
    setSelfParticipantScope('PUBLIC_ONLY')
    setSelfParticipantNotifyInApp(true)
    setSelfParticipantNotifyEmail(false)
  }, [ownParticipant])

  useEffect(() => {
    setParticipantUserId('')
    setParticipantExternalName('')
    setParticipantExternalEmail('')
    setParticipantReason('')
    setGovernanceReason('')
    setSplitTitle('')
    setSplitDescription('')
    setSplitReason('')
  }, [selectedTicketId])

  const availableOperatorTemplates = useMemo(() => {
    if (isRequester || !detail) return []
    return operatorReplyTemplates.filter((template) => template.statuses.includes(detail.status) || template.statuses.includes(detail.category))
  }, [detail, isRequester])

  const waitingUserSince = useMemo(() => {
    if (!detail) return null
    const history = historyQuery.data ?? []
    for (let index = history.length - 1; index >= 0; index -= 1) {
      const item = history[index]
      if (item.event_type !== 'status_changed') continue
      if ((item.new_value ?? '').toUpperCase() !== 'WAITING_USER') continue
      return item.created_at
    }
    return detail.status === 'WAITING_USER' ? detail.updated_at : null
  }, [detail, historyQuery.data])

  const waitingUserAgeHours = useMemo(() => {
    if (!waitingUserSince) return 0
    return Math.floor((Date.now() - new Date(waitingUserSince).getTime()) / 3600000)
  }, [waitingUserSince])

  const selectedOperatorTemplate = useMemo(
    () => availableOperatorTemplates.find((template) => template.id === selectedOperatorTemplateId) ?? availableOperatorTemplates[0] ?? null,
    [availableOperatorTemplates, selectedOperatorTemplateId]
  )

  const reminderOperatorTemplate = useMemo(
    () => availableOperatorTemplates.find((template) => template.id === 'waiting-user-timebox') ?? selectedOperatorTemplate,
    [availableOperatorTemplates, selectedOperatorTemplate]
  )

  useEffect(() => {
    if (availableOperatorTemplates.length === 0) {
      setSelectedOperatorTemplateId('')
      return
    }
    setSelectedOperatorTemplateId((current) =>
      availableOperatorTemplates.some((template) => template.id === current) ? current : availableOperatorTemplates[0].id
    )
  }, [availableOperatorTemplates])

  const timelineItems = useMemo<TicketTimelineItem[]>(() => {
    if (!detail) return []

    const items: TicketTimelineItem[] = [
      {
        id: 'created',
        title: 'Заявка создана',
        timestamp: detail.created_at,
        note: `${t('ticket.onBehalf.registeredBy')}: ${detail.created_by_name ?? detail.requester_name} · ${creationChannelLabel(detail.creation_channel)}`,
        tone: 'info',
      },
    ]

    if (detail.response_due_at) {
      let note = t('ticket.timeline.responseDue', { date: formatDateTime(detail.response_due_at) })
      let tone: TicketTimelineItem['tone'] = 'info'
      if (detail.is_response_breached) {
        note = t('ticket.timeline.responseBreached', { duration: formatMinutes(detail.response_minutes) })
        tone = 'danger'
      } else if (detail.response_minutes != null) {
        note = t('ticket.timeline.responseMet', { duration: formatMinutes(detail.response_minutes) })
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
      let note = t('ticket.timeline.resolutionDue', { date: formatDateTime(detail.resolution_due_at) })
      let tone: TicketTimelineItem['tone'] = 'info'
      if (detail.is_resolution_breached && !resolutionDone) {
        note = t('ticket.timeline.resolutionBreached')
        tone = 'danger'
      } else if (resolutionDone) {
        note = t('ticket.timeline.resolutionRecorded', { date: formatDateTime(detail.resolved_at ?? detail.closed_at) })
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
        note: t('ticket.timeline.movedResolved'),
        tone: 'success',
      })
    }

    if (detail.closed_at) {
      items.push({
        id: 'closed',
        title: 'Заявка закрыта',
        timestamp: detail.closed_at,
        note: t('ticket.timeline.closedNote'),
        tone: 'success',
      })
    }

    if (detail.reopened_at) {
      items.push({
        id: 'reopened',
        title: 'Заявка переоткрыта',
        timestamp: detail.reopened_at,
        note: t('ticket.timeline.reopenedNote'),
        tone: 'warning',
      })
    }

    if (detail.status === 'WAITING_USER' || waitingUserSince) {
      items.push({
        id: 'waiting-user',
        title: 'Ожидается ответ пользователя',
        timestamp: waitingUserSince,
        note: t('ticket.timeline.waitingNote'),
        tone: 'warning',
      })
    }

    return items.sort((a, b) => {
      const left = a.timestamp ? new Date(a.timestamp).getTime() : 0
      const right = b.timestamp ? new Date(b.timestamp).getTime() : 0
      return right - left
    })
  }, [detail, formatDateTime, t, waitingUserSince])

  useEffect(() => {
    if (!detail) return
    setTransitionStatus(availableTransitionOptions[0]?.value ?? '')
    setAssignUserId(detail.assignee_id ?? '')
    setRequesterDecisionComment('')
    setRequesterSatisfaction(null)
    setRequesterReopenReason('')
  }, [availableTransitionOptions, detail?.id, detail?.status, detail?.assignee_id])

  const assigneeOptions = useMemo(() => {
    const values = new Set<string>()
    tickets.forEach((ticket) => {
      if (ticket.assignee_name) values.add(ticket.assignee_name)
    })
    return Array.from(values).sort((a, b) => a.localeCompare(b, 'ru'))
  }, [tickets])

  const bulkAssigneeName = useMemo(() => {
    if (!bulkAssigneeId) return 'Без назначения'
    return users.find((user) => user.id === bulkAssigneeId)?.full_name ?? t('ticket.selectedAssignee')
  }, [bulkAssigneeId, t, users])

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
      <QueryFailureNotice
        title="Часть данных Service Desk недоступна."
        sources={[
          { label: 'очередь заявок', query: ticketsQuery },
          { label: 'активы', query: assetsQuery },
          { label: 'пользователи', query: usersQuery },
          { label: 'детали заявки', query: selectedTicketQuery },
          { label: 'история заявки', query: historyQuery },
          { label: 'AI suggestions', query: aiSuggestionsQuery },
          { label: 'knowledge recommendations', query: ticketKnowledgeQuery },
          { label: 'known errors', query: ticketKnownErrorsQuery },
        ]}
      />
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
        {canCreate ? (
          <button type="button" className="ghost-button" onClick={() => setIsCreateOpen(true)}>
            {isRequester ? 'Создать обращение' : 'Создать заявку'}
          </button>
        ) : null}
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
                {translate(template.label)}
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {actionFeedback ? (
        <section
          className="foundation-card"
          role={actionFeedback.kind === 'error' ? 'alert' : 'status'}
          aria-live={actionFeedback.kind === 'error' ? 'assertive' : 'polite'}
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
            {translate(item.label)}
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
                <option key={option.value} value={option.value}>{translate(option.label)}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Приоритет</span>
            <select value={priorityFilter} onChange={(event) => setPriorityFilter(event.target.value)}>
              {priorityOptions.map((option) => (
                <option key={option.value} value={option.value}>{translate(option.label)}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Категория</span>
            <select value={categoryFilter} onChange={(event) => setCategoryFilter(event.target.value)}>
              {categoryOptions.map((option) => (
                <option key={option.value} value={option.value}>{translate(option.label)}</option>
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

      {canOperate ? (
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

      {canBulkTickets ? (
        <section className="foundation-card tickets-toolbar" style={{ marginTop: 12 }}>
          <div className="tickets-toolbar-group" style={{ gridTemplateColumns: canSelectAssignee ? 'repeat(4, minmax(0, 1fr))' : 'repeat(3, minmax(0, 1fr))' }}>
            <label className="inline-field">
              <span>Массовый статус</span>
              <select value={bulkStatus} onChange={(event) => setBulkStatus(event.target.value)}>
                {transitionOptions.filter((item) => item.value !== 'ALL').map((option) => (
                  <option key={option.value} value={option.value}>{translate(option.label)}</option>
                ))}
              </select>
            </label>
            {canSelectAssignee ? (
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
                disabled={selectedTicketIds.length === 0 || bulkPreviewMutation.isPending}
                onClick={() => bulkPreviewMutation.mutate()}
              >
                {bulkPreviewMutation.isPending
                  ? 'Серверная проверка...'
                  : 'Предпросмотр и подтверждение'}
              </button>
            </div>
          </div>
        </section>
      ) : null}

      {isBulkPreviewOpen && bulkPlan ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsBulkPreviewOpen(false)}>
          <div
            ref={bulkDialogRef}
            className="modal-card modal-card-large"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ticket-bulk-dialog-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">BULK PREVIEW</p>
                <h2 id="ticket-bulk-dialog-title">Подтверждение массового действия</h2>
                <p className="modal-subtitle">
                  Сервер уже проверил права, tenant, переходы и состояние каждой заявки.
                  Перед execute проверки будут выполнены повторно.
                </p>
              </div>
              <button type="button" className="ghost-button" onClick={() => setIsBulkPreviewOpen(false)}>Закрыть</button>
            </div>

            <section className="foundation-card" style={{ marginBottom: 12 }}>
              <div className="detail-fields">
                <div><span>Допущено</span><strong>{bulkPlan.eligible_count}</strong></div>
                <div><span>Исключено</span><strong>{bulkPlan.skipped_count}</strong></div>
                <div><span>Новый статус</span><strong>{statusLabel(bulkStatus, translate)}</strong></div>
                <div><span>Назначение</span><strong>{bulkAssigneeName}</strong></div>
                <div><span>Комментарий</span><strong>{bulkComment || '—'}</strong></div>
                <div><span>Действует до</span><strong>{formatDateTime(bulkPlan.expires_at)}</strong></div>
                <div><span>Operation hash</span><strong><code>{bulkPlan.operation_sha256.slice(0, 16)}</code></strong></div>
                <div><span>Targets hash</span><strong><code>{bulkPlan.targets_sha256.slice(0, 16)}</code></strong></div>
              </div>
            </section>

            <section className="ticket-table-wrap" style={{ maxHeight: 320, overflow: 'auto' }}>
              <table className="ticket-table">
                <caption className="sr-only">Предварительная проверка массового изменения заявок</caption>
                <thead>
                  <tr>
                    <th>Номер</th>
                    <th>Тема</th>
                    <th>Текущий статус</th>
                    <th>Целевой статус</th>
                    <th>Результат preview</th>
                  </tr>
                </thead>
                <tbody>
                  {bulkPlan.targets.map((ticket) => (
                    <tr key={ticket.ticket_id}>
                      <td>{ticket.ticket_number ?? '—'}</td>
                      <td>{ticket.title}</td>
                      <td>{statusLabel(ticket.current_status, translate)}</td>
                      <td>{ticket.target_status ? statusLabel(ticket.target_status, translate) : 'Без изменения'}</td>
                      <td>
                        <span className={ticket.eligible ? 'badge badge-positive' : 'badge badge-warning'}>
                          {ticket.eligible ? 'Допущено' : ticket.reason ?? 'Исключено'}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>

            <label className="inline-field" style={{ marginTop: 16 }}>
              <span>
                Для выполнения введите <code>{bulkPlan.confirmation_phrase}</code>
              </span>
              <input
                ref={bulkConfirmationRef}
                data-dialog-autofocus
                value={bulkConfirmation}
                onChange={(event) => setBulkConfirmation(event.target.value)}
                autoComplete="off"
              />
            </label>

            <div className="analytics-actions" style={{ marginTop: 16, justifyContent: 'flex-end' }}>
              <button type="button" className="ghost-button" onClick={() => setIsBulkPreviewOpen(false)}>
                Отмена
              </button>
              <button
                type="button"
                disabled={
                  bulkPlan.eligible_count === 0
                  || bulkConfirmation !== bulkPlan.confirmation_phrase
                  || bulkExecuteMutation.isPending
                }
                onClick={() => bulkExecuteMutation.mutate()}
              >
                {bulkExecuteMutation.isPending
                  ? 'Повторная проверка и применение...'
                  : 'Выполнить проверенный план'}
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
        {ticketsQuery.isPending ? <p className="muted" role="status">Загрузка заявок...</p> : null}
        {ticketsQuery.isError ? <p className="error-message" role="alert">Не удалось загрузить список заявок.</p> : null}
        {!ticketsQuery.isPending && !ticketsQuery.isError ? (
          <>
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <caption className="sr-only">Список заявок</caption>
                <thead>
                  <tr>
                    {canBulkTickets ? (
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
                      {canBulkTickets ? (
                        <td>
                          <input
                            type="checkbox"
                            checked={selectedTicketIds.includes(ticket.id)}
                            onChange={() => toggleTicketSelection(ticket.id)}
                            aria-label={t('ticket.selectAria', { id: ticket.ticket_number ?? ticket.id })}
                          />
                        </td>
                      ) : null}
                      <td>{ticket.ticket_number ?? '—'}</td>
                      <td>
                        <strong>{ticket.title}</strong>
                        <p className="table-subtext">{ticket.location}</p>
                      </td>
                      <td>{statusLabel(ticket.status, translate)}</td>
                      <td>{priorityLabel(ticket.priority, translate)}</td>
                      <td>{ticket.category_label}</td>
                      <td>
                        {ticket.requester_name}
                        <p className="table-subtext">{ticket.requester_email}</p>
                      </td>
                      <td>{ticket.assignee_name ?? 'Не назначен'}</td>
                      <td>
                        <div className="ticket-sla-cell">
                          <strong>{translate(slaBadgeLabel(ticket.sla_badge))}</strong>
                          <small>{formatDateTime(ticket.resolution_due_at ?? ticket.sla_due_at)}</small>
                          <small style={{ color: aiSlaRiskLabel(ticket).color }}>AI риск: {translate(aiSlaRiskLabel(ticket).label)}</small>
                        </div>
                      </td>
                      <td>{formatDateTime(ticket.updated_at)}</td>
                      <td>
                        <div className="analytics-actions" style={{ justifyContent: 'flex-start', flexWrap: 'wrap' }}>
                          {canQuickAssignToMe(canSelfAssign, ticket.assignee_id, ticket.assignee_name) ? (
                            <button
                              type="button"
                              className="ghost-button row-action"
                              onClick={() => assignMutation.mutate({ ticketId: ticket.id, comment: 'Взял в работу' })}
                              disabled={assignMutation.isPending}
                            >
                              Взять
                            </button>
                          ) : null}
                          {canOperate && !isRequester && canQuickStart(restrictOperationsToAssigned, ticket.status, ticket.assignee_id, ticket.assignee_name, session?.user.id, session?.user.full_name) ? (
                            <button
                              type="button"
                              className="ghost-button row-action"
                              onClick={() => transitionMutation.mutate({
                                ticketId: ticket.id,
                                status: 'IN_PROGRESS',
                                expectedVersion: ticket.governance_version,
                                idempotencyKey: governanceIdempotencyKey('ticket-transition'),
                                comment: 'Переведено в работу',
                                is_internal: isStaff,
                              })}
                              disabled={transitionMutation.isPending}
                            >
                              Старт
                            </button>
                          ) : null}
                          {canOperate && !isRequester && canQuickResolve(restrictOperationsToAssigned, ticket.status, ticket.assignee_id, ticket.assignee_name, session?.user.id, session?.user.full_name) ? (
                            <button
                              type="button"
                              className="ghost-button row-action"
                              onClick={() => transitionMutation.mutate({
                                ticketId: ticket.id,
                                status: 'RESOLVED',
                                expectedVersion: ticket.governance_version,
                                idempotencyKey: governanceIdempotencyKey('ticket-transition'),
                                comment: 'Решено оператором',
                                is_internal: isStaff,
                              })}
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

      {isCreateOpen && canCreate ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setIsCreateOpen(false)}>
          <div
            ref={createDialogRef}
            className="modal-card modal-card-large"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ticket-create-dialog-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">НОВАЯ ЗАЯВКА</p>
                <h2 id="ticket-create-dialog-title">Создание обращения</h2>
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
                    setCreateValidationError(t('ticket.requiredFields', { fields: requiredLabels }))
                    return
                  }
                }
                if (isCreatingOnBehalf && createForm.on_behalf_reason.trim().length < 3) {
                  setCreateValidationError(t('ticket.onBehalf.reasonRequired'))
                  return
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
                          <strong>{translate(template.label)}</strong>
                          <span className="muted" style={{ fontSize: '.82rem' }}>{translate(template.summary)}</span>
                          <small className="muted">Обязательно: {template.requiredFields.map((field) => translate(requesterFieldLabels[field])).join(', ')}</small>
                        </button>
                      )
                    })}
                  </div>
                </section>
              ) : null}

              {isRequester ? (
                <section className="foundation-card" style={{ marginBottom: 12, gridTemplateColumns: '1fr', gap: 10 }}>
                  <div className="detail-fields" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
                    <div><span>Каталог</span><strong>{translate(selectedRequesterTemplate?.label ?? 'Общий запрос')}</strong></div>
                    <div><span>Обязательные поля</span><strong>{requesterRequiredFields.map((field) => translate(requesterFieldLabels[field])).join(', ')}</strong></div>
                    <div><span>SLA приоритет</span><strong>{priorityLabel(createForm.priority, translate)}</strong></div>
                  </div>
                </section>
              ) : null}

              {createValidationError ? <p className="error-message" role="alert">{createValidationError}</p> : null}

              <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={!canUseAiAssist || aiCreateAssistMutation.isPending || !createForm.title.trim() || !createForm.description.trim()}
                  title={!canUseAiAssist ? 'Недостаточно прав для AI подсказок' : undefined}
                  onClick={() => {
                    setAiCreateHint(null)
                    aiCreateAssistMutation.mutate({
                      inputText: `${createForm.title}. ${createForm.description}. ${createForm.location ? `Локация: ${createForm.location}.` : ''}`,
                    })
                  }}
                >
                  {aiCreateAssistMutation.isPending ? 'AI анализирует форму...' : 'AI предложить категорию и приоритет'}
                </button>
              </div>
              {aiCreateHint ? <p className="loading-state">{aiCreateHint}</p> : null}

              <div className="form-grid">
                <label>
                  <span>Тема</span>
                  <input required value={createForm.title} onChange={(event) => setCreateForm((state) => ({ ...state, title: event.target.value }))} />
                </label>
                <label>
                  <span>Категория</span>
                  <select value={createForm.category} onChange={(event) => setCreateForm((state) => ({ ...state, category: event.target.value }))}>
                    {categoryOptions.filter((item) => item.value !== 'ALL').map((option) => (
                      <option key={option.value} value={option.value}>{translate(option.label)}</option>
                    ))}
                  </select>
                </label>
                <label>
                  <span>Приоритет</span>
                  <select value={createForm.priority} onChange={(event) => setCreateForm((state) => ({ ...state, priority: event.target.value }))}>
                    {priorityOptions.filter((item) => item.value !== 'ALL').map((option) => (
                      <option key={option.value} value={option.value}>{translate(option.label)}</option>
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
                {!canCreateOnBehalf ? (
                  <>
                    <label>
                      <span>{t('ticket.onBehalf.requester')}</span>
                      <input value={createForm.requester_name} disabled />
                    </label>
                    <label>
                      <span>Email</span>
                      <input value={createForm.requester_email} disabled />
                    </label>
                  </>
                ) : (
                  <label>
                    <span>{t('ticket.onBehalf.requester')}</span>
                    <select value={createForm.requester_id} onChange={(event) => {
                      const user = requesterCandidates.find((item) => item.id === event.target.value)
                      const selfSelected = event.target.value === session?.user.id
                      setCreateForm((state) => ({
                        ...state,
                        requester_id: event.target.value,
                        requester_name: user?.full_name ?? (selfSelected ? session?.user.full_name ?? '' : ''),
                        requester_email: user?.email ?? (selfSelected ? session?.user.email ?? '' : ''),
                        requester_contact: user?.phone ?? state.requester_contact,
                        department: user?.department ?? state.department,
                        location: user?.location ?? state.location,
                        on_behalf_reason: selfSelected ? '' : state.on_behalf_reason,
                      }))
                    }} disabled={requesterCandidatesQuery.isPending}>
                      <option value={session?.user.id}>{t('ticket.onBehalf.self')} · {session?.user.full_name}</option>
                      {requesterCandidates.filter((user) => user.id !== session?.user.id).map((user) => (
                        <option key={user.id} value={user.id}>{user.full_name} · {user.email}</option>
                      ))}
                    </select>
                    {requesterCandidatesQuery.isPending ? <small>{t('ticket.onBehalf.directoryLoading')}</small> : null}
                    {requesterCandidatesQuery.isError ? <small className="error-message">{t('ticket.onBehalf.directoryFailed')}</small> : null}
                  </label>
                )}
                {canSelectAssignee ? <label>
                  <span>Исполнитель</span>
                  <select value={createForm.assignee_id} onChange={(event) => setCreateForm((state) => ({ ...state, assignee_id: event.target.value }))}>
                    <option value="">Не назначать</option>
                    {users.filter((user) => ['IT Manager', 'Network Agent', 'Support Agent'].some((name) => user.full_name.includes(name))).map((user) => (
                      <option key={user.id} value={user.id}>{user.full_name}</option>
                    ))}
                  </select>
                </label> : null}
                {canReadAssets ? <label>
                  <span>Актив</span>
                  <select value={createForm.asset_id} onChange={(event) => setCreateForm((state) => ({ ...state, asset_id: event.target.value }))}>
                    <option value="">Не привязан</option>
                    {assets.map((asset) => (
                      <option key={asset.id} value={asset.id}>{asset.asset_tag} · {asset.name}</option>
                    ))}
                  </select>
                </label> : null}
              </div>
              {isCreatingOnBehalf ? (
                <section className="foundation-card" style={{ margin: '12px 0', gridTemplateColumns: '1fr', gap: 8 }}>
                  <label>
                    <span>{t('ticket.onBehalf.reason')}</span>
                    <textarea
                      required
                      minLength={3}
                      maxLength={2000}
                      rows={3}
                      value={createForm.on_behalf_reason}
                      placeholder={t('ticket.onBehalf.reasonPlaceholder')}
                      onChange={(event) => setCreateForm((state) => ({ ...state, on_behalf_reason: event.target.value }))}
                    />
                  </label>
                  <small className="muted">{t('ticket.onBehalf.auditHint')}</small>
                </section>
              ) : null}
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
          <div
            ref={detailDialogRef}
            className="modal-card modal-card-xl"
            role="dialog"
            aria-modal="true"
            aria-labelledby="ticket-detail-dialog-title"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <div className="modal-header">
              <div>
                <p className="eyebrow">КАРТОЧКА ЗАЯВКИ</p>
                <h2 id="ticket-detail-dialog-title">{detail?.ticket_number ?? 'Загрузка...'}</h2>
                <p className="modal-subtitle">{detail?.title ?? ''}</p>
              </div>
              <button type="button" className="ghost-button" onClick={() => setSelectedTicketId(null)}>Закрыть</button>
            </div>

            {selectedTicketQuery.isPending && !detail ? <p className="muted" role="status">Загрузка...</p> : null}
            {selectedTicketQuery.isError && !detail ? <p className="error-message" role="alert">Не удалось получить детали заявки.</p> : null}

            {detail ? (
              <>
                {detail.merged_into_id ? (
                  <section
                    className="foundation-card"
                    style={{ marginBottom: 14, gridTemplateColumns: '1fr auto', borderColor: '#b54708' }}
                    role="status"
                  >
                    <div>
                      <strong>{t('ticket.duplicates.mergedBanner')}</strong>
                      <p className="muted" style={{ marginBottom: 0 }}>
                        {t('ticket.duplicates.mergedBy', { name: detail.merged_by_name ?? '—' })}
                      </p>
                    </div>
                    <button
                      type="button"
                      className="ghost-button"
                      onClick={() => setSelectedTicketId(detail.merged_into_id)}
                    >
                      {t('ticket.duplicates.openTarget')}
                    </button>
                  </section>
                ) : null}
                <section className="foundation-card" style={{ marginBottom: 14, gridTemplateColumns: '1fr auto' }}>
                  <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                    <span className="inline-pill">{statusLabel(detail.status, translate)}</span>
                    <span className="inline-pill">{priorityLabel(detail.priority, translate)}</span>
                    <span className="inline-pill">SLA: {translate(slaBadgeLabel(detail.sla_badge))}</span>
                    {canOperate && detail.status === 'WAITING_USER' ? (
                      <span className="inline-pill" style={{ borderColor: waitingUserAgeHours >= 24 ? '#b54708' : undefined }}>
                        Ожидание пользователя: {formatDurationSince(waitingUserSince)}
                      </span>
                    ) : null}
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    {canSelfAssign ? (
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => assignMutation.mutate({ ticketId: detail.id, comment: 'Взял в работу' })}
                        disabled={assignMutation.isPending}
                      >
                        Взять в работу
                      </button>
                    ) : null}
                    {canOperate && canSelectAssignee ? (
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => assignMutation.mutate({ ticketId: detail.id, assignee_id: assignUserId || null, comment: assignComment || undefined })}
                        disabled={assignMutation.isPending}
                      >
                        Назначить
                      </button>
                    ) : null}
                    {canOperateDetail ? (
                      <>
                        {transitionStatus ? (
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={() => transitionMutation.mutate({
                              ticketId: detail.id,
                              status: transitionStatus,
                              expectedVersion: detail.governance_version,
                              idempotencyKey: governanceIdempotencyKey('ticket-transition'),
                              comment: transitionComment,
                              is_internal: isStaff,
                            })}
                            disabled={transitionMutation.isPending}
                          >
                            Сменить статус
                          </button>
                        ) : null}
                        {availableTransitionOptions.some((option) => option.value === 'CLOSED') ? (
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={() => transitionMutation.mutate({
                              ticketId: detail.id,
                              status: 'CLOSED',
                              expectedVersion: detail.governance_version,
                              idempotencyKey: governanceIdempotencyKey('ticket-transition'),
                              comment: 'Закрыто оператором',
                            })}
                            disabled={transitionMutation.isPending}
                          >
                            Закрыть
                          </button>
                        ) : null}
                        {availableTransitionOptions.some((option) => option.value === 'REOPENED') ? (
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={() => transitionMutation.mutate({
                              ticketId: detail.id,
                              status: 'REOPENED',
                              expectedVersion: detail.governance_version,
                              idempotencyKey: governanceIdempotencyKey('ticket-transition'),
                              comment: 'Переоткрытие по запросу',
                            })}
                            disabled={transitionMutation.isPending}
                          >
                            Переоткрыть
                          </button>
                        ) : null}
                      </>
                    ) : null}
                  </div>
                </section>

                <section className="module-subnav">
                  <button type="button" className={`module-subnav-tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Обзор</button>
                  <button type="button" className={`module-subnav-tab ${activeTab === 'comments' ? 'active' : ''}`} onClick={() => setActiveTab('comments')}>Комментарии</button>
                  {canReadParticipants ? <button type="button" className={`module-subnav-tab ${activeTab === 'participants' ? 'active' : ''}`} onClick={() => setActiveTab('participants')}>{t('ticket.participants.tab')}</button> : null}
                  {canReadDuplicates || canSplitTickets ? <button type="button" className={`module-subnav-tab ${activeTab === 'duplicates' ? 'active' : ''}`} onClick={() => setActiveTab('duplicates')}>{t('ticket.duplicates.tab')}</button> : null}
                  <button type="button" className={`module-subnav-tab ${activeTab === 'history' ? 'active' : ''}`} onClick={() => setActiveTab('history')}>История</button>
                  <button type="button" className={`module-subnav-tab ${activeTab === 'sla' ? 'active' : ''}`} onClick={() => setActiveTab('sla')}>SLA</button>
                  <button type="button" className={`module-subnav-tab ${activeTab === 'asset' ? 'active' : ''}`} onClick={() => setActiveTab('asset')}>Актив</button>
                  {isStaff && canReadAssets ? <button type="button" className={`module-subnav-tab ${activeTab === 'impact' ? 'active' : ''}`} onClick={() => setActiveTab('impact')}>Влияние</button> : null}
                  {canViewAiTab ? <button type="button" className={`module-subnav-tab ${activeTab === 'ai' ? 'active' : ''}`} onClick={() => setActiveTab('ai')}>AI</button> : null}
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
                          <strong>{translate(item.title)}</strong>
                          <span>{formatDateTime(item.timestamp)}</span>
                        </header>
                        <p>{item.note}</p>
                      </article>
                    ))}
                  </div>
                </section>

                <section className="ticket-detail-panel" style={{ marginTop: 12 }}>
                  {activeTab === 'overview' ? (
                    <>
                      <div className="detail-fields">
                        <div><span>Заявитель</span><strong>{detail.requester_name}</strong></div>
                        <div><span>Email</span><strong>{detail.requester_email}</strong></div>
                        <div><span>{t('ticket.onBehalf.registeredBy')}</span><strong>{detail.created_by_name ?? '—'}</strong></div>
                        <div><span>{t('ticket.onBehalf.reason')}</span><strong>{creationChannelLabel(detail.creation_channel)}</strong></div>
                        <div><span>Категория</span><strong>{detail.category_label}</strong></div>
                        <div><span>Приоритет</span><strong>{priorityLabel(detail.priority, translate)}</strong></div>
                        <div><span>Исполнитель</span><strong>{detail.assignee_name ?? 'Не назначен'}</strong></div>
                        <div><span>Отдел</span><strong>{detail.department}</strong></div>
                        <div><span>Локация</span><strong>{detail.location}</strong></div>
                        <div><span>Обновлено</span><strong>{formatDateTime(detail.updated_at)}</strong></div>
                        <div><span>{t('ticket.duplicates.version')}</span><strong>{detail.governance_version}</strong></div>
                        {detail.parent_ticket_id ? <div><span>{t('ticket.duplicates.parent')}</span><button type="button" className="ghost-button" onClick={() => setSelectedTicketId(detail.parent_ticket_id)}>{detail.parent_ticket_id}</button></div> : null}
                        {detail.merged_at ? <div><span>{t('ticket.duplicates.mergedAt')}</span><strong>{formatDateTime(detail.merged_at)}</strong></div> : null}
                      </div>
                      <EntityCustomFieldsPanel
                        entityType="ticket"
                        entityId={detail.id}
                        tenantId={detail.tenant_id}
                      />
                      {canReadKnownErrors ? (
                        <section className="ticket-known-errors">
                          <div className="section-header">
                            <div><p className="eyebrow">Known Error Database</p><h4>Проверенные обходные решения</h4></div>
                            <Link to="/problems">Открыть поиск KEDB</Link>
                          </div>
                          {ticketKnownErrorsQuery.isPending ? <p className="muted">Проверяем активные Known Errors…</p> : null}
                          {ticketKnownErrorsQuery.data?.items.map((item) => (
                            <article key={item.id}>
                              <div><strong>{item.known_error_title}</strong><span>{item.problem_number} · {item.service_name ?? 'Без сервиса'}</span></div>
                              <p>{item.workaround}</p>
                            </article>
                          ))}
                          {!ticketKnownErrorsQuery.isPending && !ticketKnownErrorsQuery.data?.items.length ? <p className="muted">Активных Known Errors пока нет.</p> : null}
                        </section>
                      ) : null}
                    </>
                  ) : null}

                  {activeTab === 'comments' ? (
                    <div className="activity-columns" style={{ gridTemplateColumns: '1fr' }}>
                      {canComment ? <div className="comment-box">
                        <h4>Добавить комментарий</h4>
                        {canOperate && detail.status === 'WAITING_USER' ? (
                          <div
                            style={{
                              border: '1px solid #b54708',
                              background: '#2f210c',
                              borderRadius: 12,
                              padding: 10,
                              marginBottom: 10,
                            }}
                          >
                            <p style={{ margin: 0, color: '#fbcf93', fontWeight: 700 }}>
                              Ожидание ответа пользователя: {formatDurationSince(waitingUserSince)}
                            </p>
                            {waitingUserAgeHours >= 24 ? (
                              <p style={{ margin: '6px 0 0', color: '#f4d8b5' }}>
                                Ожидание превышает 24 часа. Рекомендуется отправить напоминание.
                              </p>
                            ) : null}
                          </div>
                        ) : null}
                        {canOperate && availableOperatorTemplates.length > 0 ? (
                          <div style={{ display: 'grid', gap: 8, marginBottom: 10 }}>
                            <p className="muted" style={{ margin: 0 }}>Быстрые шаблоны ответа:</p>
                            <div className="analytics-actions" style={{ justifyContent: 'flex-start', flexWrap: 'wrap' }}>
                              {availableOperatorTemplates.map((template) => (
                                <button
                                  key={template.id}
                                  type="button"
                                  className="ghost-button"
                                  style={{ borderColor: selectedOperatorTemplateId === template.id ? '#40a8ff' : undefined }}
                                  onClick={() => {
                                    setSelectedOperatorTemplateId(template.id)
                                    setCommentInternal(false)
                                    setCommentBody(template.body)
                                  }}
                                >
                                  {translate(template.label)}
                                </button>
                              ))}
                            </div>
                          </div>
                        ) : null}
                        <textarea value={commentBody} onChange={(event) => setCommentBody(event.target.value)} rows={4} />
                        {canUseInternalComment ? (
                          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                            <input type="checkbox" checked={commentInternal} onChange={(event) => setCommentInternal(event.target.checked)} />
                            Внутренний комментарий
                          </label>
                        ) : null}
                        <div className="analytics-actions" style={{ justifyContent: 'flex-start', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            className="ghost-button"
                            onClick={() => {
                              setAiCommentHint(null)
                              aiCommentDraftMutation.mutate({
                                ticketId: detail.id,
                                text: `${detail.title}. ${detail.description ?? ''}. Статус: ${detail.status}. Приоритет: ${detail.priority}.`,
                              })
                            }}
                            disabled={!canUseAiAssist || aiCommentDraftMutation.isPending}
                            title={!canUseAiAssist ? 'Недостаточно прав для AI подсказок' : undefined}
                          >
                            {aiCommentDraftMutation.isPending ? 'AI пишет черновик...' : 'AI-черновик ответа'}
                          </button>
                          <button
                            type="button"
                            onClick={() => commentMutation.mutate({ ticketId: detail.id, body: commentBody, is_internal: commentInternal && canUseInternalComment })}
                            disabled={!commentBody.trim() || commentMutation.isPending}
                          >
                            {commentMutation.isPending ? 'Отправка...' : 'Добавить комментарий'}
                          </button>
                          {canOperateDetail && detail.status === 'WAITING_USER' && availableOperatorTemplates.length > 0 ? (
                            <button
                              type="button"
                              className="ghost-button"
                              disabled={handoffToRequesterMutation.isPending || !selectedOperatorTemplate}
                              onClick={() =>
                                handoffToRequesterMutation.mutate({
                                  ticketId: detail.id,
                                  body: selectedOperatorTemplate?.body ?? commentBody,
                                  shouldTransition: false,
                                  expectedVersion: detail.governance_version,
                                  idempotencyKey: governanceIdempotencyKey('ticket-handoff'),
                                })
                              }
                            >
                              {handoffToRequesterMutation.isPending ? 'Отправка...' : 'Отправить шаблон'}
                            </button>
                          ) : null}
                          {canOperateDetail && detail.status === 'WAITING_USER' && waitingUserAgeHours >= 24 && reminderOperatorTemplate ? (
                            <button
                              type="button"
                              className="ghost-button"
                              disabled={handoffToRequesterMutation.isPending}
                              onClick={() =>
                                handoffToRequesterMutation.mutate({
                                  ticketId: detail.id,
                                  body: reminderOperatorTemplate.body,
                                  shouldTransition: false,
                                  expectedVersion: detail.governance_version,
                                  idempotencyKey: governanceIdempotencyKey('ticket-handoff'),
                                })
                              }
                            >
                              {handoffToRequesterMutation.isPending ? 'Отправка...' : 'Напомнить пользователю (24ч+)'}
                            </button>
                          ) : null}
                          {canOperateDetail && canHandoffToRequester(detail.status) && detail.status !== 'WAITING_USER' && availableOperatorTemplates.length > 0 ? (
                            <button
                              type="button"
                              className="ghost-button"
                              disabled={handoffToRequesterMutation.isPending || !selectedOperatorTemplate}
                              onClick={() =>
                                handoffToRequesterMutation.mutate({
                                  ticketId: detail.id,
                                  body: selectedOperatorTemplate?.body ?? commentBody,
                                  shouldTransition: true,
                                  expectedVersion: detail.governance_version,
                                  idempotencyKey: governanceIdempotencyKey('ticket-handoff'),
                                })
                              }
                            >
                              {handoffToRequesterMutation.isPending ? 'Применение...' : 'Запросить данные и перевести в Ожидает пользователя'}
                            </button>
                          ) : null}
                        </div>
                        {aiCommentHint ? <p className="loading-state" style={{ marginTop: 8 }}>{aiCommentHint}</p> : null}
                      </div> : null}
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

                  {activeTab === 'participants' && canReadParticipants ? (
                    <div style={{ display: 'grid', gap: 16 }}>
                      <div className="section-header">
                        <div>
                          <h3>{t('ticket.participants.title')}</h3>
                          <p className="muted">{t('ticket.participants.subtitle')}</p>
                        </div>
                      </div>

                      {participantsQuery.isPending ? <p className="muted">{t('ticket.participants.loading')}</p> : null}
                      {participantsQuery.isError ? (
                        <div className="alert alert-error" role="alert">
                          {t('ticket.participants.loadFailed')}
                          <button type="button" className="ghost-button" onClick={() => participantsQuery.refetch()}>
                            {t('common.retry')}
                          </button>
                        </div>
                      ) : null}

                      {canWatchTicket ? (
                        <section className="section-card">
                          <h4>{ownParticipant ? t('ticket.participants.update') : t('ticket.participants.watch')}</h4>
                          <p className="muted">{t('ticket.participants.selfHint')}</p>
                          <div className="form-grid">
                            <label>
                              <span>{t('ticket.participants.scope')}</span>
                              <select
                                value={selfParticipantScope}
                                onChange={(event) => setSelfParticipantScope(event.target.value as TicketParticipant['notification_scope'])}
                              >
                                {(Object.keys(participantScopeLabels) as TicketParticipant['notification_scope'][]).map((scope) => (
                                  <option key={scope} value={scope}>{participantScopeLabels[scope]}</option>
                                ))}
                              </select>
                            </label>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                              <input type="checkbox" checked={selfParticipantNotifyInApp} onChange={(event) => setSelfParticipantNotifyInApp(event.target.checked)} />
                              {t('ticket.participants.inApp')}
                            </label>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                              <input type="checkbox" checked={selfParticipantNotifyEmail} onChange={(event) => setSelfParticipantNotifyEmail(event.target.checked)} />
                              {t('ticket.participants.email')}
                            </label>
                          </div>
                          <button
                            type="button"
                            onClick={() => watchTicketMutation.mutate(detail.id)}
                            disabled={watchTicketMutation.isPending}
                          >
                            {ownParticipant ? t('ticket.participants.update') : t('ticket.participants.watch')}
                          </button>
                        </section>
                      ) : null}

                      {canManageParticipants ? (
                        <section className="section-card">
                          <h4>{t('ticket.participants.add')}</h4>
                          <div className="form-grid">
                            <label>
                              <span>{t('ticket.participants.selectUser')}</span>
                              <select
                                value={participantUserId}
                                onChange={(event) => {
                                  setParticipantUserId(event.target.value)
                                  if (event.target.value) {
                                    setParticipantExternalName('')
                                    setParticipantExternalEmail('')
                                  }
                                }}
                              >
                                <option value="">—</option>
                                {availableParticipantCandidates.map((candidate) => (
                                  <option key={candidate.id} value={candidate.id}>
                                    {candidate.full_name} · {candidate.email} · {candidate.role}
                                  </option>
                                ))}
                              </select>
                            </label>
                            <label>
                              <span>{t('ticket.participants.externalName')}</span>
                              <input
                                value={participantExternalName}
                                onChange={(event) => setParticipantExternalName(event.target.value)}
                                placeholder={t('ticket.participants.externalNamePlaceholder')}
                                disabled={Boolean(participantUserId)}
                              />
                            </label>
                            <label>
                              <span>{t('ticket.participants.externalEmail')}</span>
                              <input
                                type="email"
                                value={participantExternalEmail}
                                onChange={(event) => setParticipantExternalEmail(event.target.value)}
                                placeholder="user@example.com"
                                disabled={Boolean(participantUserId)}
                              />
                            </label>
                            <label>
                              <span>{t('ticket.participants.role')}</span>
                              <select value={participantRole} onChange={(event) => setParticipantRole(event.target.value as TicketParticipant['participant_role'])}>
                                {(Object.keys(participantRoleLabels) as TicketParticipant['participant_role'][]).map((roleCode) => (
                                  <option key={roleCode} value={roleCode}>{participantRoleLabels[roleCode]}</option>
                                ))}
                              </select>
                            </label>
                            <label>
                              <span>{t('ticket.participants.scope')}</span>
                              <select value={participantScope} onChange={(event) => setParticipantScope(event.target.value as TicketParticipant['notification_scope'])}>
                                {(Object.keys(participantScopeLabels) as TicketParticipant['notification_scope'][]).map((scope) => (
                                  <option key={scope} value={scope}>{participantScopeLabels[scope]}</option>
                                ))}
                              </select>
                            </label>
                            <label>
                              <span>{t('ticket.participants.reason')}</span>
                              <input
                                value={participantReason}
                                onChange={(event) => setParticipantReason(event.target.value)}
                                placeholder={t('ticket.participants.reasonPlaceholder')}
                                minLength={3}
                              />
                            </label>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                              <input
                                type="checkbox"
                                checked={participantNotifyInApp}
                                onChange={(event) => setParticipantNotifyInApp(event.target.checked)}
                                disabled={!participantUserId}
                              />
                              {t('ticket.participants.inApp')}
                            </label>
                            <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                              <input type="checkbox" checked={participantNotifyEmail} onChange={(event) => setParticipantNotifyEmail(event.target.checked)} />
                              {t('ticket.participants.email')}
                            </label>
                          </div>
                          <button
                            type="button"
                            onClick={() => addParticipantMutation.mutate(detail.id)}
                            disabled={
                              addParticipantMutation.isPending
                              || participantReason.trim().length < 3
                              || (!participantUserId && (!participantExternalName.trim() || !participantExternalEmail.includes('@')))
                            }
                          >
                            {t('ticket.participants.add')}
                          </button>
                        </section>
                      ) : null}

                      <div className="activity-list">
                        {!participantsQuery.isPending && participants.length === 0 ? <p className="muted">{t('ticket.participants.empty')}</p> : null}
                        {participants.map((participant) => {
                          const canEdit = canManageParticipants || (canWatchTicket && participant.user_id === session?.user.id)
                          return (
                            <article className="activity-item" key={participant.id}>
                              <header>
                                <div>
                                  <strong>{participant.display_name}</strong>
                                  <p className="muted" style={{ margin: '2px 0 0' }}>{participant.email}</p>
                                </div>
                                <span>{participantRoleLabels[participant.participant_role]}</span>
                              </header>
                              <div className="form-grid">
                                {canManageParticipants ? (
                                  <label>
                                    <span>{t('ticket.participants.role')}</span>
                                    <select
                                      value={participant.participant_role}
                                      disabled={updateParticipantMutation.isPending}
                                      onChange={(event) => updateParticipantMutation.mutate({
                                        participant,
                                        changes: { participant_role: event.target.value as TicketParticipant['participant_role'] },
                                      })}
                                    >
                                      {(Object.keys(participantRoleLabels) as TicketParticipant['participant_role'][]).map((roleCode) => (
                                        <option key={roleCode} value={roleCode}>{participantRoleLabels[roleCode]}</option>
                                      ))}
                                    </select>
                                  </label>
                                ) : null}
                                <label>
                                  <span>{t('ticket.participants.scope')}</span>
                                  <select
                                    value={participant.notification_scope}
                                    disabled={!canEdit || updateParticipantMutation.isPending}
                                    onChange={(event) => updateParticipantMutation.mutate({
                                      participant,
                                      changes: { notification_scope: event.target.value as TicketParticipant['notification_scope'] },
                                    })}
                                  >
                                    {(Object.keys(participantScopeLabels) as TicketParticipant['notification_scope'][]).map((scope) => (
                                      <option key={scope} value={scope}>{participantScopeLabels[scope]}</option>
                                    ))}
                                  </select>
                                </label>
                                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                                  <input
                                    type="checkbox"
                                    checked={participant.notify_in_app}
                                    disabled={!canEdit || !participant.user_id || updateParticipantMutation.isPending}
                                    onChange={(event) => updateParticipantMutation.mutate({ participant, changes: { notify_in_app: event.target.checked } })}
                                  />
                                  {t('ticket.participants.inApp')}
                                </label>
                                <label style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                                  <input
                                    type="checkbox"
                                    checked={participant.notify_email}
                                    disabled={!canEdit || updateParticipantMutation.isPending}
                                    onChange={(event) => updateParticipantMutation.mutate({ participant, changes: { notify_email: event.target.checked } })}
                                  />
                                  {t('ticket.participants.email')}
                                </label>
                              </div>
                              {canEdit ? (
                                <button
                                  type="button"
                                  className="ghost-button"
                                  onClick={() => removeParticipantMutation.mutate(participant)}
                                  disabled={removeParticipantMutation.isPending}
                                >
                                  {t('ticket.participants.remove')}
                                </button>
                              ) : null}
                            </article>
                          )
                        })}
                      </div>
                    </div>
                  ) : null}

                  {activeTab === 'duplicates' && (canReadDuplicates || canSplitTickets) ? (
                    <div className="activity-list">
                      <section className="section-card">
                        <div className="section-header">
                          <div>
                            <h3>{t('ticket.duplicates.title')}</h3>
                            <p className="muted">{t('ticket.duplicates.subtitle')}</p>
                          </div>
                          {canReadDuplicates ? (
                            <button
                              type="button"
                              className="ghost-button"
                              onClick={() => duplicateCandidatesQuery.refetch()}
                              disabled={duplicateCandidatesQuery.isFetching}
                            >
                              {t('ticket.duplicates.refresh')}
                            </button>
                          ) : null}
                        </div>

                        {canReadDuplicates && !detail.merged_into_id ? (
                          <label style={{ display: 'grid', gap: 6, marginBottom: 12 }}>
                            <span>{t('ticket.duplicates.reason')}</span>
                            <textarea
                              rows={3}
                              minLength={3}
                              maxLength={2000}
                              value={governanceReason}
                              onChange={(event) => setGovernanceReason(event.target.value)}
                              placeholder={t('ticket.duplicates.reasonPlaceholder')}
                            />
                            <small className="muted">{t('ticket.duplicates.auditHint')}</small>
                          </label>
                        ) : null}

                        {duplicateCandidatesQuery.isPending && canReadDuplicates ? <p className="muted">{t('ticket.duplicates.loading')}</p> : null}
                        {duplicateCandidatesQuery.isError ? (
                          <QueryFailureNotice
                            title={t('ticket.duplicates.loadFailed')}
                            sources={[{ label: t('ticket.duplicates.title'), query: duplicateCandidatesQuery }]}
                          />
                        ) : null}
                        {canReadDuplicates && !duplicateCandidatesQuery.isPending && !duplicateCandidatesQuery.data?.length ? (
                          <p className="muted">{t('ticket.duplicates.empty')}</p>
                        ) : null}

                        {(duplicateCandidatesQuery.data ?? []).map((candidate) => (
                          <article className="activity-item" key={candidate.id}>
                            <header>
                              <div>
                                <strong>{candidate.ticket_number ?? candidate.id} · {candidate.title}</strong>
                                <p className="muted" style={{ margin: '3px 0 0' }}>
                                  {candidate.requester_name} · {statusLabel(candidate.status, translate)} · {formatDateTime(candidate.created_at)}
                                </p>
                              </div>
                              <span className="inline-pill">{candidate.score}%</span>
                            </header>
                            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 8 }}>
                              {candidate.evidence.map((signal) => (
                                <span className="inline-pill" key={signal}>{t(duplicateSignalMessageKey(signal))}</span>
                              ))}
                            </div>
                            <div className="analytics-actions" style={{ justifyContent: 'flex-start', marginTop: 12 }}>
                              <button
                                type="button"
                                className="ghost-button"
                                onClick={() => setSelectedTicketId(candidate.id)}
                              >
                                {t('ticket.duplicates.openCandidate')}
                              </button>
                              {canManageDuplicates ? (
                                <button
                                  type="button"
                                  className="ghost-button"
                                  disabled={
                                    governanceReason.trim().length < 3
                                    || dismissDuplicateMutation.isPending
                                    || mergeTicketMutation.isPending
                                  }
                                  onClick={() => dismissDuplicateMutation.mutate({
                                    ticketId: detail.id,
                                    sourceVersion: detail.governance_version,
                                    candidate,
                                    reason: governanceReason.trim(),
                                    idempotencyKey: governanceIdempotencyKey('dismiss'),
                                  })}
                                >
                                  {t('ticket.duplicates.dismiss')}
                                </button>
                              ) : null}
                              {canMergeTickets ? (
                                <button
                                  type="button"
                                  disabled={
                                    governanceReason.trim().length < 3
                                    || dismissDuplicateMutation.isPending
                                    || mergeTicketMutation.isPending
                                  }
                                  onClick={() => {
                                    if (!window.confirm(t('ticket.duplicates.mergeConfirm'))) return
                                    mergeTicketMutation.mutate({
                                      ticketId: detail.id,
                                      sourceVersion: detail.governance_version,
                                      candidate,
                                      reason: governanceReason.trim(),
                                      idempotencyKey: governanceIdempotencyKey('merge'),
                                    })
                                  }}
                                >
                                  {t('ticket.duplicates.mergeCurrent')}
                                </button>
                              ) : null}
                            </div>
                          </article>
                        ))}
                      </section>

                      {canSplitTickets && !detail.merged_into_id ? (
                        <section className="section-card">
                          <h3>{t('ticket.duplicates.splitTitle')}</h3>
                          <p className="muted">{t('ticket.duplicates.splitSubtitle')}</p>
                          <div className="form-grid">
                            <label>
                              <span>{t('ticket.duplicates.childTitle')}</span>
                              <input
                                value={splitTitle}
                                minLength={3}
                                maxLength={255}
                                onChange={(event) => setSplitTitle(event.target.value)}
                              />
                            </label>
                            <label>
                              <span>{t('ticket.duplicates.splitReason')}</span>
                              <input
                                value={splitReason}
                                minLength={3}
                                maxLength={2000}
                                onChange={(event) => setSplitReason(event.target.value)}
                                placeholder={t('ticket.duplicates.reasonPlaceholder')}
                              />
                            </label>
                          </div>
                          <label style={{ display: 'grid', gap: 6, margin: '10px 0' }}>
                            <span>{t('ticket.duplicates.childDescription')}</span>
                            <textarea
                              rows={4}
                              value={splitDescription}
                              onChange={(event) => setSplitDescription(event.target.value)}
                            />
                          </label>
                          <button
                            type="button"
                            disabled={
                              splitTitle.trim().length < 3
                              || splitReason.trim().length < 3
                              || splitTicketMutation.isPending
                            }
                            onClick={() => splitTicketMutation.mutate({
                              ticketId: detail.id,
                              sourceVersion: detail.governance_version,
                              title: splitTitle.trim(),
                              description: splitDescription.trim(),
                              reason: splitReason.trim(),
                              idempotencyKey: governanceIdempotencyKey('split'),
                            })}
                          >
                            {splitTicketMutation.isPending ? t('ticket.duplicates.splitting') : t('ticket.duplicates.split')}
                          </button>
                        </section>
                      ) : null}
                    </div>
                  ) : null}

                  {activeTab === 'history' ? (
                    <div className="activity-list">
                      {historyQuery.isPending ? <p className="muted">Загрузка истории...</p> : null}
                      {!historyQuery.isPending && (historyQuery.data ?? []).length === 0 ? <p className="muted">История пока пуста.</p> : null}
                      {(historyQuery.data ?? []).map((item) => (
                        <article className="activity-item" key={item.id}>
                          <header>
                            <strong><TicketHistoryRawValue value={item.actor_name} /></strong>
                            <span>{formatDateTime(item.created_at)}</span>
                          </header>
                          <p>{ticketHistoryMessage(item)}</p>
                        </article>
                      ))}
                    </div>
                  ) : null}

                  {activeTab === 'sla' ? (
                    <div className="detail-fields">
                      <div><span>SLA badge</span><strong>{translate(slaBadgeLabel(detail.sla_badge))}</strong></div>
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

                  {activeTab === 'impact' && isStaff && canReadAssets ? (
                    <CMDBImpactPanel
                      accessToken={session?.access_token ?? ''}
                      rootCiIds={detail.asset_id ? [detail.asset_id] : []}
                      entityType="TICKET"
                      entityId={detail.id}
                      title="Влияние инцидента"
                    />
                  ) : null}

                  {activeTab === 'ai' && canViewAiTab ? (
                    <div className="activity-list">
                      {canUseAiAssist ? <button
                        type="button"
                        onClick={() => aiMutation.mutate({ ticketId: detail.id, text: `${detail.title}. ${detail.description ?? ''}` })}
                        disabled={aiMutation.isPending}
                      >
                        {aiMutation.isPending ? 'Анализ...' : 'Сгенерировать AI рекомендации'}
                      </button> : null}
                      {canCreateArticleFromTicket ? <button
                        type="button"
                        className="ghost-button"
                        onClick={() => articleMutation.mutate(detail.id)}
                        disabled={articleMutation.isPending || !['RESOLVED', 'CLOSED'].includes(detail.status)}
                        title={!['RESOLVED', 'CLOSED'].includes(detail.status) ? 'Доступно только для RESOLVED/CLOSED' : undefined}
                      >
                        {articleMutation.isPending ? 'Создание...' : 'Создать статью из заявки'}
                      </button> : null}
                      {canReadTicketKnowledge ? <><h4>Прикрепленные статьи</h4>
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
                            {canRecordKnowledgeUsage ? <button
                              type="button"
                              className="ghost-button"
                              onClick={() => useArticleMutation.mutate({ ticketId: detail.id, articleId: link.article_id })}
                              disabled={useArticleMutation.isPending}
                            >
                              Использовать для решения
                            </button> : null}
                          </div>
                        </article>
                      ))}</> : null}

                      {canViewAiSuggestions ? <><h4>Suggested articles</h4>
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
                              {canAttachKnowledge ? <button
                                type="button"
                                className="ghost-button"
                                disabled={attachArticleMutation.isPending}
                                onClick={() =>
                                  attachArticleMutation.mutate({
                                    ticketId: detail.id,
                                    articleId: item.recommended_article_id ?? '',
                                    confidence: item.confidence_value ?? null,
                                  })
                                }
                              >
                                Прикрепить статью
                              </button> : null}
                              {canRecordKnowledgeUsage ? <button
                                type="button"
                                className="ghost-button"
                                disabled={useArticleMutation.isPending}
                                onClick={() => useArticleMutation.mutate({ ticketId: detail.id, articleId: item.recommended_article_id ?? '' })}
                              >
                                Использовать для решения
                              </button> : null}
                            </div>
                          ) : (
                            <p className="muted">Нет article_id для привязки.</p>
                          )}
                        </article>
                      ))}</> : null}
                    </div>
                  ) : null}
                </section>

                {canOperateDetail ? (
                  <section className="ticket-detail-panel" style={{ marginTop: 12 }}>
                    <h3>Операции</h3>
                    <div className="form-grid" style={{ gridTemplateColumns: 'repeat(3, minmax(0, 1fr))' }}>
                      {availableTransitionOptions.length > 0 ? (
                        <label>
                          <span>Новый статус</span>
                          <select value={transitionStatus} onChange={(event) => setTransitionStatus(event.target.value)}>
                            {availableTransitionOptions.map((option) => <option key={option.value} value={option.value}>{translate(option.label)}</option>)}
                          </select>
                        </label>
                      ) : <div />}
                      {canSelectAssignee ? (
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
                    {canRequesterAccept(detail.status) ? (
                      <label>
                        <span>Оценка решения (обязательно)</span>
                        <div className="analytics-actions" style={{ justifyContent: 'flex-start', flexWrap: 'wrap' }}>
                          {[1, 2, 3, 4, 5].map((score) => (
                            <button
                              key={score}
                              type="button"
                              className="ghost-button"
                              style={{ borderColor: requesterSatisfaction === score ? '#40a8ff' : undefined }}
                              onClick={() => setRequesterSatisfaction(score)}
                            >
                              {score}
                            </button>
                          ))}
                        </div>
                      </label>
                    ) : null}
                    <label>
                      <span>Комментарий пользователя</span>
                      <textarea
                        value={requesterDecisionComment}
                        onChange={(event) => setRequesterDecisionComment(event.target.value)}
                        rows={3}
                        placeholder="Например: проблема воспроизводится при подключении из кабинета 401"
                      />
                    </label>
                    {canRequesterReopen(detail.status) ? (
                      <label>
                        <span>Причина переоткрытия (обязательно для переоткрытия)</span>
                        <select value={requesterReopenReason} onChange={(event) => setRequesterReopenReason(event.target.value)}>
                          <option value="">Выберите причину</option>
                          {requesterReopenReasonOptions.map((option) => (
                            <option key={option.value} value={option.value}>{translate(option.label)}</option>
                          ))}
                        </select>
                      </label>
                    ) : null}
                    <div className="analytics-actions" style={{ justifyContent: 'flex-start' }}>
                      {canRequesterAccept(detail.status) ? (
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() =>
                            transitionMutation.mutate({
                              ticketId: detail.id,
                              status: 'CLOSED',
                              expectedVersion: detail.governance_version,
                              idempotencyKey: governanceIdempotencyKey('ticket-transition'),
                              comment: `Оценка решения: ${requesterSatisfaction}/5${requesterDecisionComment.trim() ? `. Комментарий: ${requesterDecisionComment.trim()}` : ''}`,
                              is_internal: false,
                              satisfaction_score: requesterSatisfaction ?? undefined,
                            })
                          }
                          disabled={transitionMutation.isPending || requesterSatisfaction == null}
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
                              expectedVersion: detail.governance_version,
                              idempotencyKey: governanceIdempotencyKey('ticket-transition'),
                              comment: `Причина переоткрытия: ${requesterReopenReasonLabel(requesterReopenReason)}${requesterDecisionComment.trim() ? `. Комментарий: ${requesterDecisionComment.trim()}` : ''}`,
                              is_internal: false,
                              reopen_reason: requesterReopenReasonLabel(requesterReopenReason),
                            })
                          }
                          disabled={transitionMutation.isPending || !requesterReopenReason}
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
