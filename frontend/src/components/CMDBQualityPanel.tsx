import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  activateCMDBCertificationCampaign,
  completeCMDBCertificationCampaign,
  createCMDBCertificationCampaign,
  decideCMDBCertificationItem,
  fetchCMDBCertificationCampaign,
  fetchCMDBCertificationCampaigns,
  fetchCMDBQualityFindings,
  fetchCMDBQualityOverview,
  runCMDBQualityScan,
  updateCMDBQualityFinding,
  type CMDBCertificationCampaign,
  type CMDBCertificationItem,
  type CMDBQualityFinding,
} from '../api/client'
import QueryFailureNotice from './QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'


type CMDBQualityPanelProps = {
  accessToken: string
  tenantId?: string
  currentUserId?: string
  canScan: boolean
  canManage: boolean
}

const dimensionLabels: Record<string, string> = {
  COMPLETENESS: 'Полнота',
  CORRECTNESS: 'Корректность',
  FRESHNESS: 'Актуальность',
  DUPLICATE: 'Дубликаты',
  ORPHAN: 'Связность',
  CERTIFICATION: 'Сертификация',
}

const severityLabels: Record<string, string> = {
  LOW: 'Низкая',
  MEDIUM: 'Средняя',
  HIGH: 'Высокая',
  CRITICAL: 'Критическая',
}

function formatDate(value: string | null | undefined, locale: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

function defaultDueDate() {
  const value = new Date()
  value.setDate(value.getDate() + 14)
  return value.toISOString().slice(0, 10)
}

export default function CMDBQualityPanel({
  accessToken,
  tenantId,
  currentUserId,
  canScan,
  canManage,
}: CMDBQualityPanelProps) {
  const queryClient = useQueryClient()
  const { uiLocale: locale, translate } = useTenantExperience()
  const [tab, setTab] = useState<'findings' | 'campaigns'>('findings')
  const [findingStatus, setFindingStatus] = useState('OPEN')
  const [dimension, setDimension] = useState('ALL')
  const [severity, setSeverity] = useState('ALL')
  const [findingNotes, setFindingNotes] = useState<Record<string, string>>({})
  const [selectedCampaignId, setSelectedCampaignId] = useState<string | null>(null)
  const [campaignName, setCampaignName] = useState('')
  const [campaignDescription, setCampaignDescription] = useState('')
  const [campaignDue, setCampaignDue] = useState(defaultDueDate)
  const [campaignCriticality, setCampaignCriticality] = useState('ALL')
  const [campaignEnvironment, setCampaignEnvironment] = useState('ALL')
  const [onlyWithoutOwner, setOnlyWithoutOwner] = useState(false)
  const [decisionNotes, setDecisionNotes] = useState<Record<string, string>>({})

  const overviewKey = ['cmdb-quality-overview', accessToken, tenantId]
  const findingsKey = ['cmdb-quality-findings', accessToken, tenantId, findingStatus, dimension, severity]
  const campaignsKey = ['cmdb-certification-campaigns', accessToken, tenantId]
  const overviewQuery = useQuery({
    queryKey: overviewKey,
    queryFn: () => fetchCMDBQualityOverview(accessToken, tenantId),
    enabled: Boolean(accessToken),
  })
  const findingsQuery = useQuery({
    queryKey: findingsKey,
    queryFn: () => fetchCMDBQualityFindings(accessToken, {
      tenant_id: tenantId,
      finding_status: findingStatus,
      dimension,
      severity,
    }),
    enabled: Boolean(accessToken),
  })
  const campaignsQuery = useQuery({
    queryKey: campaignsKey,
    queryFn: () => fetchCMDBCertificationCampaigns(accessToken, tenantId),
    enabled: Boolean(accessToken),
  })
  const campaignQuery = useQuery({
    queryKey: ['cmdb-certification-campaign', accessToken, selectedCampaignId],
    queryFn: () => fetchCMDBCertificationCampaign(accessToken, selectedCampaignId ?? ''),
    enabled: Boolean(accessToken && selectedCampaignId),
  })

  async function refreshQuality() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['cmdb-quality-overview'] }),
      queryClient.invalidateQueries({ queryKey: ['cmdb-quality-findings'] }),
      queryClient.invalidateQueries({ queryKey: ['cmdb-certification-campaigns'] }),
    ])
  }

  function cacheCampaign(campaign: CMDBCertificationCampaign) {
    setSelectedCampaignId(campaign.id)
    queryClient.setQueryData(
      ['cmdb-certification-campaign', accessToken, campaign.id],
      campaign,
    )
  }

  const scanMutation = useMutation({
    mutationFn: () => runCMDBQualityScan(accessToken, tenantId),
    onSuccess: refreshQuality,
  })
  const findingMutation = useMutation({
    mutationFn: ({
      finding,
      status,
      takeOwnership,
    }: {
      finding: CMDBQualityFinding
      status?: CMDBQualityFinding['status']
      takeOwnership?: boolean
    }) => updateCMDBQualityFinding(accessToken, finding.id, {
      expected_version: finding.version,
      owner_user_id: takeOwnership ? currentUserId : undefined,
      finding_status: status,
      resolution_note: status && ['RESOLVED', 'WAIVED'].includes(status)
        ? findingNotes[finding.id]?.trim()
        : undefined,
    }),
    onSuccess: refreshQuality,
  })
  const createCampaignMutation = useMutation({
    mutationFn: () => createCMDBCertificationCampaign(accessToken, {
      tenant_id: tenantId,
      name: campaignName.trim(),
      description: campaignDescription.trim() || undefined,
      due_at: new Date(`${campaignDue}T23:59:59`).toISOString(),
      scope: {
        criticalities: campaignCriticality === 'ALL'
          ? []
          : [campaignCriticality as 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'],
        environments: campaignEnvironment === 'ALL'
          ? []
          : [campaignEnvironment as 'PRODUCTION' | 'STAGING' | 'TEST' | 'DEVELOPMENT' | 'OTHER'],
        only_without_owner: onlyWithoutOwner,
        default_certifier_user_id: currentUserId,
      },
    }),
    onSuccess: async (campaign) => {
      cacheCampaign(campaign)
      setCampaignName('')
      setCampaignDescription('')
      await refreshQuality()
    },
  })
  const activateMutation = useMutation({
    mutationFn: (campaign: CMDBCertificationCampaign) =>
      activateCMDBCertificationCampaign(accessToken, campaign),
    onSuccess: async (campaign) => {
      cacheCampaign(campaign)
      await refreshQuality()
    },
  })
  const decisionMutation = useMutation({
    mutationFn: ({
      campaign,
      item,
      decision,
    }: {
      campaign: CMDBCertificationCampaign
      item: CMDBCertificationItem
      decision: 'CERTIFIED' | 'REJECTED'
    }) => decideCMDBCertificationItem(
      accessToken,
      campaign.id,
      item,
      decision,
      decisionNotes[item.id]?.trim() ?? '',
    ),
    onSuccess: async (campaign) => {
      cacheCampaign(campaign)
      await refreshQuality()
    },
  })
  const completeMutation = useMutation({
    mutationFn: (campaign: CMDBCertificationCampaign) =>
      completeCMDBCertificationCampaign(accessToken, campaign),
    onSuccess: async (campaign) => {
      cacheCampaign(campaign)
      await refreshQuality()
    },
  })

  const overview = overviewQuery.data
  const snapshot = overview?.latest
  const campaign = campaignQuery.data
  const scoreCards = useMemo(() => snapshot ? [
    ['Общий индекс', snapshot.overall_score],
    ['Полнота', snapshot.completeness_score],
    ['Корректность', snapshot.correctness_score],
    ['Актуальность', snapshot.freshness_score],
    ['Без дублей', snapshot.duplicate_score],
    ['Связность', snapshot.orphan_score],
  ] : [], [snapshot])
  const mutationError = [
    scanMutation.error,
    findingMutation.error,
    createCampaignMutation.error,
    activateMutation.error,
    decisionMutation.error,
    completeMutation.error,
  ].find(Boolean)

  return (
    <LocalizedContent>
    <section className="cmdb-quality-workspace">
      <QueryFailureNotice
        title="Часть данных CMDB Quality недоступна."
        sources={[
          { label: translate('обзор качества'), query: overviewQuery },
          { label: translate('нарушения качества'), query: findingsQuery },
          { label: translate('кампании сертификации'), query: campaignsQuery },
          { label: translate('выбранная кампания'), query: campaignQuery },
        ]}
      />
      <div className="section-header">
        <div>
          <p className="eyebrow">CMDB DATA GOVERNANCE</p>
          <h2 className="section-title">Качество и сертификация данных</h2>
          <p className="section-subtitle">Измеримые показатели, владельцы исправлений, сроки и доказательства периодической проверки CI.</p>
        </div>
        {canScan ? (
          <button type="button" disabled={scanMutation.isPending} onClick={() => scanMutation.mutate()}>
            {scanMutation.isPending ? 'Проверка…' : 'Запустить quality scan'}
          </button>
        ) : null}
      </div>

      {mutationError ? (
        <p className="error-message">
          {mutationError instanceof Error ? mutationError.message : 'Операция не выполнена.'}
        </p>
      ) : null}

      {snapshot ? (
        <>
          <div className="quality-score-grid">
            {scoreCards.map(([label, score]) => (
              <article key={String(label)}>
                <div className={`quality-score score-${Number(score) >= 90 ? 'good' : Number(score) >= 70 ? 'warn' : 'bad'}`}>
                  {Number(score).toFixed(0)}
                </div>
                <div><strong>{label}</strong><span>из 100</span></div>
              </article>
            ))}
          </div>
          <div className="quality-queue-strip">
            <span><strong>{overview?.open_findings ?? 0}</strong> открыто</span>
            <span><strong>{overview?.overdue_findings ?? 0}</strong> просрочено</span>
            <span><strong>{overview?.unassigned_findings ?? 0}</strong> без владельца</span>
            <span><strong>{overview?.active_campaigns ?? 0}</strong> активных кампаний</span>
            <span>Снимок {formatDate(snapshot.created_at, locale)} · {snapshot.integrity_valid ? 'hash подтверждён' : 'ошибка целостности'}</span>
          </div>
        </>
      ) : (
        <p className="empty-state">Quality scan ещё не выполнялся. Запустите первую проверку для формирования baseline.</p>
      )}

      <div className="module-subnav">
        <button type="button" className={`module-subnav-tab ${tab === 'findings' ? 'active' : ''}`} onClick={() => setTab('findings')}>Очередь исправлений</button>
        <button type="button" className={`module-subnav-tab ${tab === 'campaigns' ? 'active' : ''}`} onClick={() => setTab('campaigns')}>Сертификация CI</button>
      </div>

      {tab === 'findings' ? (
        <>
          <div className="quality-filters">
            <label>Статус<select value={findingStatus} onChange={(event) => setFindingStatus(event.target.value)}><option value="OPEN">Открытые</option><option value="RESOLVED">Решённые</option><option value="WAIVED">Исключения</option><option value="ALL">Все</option></select></label>
            <label>Измерение<select value={dimension} onChange={(event) => setDimension(event.target.value)}><option value="ALL">Все</option>{Object.entries(dimensionLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
            <label>Критичность<select value={severity} onChange={(event) => setSeverity(event.target.value)}><option value="ALL">Все</option>{Object.entries(severityLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label>
          </div>
          <div className="quality-finding-list">
            {findingsQuery.isPending ? <p className="loading-state">Загрузка findings…</p> : null}
            {!findingsQuery.isPending && !findingsQuery.isError && !findingsQuery.data?.length ? <p className="empty-state">Findings по выбранному фильтру отсутствуют.</p> : null}
            {findingsQuery.data?.map((finding) => {
              const requiresNote = Boolean(findingNotes[finding.id]?.trim().length && findingNotes[finding.id].trim().length >= 3)
              return (
                <article className={`quality-finding severity-${finding.severity.toLowerCase()} ${finding.overdue ? 'overdue' : ''}`} key={finding.id}>
                  <header>
                    <div>
                      <span>{dimensionLabels[finding.dimension]} · {finding.rule_code}</span>
                      <h3>{finding.title}</h3>
                      <p>{finding.asset_tag ? `${finding.asset_tag} · ${finding.asset_name}` : finding.subject_type}</p>
                    </div>
                    <span className={`impact-severity impact-${finding.severity.toLowerCase()}`}>{severityLabels[finding.severity]}</span>
                  </header>
                  <p>{finding.details}</p>
                  <div className="quality-finding-meta">
                    <span>Владелец: {finding.owner_name ?? 'не назначен'}</span>
                    <span>Срок: {formatDate(finding.due_at, locale)}{finding.overdue ? ' · ПРОСРОЧЕНО' : ''}</span>
                    <span>Возраст: {finding.age_days} дн.</span>
                    <span>Повторений: {finding.occurrence_count}</span>
                  </div>
                  {canManage && ['OPEN', 'IN_PROGRESS'].includes(finding.status) ? (
                    <div className="quality-finding-actions">
                      {!finding.owner_user_id && currentUserId ? <button type="button" className="ghost-button" disabled={findingMutation.isPending} onClick={() => findingMutation.mutate({ finding, takeOwnership: true, status: 'IN_PROGRESS' })}>Взять в работу</button> : null}
                      <input value={findingNotes[finding.id] ?? ''} onChange={(event) => setFindingNotes((state) => ({ ...state, [finding.id]: event.target.value }))} placeholder="Результат исправления или обоснование исключения" />
                      <button type="button" disabled={!requiresNote || findingMutation.isPending} onClick={() => findingMutation.mutate({ finding, status: 'RESOLVED' })}>Закрыть</button>
                      <button type="button" className="ghost-button" disabled={!requiresNote || findingMutation.isPending} onClick={() => findingMutation.mutate({ finding, status: 'WAIVED' })}>Принять исключение</button>
                    </div>
                  ) : null}
                  {finding.resolution_note ? <p className="quality-resolution">Решение: {finding.resolution_note}</p> : null}
                </article>
              )
            })}
          </div>
        </>
      ) : (
        <div className="quality-campaign-layout">
          <div className="quality-campaign-sidebar">
            {canManage ? (
              <form className="quality-campaign-form" onSubmit={(event) => { event.preventDefault(); createCampaignMutation.mutate() }}>
                <h3>Новая кампания</h3>
                <label>Название<input value={campaignName} onChange={(event) => setCampaignName(event.target.value)} required minLength={3} /></label>
                <label>Описание<textarea value={campaignDescription} onChange={(event) => setCampaignDescription(event.target.value)} /></label>
                <label>Срок<input type="date" value={campaignDue} onChange={(event) => setCampaignDue(event.target.value)} required /></label>
                <label>Критичность<select value={campaignCriticality} onChange={(event) => setCampaignCriticality(event.target.value)}><option value="ALL">Все</option>{['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'].map((value) => <option key={value}>{value}</option>)}</select></label>
                <label>Среда<select value={campaignEnvironment} onChange={(event) => setCampaignEnvironment(event.target.value)}><option value="ALL">Все</option>{['PRODUCTION', 'STAGING', 'TEST', 'DEVELOPMENT', 'OTHER'].map((value) => <option key={value}>{value}</option>)}</select></label>
                <label className="checkbox-label"><input type="checkbox" checked={onlyWithoutOwner} onChange={(event) => setOnlyWithoutOwner(event.target.checked)} />Только CI без владельца</label>
                <button type="submit" disabled={campaignName.trim().length < 3 || createCampaignMutation.isPending}>Создать draft</button>
              </form>
            ) : null}
            <div className="quality-campaign-list">
              {campaignsQuery.data?.map((item) => (
                <button type="button" className={selectedCampaignId === item.id ? 'active' : ''} key={item.id} onClick={() => setSelectedCampaignId(item.id)}>
                  <strong>{item.name}</strong>
                  <span>{item.status} · {item.progress_percent}% · до {formatDate(item.due_at, locale)}</span>
                </button>
              ))}
              {!campaignsQuery.isPending && !campaignsQuery.data?.length ? <p className="empty-state">Кампаний пока нет.</p> : null}
            </div>
          </div>
          <div className="quality-campaign-detail">
            {!selectedCampaignId ? <p className="empty-state">Выберите кампанию или создайте новую.</p> : null}
            {campaignQuery.isPending ? <p className="loading-state">Загрузка кампании…</p> : null}
            {campaign ? (
              <>
                <div className="section-header">
                  <div><p className="eyebrow">{campaign.status}</p><h3>{campaign.name}</h3><p>{campaign.description ?? 'Без описания'}</p></div>
                  <div className="quality-campaign-actions">
                    {canManage && campaign.status === 'DRAFT' ? <button type="button" disabled={activateMutation.isPending} onClick={() => activateMutation.mutate(campaign)}>Запустить</button> : null}
                    {canManage && campaign.status === 'ACTIVE' && campaign.pending_items === 0 ? <button type="button" disabled={completeMutation.isPending} onClick={() => completeMutation.mutate(campaign)}>Завершить</button> : null}
                  </div>
                </div>
                <div className="quality-queue-strip">
                  <span><strong>{campaign.total_items}</strong> CI</span>
                  <span><strong>{campaign.pending_items}</strong> ожидают</span>
                  <span><strong>{campaign.certified_items}</strong> подтверждено</span>
                  <span><strong>{campaign.rejected_items}</strong> отклонено</span>
                  <span>Срок {formatDate(campaign.due_at, locale)}</span>
                </div>
                <div className="certification-item-list">
                  {campaign.items?.map((item) => {
                    const noteReady = (decisionNotes[item.id]?.trim().length ?? 0) >= 3
                    return (
                      <article key={item.id} className={item.asset_changed ? 'stale' : ''}>
                        <div>
                          <strong>{item.asset_tag} · {item.asset_name}</strong>
                          <span>{item.status} · certifier: {item.certifier_name ?? 'не назначен'} · CI v{item.asset_version} · {item.integrity_valid ? 'hash подтверждён' : 'ошибка hash'}</span>
                          {item.asset_changed ? <span className="error-message">CI изменился после запуска кампании (сейчас v{item.current_asset_version})</span> : null}
                          {!item.integrity_valid ? <span className="error-message">Нарушена целостность snapshot — подтверждение заблокировано.</span> : null}
                        </div>
                        {item.status === 'PENDING' && canScan ? (
                          <div className="certification-actions">
                            <input value={decisionNotes[item.id] ?? ''} onChange={(event) => setDecisionNotes((state) => ({ ...state, [item.id]: event.target.value }))} placeholder="Доказательство проверки / причина отклонения" />
                            <button type="button" disabled={!noteReady || item.asset_changed || !item.integrity_valid || decisionMutation.isPending} onClick={() => decisionMutation.mutate({ campaign, item, decision: 'CERTIFIED' })}>Подтвердить</button>
                            <button type="button" className="danger-button" disabled={!noteReady || decisionMutation.isPending} onClick={() => decisionMutation.mutate({ campaign, item, decision: 'REJECTED' })}>Отклонить</button>
                          </div>
                        ) : item.decision_note ? <span>{item.decision_note}</span> : null}
                      </article>
                    )
                  })}
                </div>
              </>
            ) : null}
          </div>
        </div>
      )}
    </section>
    </LocalizedContent>
  )
}
