import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  assignAsset,
  commitAssetImport,
  type Asset,
  type AssetDetail,
  type AssetHistory,
  type AssetHistoryFeedItem,
  disposeAsset,
  fetchAssetById,
  fetchAssetHistory,
  fetchAssetHistoryFeed,
  fetchAssetImportBatches,
  fetchAssetImportRows,
  fetchAssetsPage,
  moveAsset,
  previewAssetImport,
  restoreAsset,
  uploadAssetImport,
  verifyAsset,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'


type AssetsMode = 'registry' | 'import' | 'inventory' | 'rooms' | 'responsible' | 'disposal' | 'history'
type DetailTab = 'overview' | 'accounting' | 'location' | 'responsible' | 'tickets' | 'history'
type ActionModalType = 'move' | 'assign' | 'verify' | 'dispose' | 'restore' | null

const statusRu: Record<string, string> = {
  active: 'Активный',
  inactive: 'Неактивный',
  disposed: 'Списан',
  in_stock: 'В запасах',
  in_use: 'В эксплуатации',
  in_repair: 'В ремонте',
  maintenance: 'На обслуживании',
  broken: 'Неисправен',
}

const verificationRu: Record<string, string> = {
  verified: 'Проверено',
  pending: 'Ожидает проверки',
  needs_location: 'Требует кабинета',
  failed: 'Ошибка',
  unknown: 'Неизвестно',
}

const sourceRu: Record<string, string> = {
  excel_import: 'Импорт Excel',
}

function ruStatus(value: string | null | undefined) {
  const key = String(value ?? '').toLowerCase()
  if (!key) return '—'
  return statusRu[key] ?? value ?? '—'
}

function ruVerification(value: string | null | undefined) {
  const key = String(value ?? '').toLowerCase()
  if (!key) return '—'
  return verificationRu[key] ?? value ?? '—'
}

function ruSource(value: string | null | undefined) {
  const key = String(value ?? '').toLowerCase()
  if (!key) return 'manual'
  return sourceRu[key] ?? value ?? 'manual'
}

function roomLabel(asset: Asset) {
  if (asset.room && asset.room.trim()) return asset.room
  return 'Кабинет не указан'
}

function formatMoney(value: number | null | undefined) {
  if (value == null) return '—'
  return new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 }).format(value)
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium' }).format(new Date(value))
}

export default function AssetsPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()

  const [activeMode, setActiveMode] = useState<AssetsMode>('registry')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(50)

  const [typeFilter, setTypeFilter] = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [roomFilter, setRoomFilter] = useState('ALL')
  const [responsibleFilter, setResponsibleFilter] = useState('ALL')
  const [molFilter, setMolFilter] = useState('ALL')
  const [yearFilter, setYearFilter] = useState('ALL')
  const [sourceFilter, setSourceFilter] = useState('ALL')
  const [verificationFilter, setVerificationFilter] = useState('ALL')

  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null)
  const [detailTab, setDetailTab] = useState<DetailTab>('overview')

  const [actionModalType, setActionModalType] = useState<ActionModalType>(null)
  const [actionAssetId, setActionAssetId] = useState<string | null>(null)

  const [moveForm, setMoveForm] = useState({ building: '', floor: '', room: '', location_label: '', comment: '' })
  const [assignForm, setAssignForm] = useState({ responsible_person_name: '', responsible_department: '', mol_name: '', mol_department: '', comment: '' })
  const [verifyForm, setVerifyForm] = useState({ verification_status: 'verified', comment: '' })
  const [disposeForm, setDisposeForm] = useState({ writeoff_reason: '', comment: '', confirm: false })
  const [restoreComment, setRestoreComment] = useState('')

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)

  const [historyAction, setHistoryAction] = useState('ALL')
  const [historyActor, setHistoryActor] = useState('')
  const [historyAsset, setHistoryAsset] = useState('')
  const [historyDateFrom, setHistoryDateFrom] = useState('')
  const [historyDateTo, setHistoryDateTo] = useState('')

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSearch(search.trim())
      setPage(1)
    }, 250)
    return () => window.clearTimeout(timer)
  }, [search])

  const assetsQuery = useQuery({
    queryKey: [
      'assets',
      session?.access_token,
      debouncedSearch,
      typeFilter,
      statusFilter,
      roomFilter,
      responsibleFilter,
      molFilter,
      yearFilter,
      sourceFilter,
      verificationFilter,
      page,
      pageSize,
    ],
    queryFn: () =>
      fetchAssetsPage(session?.access_token ?? '', {
        q: debouncedSearch || undefined,
        asset_type: typeFilter,
        status: statusFilter,
        room: roomFilter,
        responsible_person_name: responsibleFilter,
        mol_name: molFilter,
        purchase_year: yearFilter === 'ALL' ? undefined : Number(yearFilter),
        source: sourceFilter,
        verification_status: verificationFilter,
        page,
        page_size: pageSize,
      }),
    enabled: Boolean(session?.access_token),
  })

  const detailQuery = useQuery({
    queryKey: ['asset-detail', session?.access_token, selectedAssetId],
    queryFn: () => fetchAssetById(session?.access_token ?? '', selectedAssetId ?? ''),
    enabled: Boolean(session?.access_token && selectedAssetId),
  })

  const detailHistoryQuery = useQuery({
    queryKey: ['asset-history', session?.access_token, selectedAssetId],
    queryFn: () => fetchAssetHistory(session?.access_token ?? '', selectedAssetId ?? ''),
    enabled: Boolean(session?.access_token && selectedAssetId),
  })

  const historyFeedQuery = useQuery({
    queryKey: ['asset-history-feed', session?.access_token, historyAction, historyActor, historyAsset, historyDateFrom, historyDateTo],
    queryFn: () =>
      fetchAssetHistoryFeed(session?.access_token ?? '', {
        action: historyAction,
        actor: historyActor || undefined,
        asset_q: historyAsset || undefined,
        date_from: historyDateFrom ? new Date(historyDateFrom).toISOString() : undefined,
        date_to: historyDateTo ? new Date(historyDateTo).toISOString() : undefined,
        limit: 200,
      }),
    enabled: Boolean(session?.access_token) && activeMode === 'history',
  })

  const batchesQuery = useQuery({
    queryKey: ['asset-import-batches', session?.access_token],
    queryFn: () => fetchAssetImportBatches(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token) && activeMode === 'import',
  })

  const rowsQuery = useQuery({
    queryKey: ['asset-import-rows', session?.access_token, activeBatchId],
    queryFn: () => fetchAssetImportRows(session?.access_token ?? '', activeBatchId ?? ''),
    enabled: Boolean(session?.access_token && activeBatchId) && activeMode === 'import',
  })

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => uploadAssetImport(session?.access_token ?? '', file),
    onSuccess: async (batch) => {
      setActiveBatchId(batch.id)
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
    },
  })

  const previewMutation = useMutation({
    mutationFn: async (batchId: string) => previewAssetImport(session?.access_token ?? '', { batch_id: batchId, dry_run: true }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-import-rows'] })
    },
  })

  const commitMutation = useMutation({
    mutationFn: async (batchId: string) => commitAssetImport(session?.access_token ?? '', batchId, { dry_run: false }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-import-rows'] })
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
    },
  })

  const moveMutation = useMutation({
    mutationFn: async (assetId: string) => moveAsset(session?.access_token ?? '', assetId, moveForm),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const assignMutation = useMutation({
    mutationFn: async (assetId: string) => assignAsset(session?.access_token ?? '', assetId, assignForm),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const verifyMutation = useMutation({
    mutationFn: async (assetId: string) => verifyAsset(session?.access_token ?? '', assetId, verifyForm),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const disposeMutation = useMutation({
    mutationFn: async (assetId: string) => disposeAsset(session?.access_token ?? '', assetId, { writeoff_reason: disposeForm.writeoff_reason, comment: disposeForm.comment }),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const restoreMutation = useMutation({
    mutationFn: async (assetId: string) => restoreAsset(session?.access_token ?? '', assetId, { comment: restoreComment }),
    onSuccess: async () => {
      setActionModalType(null)
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-detail', session?.access_token, actionAssetId] })
      await queryClient.invalidateQueries({ queryKey: ['asset-history-feed'] })
    },
  })

  const assets = assetsQuery.data?.items ?? []
  const total = assetsQuery.data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const selectedAsset: AssetDetail | null = detailQuery.data ?? null
  const selectedAssetHistory: AssetHistory[] = detailHistoryQuery.data ?? []
  const historyFeed: AssetHistoryFeedItem[] = historyFeedQuery.data ?? []
  const activeBatch = (batchesQuery.data ?? []).find((item) => item.id === activeBatchId)

  useEffect(() => {
    if (!activeBatchId && batchesQuery.data?.length) {
      setActiveBatchId(batchesQuery.data[0].id)
    }
  }, [activeBatchId, batchesQuery.data])

  const typeOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.asset_type))).sort()], [assets])
  const statusOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.status))).sort()], [assets])
  const roomOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => roomLabel(a)))).sort()], [assets])
  const responsibleOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.responsible_person_name).filter(Boolean) as string[])).sort()], [assets])
  const molOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.mol_name).filter(Boolean) as string[])).sort()], [assets])
  const yearOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.purchase_year).filter((v): v is number => typeof v === 'number'))).sort((a, b) => b - a).map(String)], [assets])
  const sourceOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.source ?? 'manual'))).sort()], [assets])
  const verificationOptions = useMemo(() => ['ALL', ...Array.from(new Set(assets.map((a) => a.verification_status).filter(Boolean) as string[])).sort()], [assets])

  const inventoryStats = useMemo(() => {
    const verified = assets.filter((a) => (a.verification_status ?? '').toLowerCase() === 'verified').length
    const needsLocation = assets.filter((a) => (a.verification_status ?? '').toLowerCase() === 'needs_location').length
    const needsVerification = assets.filter((a) => ['pending', 'unknown', 'needs_location'].includes((a.verification_status ?? '').toLowerCase())).length
    const disposed = assets.filter((a) => (a.status ?? '').toLowerCase() === 'disposed').length
    const excel = assets.filter((a) => (a.source ?? '').toLowerCase() === 'excel_import').length
    const withoutMol = assets.filter((a) => !(a.mol_name && a.mol_name.trim())).length
    const withoutRoom = assets.filter((a) => roomLabel(a) === 'Кабинет не указан').length
    return { verified, needsLocation, needsVerification, disposed, excel, withoutMol, withoutRoom }
  }, [assets])

  const roomsGroups = useMemo(() => {
    const map = new Map<string, Asset[]>()
    for (const asset of assets) {
      const key = roomLabel(asset)
      if (!map.has(key)) map.set(key, [])
      map.get(key)?.push(asset)
    }
    return Array.from(map.entries()).map(([room, items]) => {
      const types = Array.from(new Set(items.map((a) => a.asset_type))).join(', ')
      const responsibles = Array.from(new Set(items.map((a) => a.responsible_person_name).filter(Boolean) as string[])).join(', ')
      return {
        room,
        count: items.length,
        types,
        responsibles: responsibles || '—',
        needsVerification: items.filter((a) => ['pending', 'unknown', 'needs_location'].includes((a.verification_status ?? '').toLowerCase())).length,
      }
    }).sort((a, b) => b.count - a.count)
  }, [assets])

  const responsibleGroups = useMemo(() => {
    const map = new Map<string, Asset[]>()
    for (const asset of assets) {
      const key = asset.responsible_person_name || asset.mol_name || 'Не назначен'
      if (!map.has(key)) map.set(key, [])
      map.get(key)?.push(asset)
    }
    return Array.from(map.entries()).map(([responsible, items]) => ({
      responsible,
      department: items[0]?.responsible_department || items[0]?.mol_department || '—',
      count: items.length,
      residual: items.reduce((sum, item) => sum + Number(item.residual_cost ?? item.residual_value ?? 0), 0),
      withoutRoom: items.filter((item) => roomLabel(item) === 'Кабинет не указан').length,
      disposed: items.filter((item) => (item.status ?? '').toLowerCase() === 'disposed').length,
    })).sort((a, b) => b.count - a.count)
  }, [assets])

  const disposedAssets = useMemo(() => assets.filter((a) => (a.status ?? '').toLowerCase() === 'disposed'), [assets])

  const openActionModal = (type: ActionModalType, assetId: string) => {
    setActionAssetId(assetId)
    setActionModalType(type)
  }

  const closeActionModal = () => {
    setActionModalType(null)
    setActionAssetId(null)
    setDisposeForm({ writeoff_reason: '', comment: '', confirm: false })
  }

  const closeDetail = () => {
    setSelectedAssetId(null)
    setDetailTab('overview')
  }

  return (
    <AppShell title="Активы" subtitle="Реестр оборудования, импорт Excel, закрепление, кабинеты и состояние активов.">
      <nav className="module-subnav" aria-label="Assets navigation">
        <button type="button" className={`module-subnav-tab ${activeMode === 'registry' ? 'active' : ''}`} onClick={() => setActiveMode('registry')}>Реестр активов</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'import' ? 'active' : ''}`} onClick={() => setActiveMode('import')}>Импорт Excel</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'inventory' ? 'active' : ''}`} onClick={() => setActiveMode('inventory')}>Инвентаризация</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'rooms' ? 'active' : ''}`} onClick={() => setActiveMode('rooms')}>Кабинеты</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'responsible' ? 'active' : ''}`} onClick={() => setActiveMode('responsible')}>Ответственные</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'disposal' ? 'active' : ''}`} onClick={() => setActiveMode('disposal')}>Списание</button>
        <button type="button" className={`module-subnav-tab ${activeMode === 'history' ? 'active' : ''}`} onClick={() => setActiveMode('history')}>История</button>
      </nav>

      {activeMode === 'registry' ? (
        <>
          <section className="foundation-card table-toolbar">
            <div className="table-filters" style={{ gridTemplateColumns: 'repeat(6, minmax(0,1fr))' }}>
              <label className="inline-field"><span>Поиск</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Инв. №, имя, серийный номер" /></label>
              <label className="inline-field"><span>Тип</span><select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>{typeOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>Статус</span><select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>{statusOptions.map((item) => <option key={item} value={item}>{ruStatus(item)}</option>)}</select></label>
              <label className="inline-field"><span>Кабинет</span><select value={roomFilter} onChange={(event) => setRoomFilter(event.target.value)}>{roomOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>Ответственный</span><select value={responsibleFilter} onChange={(event) => setResponsibleFilter(event.target.value)}>{responsibleOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>МОЛ</span><select value={molFilter} onChange={(event) => setMolFilter(event.target.value)}>{molOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>Год покупки</span><select value={yearFilter} onChange={(event) => setYearFilter(event.target.value)}>{yearOptions.map((item) => <option key={item} value={item}>{item}</option>)}</select></label>
              <label className="inline-field"><span>Источник</span><select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>{sourceOptions.map((item) => <option key={item} value={item}>{ruSource(item)}</option>)}</select></label>
              <label className="inline-field"><span>Проверка</span><select value={verificationFilter} onChange={(event) => setVerificationFilter(event.target.value)}>{verificationOptions.map((item) => <option key={item} value={item}>{ruVerification(item)}</option>)}</select></label>
              <label className="inline-field"><span>page_size</span><select value={String(pageSize)} onChange={(event) => { setPageSize(Number(event.target.value)); setPage(1) }}><option value="25">25</option><option value="50">50</option><option value="100">100</option></select></label>
            </div>
          </section>

          <section className="section-card">
            <div className="ticket-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Инв. №</th><th>Наименование</th><th>Тип</th><th>Статус</th><th>Кабинет</th><th>Ответственный</th><th>МОЛ</th><th>Остаточная стоимость</th><th>Проверка</th><th>Источник</th><th>Действия</th>
                  </tr>
                </thead>
                <tbody>
                  {assetsQuery.isPending ? <tr><td colSpan={11}><p className="loading-state">Загрузка данных...</p></td></tr> : null}
                  {!assetsQuery.isPending && assets.length === 0 ? <tr><td colSpan={11}><p className="empty-state">Данных пока нет.</p></td></tr> : null}
                  {assets.map((asset) => (
                    <tr key={asset.id}>
                      <td>{asset.inventory_number ?? asset.asset_tag}</td>
                      <td>{asset.name}</td>
                      <td>{asset.asset_type}</td>
                      <td>{ruStatus(asset.status)}</td>
                      <td>{roomLabel(asset)}</td>
                      <td>{asset.responsible_person_name ?? '—'}</td>
                      <td>{asset.mol_name ?? '—'}</td>
                      <td>{formatMoney(asset.residual_cost ?? asset.residual_value)}</td>
                      <td>{ruVerification(asset.verification_status)}</td>
                      <td>{ruSource(asset.source)}</td>
                      <td>
                        <div className="analytics-actions">
                          <button type="button" className="ghost-button" onClick={() => setSelectedAssetId(asset.id)}>Детали</button>
                          <button type="button" className="ghost-button" onClick={() => openActionModal('move', asset.id)}>Переместить</button>
                          <button type="button" className="ghost-button" onClick={() => openActionModal('assign', asset.id)}>Закрепить</button>
                          <button type="button" className="ghost-button" onClick={() => openActionModal('verify', asset.id)}>Проверить</button>
                          <button type="button" className="ghost-button" onClick={() => openActionModal('dispose', asset.id)}>Списать</button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="table-pagination">
              <p className="muted">Показано {assets.length} из {total}</p>
              <div className="analytics-actions">
                <button type="button" className="ghost-button" disabled={page <= 1} onClick={() => setPage((v) => Math.max(1, v - 1))}>Назад</button>
                <span className="muted">Страница {page} / {totalPages}</span>
                <button type="button" className="ghost-button" disabled={page >= totalPages} onClick={() => setPage((v) => Math.min(totalPages, v + 1))}>Вперед</button>
              </div>
            </div>
          </section>
        </>
      ) : null}

      {activeMode === 'inventory' ? (
        <>
          <section className="module-overview-grid">
            <article className="metric-card"><span>Всего активов</span><strong>{assets.length}</strong></article>
            <article className="metric-card"><span>Проверено</span><strong>{inventoryStats.verified}</strong></article>
            <article className="metric-card"><span>Требует кабинета</span><strong>{inventoryStats.needsLocation}</strong></article>
            <article className="metric-card"><span>Требует проверки</span><strong>{inventoryStats.needsVerification}</strong></article>
            <article className="metric-card"><span>Списано</span><strong>{inventoryStats.disposed}</strong></article>
            <article className="metric-card"><span>Импорт Excel</span><strong>{inventoryStats.excel}</strong></article>
            <article className="metric-card"><span>Активы без МОЛ</span><strong>{inventoryStats.withoutMol}</strong></article>
            <article className="metric-card"><span>Активы без кабинета</span><strong>{inventoryStats.withoutRoom}</strong></article>
          </section>
          <section className="section-card">
            <header className="section-header"><h3 className="section-title">Быстрые фильтры</h3></header>
            <div className="analytics-actions">
              <button type="button" className="ghost-button" onClick={() => { setRoomFilter('Кабинет не указан'); setActiveMode('registry') }}>Требует кабинета</button>
              <button type="button" className="ghost-button" onClick={() => { setVerificationFilter('pending'); setActiveMode('registry') }}>Требует проверки</button>
              <button type="button" className="ghost-button" onClick={() => { setMolFilter('ALL'); setActiveMode('registry') }}>Без МОЛ</button>
              <button type="button" className="ghost-button" onClick={() => { setStatusFilter('disposed'); setActiveMode('registry') }}>Списанные</button>
              <button type="button" className="ghost-button" onClick={() => { setSourceFilter('excel_import'); setActiveMode('registry') }}>Импорт Excel</button>
            </div>
          </section>
        </>
      ) : null}

      {activeMode === 'rooms' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Группировка по кабинетам</h3></header>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Кабинет</th><th>Количество активов</th><th>Ответственные</th><th>Типы оборудования</th><th>Требует проверки</th><th>Действие</th></tr></thead>
              <tbody>
                {roomsGroups.map((item) => (
                  <tr key={item.room}>
                    <td>{item.room}</td>
                    <td>{item.count}</td>
                    <td>{item.responsibles}</td>
                    <td>{item.types || '—'}</td>
                    <td>{item.needsVerification}</td>
                    <td><button type="button" className="ghost-button" onClick={() => { setRoomFilter(item.room); setActiveMode('registry') }}>Показать активы</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeMode === 'responsible' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Группировка по ответственным</h3></header>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Ответственный</th><th>Подразделение</th><th>Количество активов</th><th>Общая остаточная стоимость</th><th>Активы без кабинета</th><th>Списанные</th><th>Действие</th></tr></thead>
              <tbody>
                {responsibleGroups.map((item) => (
                  <tr key={item.responsible}>
                    <td>{item.responsible}</td>
                    <td>{item.department}</td>
                    <td>{item.count}</td>
                    <td>{formatMoney(item.residual)}</td>
                    <td>{item.withoutRoom}</td>
                    <td>{item.disposed}</td>
                    <td><button type="button" className="ghost-button" onClick={() => { setResponsibleFilter(item.responsible); setActiveMode('registry') }}>Показать активы</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeMode === 'disposal' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Списанные активы</h3></header>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Инв. №</th><th>Наименование</th><th>Дата списания</th><th>Причина</th><th>Остаточная стоимость</th><th>Ответственный</th><th>Действие</th></tr></thead>
              <tbody>
                {disposedAssets.map((asset) => (
                  <tr key={asset.id}>
                    <td>{asset.inventory_number ?? asset.asset_tag}</td>
                    <td>{asset.name}</td>
                    <td>{formatDate(asset.writeoff_date ?? asset.disposed_at)}</td>
                    <td>{asset.writeoff_reason ?? '—'}</td>
                    <td>{formatMoney(asset.residual_cost ?? asset.residual_value)}</td>
                    <td>{asset.responsible_person_name ?? '—'}</td>
                    <td><button type="button" className="ghost-button" onClick={() => openActionModal('restore', asset.id)}>Восстановить</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeMode === 'history' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">История активов</h3></header>
          <div className="table-filters" style={{ gridTemplateColumns: 'repeat(5, minmax(0,1fr))' }}>
            <label className="inline-field"><span>action</span><select value={historyAction} onChange={(event) => setHistoryAction(event.target.value)}><option value="ALL">Все</option><option value="asset_updated">asset_updated</option><option value="asset_moved">asset_moved</option><option value="asset_assigned">asset_assigned</option><option value="asset_verified">asset_verified</option><option value="asset_disposed">asset_disposed</option><option value="asset_restored">asset_restored</option></select></label>
            <label className="inline-field"><span>actor</span><input value={historyActor} onChange={(event) => setHistoryActor(event.target.value)} placeholder="email или ФИО" /></label>
            <label className="inline-field"><span>asset</span><input value={historyAsset} onChange={(event) => setHistoryAsset(event.target.value)} placeholder="имя/инв.№" /></label>
            <label className="inline-field"><span>date_from</span><input type="date" value={historyDateFrom} onChange={(event) => setHistoryDateFrom(event.target.value)} /></label>
            <label className="inline-field"><span>date_to</span><input type="date" value={historyDateTo} onChange={(event) => setHistoryDateTo(event.target.value)} /></label>
          </div>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Дата</th><th>Action</th><th>Asset</th><th>Actor</th><th>Комментарий</th></tr></thead>
              <tbody>
                {historyFeedQuery.isPending ? <tr><td colSpan={5}><p className="loading-state">Загрузка данных...</p></td></tr> : null}
                {!historyFeedQuery.isPending && historyFeed.length === 0 ? <tr><td colSpan={5}><p className="empty-state">Данных пока нет.</p></td></tr> : null}
                {historyFeed.map((item) => (
                  <tr key={item.id}>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.action}</td>
                    <td>{item.asset_name ?? '—'} · {item.inventory_number ?? '—'}</td>
                    <td>{item.actor_email ?? '—'}</td>
                    <td>{item.comment ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {activeMode === 'import' ? (
        <section className="section-card">
          <header className="section-header"><h3 className="section-title">Импорт Excel</h3><p className="section-subtitle">Upload → preview → commit. Существующие импортированные активы не удаляются.</p></header>
          <div className="analytics-actions">
            <input type="file" accept=".xlsx" onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)} />
            <button type="button" onClick={async () => {
              if (!selectedFile) return
              const batch = await uploadMutation.mutateAsync(selectedFile)
              await previewMutation.mutateAsync(batch.id)
            }} disabled={!selectedFile || uploadMutation.isPending || previewMutation.isPending}>Загрузить и проверить</button>
            <button type="button" className="ghost-button" onClick={() => { if (activeBatchId) previewMutation.mutate(activeBatchId) }} disabled={!activeBatchId || previewMutation.isPending}>Обновить preview</button>
            <button type="button" className="ghost-button" onClick={() => { if (activeBatchId) commitMutation.mutate(activeBatchId) }} disabled={!activeBatchId || commitMutation.isPending}>Импортировать валидные</button>
          </div>
          <p className="muted">Batch: {activeBatchId ?? '—'} · Статус: {activeBatch?.status ?? '—'}</p>
          <div className="ticket-table-wrap">
            <table className="ticket-table">
              <thead><tr><th>Строка</th><th>Инв. №</th><th>Наименование</th><th>Статус</th><th>Ошибка</th></tr></thead>
              <tbody>
                {(rowsQuery.data ?? []).map((row) => (
                  <tr key={row.id}>
                    <td>{row.row_number}</td>
                    <td>{String(row.normalized.inventory_number ?? '—')}</td>
                    <td>{String(row.normalized.name ?? '—')}</td>
                    <td>{row.status}</td>
                    <td>{row.error_message ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}

      {selectedAssetId ? (
        <div className="modal-backdrop" role="presentation" onClick={closeDetail}>
          <section className="modal-card modal-card-xl" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <p className="eyebrow">КАРТОЧКА ОБОРУДОВАНИЯ</p>
                <h2>{selectedAsset?.name ?? 'Загрузка...'}</h2>
                <p className="modal-subtitle">{selectedAsset?.inventory_number ?? selectedAsset?.asset_tag ?? '—'} · {ruStatus(selectedAsset?.status)}</p>
              </div>
              <button type="button" className="ghost-button" onClick={closeDetail}>Закрыть</button>
            </div>

            <nav className="module-subnav">
              <button type="button" className={`module-subnav-tab ${detailTab === 'overview' ? 'active' : ''}`} onClick={() => setDetailTab('overview')}>Обзор</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'accounting' ? 'active' : ''}`} onClick={() => setDetailTab('accounting')}>Учёт</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'location' ? 'active' : ''}`} onClick={() => setDetailTab('location')}>Локация</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'responsible' ? 'active' : ''}`} onClick={() => setDetailTab('responsible')}>Ответственные</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'tickets' ? 'active' : ''}`} onClick={() => setDetailTab('tickets')}>Заявки</button>
              <button type="button" className={`module-subnav-tab ${detailTab === 'history' ? 'active' : ''}`} onClick={() => setDetailTab('history')}>История</button>
            </nav>

            {detailTab === 'overview' ? (
              <div className="detail-fields">
                <div><span>Тип</span><strong>{selectedAsset?.asset_type ?? '—'}</strong></div>
                <div><span>Статус</span><strong>{ruStatus(selectedAsset?.status)}</strong></div>
                <div><span>Источник</span><strong>{ruSource(selectedAsset?.source)}</strong></div>
                <div><span>Дата импорта</span><strong>{formatDateTime(selectedAsset?.imported_at)}</strong></div>
                <div><span>notes</span><strong>{selectedAsset?.notes ?? selectedAsset?.description ?? '—'}</strong></div>
              </div>
            ) : null}

            {detailTab === 'accounting' ? (
              <div className="detail-fields">
                <div><span>purchase_date</span><strong>{formatDate(selectedAsset?.purchase_date)}</strong></div>
                <div><span>purchase_year</span><strong>{selectedAsset?.purchase_year ?? '—'}</strong></div>
                <div><span>initial_cost</span><strong>{formatMoney(selectedAsset?.initial_cost)}</strong></div>
                <div><span>depreciation_amount</span><strong>{formatMoney(selectedAsset?.depreciation_amount)}</strong></div>
                <div><span>residual_cost</span><strong>{formatMoney(selectedAsset?.residual_cost ?? selectedAsset?.residual_value)}</strong></div>
                <div><span>writeoff</span><strong>{formatDate(selectedAsset?.writeoff_date)} · {selectedAsset?.writeoff_reason ?? '—'}</strong></div>
              </div>
            ) : null}

            {detailTab === 'location' ? (
              <div className="detail-fields">
                <div><span>building</span><strong>{selectedAsset?.building ?? '—'}</strong></div>
                <div><span>floor</span><strong>{selectedAsset?.floor ?? '—'}</strong></div>
                <div><span>room</span><strong>{selectedAsset?.room ?? 'Кабинет не указан'}</strong></div>
                <div><span>location_label</span><strong>{selectedAsset?.location_label ?? '—'}</strong></div>
                <div><span>location_verified_at</span><strong>{formatDateTime(selectedAsset?.location_verified_at)}</strong></div>
              </div>
            ) : null}

            {detailTab === 'responsible' ? (
              <div className="detail-fields">
                <div><span>responsible_person_name</span><strong>{selectedAsset?.responsible_person_name ?? '—'}</strong></div>
                <div><span>responsible_department</span><strong>{selectedAsset?.responsible_department ?? '—'}</strong></div>
                <div><span>mol_name</span><strong>{selectedAsset?.mol_name ?? '—'}</strong></div>
                <div><span>mol_department</span><strong>{selectedAsset?.mol_department ?? '—'}</strong></div>
              </div>
            ) : null}

            {detailTab === 'tickets' ? (
              <div className="activity-list">
                {(selectedAsset?.linked_tickets_summary ?? []).length === 0 ? <p className="empty-state">Связанных заявок нет.</p> : null}
                {(selectedAsset?.linked_tickets_summary ?? []).map((item) => (
                  <article className="activity-item" key={item.id}>
                    <header><strong>{item.ticket_number ?? item.id}</strong><span>{item.status}</span></header>
                    <p>{item.title}</p>
                  </article>
                ))}
              </div>
            ) : null}

            {detailTab === 'history' ? (
              <div className="activity-list">
                {selectedAssetHistory.length === 0 ? <p className="empty-state">История актива пока пуста.</p> : null}
                {selectedAssetHistory.map((item) => (
                  <article className="activity-item" key={item.id}>
                    <header><strong>{item.action}</strong><span>{formatDateTime(item.created_at)}</span></header>
                    <p>{item.comment ?? '—'}</p>
                  </article>
                ))}
              </div>
            ) : null}
          </section>
        </div>
      ) : null}

      {actionModalType ? (
        <div className="modal-backdrop" role="presentation" onClick={closeActionModal}>
          <section className="modal-card" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h2>
                {actionModalType === 'move' ? 'Переместить' : null}
                {actionModalType === 'assign' ? 'Закрепить' : null}
                {actionModalType === 'verify' ? 'Проверить' : null}
                {actionModalType === 'dispose' ? 'Списать' : null}
                {actionModalType === 'restore' ? 'Восстановить' : null}
              </h2>
              <button type="button" className="ghost-button" onClick={closeActionModal}>Закрыть</button>
            </div>

            {actionModalType === 'move' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId) moveMutation.mutate(actionAssetId) }}>
                <label><span>building</span><input value={moveForm.building} onChange={(event) => setMoveForm((s) => ({ ...s, building: event.target.value }))} /></label>
                <label><span>floor</span><input value={moveForm.floor} onChange={(event) => setMoveForm((s) => ({ ...s, floor: event.target.value }))} /></label>
                <label><span>room</span><input value={moveForm.room} onChange={(event) => setMoveForm((s) => ({ ...s, room: event.target.value }))} /></label>
                <label><span>location_label</span><input value={moveForm.location_label} onChange={(event) => setMoveForm((s) => ({ ...s, location_label: event.target.value }))} /></label>
                <label><span>comment</span><textarea value={moveForm.comment} onChange={(event) => setMoveForm((s) => ({ ...s, comment: event.target.value }))} /></label>
                <button type="submit" disabled={moveMutation.isPending}>Сохранить</button>
              </form>
            ) : null}

            {actionModalType === 'assign' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId) assignMutation.mutate(actionAssetId) }}>
                <label><span>responsible_person_name</span><input value={assignForm.responsible_person_name} onChange={(event) => setAssignForm((s) => ({ ...s, responsible_person_name: event.target.value }))} required /></label>
                <label><span>responsible_department</span><input value={assignForm.responsible_department} onChange={(event) => setAssignForm((s) => ({ ...s, responsible_department: event.target.value }))} /></label>
                <label><span>mol_name</span><input value={assignForm.mol_name} onChange={(event) => setAssignForm((s) => ({ ...s, mol_name: event.target.value }))} /></label>
                <label><span>mol_department</span><input value={assignForm.mol_department} onChange={(event) => setAssignForm((s) => ({ ...s, mol_department: event.target.value }))} /></label>
                <label><span>comment</span><textarea value={assignForm.comment} onChange={(event) => setAssignForm((s) => ({ ...s, comment: event.target.value }))} /></label>
                <button type="submit" disabled={assignMutation.isPending}>Сохранить</button>
              </form>
            ) : null}

            {actionModalType === 'verify' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId) verifyMutation.mutate(actionAssetId) }}>
                <label><span>verification_status</span><select value={verifyForm.verification_status} onChange={(event) => setVerifyForm((s) => ({ ...s, verification_status: event.target.value }))}><option value="verified">verified</option><option value="pending">pending</option><option value="needs_location">needs_location</option><option value="failed">failed</option></select></label>
                <label><span>comment</span><textarea value={verifyForm.comment} onChange={(event) => setVerifyForm((s) => ({ ...s, comment: event.target.value }))} /></label>
                <button type="submit" disabled={verifyMutation.isPending}>Сохранить</button>
              </form>
            ) : null}

            {actionModalType === 'dispose' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId && disposeForm.confirm) disposeMutation.mutate(actionAssetId) }}>
                <label><span>writeoff_reason</span><input value={disposeForm.writeoff_reason} onChange={(event) => setDisposeForm((s) => ({ ...s, writeoff_reason: event.target.value }))} required /></label>
                <label><span>comment</span><textarea value={disposeForm.comment} onChange={(event) => setDisposeForm((s) => ({ ...s, comment: event.target.value }))} /></label>
                <label><span><input type="checkbox" checked={disposeForm.confirm} onChange={(event) => setDisposeForm((s) => ({ ...s, confirm: event.target.checked }))} /> Подтверждаю списание</span></label>
                <button type="submit" disabled={disposeMutation.isPending || !disposeForm.confirm}>Списать</button>
              </form>
            ) : null}

            {actionModalType === 'restore' ? (
              <form className="modal-form" onSubmit={(event) => { event.preventDefault(); if (actionAssetId) restoreMutation.mutate(actionAssetId) }}>
                <label><span>comment</span><textarea value={restoreComment} onChange={(event) => setRestoreComment(event.target.value)} /></label>
                <button type="submit" disabled={restoreMutation.isPending}>Восстановить</button>
              </form>
            ) : null}
          </section>
        </div>
      ) : null}
    </AppShell>
  )
}
