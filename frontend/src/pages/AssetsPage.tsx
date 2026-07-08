import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  commitAssetImport,
  fetchAsset,
  fetchAssetImportBatches,
  fetchAssetImportRows,
  fetchAssetImportSummary,
  fetchAssetTickets,
  fetchAssets,
  previewAssetImport,
  uploadAssetImport,
  type AssetImportRow,
  type AssetTicket,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import HealthBadge from '../components/HealthBadge'

const statusLabels: Record<string, string> = {
  in_use: 'В эксплуатации',
  in_stock: 'На складе',
  in_repair: 'В ремонте',
  maintenance: 'На обслуживании',
  broken: 'Неисправен',
  retired: 'Списан',
  active: 'Активный',
  disposed: 'Списан',
}

const typeLabels: Record<string, string> = {
  Laptop: 'Ноутбук',
  Desktop: 'Компьютер',
  Printer: 'Принтер',
  Monitor: 'Монитор',
  Server: 'Сервер',
  'Network Switch': 'Коммутатор',
  monitor: 'Монитор',
  desktop: 'Системный блок',
  computer_set: 'Комплект компьютер + монитор',
  component: 'Комплектующие',
  mfp_printer: 'МФУ / Принтер',
  printer: 'Принтер',
  network_equipment: 'Сетевое оборудование',
  laptop: 'Ноутбук',
  projector: 'Проектор',
  all_in_one: 'Моноблок',
  screen: 'Экран',
  scanner: 'Сканер',
  other: 'Прочее',
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium' }).format(new Date(value))
}

function AssetStatusBadge({ status }: { status: string }) {
  return <span className={`asset-status asset-status-${status}`}>{statusLabels[status] ?? status}</span>
}

function downloadErrorRows(rows: AssetImportRow[]) {
  const withErrors = rows.filter((item) => item.status === 'error' || item.status === 'duplicate')
  const header = ['row_number', 'inventory_number', 'name', 'type', 'status', 'assigned_to_name', 'location', 'purchase_year', 'error_message']
  const lines = withErrors.map((item) => {
    const normalized = item.normalized
    const values = [
      item.row_number,
      normalized.inventory_number ?? '',
      normalized.name ?? '',
      normalized.asset_type ?? '',
      normalized.status ?? '',
      normalized.assigned_to_name ?? '',
      normalized.location ?? '',
      normalized.purchase_year ?? '',
      item.error_message ?? '',
    ]
    return values.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(',')
  })
  const csv = [header.join(','), ...lines].join('\n')
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `asset-import-errors-${Date.now()}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}

export default function AssetsPage() {
  const { session } = useAuth()
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [sourceFilter, setSourceFilter] = useState('ALL')
  const [verificationFilter, setVerificationFilter] = useState('ALL')
  const [withoutLocation, setWithoutLocation] = useState(false)
  const [disposedOnly, setDisposedOnly] = useState(false)
  const [assignedFilter, setAssignedFilter] = useState('ALL')
  const [yearFilter, setYearFilter] = useState('ALL')
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)

  const canPreviewImport = Boolean(session?.user.permissions.includes('assets.import.preview'))
  const canCommitImport = Boolean(session?.user.permissions.includes('assets.import.commit'))
  const canReadBatches = Boolean(session?.user.permissions.includes('assets.import.read_batches'))

  const assetsQuery = useQuery({
    queryKey: [
      'assets',
      session?.access_token,
      sourceFilter,
      verificationFilter,
      withoutLocation,
      disposedOnly,
      assignedFilter,
      yearFilter,
      typeFilter,
    ],
    queryFn: () =>
      fetchAssets(session?.access_token ?? '', {
        source: sourceFilter,
        verification_status: verificationFilter,
        without_location: withoutLocation,
        disposed: disposedOnly,
        assigned_to_name: assignedFilter,
        purchase_year: yearFilter === 'ALL' ? undefined : Number(yearFilter),
        type: typeFilter,
      }),
    enabled: Boolean(session?.access_token),
  })

  const selectedAssetQuery = useQuery({
    queryKey: ['asset', session?.access_token, selectedAssetId],
    queryFn: () => fetchAsset(session?.access_token ?? '', selectedAssetId ?? ''),
    enabled: Boolean(session?.access_token && selectedAssetId),
  })

  const relatedTicketsQuery = useQuery({
    queryKey: ['asset-tickets', session?.access_token, selectedAssetId],
    queryFn: () => fetchAssetTickets(session?.access_token ?? '', selectedAssetId ?? ''),
    enabled: Boolean(session?.access_token && selectedAssetId),
  })

  const importBatchesQuery = useQuery({
    queryKey: ['asset-import-batches', session?.access_token],
    queryFn: () => fetchAssetImportBatches(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadBatches),
  })

  const importRowsQuery = useQuery({
    queryKey: ['asset-import-rows', session?.access_token, activeBatchId],
    queryFn: () => fetchAssetImportRows(session?.access_token ?? '', activeBatchId ?? ''),
    enabled: Boolean(session?.access_token && activeBatchId && canReadBatches),
  })

  const importSummaryQuery = useQuery({
    queryKey: ['asset-import-summary', session?.access_token],
    queryFn: () => fetchAssetImportSummary(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadBatches),
  })

  const uploadMutation = useMutation({
    mutationFn: async (file: File) => {
      if (!session?.access_token) throw new Error('No session')
      return uploadAssetImport(session.access_token, file)
    },
    onSuccess: async (batch) => {
      setActiveBatchId(batch.id)
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
    },
  })

  const previewMutation = useMutation({
    mutationFn: async (batchId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return previewAssetImport(session.access_token, { batch_id: batchId, dry_run: true })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-import-rows'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-import-summary'] })
    },
  })

  const commitMutation = useMutation({
    mutationFn: async (batchId: string) => {
      if (!session?.access_token) throw new Error('No session')
      return commitAssetImport(session.access_token, batchId, { dry_run: false })
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['asset-import-batches'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-import-rows'] })
      await queryClient.invalidateQueries({ queryKey: ['asset-import-summary'] })
      await queryClient.invalidateQueries({ queryKey: ['assets'] })
      setSourceFilter('excel_import')
    },
  })

  const assets = assetsQuery.data ?? []

  useEffect(() => {
    if (!selectedAssetId && assets.length > 0) {
      setSelectedAssetId(assets[0].id)
    }
  }, [assets, selectedAssetId])

  useEffect(() => {
    if (!activeBatchId && importBatchesQuery.data && importBatchesQuery.data.length > 0) {
      setActiveBatchId(importBatchesQuery.data[0].id)
    }
  }, [activeBatchId, importBatchesQuery.data])

  const filteredAssets = useMemo(() => {
    const query = search.trim().toLowerCase()
    return assets.filter((asset) => {
      const matchesSearch =
        !query ||
        [asset.asset_tag, asset.name, asset.serial_number, asset.inventory_number, asset.manufacturer, asset.model, asset.assigned_to_name, asset.department]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(query))
      const matchesStatus = statusFilter === 'ALL' || asset.status === statusFilter
      return matchesSearch && matchesStatus
    })
  }, [assets, search, statusFilter])

  const typeOptions = useMemo(() => Array.from(new Set((assetsQuery.data ?? []).map((asset) => asset.type ?? asset.asset_type))).sort(), [assetsQuery.data])
  const statusOptions = useMemo(() => Array.from(new Set((assetsQuery.data ?? []).map((asset) => asset.status))).sort(), [assetsQuery.data])
  const sourceOptions = useMemo(() => Array.from(new Set((assetsQuery.data ?? []).map((asset) => asset.source ?? 'manual'))).sort(), [assetsQuery.data])
  const verificationOptions = useMemo(
    () => Array.from(new Set((assetsQuery.data ?? []).map((asset) => asset.verification_status).filter(Boolean) as string[])).sort(),
    [assetsQuery.data],
  )
  const assignedOptions = useMemo(
    () => Array.from(new Set((assetsQuery.data ?? []).map((asset) => asset.assigned_to_name).filter(Boolean) as string[])).sort(),
    [assetsQuery.data],
  )
  const yearOptions = useMemo(
    () =>
      Array.from(new Set((assetsQuery.data ?? []).map((asset) => asset.purchase_year).filter((year): year is number => typeof year === 'number')))
        .sort((a, b) => b - a)
        .map(String),
    [assetsQuery.data],
  )
  const problemAssets = assets.filter((asset) => ['broken', 'in_repair', 'maintenance'].includes(asset.status)).length
  const warrantySoon = assets.filter((asset) => asset.warranty_until && new Date(asset.warranty_until).getTime() < Date.now() + 1000 * 60 * 60 * 24 * 45).length
  const importedCount = assets.filter((asset) => asset.source === 'excel_import').length
  const missingLocationCount = assets.filter((asset) => asset.verification_status === 'needs_location').length
  const disposedCount = assets.filter((asset) => asset.status === 'disposed').length
  const activeCount = assets.filter((asset) => asset.status === 'active' || asset.status === 'in_use').length
  const verificationRequiredCount = assets.filter((asset) => asset.verification_status === 'needs_location').length
  const duplicateInventoryCount = useMemo(() => {
    const counter = new Map<string, number>()
    for (const item of assets) {
      if (!item.inventory_number) continue
      counter.set(item.inventory_number, (counter.get(item.inventory_number) ?? 0) + 1)
    }
    return Array.from(counter.values()).filter((count) => count > 1).length
  }, [assets])

  const selectedAsset = selectedAssetQuery.data
  const relatedTickets: AssetTicket[] = relatedTicketsQuery.data ?? []
  const importRows = importRowsQuery.data ?? []
  const importPreview = importBatchesQuery.data?.find((item) => item.id === activeBatchId)?.summary?.preview as Record<string, unknown> | undefined

  return (
    <AppShell title="Активы" subtitle="Инвентаризация, привязка к заявкам и срокам обслуживания уже читаются из backend.">
      <section className="foundation-card">
        <div>
          <p className="eyebrow">ASSET MANAGEMENT</p>
          <h2>Реестр оборудования</h2>
          <p>Раздел показывает текущие активы, проверку локаций, статус инвентаризации и workflow импорта из бухгалтерского Excel без прямой записи до preview.</p>
        </div>
        <div className="status-column">
          <HealthBadge />
          <div className="status-list">
            <span>✓ Preview before commit</span>
            <span>✓ Duplicate inventory control</span>
            <span>✓ Imported assets traceability</span>
          </div>
        </div>
      </section>

      <section className="metric-grid assets-metrics">
        <article className="metric-card">
          <span>Всего импортировано</span>
          <strong>{assetsQuery.isPending ? '…' : importedCount}</strong>
          <p>Активы с source = excel_import.</p>
        </article>
        <article className="metric-card">
          <span>Без кабинета</span>
          <strong>{assetsQuery.isPending ? '…' : missingLocationCount}</strong>
          <p>Активы с verification_status = needs_location.</p>
        </article>
        <article className="metric-card">
          <span>Списано</span>
          <strong>{assetsQuery.isPending ? '…' : disposedCount}</strong>
          <p>Статус disposed.</p>
        </article>
        <article className="metric-card">
          <span>Активные</span>
          <strong>{assetsQuery.isPending ? '…' : activeCount}</strong>
          <p>Статус active/in_use.</p>
        </article>
        <article className="metric-card">
          <span>Требует проверки</span>
          <strong>{assetsQuery.isPending ? '…' : verificationRequiredCount}</strong>
          <p>Нужна верификация локации.</p>
        </article>
        <article className="metric-card">
          <span>Дубли инв. номеров</span>
          <strong>{assetsQuery.isPending ? '…' : duplicateInventoryCount}</strong>
          <p>Контроль качества данных.</p>
        </article>
        <article className="metric-card">
          <span>Проблемные активы</span>
          <strong>{assetsQuery.isPending ? '…' : problemAssets}</strong>
          <p>Неисправные или в ремонте.</p>
        </article>
        <article className="metric-card">
          <span>Скоро окончится гарантия</span>
          <strong>{assetsQuery.isPending ? '…' : warrantySoon}</strong>
          <p>Окно гарантии менее 45 дней.</p>
        </article>
      </section>

      {canPreviewImport ? (
        <section className="foundation-card admin-panel">
          <div>
            <p className="eyebrow">ASSET IMPORT</p>
            <h2>Импорт из Excel</h2>
            <p>Файл сначала загружается и проверяется, активы создаются только после явного commit.</p>
          </div>
          <div className="tickets-toolbar-group">
            <label className="inline-field">
              <span>Файл .xlsx</span>
              <input
                type="file"
                accept=".xlsx"
                onChange={(event) => {
                  const nextFile = event.target.files?.[0] ?? null
                  setSelectedFile(nextFile)
                }}
              />
            </label>
            <button
              type="button"
              className="primary-button"
              disabled={!selectedFile || uploadMutation.isPending || previewMutation.isPending}
              onClick={async () => {
                if (!selectedFile) return
                const batch = await uploadMutation.mutateAsync(selectedFile)
                await previewMutation.mutateAsync(batch.id)
              }}
            >
              Загрузить и проверить
            </button>
            <button
              type="button"
              className="ghost-button"
              disabled={!activeBatchId || previewMutation.isPending}
              onClick={() => {
                if (!activeBatchId) return
                previewMutation.mutate(activeBatchId)
              }}
            >
              Обновить preview
            </button>
            <button
              type="button"
              className="ghost-button"
              disabled={!activeBatchId || !canCommitImport || commitMutation.isPending}
              onClick={() => {
                if (!activeBatchId) return
                commitMutation.mutate(activeBatchId)
              }}
            >
              Импортировать валидные
            </button>
            <button
              type="button"
              className="ghost-button"
              disabled={importRows.length === 0}
              onClick={() => downloadErrorRows(importRows)}
            >
              Скачать отчёт ошибок
            </button>
            <button type="button" className="ghost-button" onClick={() => setActiveBatchId(null)}>
              Отменить импорт
            </button>
          </div>
          {uploadMutation.isError || previewMutation.isError || commitMutation.isError ? (
            <p className="error-message">Не удалось выполнить импорт. Проверьте формат файла и права доступа.</p>
          ) : null}
          <div className="metric-grid assets-metrics analytics-mini-grid">
            <article className="metric-card"><span>Всего строк</span><strong>{Number(importPreview?.total_rows ?? importSummaryQuery.data?.total_rows ?? 0)}</strong></article>
            <article className="metric-card"><span>Валидных</span><strong>{Number(importPreview?.valid_rows ?? 0)}</strong></article>
            <article className="metric-card"><span>Ошибок</span><strong>{Number(importPreview?.error_rows ?? 0)}</strong></article>
            <article className="metric-card"><span>Дубликаты</span><strong>{Number(importPreview?.duplicate_rows ?? 0)}</strong></article>
            <article className="metric-card"><span>Списанные</span><strong>{Number(importPreview?.disposed_rows ?? 0)}</strong></article>
            <article className="metric-card"><span>Без кабинета</span><strong>{Number(importPreview?.missing_location_rows ?? 0)}</strong></article>
            <article className="metric-card"><span>Переведено в запасы</span><strong>{Number(importPreview?.in_stock_rows ?? 0)}</strong></article>
            <article className="metric-card"><span>Импортировано batch</span><strong>{importBatchesQuery.data?.find((item) => item.id === activeBatchId)?.imported_rows ?? 0}</strong></article>
          </div>
          <div className="ticket-table-wrap analytics-table-space">
            <table className="ticket-table">
              <thead>
                <tr>
                  <th>row_number</th>
                  <th>inventory_number</th>
                  <th>name</th>
                  <th>type</th>
                  <th>status</th>
                  <th>assigned_to_name</th>
                  <th>location</th>
                  <th>purchase_year</th>
                  <th>error_message</th>
                </tr>
              </thead>
              <tbody>
                {importRows.map((row) => (
                  <tr key={row.id}>
                    <td>{row.row_number}</td>
                    <td>{String(row.normalized.inventory_number ?? '—')}</td>
                    <td>{String(row.normalized.name ?? '—')}</td>
                    <td>{typeLabels[String(row.normalized.asset_type ?? '')] ?? String(row.normalized.asset_type ?? '—')}</td>
                    <td>{String(row.status)}</td>
                    <td>{String(row.normalized.assigned_to_name ?? '—')}</td>
                    <td>{String(row.normalized.location ?? '—')}</td>
                    <td>{String(row.normalized.purchase_year ?? '—')}</td>
                    <td>{row.error_message ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {commitMutation.data ? (
            <p className="muted">
              Импорт завершён: обработано {commitMutation.data.total_rows}, импортировано {commitMutation.data.imported_rows}, ошибок {commitMutation.data.error_rows}.
            </p>
          ) : null}
        </section>
      ) : null}

      <section className="foundation-card tickets-toolbar">
        <div className="tickets-toolbar-group">
          <label className="inline-field">
            <span>Поиск</span>
            <input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="№, название, серийный номер, сотрудник..." />
          </label>
          <label className="inline-field">
            <span>Тип</span>
            <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)}>
              <option value="ALL">Все типы</option>
              {typeOptions.map((type) => (
                <option key={type} value={type}>
                  {typeLabels[type] ?? type}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Статус</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
              <option value="ALL">Все статусы</option>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {statusLabels[status] ?? status}
                </option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Источник</span>
            <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
              <option value="ALL">Все источники</option>
              {sourceOptions.map((source) => (
                <option key={source} value={source}>{source}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Verification</span>
            <select value={verificationFilter} onChange={(event) => setVerificationFilter(event.target.value)}>
              <option value="ALL">Все</option>
              {verificationOptions.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>МОЛ</span>
            <select value={assignedFilter} onChange={(event) => setAssignedFilter(event.target.value)}>
              <option value="ALL">Все</option>
              {assignedOptions.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Год</span>
            <select value={yearFilter} onChange={(event) => setYearFilter(event.target.value)}>
              <option value="ALL">Все</option>
              {yearOptions.map((item) => (
                <option key={item} value={item}>{item}</option>
              ))}
            </select>
          </label>
          <label className="inline-field">
            <span>Флаги</span>
            <div className="status-list">
              <label><input type="checkbox" checked={withoutLocation} onChange={(event) => setWithoutLocation(event.target.checked)} /> без кабинета</label>
              <label><input type="checkbox" checked={disposedOnly} onChange={(event) => setDisposedOnly(event.target.checked)} /> списанные</label>
            </div>
          </label>
        </div>
      </section>

      <section className="asset-list-shell">
        {assetsQuery.isPending ? (
          <p className="muted">Загрузка активов…</p>
        ) : assetsQuery.isError ? (
          <p className="error-message">Не удалось получить список активов.</p>
        ) : (
          <div className="asset-table-layout">
            <div className="asset-table-wrap">
              <table className="ticket-table">
                <thead>
                  <tr>
                    <th>Актив</th>
                    <th>Тип</th>
                    <th>Назначение</th>
                    <th>Статус</th>
                    <th>Источник</th>
                    <th>Гарантия</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredAssets.map((asset) => (
                    <tr key={asset.id} className={selectedAssetId === asset.id ? 'row-selected' : ''}>
                      <td>
                        <strong>{asset.asset_tag}</strong>
                        <p className="table-subtext">{asset.name}</p>
                      </td>
                      <td>{typeLabels[asset.type ?? asset.asset_type] ?? asset.type ?? asset.asset_type}</td>
                      <td>
                        <strong>{asset.assigned_to_name ?? 'Не назначен'}</strong>
                        <p className="table-subtext">{asset.department ?? '—'}</p>
                      </td>
                      <td><AssetStatusBadge status={asset.status} /></td>
                      <td>{asset.source ?? 'manual'}</td>
                      <td>
                        <div className="ticket-sla-cell">
                          <span>{formatDate(asset.warranty_until)}</span>
                          <small>{asset.warranty_until ? 'Warranty' : '—'}</small>
                        </div>
                      </td>
                      <td>
                        <button type="button" className="ghost-button row-action" onClick={() => setSelectedAssetId(asset.id)}>
                          Детали
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <aside className="asset-detail-panel">
              {selectedAssetQuery.isPending || relatedTicketsQuery.isPending ? (
                <p className="muted">Загрузка карточки актива…</p>
              ) : selectedAssetQuery.isError || !selectedAsset ? (
                <p className="muted">Выберите актив для просмотра подробностей.</p>
              ) : (
                <>
                  <p className="eyebrow">КАРТОЧКА АКТИВА</p>
                  <h3>{selectedAsset.asset_tag}</h3>
                  <p className="asset-description">{selectedAsset.name}</p>
                  <div className="detail-fields">
                    <div><span>Тип</span><strong>{typeLabels[selectedAsset.type ?? selectedAsset.asset_type] ?? selectedAsset.type ?? selectedAsset.asset_type}</strong></div>
                    <div><span>Оригинальный тип</span><strong>{selectedAsset.original_type ?? '—'}</strong></div>
                    <div><span>Серийный номер</span><strong>{selectedAsset.serial_number ?? '—'}</strong></div>
                    <div><span>Инв. номер</span><strong>{selectedAsset.inventory_number ?? '—'}</strong></div>
                    <div><span>Производитель</span><strong>{selectedAsset.manufacturer ?? '—'}</strong></div>
                    <div><span>Модель</span><strong>{selectedAsset.model ?? '—'}</strong></div>
                    <div><span>Источник</span><strong>{selectedAsset.source ?? 'manual'}</strong></div>
                    <div><span>Назначен</span><strong>{selectedAsset.assigned_to_name ?? '—'}</strong></div>
                    <div><span>МОЛ / отдел</span><strong>{selectedAsset.department ?? '—'}</strong></div>
                    <div><span>Локация</span><strong>{selectedAsset.location}</strong></div>
                    <div><span>Год</span><strong>{selectedAsset.purchase_year ?? '—'}</strong></div>
                    <div><span>Verification</span><strong>{selectedAsset.verification_status ?? '—'}</strong></div>
                    <div><span>Гарантия до</span><strong>{formatDate(selectedAsset.warranty_until)}</strong></div>
                    <div><span>Здоровье</span><strong>{selectedAsset.health}</strong></div>
                  </div>

                  <div className="activity-list">
                    <h4>Связанные заявки</h4>
                    {relatedTickets.length === 0 ? (
                      <p className="muted">Заявок по этому активу пока нет.</p>
                    ) : (
                      relatedTickets.map((ticket) => (
                        <article className="activity-item" key={ticket.id}>
                          <header>
                            <strong>{ticket.ticket_number}</strong>
                            <span>{ticket.sla_status ?? '—'}</span>
                          </header>
                          <p>{ticket.title}</p>
                          <small>{ticket.priority} · {ticket.status}</small>
                        </article>
                      ))
                    )}
                  </div>
                </>
              )}
            </aside>
          </div>
        )}
      </section>
    </AppShell>
  )
}
