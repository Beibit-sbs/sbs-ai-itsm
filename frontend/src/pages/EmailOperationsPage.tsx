import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  API_BASE_URL,
  changeEmailChannelState,
  createEmailChannel,
  createEmailAttachmentDownloadToken,
  decideEmailAttachment,
  fetchEmailAttachments,
  fetchEmailChannelDashboard,
  fetchEmailChannels,
  fetchEmailConversations,
  fetchEmailDeliveryEvents,
  fetchEmailLogPage,
  fetchInboundEmail,
  fetchTenants,
  reprocessInboundEmail,
  rotateEmailChannelSecret,
  sendEmailChannelTest,
  synchronizeEmailChannel,
  synchronizeEmailSubscription,
  testEmailChannelConnection,
  updateEmailChannel,
  type EmailChannel,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

type View = 'overview' | 'channels' | 'inbound' | 'outbound' | 'attachments' | 'threads'

const views: Array<{ key: View; label: string }> = [
  { key: 'overview', label: 'Обзор' },
  { key: 'channels', label: 'Подключение Microsoft 365' },
  { key: 'inbound', label: 'Входящие и карантин' },
  { key: 'outbound', label: 'Исходящие' },
  { key: 'attachments', label: 'Вложения' },
  { key: 'threads', label: 'Цепочки' },
]

const defaultExtensions = '.pdf, .doc, .docx, .xls, .xlsx, .ppt, .pptx, .txt, .csv, .png, .jpg, .jpeg, .zip'

function statusClass(value: string) {
  const normalized = value.toLowerCase()
  if (['active', 'accepted', 'delivered', 'sent', 'processed', 'stored', 'released', 'clean', 'healthy'].includes(normalized)) {
    return 'badge badge-positive'
  }
  if (['draft', 'paused', 'queued', 'retry', 'received', 'pending', 'quarantined', 'not_configured', 'simulated'].includes(normalized)) {
    return 'badge badge-warning'
  }
  return 'badge badge-danger'
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

function splitValues(value: string) {
  return value
    .split(/[\n,;]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export default function EmailOperationsPage() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const canManage = isRoot || session?.user.permissions.includes('email.channel.manage')
  const canManageInbound = isRoot || session?.user.permissions.includes('email.inbound.manage')
  const canManageAttachments = isRoot || session?.user.permissions.includes('email.attachments.manage')
  const [view, setView] = useState<View>('overview')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [selectedChannelId, setSelectedChannelId] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [inboundStatus, setInboundStatus] = useState('ALL')
  const [attachmentStatus, setAttachmentStatus] = useState('ALL')
  const [outboundStatus, setOutboundStatus] = useState('ALL')
  const [testRecipient, setTestRecipient] = useState(session?.user.email ?? '')
  const [newSecret, setNewSecret] = useState('')
  const [createDraft, setCreateDraft] = useState({
    name: 'Service Desk Microsoft 365',
    provider_type: 'MICROSOFT_GRAPH' as 'MICROSOFT_GRAPH' | 'MOCK',
    mailbox_address: '',
    mailbox_user_id: '',
    entra_tenant_id: '',
    client_id: '',
    client_secret: '',
    inbound_enabled: true,
    outbound_enabled: true,
    default_target: 'TICKET' as 'TICKET' | 'REQUEST',
    allowed_sender_domains: '',
    allowed_attachment_extensions: defaultExtensions,
    max_attachment_mb: '10',
  })
  const [editDraft, setEditDraft] = useState({
    name: '',
    mailbox_address: '',
    mailbox_user_id: '',
    entra_tenant_id: '',
    client_id: '',
    inbound_enabled: true,
    outbound_enabled: true,
    default_target: 'TICKET' as 'TICKET' | 'REQUEST',
    allowed_sender_domains: '',
    allowed_attachment_extensions: defaultExtensions,
    max_attachment_mb: '10',
  })

  const tenantsQuery = useQuery({
    queryKey: ['email-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot),
  })
  useEffect(() => {
    if (isRoot && !tenantId && tenantsQuery.data?.length) {
      setTenantId(tenantsQuery.data[0].id)
    }
  }, [isRoot, tenantId, tenantsQuery.data])

  const scopedTenant = isRoot ? tenantId || null : session?.user.tenant_id ?? null
  const dashboardQuery = useQuery({
    queryKey: ['email-dashboard', token, scopedTenant],
    queryFn: () => fetchEmailChannelDashboard(token, scopedTenant),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 30_000,
  })
  const channelsQuery = useQuery({
    queryKey: ['email-channels', token, scopedTenant],
    queryFn: () => fetchEmailChannels(token, scopedTenant),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 30_000,
  })
  const inboundQuery = useQuery({
    queryKey: ['email-inbound', token, scopedTenant, inboundStatus, selectedChannelId],
    queryFn: () => fetchInboundEmail(token, {
      tenant_id: scopedTenant,
      status: inboundStatus,
      channel_id: selectedChannelId || undefined,
    }),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 15_000,
  })
  const attachmentsQuery = useQuery({
    queryKey: ['email-attachments', token, scopedTenant, attachmentStatus],
    queryFn: () => fetchEmailAttachments(token, {
      tenant_id: scopedTenant,
      status: attachmentStatus,
    }),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 30_000,
  })
  const conversationsQuery = useQuery({
    queryKey: ['email-conversations', token, scopedTenant],
    queryFn: () => fetchEmailConversations(token, scopedTenant),
    enabled: Boolean(token && scopedTenant),
  })
  const deliveriesQuery = useQuery({
    queryKey: ['email-deliveries', token, scopedTenant],
    queryFn: () => fetchEmailDeliveryEvents(token, scopedTenant),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 15_000,
  })
  const outboundQuery = useQuery({
    queryKey: ['email-outbound-log', token, outboundStatus],
    queryFn: () => fetchEmailLogPage(token, {
      status: outboundStatus,
      page: 1,
      page_size: 100,
    }),
    enabled: Boolean(token && scopedTenant),
    refetchInterval: 15_000,
  })

  const selectedChannel = useMemo(
    () => (channelsQuery.data ?? []).find((item) => item.id === selectedChannelId) ?? null,
    [channelsQuery.data, selectedChannelId],
  )
  const scopedOutbound = useMemo(
    () => (outboundQuery.data?.items ?? []).filter((item) => !scopedTenant || item.tenant_id === scopedTenant),
    [outboundQuery.data, scopedTenant],
  )

  useEffect(() => {
    if (!selectedChannelId && channelsQuery.data?.length) {
      setSelectedChannelId(channelsQuery.data[0].id)
    }
  }, [channelsQuery.data, selectedChannelId])
  useEffect(() => {
    if (!selectedChannel) return
    setEditDraft({
      name: selectedChannel.name,
      mailbox_address: selectedChannel.mailbox_address,
      mailbox_user_id: selectedChannel.mailbox_user_id ?? '',
      entra_tenant_id: selectedChannel.entra_tenant_id ?? '',
      client_id: selectedChannel.client_id ?? '',
      inbound_enabled: selectedChannel.inbound_enabled,
      outbound_enabled: selectedChannel.outbound_enabled,
      default_target: selectedChannel.default_target,
      allowed_sender_domains: selectedChannel.allowed_sender_domains.join(', '),
      allowed_attachment_extensions: selectedChannel.allowed_attachment_extensions.join(', '),
      max_attachment_mb: String(Math.round(selectedChannel.max_attachment_bytes / 1024 / 1024)),
    })
  }, [selectedChannel])

  const invalidate = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['email-dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['email-channels'] }),
      queryClient.invalidateQueries({ queryKey: ['email-inbound'] }),
      queryClient.invalidateQueries({ queryKey: ['email-attachments'] }),
      queryClient.invalidateQueries({ queryKey: ['email-conversations'] }),
      queryClient.invalidateQueries({ queryKey: ['email-deliveries'] }),
      queryClient.invalidateQueries({ queryKey: ['email-outbound-log'] }),
    ])
  }

  const runAction = async (key: string, action: () => Promise<unknown>, success: string) => {
    setBusyAction(key)
    setError('')
    setNotice('')
    try {
      await action()
      setNotice(success)
      await invalidate()
    } catch (actionError) {
      setError(errorText(actionError))
    } finally {
      setBusyAction('')
    }
  }

  const createChannel = async () => {
    if (!scopedTenant) return
    await runAction('create', async () => {
      const created = await createEmailChannel(token, {
        tenant_id: scopedTenant,
        name: createDraft.name,
        provider_type: createDraft.provider_type,
        mailbox_address: createDraft.mailbox_address,
        mailbox_user_id: createDraft.mailbox_user_id || null,
        entra_tenant_id: createDraft.entra_tenant_id || null,
        client_id: createDraft.client_id || null,
        client_secret: createDraft.client_secret || null,
        inbound_enabled: createDraft.inbound_enabled,
        outbound_enabled: createDraft.outbound_enabled,
        default_target: createDraft.default_target,
        allowed_sender_domains: splitValues(createDraft.allowed_sender_domains),
        allowed_attachment_extensions: splitValues(createDraft.allowed_attachment_extensions),
        max_attachment_bytes: Number(createDraft.max_attachment_mb) * 1024 * 1024,
      })
      setSelectedChannelId(created.id)
      setCreateDraft((current) => ({ ...current, client_secret: '' }))
    }, 'Канал создан в статусе DRAFT. Проверьте соединение и активируйте его.')
  }

  const saveChannel = async () => {
    if (!selectedChannel) return
    await runAction('save', () => updateEmailChannel(token, selectedChannel.id, {
      expected_version: selectedChannel.version,
      name: editDraft.name,
      mailbox_address: editDraft.mailbox_address,
      mailbox_user_id: editDraft.mailbox_user_id || null,
      entra_tenant_id: editDraft.entra_tenant_id || null,
      client_id: editDraft.client_id || null,
      inbound_enabled: editDraft.inbound_enabled,
      outbound_enabled: editDraft.outbound_enabled,
      default_target: editDraft.default_target,
      allowed_sender_domains: splitValues(editDraft.allowed_sender_domains),
      allowed_attachment_extensions: splitValues(editDraft.allowed_attachment_extensions),
      max_attachment_bytes: Number(editDraft.max_attachment_mb) * 1024 * 1024,
    }), 'Настройки канала сохранены.')
  }

  const downloadAttachment = async (attachmentId: string, filename: string) => {
    setBusyAction(`download-${attachmentId}`)
    setError('')
    try {
      const signed = await createEmailAttachmentDownloadToken(token, attachmentId)
      const response = await fetch(`${API_BASE_URL}/email/attachments/${attachmentId}/download?token=${encodeURIComponent(signed.token)}`, {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!response.ok) {
        const payload = await response.json().catch(() => null) as { detail?: string } | null
        throw new Error(payload?.detail ?? `HTTP ${response.status}`)
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = filename
      anchor.click()
      URL.revokeObjectURL(url)
    } catch (downloadError) {
      setError(errorText(downloadError))
    } finally {
      setBusyAction('')
    }
  }

  const dashboard = dashboardQuery.data
  const busy = Boolean(busyAction)

  return (
    <LocalizedContent><AppShell
      title="Почтовый канал"
      subtitle="Microsoft 365 / Exchange Online: входящие заявки, цепочки, безопасные вложения и контролируемая доставка"
    >
      <section className="identity-toolbar panel">
        <div className="segmented-control" aria-label="Раздел почтового канала">
          {views.map((item) => (
            <button type="button" key={item.key} className={view === item.key ? 'active' : ''} onClick={() => setView(item.key)}>
              {translate(item.label)}
            </button>
          ))}
        </div>
        {isRoot ? (
          <label>Организация<select value={tenantId} onChange={(event) => {
            setTenantId(event.target.value)
            setSelectedChannelId('')
          }}>
            {(tenantsQuery.data ?? []).map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
          </select></label>
        ) : null}
      </section>

      {notice ? <div className="alert alert-success">{notice}</div> : null}
      <QueryFailureNotice
        title="Часть данных Email Operations недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: translate('оперативная сводка'), query: dashboardQuery },
          { label: translate('каналы'), query: channelsQuery },
          { label: translate('входящие сообщения'), query: inboundQuery },
          { label: translate('вложения'), query: attachmentsQuery },
          { label: 'conversation threads', query: conversationsQuery },
          { label: 'delivery attempts', query: deliveriesQuery },
          { label: translate('исходящие сообщения'), query: outboundQuery },
        ]}
      />
      {error ? <div className="alert alert-error" role="alert">{error}</div> : null}

      {view === 'overview' ? (
        <>
          <section className="identity-metrics email-metrics">
            <article><strong>{dashboard?.active_production_channels ?? 0}</strong><span>production-каналов</span></article>
            <article><strong>{dashboard?.queued_outbound ?? 0}</strong><span>в очереди</span></article>
            <article><strong>{dashboard?.simulated_outbound ?? 0}</strong><span>симуляций без отправки</span></article>
            <article className={(dashboard?.failed_outbound ?? 0) > 0 ? 'metric-danger' : ''}><strong>{dashboard?.failed_outbound ?? 0}</strong><span>ошибок отправки</span></article>
            <article><strong>{dashboard?.inbound_received ?? 0}</strong><span>входящих</span></article>
            <article className={(dashboard?.inbound_quarantined ?? 0) > 0 ? 'metric-danger' : ''}><strong>{dashboard?.inbound_quarantined ?? 0}</strong><span>в карантине</span></article>
            <article><strong>{dashboard?.attachments_quarantined ?? 0}</strong><span>вложений на проверке</span></article>
          </section>
          <section className="identity-overview-grid">
            <article className="panel">
              <div className="section-heading">
                <div><p className="eyebrow">СОСТОЯНИЕ</p><h2>Готовность почтового канала</h2></div>
                <span className={statusClass(dashboard?.channel_health ?? 'NOT_CONFIGURED')}>{dashboard?.channel_health ?? 'NOT_CONFIGURED'}</span>
              </div>
              <ul className="identity-checklist">
                <li>{dashboard?.active_production_channels ? '✓' : '○'} Активное подключение Microsoft Graph.</li>
                <li>{dashboard?.webhook_public_url_configured ? '✓' : '○'} Публичный HTTPS webhook. Без него работает delta polling.</li>
                <li>{dashboard?.antivirus_configured ? '✓' : '○'} ClamAV для автоматического выпуска вложений. Без чистого результата файл остаётся в карантине.</li>
                <li>{dashboard?.manual_unscanned_release_enabled ? '⚠' : '✓'} Ручной выпуск без CLEAN-сканирования {dashboard?.manual_unscanned_release_enabled ? 'разрешён явной политикой' : 'запрещён (fail-closed)'}.</li>
                <li>✓ Секрет приложения хранится зашифрованным и никогда не возвращается в интерфейс.</li>
                <li>✓ Повторы идемпотентны; очередь учитывает 429, Retry-After и временные ошибки Microsoft 365.</li>
                <li>✓ Статус ACCEPTED не выдаётся за DELIVERED без отдельного сигнала доставки.</li>
              </ul>
            </article>
            <article className="panel">
              <p className="eyebrow">КАК ЭТО РАБОТАЕТ</p><h2>Письмо → заявка → ответ</h2>
              <ol className="identity-steps">
                <li>Новое письмо создаёт инцидент или запрос услуги — это задаётся в канале.</li>
                <li>В тему исходящих ответов добавляется скрытый устойчивый маркер цепочки SBS.</li>
                <li>Ответ автора становится публичным комментарием именно в своей заявке.</li>
                <li>Чужой отправитель, DMARC fail, автоответ и loop‑письмо не попадут в заявку.</li>
                <li>Исполняемые файлы блокируются; остальные проходят карантин и антивирус.</li>
                <li>Все решения, повторы, выпуск вложений и изменения конфигурации попадают в аудит.</li>
              </ol>
            </article>
          </section>
        </>
      ) : null}

      {view === 'channels' ? (
        <section className="email-channel-grid">
          <article className="panel">
            <div className="section-heading">
              <div><p className="eyebrow">CONTROL PLANE</p><h2>Почтовые каналы</h2></div>
              <span className="badge">{channelsQuery.data?.length ?? 0}</span>
            </div>
            <div className="identity-connector-list">
              {(channelsQuery.data ?? []).map((channel) => (
                <button
                  type="button"
                  key={channel.id}
                  className={selectedChannelId === channel.id ? 'identity-connector-card selected' : 'identity-connector-card'}
                  onClick={() => setSelectedChannelId(channel.id)}
                >
                  <span><strong>{channel.name}</strong><small>{channel.mailbox_address} · {channel.provider_type}</small></span>
                  <span className={statusClass(channel.status)}>{channel.status}</span>
                  <span className="identity-card-stats">{channel.provider_type === 'MOCK' ? translate('simulation only') : `${channel.success_count} ${translate('success')}`} · {channel.failure_count} {translate('errors')}</span>
                </button>
              ))}
              {!channelsQuery.isLoading && !channelsQuery.data?.length ? <p className="empty-state">Каналов пока нет. Создайте первый справа.</p> : null}
            </div>

            {selectedChannel ? (
              <div className="email-channel-details">
                {selectedChannel.provider_type === 'MOCK' ? <p className="inline-warning">Локальная симуляция: письма не покидают платформу и никогда не считаются отправленными или доставленными.</p> : null}
                <div className="key-value-list">
                  <span>Секрет</span><strong>{selectedChannel.client_secret_configured ? 'настроен' : 'не задан'}</strong>
                  <span>Последняя синхронизация</span><strong>{formatDateTime(selectedChannel.last_sync_at)}</strong>
                  <span>Webhook</span><strong>{selectedChannel.graph_subscription_id ? `${translate('активен до')} ${formatDateTime(selectedChannel.graph_subscription_expires_at)}` : 'не создан — работает polling'}</strong>
                  <span>Delta checkpoint</span><strong>{selectedChannel.delta_sync_initialized ? 'сохранён' : 'будет создан при первой синхронизации'}</strong>
                </div>
                {selectedChannel.last_error ? <p className="inline-error">{selectedChannel.last_error}</p> : null}
                {canManage && selectedChannel.status !== 'REVOKED' ? (
                  <>
                    <div className="button-row">
                      <button type="button" disabled={busy} onClick={() => runAction('test', () => testEmailChannelConnection(token, selectedChannel.id), selectedChannel.provider_type === 'MOCK' ? 'Проверена локальная симуляция; внешнего соединения нет.' : 'Microsoft 365 подтвердил доступ к Inbox.')}>Проверить соединение</button>
                      {['DRAFT', 'PAUSED', 'ERROR'].includes(selectedChannel.status) ? <button type="button" disabled={busy} onClick={() => runAction('activate', () => changeEmailChannelState(token, selectedChannel.id, { expected_version: selectedChannel.version, action: 'ACTIVATE', reason: translate('Проверено и активировано администратором') }), 'Канал активирован.')}>Активировать</button> : null}
                      {selectedChannel.status === 'ACTIVE' ? <button type="button" className="secondary" disabled={busy} onClick={() => runAction('pause', () => changeEmailChannelState(token, selectedChannel.id, { expected_version: selectedChannel.version, action: 'PAUSE', reason: translate('Приостановлено администратором') }), 'Канал приостановлен.')}>Приостановить</button> : null}
                      {selectedChannel.status === 'ACTIVE' && selectedChannel.inbound_enabled && selectedChannel.provider_type === 'MICROSOFT_GRAPH' ? <button type="button" className="secondary" disabled={busy} onClick={() => runAction('sync', () => synchronizeEmailChannel(token, selectedChannel.id), 'Входящая почта синхронизирована.')}>Синхронизировать сейчас</button> : null}
                      {selectedChannel.status === 'ACTIVE' && selectedChannel.inbound_enabled && selectedChannel.provider_type === 'MICROSOFT_GRAPH' ? <button type="button" className="secondary" disabled={busy} onClick={() => runAction('subscription', () => synchronizeEmailSubscription(token, selectedChannel.id), 'Webhook Microsoft Graph создан или продлён.')}>Настроить webhook</button> : null}
                    </div>
                    <form className="form-grid email-config-form" onSubmit={(event) => {
                      event.preventDefault()
                      void saveChannel()
                    }}>
                      <label>Название<input required value={editDraft.name} onChange={(event) => setEditDraft({ ...editDraft, name: event.target.value })} /></label>
                      <label>Адрес ящика<input required type="email" value={editDraft.mailbox_address} onChange={(event) => setEditDraft({ ...editDraft, mailbox_address: event.target.value })} /></label>
                      <label>Mailbox object ID / UPN<input value={editDraft.mailbox_user_id} onChange={(event) => setEditDraft({ ...editDraft, mailbox_user_id: event.target.value })} /></label>
                      <label>Entra Directory (tenant) ID<input value={editDraft.entra_tenant_id} onChange={(event) => setEditDraft({ ...editDraft, entra_tenant_id: event.target.value })} /></label>
                      <label>Application (client) ID<input value={editDraft.client_id} onChange={(event) => setEditDraft({ ...editDraft, client_id: event.target.value })} /></label>
                      <label>Новые письма создают<select value={editDraft.default_target} onChange={(event) => setEditDraft({ ...editDraft, default_target: event.target.value as 'TICKET' | 'REQUEST' })}><option value="TICKET">Инцидент</option><option value="REQUEST">Запрос услуги</option></select></label>
                      <label className="check-field"><input type="checkbox" checked={editDraft.inbound_enabled} onChange={(event) => setEditDraft({ ...editDraft, inbound_enabled: event.target.checked })} /> Принимать входящие</label>
                      <label className="check-field"><input type="checkbox" checked={editDraft.outbound_enabled} onChange={(event) => setEditDraft({ ...editDraft, outbound_enabled: event.target.checked })} /> Отправлять исходящие</label>
                      <label className="span-2">Разрешённые домены отправителей (пусто = все)<textarea rows={2} value={editDraft.allowed_sender_domains} onChange={(event) => setEditDraft({ ...editDraft, allowed_sender_domains: event.target.value })} /></label>
                      <label className="span-2">Разрешённые расширения<textarea rows={2} value={editDraft.allowed_attachment_extensions} onChange={(event) => setEditDraft({ ...editDraft, allowed_attachment_extensions: event.target.value })} /></label>
                      <label>Максимум на вложение, МБ<input type="number" min="1" max="25" value={editDraft.max_attachment_mb} onChange={(event) => setEditDraft({ ...editDraft, max_attachment_mb: event.target.value })} /></label>
                      <button type="submit" disabled={busy}>Сохранить настройки</button>
                    </form>
                    {selectedChannel.provider_type === 'MICROSOFT_GRAPH' ? (
                      <div className="email-secret-rotation">
                        <label>Новый client secret<input type="password" autoComplete="new-password" value={newSecret} onChange={(event) => setNewSecret(event.target.value)} placeholder="Значение секрета, не Secret ID" /></label>
                        <button type="button" className="secondary" disabled={busy || newSecret.length < 12} onClick={() => runAction('rotate', async () => {
                          await rotateEmailChannelSecret(token, selectedChannel.id, newSecret)
                          setNewSecret('')
                        }, 'Секрет заменён. Канал поставлен на паузу до повторной проверки.')}>Заменить секрет</button>
                      </div>
                    ) : null}
                    {selectedChannel.status === 'ACTIVE' && selectedChannel.outbound_enabled ? (
                      <div className="email-test-row">
                        <label>Тестовый получатель<input type="email" value={testRecipient} onChange={(event) => setTestRecipient(event.target.value)} /></label>
                        <button type="button" disabled={busy || !testRecipient} onClick={() => runAction('test-email', () => sendEmailChannelTest(token, selectedChannel.id, {
                          to_email: testRecipient,
                          subject: translate('Проверка SBS AI ITSM'),
                          body: translate('Тестовое письмо поставлено в production-очередь SBS AI ITSM.'),
                        }), 'Тестовое письмо поставлено в очередь. Статус смотрите во вкладке «Исходящие».')}>Отправить тест</button>
                      </div>
                    ) : null}
                    <button type="button" className="danger" disabled={busy} onClick={() => {
                      if (window.confirm(translate('Отозвать канал и удалить сохранённые секреты? Это действие необратимо.'))) {
                        void runAction('revoke', () => changeEmailChannelState(token, selectedChannel.id, { expected_version: selectedChannel.version, action: 'REVOKE', reason: translate('Канал отозван администратором') }), 'Канал отозван, секреты удалены.')
                      }
                    }}>Отозвать канал</button>
                  </>
                ) : null}
              </div>
            ) : null}
          </article>

          <article className="panel">
            <p className="eyebrow">MICROSOFT ENTRA ID</p><h2>Пошаговое подключение</h2>
            <ol className="identity-steps">
              <li>Entra admin center → App registrations → New registration.</li>
              <li>API permissions → Microsoft Graph → Application permissions: <code>Mail.Read</code> и <code>Mail.Send</code>.</li>
              <li>Нажмите Grant admin consent. Ограничьте приложение только сервисным ящиком через Exchange Online RBAC for Applications.</li>
              <li>Certificates &amp; secrets → создайте secret и скопируйте именно <strong>Value</strong>. После сохранения он больше не показывается.</li>
              <li>Введите Directory ID, Application ID, адрес ящика и secret в форме ниже.</li>
              <li>Создайте канал → «Проверить соединение» → «Активировать» → «Синхронизировать сейчас».</li>
              <li>После переноса на сервер задайте <code>EMAIL_PUBLIC_BASE_URL=https://itsm.example.com</code> и нажмите «Настроить webhook».</li>
            </ol>
            <div className="alert alert-info">Локально публичный webhook не обязателен: worker забирает изменения через Microsoft Graph delta query. На сервере webhook ускоряет получение, а polling остаётся страховкой.</div>
            {canManage ? (
              <form className="form-grid email-create-form" onSubmit={(event) => {
                event.preventDefault()
                void createChannel()
              }}>
                <label>Название<input required minLength={3} value={createDraft.name} onChange={(event) => setCreateDraft({ ...createDraft, name: event.target.value })} /></label>
                <label>Провайдер<select value={createDraft.provider_type} onChange={(event) => setCreateDraft({ ...createDraft, provider_type: event.target.value as 'MICROSOFT_GRAPH' | 'MOCK' })}><option value="MICROSOFT_GRAPH">Microsoft 365 / Graph</option>{dashboard?.mock_provider_enabled ? <option value="MOCK">Mock — только локальная симуляция</option> : null}</select></label>
                <label>Адрес сервисного ящика<input required type="email" value={createDraft.mailbox_address} onChange={(event) => setCreateDraft({ ...createDraft, mailbox_address: event.target.value })} placeholder="support@example.com" /></label>
                <label>Mailbox object ID / UPN<input value={createDraft.mailbox_user_id} onChange={(event) => setCreateDraft({ ...createDraft, mailbox_user_id: event.target.value })} placeholder="необязательно, по умолчанию адрес" /></label>
                {createDraft.provider_type === 'MICROSOFT_GRAPH' ? (
                  <>
                    <label>Directory (tenant) ID<input required value={createDraft.entra_tenant_id} onChange={(event) => setCreateDraft({ ...createDraft, entra_tenant_id: event.target.value })} /></label>
                    <label>Application (client) ID<input required value={createDraft.client_id} onChange={(event) => setCreateDraft({ ...createDraft, client_id: event.target.value })} /></label>
                    <label className="span-2">Client secret Value<input required type="password" autoComplete="new-password" value={createDraft.client_secret} onChange={(event) => setCreateDraft({ ...createDraft, client_secret: event.target.value })} /></label>
                  </>
                ) : null}
                <label>Новые письма создают<select value={createDraft.default_target} onChange={(event) => setCreateDraft({ ...createDraft, default_target: event.target.value as 'TICKET' | 'REQUEST' })}><option value="TICKET">Инцидент</option><option value="REQUEST">Запрос услуги</option></select></label>
                <label>Максимум на вложение, МБ<input type="number" min="1" max="25" value={createDraft.max_attachment_mb} onChange={(event) => setCreateDraft({ ...createDraft, max_attachment_mb: event.target.value })} /></label>
                <label className="span-2">Разрешённые домены (пусто = все)<textarea rows={2} value={createDraft.allowed_sender_domains} onChange={(event) => setCreateDraft({ ...createDraft, allowed_sender_domains: event.target.value })} placeholder="example.com, partner.kz" /></label>
                <label className="span-2">Разрешённые расширения<textarea rows={2} value={createDraft.allowed_attachment_extensions} onChange={(event) => setCreateDraft({ ...createDraft, allowed_attachment_extensions: event.target.value })} /></label>
                <label className="check-field"><input type="checkbox" checked={createDraft.inbound_enabled} onChange={(event) => setCreateDraft({ ...createDraft, inbound_enabled: event.target.checked })} /> Входящая почта</label>
                <label className="check-field"><input type="checkbox" checked={createDraft.outbound_enabled} onChange={(event) => setCreateDraft({ ...createDraft, outbound_enabled: event.target.checked })} /> Исходящая почта</label>
                <button type="submit" disabled={busy || !scopedTenant}>Создать безопасный канал</button>
              </form>
            ) : null}
          </article>
        </section>
      ) : null}

      {view === 'inbound' ? (
        <section className="panel">
          <div className="section-heading"><div><p className="eyebrow">INBOUND INTAKE</p><h2>Входящие письма и карантин</h2></div><span className="badge">{inboundQuery.data?.length ?? 0}</span></div>
          <div className="filter-row">
            <select value={inboundStatus} onChange={(event) => setInboundStatus(event.target.value)}>
              <option value="ALL">Все состояния</option><option value="PROCESSED">PROCESSED</option><option value="QUARANTINED">QUARANTINED</option><option value="REJECTED">REJECTED</option><option value="LOOP">LOOP</option><option value="FAILED">FAILED</option><option value="DEAD_LETTER">DEAD LETTER</option>
            </select>
            <select value={selectedChannelId} onChange={(event) => setSelectedChannelId(event.target.value)}>
              <option value="">Все каналы</option>{(channelsQuery.data ?? []).map((channel) => <option key={channel.id} value={channel.id}>{channel.name}</option>)}
            </select>
          </div>
          <div className="table-scroll"><table>
            <thead><tr><th>Получено</th><th>Отправитель</th><th>Тема / текст</th><th>Проверка</th><th>Результат</th><th /></tr></thead>
            <tbody>{(inboundQuery.data ?? []).map((message) => (
              <tr key={message.id}>
                <td>{formatDateTime(message.received_at)}<small>{message.attachment_count} вложений</small></td>
                <td><strong>{message.from_name ?? message.from_email}</strong><small>{message.from_email}</small></td>
                <td><strong>{message.subject}</strong><small className="email-body-preview">{message.body_preview}</small></td>
                <td><span className={statusClass(message.status)}>{message.status}</span><small>{message.authentication_results ?? 'Authentication-Results отсутствует'}</small></td>
                <td>{message.related_ticket_id ? <Link to={`/tickets/${message.related_ticket_id}`}>Инцидент</Link> : message.related_request_id ? <Link to={`/requests/${message.related_request_id}`}>Запрос</Link> : '—'}<small>{message.rejection_reason ?? '—'}</small></td>
                <td>{canManageInbound && ['QUARANTINED', 'FAILED', 'DEAD_LETTER'].includes(message.status) ? <button type="button" className="secondary compact" disabled={busy} onClick={() => {
                  const override = message.status === 'QUARANTINED' && window.confirm(translate('Разрешить отправителю добавить сообщение в найденную цепочку, даже если он не является заявителем? Нажмите «Отмена» для обычной повторной обработки.'))
                  void runAction(`reprocess-${message.id}`, () => reprocessInboundEmail(token, message.id, {
                    override_sender_authorization: override,
                    reason: override ? translate('Проверено и разрешено администратором') : translate('Повтор после исправления конфигурации'),
                  }), 'Письмо повторно обработано.')
                }}>Обработать снова</button> : null}</td>
              </tr>
            ))}</tbody>
          </table></div>
          {!inboundQuery.isLoading && !inboundQuery.data?.length ? <p className="empty-state">Входящих писем по выбранному фильтру нет.</p> : null}
        </section>
      ) : null}

      {view === 'outbound' ? (
        <>
          <section className="panel">
            <div className="section-heading"><div><p className="eyebrow">DELIVERY QUEUE</p><h2>Исходящие сообщения</h2></div><span className="badge">{scopedOutbound.length}</span></div>
            <div className="filter-row"><select value={outboundStatus} onChange={(event) => setOutboundStatus(event.target.value)}><option value="ALL">Все состояния</option><option value="QUEUED">QUEUED</option><option value="RETRY">RETRY</option><option value="SIMULATED">SIMULATED</option><option value="ACCEPTED">ACCEPTED</option><option value="SENT">SENT</option><option value="BOUNCED">BOUNCED</option><option value="FAILED">FAILED</option></select></div>
            <div className="table-scroll"><table>
              <thead><tr><th>Создано</th><th>Получатель</th><th>Тема</th><th>Провайдер</th><th>Состояние</th><th>Попытки</th><th>Ошибка</th></tr></thead>
              <tbody>{scopedOutbound.map((item) => (
                <tr key={item.id}>
                  <td>{formatDateTime(item.created_at)}</td><td>{item.to_email}</td><td>{item.subject}</td><td>{item.provider}</td>
                  <td><span className={statusClass(item.status)}>{item.status}</span><small>{item.status === 'ACCEPTED' ? 'Microsoft принял запрос; это ещё не подтверждение доставки' : item.status === 'SIMULATED' ? 'Внешняя отправка не выполнялась' : formatDateTime(item.next_retry_at)}</small></td>
                  <td>{item.attempt_count ?? 0} / {item.max_attempts ?? 0}</td><td>{item.error_message ?? '—'}</td>
                </tr>
              ))}</tbody>
            </table></div>
            <p className="muted">Для ручного повтора и расширенного поиска доступен <Link to="/notifications/email-log">журнал email</Link>.</p>
          </section>
          <section className="panel">
            <div className="section-heading"><div><p className="eyebrow">PROVIDER SIGNALS</p><h2>События доставки</h2></div><span className="badge">{deliveriesQuery.data?.length ?? 0}</span></div>
            <div className="table-scroll"><table><thead><tr><th>Время</th><th>Событие</th><th>Email log</th><th>Причина</th></tr></thead><tbody>
              {(deliveriesQuery.data ?? []).map((event) => <tr key={event.id}><td>{formatDateTime(event.occurred_at)}</td><td><span className={statusClass(event.event_type)}>{event.event_type}</span></td><td><code>{event.email_log_id.slice(0, 12)}</code></td><td>{event.reason ?? '—'}</td></tr>)}
            </tbody></table></div>
          </section>
        </>
      ) : null}

      {view === 'attachments' ? (
        <section className="panel">
          <div className="section-heading"><div><p className="eyebrow">QUARANTINE</p><h2>Вложения входящей почты</h2></div><span className="badge">{attachmentsQuery.data?.length ?? 0}</span></div>
          <div className="filter-row"><select value={attachmentStatus} onChange={(event) => setAttachmentStatus(event.target.value)}><option value="ALL">Все состояния</option><option value="QUARANTINED">QUARANTINED</option><option value="STORED">STORED</option><option value="RELEASED">RELEASED</option><option value="BLOCKED">BLOCKED</option></select></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Файл</th><th>Размер / SHA-256</th><th>Проверка</th><th>Состояние</th><th>Причина</th><th /></tr></thead>
            <tbody>{(attachmentsQuery.data ?? []).map((item) => (
              <tr key={item.id}>
                <td><strong>{item.original_filename}</strong><small>заявлен: {item.content_type ?? 'не указан'}</small><small>обнаружен: {item.detected_content_type ?? 'не определён'}</small></td>
                <td>{(item.size_bytes / 1024).toFixed(1)} КБ<small>{item.sha256 ? `${item.sha256.slice(0, 16)}…` : 'hash отсутствует'}</small><small>{item.sanitization_applied ? 'метаданные очищены' : `${translate('скачиваний:')} ${item.download_count}`}</small></td>
                <td><span className={statusClass(item.scan_status)}>{item.scan_status}</span><small>{item.security_findings.length ? item.security_findings.join(', ') : 'контент прошёл локальные проверки'}</small></td><td><span className={statusClass(item.status)}>{item.status}</span></td><td>{item.blocked_reason ?? '—'}</td>
                <td><div className="button-row compact-row">
                  {['STORED', 'RELEASED'].includes(item.status) ? <button type="button" className="secondary compact" disabled={busyAction === `download-${item.id}`} onClick={() => void downloadAttachment(item.id, item.safe_filename)}>Скачать</button> : null}
                  {canManageAttachments && item.status === 'QUARANTINED' && dashboard?.manual_unscanned_release_enabled ? <button type="button" className="secondary compact" disabled={busy} onClick={() => {
                    if (window.confirm(translate('Выпустить вложение после ручной проверки? Решение будет записано в аудит.'))) {
                      void runAction(`release-${item.id}`, () => decideEmailAttachment(token, item.id, { decision: 'RELEASE', reason: translate('Выпущено после ручной проверки администратором') }), 'Вложение выпущено.')
                    }
                  }}>Выпустить</button> : null}
                  {canManageAttachments && item.status !== 'BLOCKED' ? <button type="button" className="danger compact" disabled={busy} onClick={() => runAction(`block-${item.id}`, () => decideEmailAttachment(token, item.id, { decision: 'BLOCK', reason: translate('Заблокировано администратором безопасности') }), 'Вложение заблокировано.')}>Блокировать</button> : null}
                </div></td>
              </tr>
            ))}</tbody>
          </table></div>
        </section>
      ) : null}

      {view === 'threads' ? (
        <section className="panel">
          <div className="section-heading"><div><p className="eyebrow">THREAD SAFETY</p><h2>Связанные почтовые цепочки</h2></div><span className="badge">{conversationsQuery.data?.length ?? 0}</span></div>
          <div className="table-scroll"><table>
            <thead><tr><th>Последнее письмо</th><th>Тема</th><th>Заявитель</th><th>Объект ITSM</th><th>Маркер</th></tr></thead>
            <tbody>{(conversationsQuery.data ?? []).map((item) => (
              <tr key={item.id}><td>{formatDateTime(item.last_message_at)}</td><td>{item.normalized_subject}</td><td>{item.requester_email}</td><td><Link to={item.entity_type === 'TICKET' ? `/tickets/${item.entity_id}` : `/requests/${item.entity_id}`}>{item.entity_type} · {item.entity_id.slice(0, 8)}</Link></td><td><code>{item.thread_token_hint}</code></td></tr>
            ))}</tbody>
          </table></div>
          <p className="muted">Полный thread token намеренно не показывается. Система проверяет маркер, tenant, заявителя и активного сотрудника до добавления ответа.</p>
        </section>
      ) : null}
    </AppShell></LocalizedContent>
  )
}
