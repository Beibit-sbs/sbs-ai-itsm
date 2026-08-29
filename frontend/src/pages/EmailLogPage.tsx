import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { fetchEmailLogPage, retryEmailLog, type EmailMessageLog } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'
import { useTenantExperience } from '../experience/TenantExperienceContext'

function statusClass(value: string) {
  if (['ACCEPTED', 'DELIVERED', 'SENT'].includes(value)) return 'badge badge-positive'
  if (['QUEUED', 'RETRY', 'SIMULATED'].includes(value)) return 'badge badge-warning'
  return 'badge badge-danger'
}

export default function EmailLogPage() {
  const { session } = useAuth()
  const { formatDateTime } = useTenantExperience()
  const queryClient = useQueryClient()
  const root = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const canRetryEmail = root || permissions.has('notifications.email_log.retry')
  const canReadNotifications = root
    || permissions.has('notifications.read')
    || permissions.has('notifications.templates.read')
  const canReadEmailOperations = root
    || Array.from(permissions).some((permission) => permission.startsWith('email.'))
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)
  const [selectedLog, setSelectedLog] = useState<EmailMessageLog | null>(null)
  const detailDialogRef = useDialogFocusTrap<HTMLElement>(
    Boolean(selectedLog),
    () => setSelectedLog(null),
  )

  const emailLogQuery = useQuery({
    queryKey: ['email-log', session?.access_token, statusFilter, search, page],
    queryFn: () =>
      fetchEmailLogPage(session?.access_token ?? '', {
        status: statusFilter,
        q: search,
        page,
        page_size: 20,
      }),
    enabled: Boolean(session?.access_token),
    refetchInterval: 15_000,
  })
  const retryMutation = useMutation({
    mutationFn: async (emailLogId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return retryEmailLog(session.access_token, emailLogId)
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['email-log'] })
    },
  })

  const logs = emailLogQuery.data?.items ?? []
  const total = emailLogQuery.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / 20))
  const queued = logs.filter((item) => ['QUEUED', 'RETRY'].includes(item.status)).length
  const accepted = logs.filter((item) => ['ACCEPTED', 'DELIVERED', 'SENT'].includes(item.status)).length
  const simulated = logs.filter((item) => item.status === 'SIMULATED').length
  const failed = logs.filter((item) => ['FAILED', 'BOUNCED'].includes(item.status)).length

  return (
    <AppShell title="Email Log" subtitle="Очередь исходящей почты, попытки, статусы Microsoft 365 и ошибки доставки">
      <section className="section-card">
        <div>
          <p className="eyebrow">PRODUCTION DELIVERY LOG</p>
          <h2>Журнал почтовой доставки</h2>
          <p>ACCEPTED означает, что Microsoft Graph принял запрос. DELIVERED выставляется только по отдельному подтверждённому событию провайдера.</p>
        </div>
        {canReadEmailOperations ? <div className="status-column"><Link to="/email-operations" className="ghost-button">Настроить почтовый канал</Link></div> : null}
      </section>

      <nav className="module-subnav" aria-label="Навигация уведомлений">
        {canReadNotifications ? <Link to="/notifications" className="module-subnav-tab">Уведомления</Link> : null}
        <Link to="/notifications/email-log" className="module-subnav-tab active">Email Log</Link>
        {canReadEmailOperations ? <Link to="/email-operations" className="module-subnav-tab">Почтовый канал</Link> : null}
      </nav>

      <section className="module-overview-grid">
        <article className="metric-card"><span>В очереди</span><strong>{queued}</strong><p>QUEUED / RETRY на текущей странице</p></article>
        <article className="metric-card"><span>Принято провайдером</span><strong>{accepted}</strong><p>ACCEPTED / DELIVERED / SENT</p></article>
        <article className="metric-card"><span>Только симуляция</span><strong>{simulated}</strong><p>SIMULATED — внешней отправки не было</p></article>
        <article className="metric-card"><span>Требует внимания</span><strong>{failed}</strong><p>FAILED / BOUNCED</p></article>
      </section>

      <section className="foundation-card table-toolbar">
        <div className="table-filters">
          <label className="inline-field"><span>Поиск</span><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1) }} placeholder="Тема, получатель или текст" /></label>
          <label className="inline-field"><span>Статус</span><select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(1) }}>
            <option value="ALL">Все</option><option value="QUEUED">QUEUED</option><option value="RETRY">RETRY</option><option value="SIMULATED">SIMULATED</option><option value="ACCEPTED">ACCEPTED</option><option value="DELIVERED">DELIVERED</option><option value="SENT">SENT</option><option value="BOUNCED">BOUNCED</option><option value="FAILED">FAILED</option>
          </select></label>
        </div>
        <div className="analytics-actions">
          <button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>Назад</button>
          <span>Страница {page} / {totalPages}</span>
          <button type="button" className="ghost-button" disabled={page >= totalPages} onClick={() => setPage((value) => Math.min(totalPages, value + 1))}>Вперёд</button>
        </div>
      </section>

      <section className="section-card notification-list-shell">
        {emailLogQuery.isPending ? <p className="loading-state">Загрузка…</p> : emailLogQuery.isError ? (
          <div className="error-state">Не удалось загрузить журнал.<button type="button" className="ghost-button" onClick={() => emailLogQuery.refetch()}>Повторить</button></div>
        ) : logs.length === 0 ? <p className="empty-state">Записей нет. Настройте канал и отправьте тестовое письмо.</p> : (
          <div className="ticket-table-wrap"><table className="ticket-table">
            <thead><tr><th>Получатель</th><th>Тема</th><th>Статус</th><th>Провайдер</th><th>Попытки</th><th>Следующий повтор</th><th>Ошибка</th><th /></tr></thead>
            <tbody>{logs.map((item) => (
              <tr key={item.id}>
                <td>{item.to_email}</td><td>{item.subject}</td><td><span className={statusClass(item.status)}>{item.status}</span></td><td>{item.provider}</td>
                <td>{item.attempt_count ?? 0} / {item.max_attempts ?? 0}</td><td>{formatDateTime(item.next_retry_at)}</td><td>{item.error_message ?? '—'}</td>
                <td><div className="analytics-actions">
                  <button type="button" className="ghost-button" onClick={() => setSelectedLog(item)}>Детали</button>
                  {canRetryEmail && ['FAILED', 'BOUNCED'].includes(item.status) ? <button type="button" className="ghost-button" disabled={retryMutation.isPending} onClick={() => retryMutation.mutate(item.id)}>Retry</button> : null}
                </div></td>
              </tr>
            ))}</tbody>
          </table></div>
        )}
      </section>

      {retryMutation.isError ? <p className="error-message" role="alert">{retryMutation.error instanceof Error ? retryMutation.error.message : 'Не удалось поставить письмо на повтор.'}</p> : null}

      {selectedLog ? (
        <div className="modal-backdrop" role="presentation" onClick={() => setSelectedLog(null)}>
          <section
            ref={detailDialogRef}
            className="modal-card"
            role="dialog"
            aria-modal="true"
            aria-label="Детали email"
            tabIndex={-1}
            onClick={(event) => event.stopPropagation()}
          >
            <p className="eyebrow">EMAIL DELIVERY</p><h2>{selectedLog.subject}</h2>
            <div className="key-value-list">
              <span>ID</span><code>{selectedLog.id}</code><span>Получатель</span><strong>{selectedLog.to_email}</strong>
              <span>Провайдер</span><strong>{selectedLog.provider}</strong><span>Provider request</span><code>{selectedLog.provider_message_id ?? '—'}</code>
              <span>Создано</span><strong>{formatDateTime(selectedLog.created_at)}</strong><span>Принято</span><strong>{formatDateTime(selectedLog.accepted_at ?? selectedLog.sent_at)}</strong>
              <span>Доставлено</span><strong>{formatDateTime(selectedLog.delivered_at)}</strong><span>Bounce</span><strong>{formatDateTime(selectedLog.bounced_at)}</strong>
            </div>
            <pre className="email-log-body">{selectedLog.body}</pre>
            <div className="button-row"><button type="button" className="secondary" onClick={() => setSelectedLog(null)}>Закрыть</button></div>
          </section>
        </div>
      ) : null}
    </AppShell>
  )
}
