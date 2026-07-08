import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  commitAssetImport,
  type Asset,
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

type PreviewFilter = 'ALL' | 'VALID' | 'ERROR' | 'DUPLICATE' | 'MISSING_LOCATION' | 'DISPOSED' | 'IN_STOCK'
type AssetsMode = 'registry' | 'import'

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

function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

function AssetStatusBadge({ status }: { status: string }) {
  return <span className={`asset-status asset-status-${status}`}>{statusLabels[status] ?? status}</span>
}

function ImportRowStatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase()
  const labelMap: Record<string, string> = {
    valid: 'Валидно',
    error: 'Ошибка',
    duplicate: 'Дубликат',
    skipped: 'Пропущено',
    imported: 'Создан',
    updated: 'Обновлён',
  }
  return <span className={`badge import-status-badge import-status-${normalized}`}>{labelMap[normalized] ?? status}</span>
}

function ImportFlagBadge({ kind }: { kind: 'disposed' | 'in_stock' | 'needs_location' }) {
  const labels: Record<typeof kind, string> = {
    disposed: 'Списано',
    in_stock: 'В запасах',
    needs_location: 'Нет кабинета',
  }
  return <span className={`badge import-flag-badge import-flag-${kind}`}>{labels[kind]}</span>
}

function normalizeLocationValue(rawLocation: unknown) {
  const value = String(rawLocation ?? '').trim()
  if (!value || value.toLowerCase() === 'location unknown') return 'Кабинет не указан'
  return value
}

function verificationLabel(value: string | null | undefined) {
  const normalized = String(value ?? '').toLowerCase()
  if (!normalized) return '—'
  if (normalized === 'needs_location') return 'Требуется кабинет'
  if (normalized === 'verified') return 'Проверено'
  return normalized
}

function sourceLabel(value: string | null | undefined) {
  const normalized = String(value ?? '').toLowerCase()
  if (!normalized || normalized === 'manual') return 'manual'
  if (normalized === 'excel_import') return 'excel_import'
  if (normalized === 'demo_seed') return 'demo'
  return normalized
}

function hasDisposedMarker(raw: Record<string, unknown>, normalizedStatus: string) {
  if (normalizedStatus === 'disposed') return true
  const markers = [raw.status_m, raw.status_o, raw.status, raw['Статус M'], raw['Статус O']]
  return markers.some((marker) => String(marker ?? '').toUpperCase().includes('СПИСАНО'))
}

function hasInStockMarker(raw: Record<string, unknown>, normalizedStatus: string) {
  if (normalizedStatus === 'in_stock') return true
  const statusBlob = [raw.status_m, raw.status_o, raw.status, raw['Статус M'], raw['Статус O']]
    .map((item) => String(item ?? '').toUpperCase())
    .join(' ')
  return statusBlob.includes('ПЕРЕВЕДЕНО') && statusBlob.includes('ЗАПАС')
}

function isMissingLocation(normalized: Record<string, unknown>) {
  const verificationStatus = String(normalized.verification_status ?? '').toLowerCase()
  const location = normalizeLocationValue(normalized.location)
  return verificationStatus === 'needs_location' || location === 'Кабинет не указан'
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
  const [selectedAssetFallback, setSelectedAssetFallback] = useState<Asset | null>(null)
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [activeBatchId, setActiveBatchId] = useState<string | null>(null)
  const [previewFilter, setPreviewFilter] = useState<PreviewFilter>('ALL')
  const [activeAssetsMode, setActiveAssetsMode] = useState<AssetsMode>('registry')

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
    },
  })

  const assets = assetsQuery.data ?? []

  useEffect(() => {
    if (!activeBatchId && importBatchesQuery.data && importBatchesQuery.data.length > 0) {
      setActiveBatchId(importBatchesQuery.data[0].id)
    }
  }, [activeBatchId, importBatchesQuery.data])

  useEffect(() => {
    if (!selectedAssetId) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      setSelectedAssetId(null)
      setSelectedAssetFallback(null)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectedAssetId])

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

  const selectedAsset = selectedAssetQuery.data ?? selectedAssetFallback
  const relatedTickets: AssetTicket[] = relatedTicketsQuery.data ?? []
  const importRows = importRowsQuery.data ?? []
  const activeBatch = importBatchesQuery.data?.find((item) => item.id === activeBatchId)
  const importPreview = activeBatch?.summary?.preview as Record<string, unknown> | undefined

  const previewMetrics = useMemo(() => {
    const totalRows = Number(importPreview?.total_rows ?? activeBatch?.total_rows ?? importRows.length)
    const validRowsFromSummary = Number(importPreview?.valid_rows ?? activeBatch?.valid_rows ?? 0)
    const errorRowsFromSummary = Number(importPreview?.error_rows ?? activeBatch?.error_rows ?? 0)
    const duplicateRowsFromSummary = Number(importPreview?.duplicate_rows ?? activeBatch?.skipped_rows ?? 0)
    const missingLocationFromSummary = Number(importPreview?.missing_location_rows ?? 0)
    const disposedFromSummary = Number(importPreview?.disposed_rows ?? 0)
    const inStockFromSummary = Number(importPreview?.in_stock_rows ?? 0)

    const calculated = importRows.reduce(
      (acc, row) => {
        const normalized = row.normalized
        const raw = row.raw
        const rowStatus = String(row.status ?? '').toLowerCase()
        const normalizedStatus = String(normalized.status ?? '').toLowerCase()
        acc.totalRows += 1
        if (rowStatus === 'valid') acc.validRows += 1
        if (rowStatus === 'error') acc.errorRows += 1
        if (rowStatus === 'duplicate') acc.duplicateRows += 1
        if (isMissingLocation(normalized)) acc.missingLocationRows += 1
        if (hasDisposedMarker(raw, normalizedStatus)) acc.disposedRows += 1
        if (hasInStockMarker(raw, normalizedStatus)) acc.inStockRows += 1
        if (rowStatus === 'imported') acc.createdRows += 1
        if (rowStatus === 'updated') acc.updatedRows += 1
        return acc
      },
      {
        totalRows: 0,
        validRows: 0,
        errorRows: 0,
        duplicateRows: 0,
        missingLocationRows: 0,
        disposedRows: 0,
        inStockRows: 0,
        createdRows: 0,
        updatedRows: 0,
      },
    )

    const validRows = validRowsFromSummary > 0 || importRows.length === 0 ? validRowsFromSummary : calculated.validRows
    const errorRows = errorRowsFromSummary > 0 || importRows.length === 0 ? errorRowsFromSummary : calculated.errorRows
    const duplicateRows = duplicateRowsFromSummary > 0 || importRows.length === 0 ? duplicateRowsFromSummary : calculated.duplicateRows
    const missingLocationRows = missingLocationFromSummary > 0 || importRows.length === 0 ? missingLocationFromSummary : calculated.missingLocationRows
    const disposedRows = disposedFromSummary > 0 || importRows.length === 0 ? disposedFromSummary : calculated.disposedRows
    const inStockRows = inStockFromSummary > 0 || importRows.length === 0 ? inStockFromSummary : calculated.inStockRows

    return {
      totalRows,
      validRows,
      errorRows,
      duplicateRows,
      missingLocationRows,
      disposedRows,
      inStockRows,
      willImportRows: Math.max(validRows, 0),
      createdRows: calculated.createdRows,
      updatedRows: calculated.updatedRows,
    }
  }, [importPreview, activeBatch, importRows])

  const filteredImportRows = useMemo(() => {
    return importRows.filter((row) => {
      const normalized = row.normalized
      const rowStatus = String(row.status ?? '').toLowerCase()
      const normalizedStatus = String(normalized.status ?? '').toLowerCase()

      if (previewFilter === 'ALL') return true
      if (previewFilter === 'VALID') return rowStatus === 'valid'
      if (previewFilter === 'ERROR') return rowStatus === 'error'
      if (previewFilter === 'DUPLICATE') return rowStatus === 'duplicate'
      if (previewFilter === 'MISSING_LOCATION') return isMissingLocation(normalized)
      if (previewFilter === 'DISPOSED') return hasDisposedMarker(row.raw, normalizedStatus)
      if (previewFilter === 'IN_STOCK') return hasInStockMarker(row.raw, normalizedStatus)
      return true
    })
  }, [importRows, previewFilter])

  const hasPreviewContext = Boolean(activeBatchId)
  const hasPreviewRows = importRows.length > 0
  const canRefreshPreview = Boolean(activeBatchId)
  const canCommitValidRows = Boolean(activeBatchId && canCommitImport && previewMetrics.validRows > 0)
  const canDownloadErrors = previewMetrics.errorRows > 0 || previewMetrics.duplicateRows > 0

  const activeBatchStatusLabel = (() => {
    const status = String(activeBatch?.status ?? '').toLowerCase()
    if (!status) return '—'
    if (status === 'uploaded') return 'Загружен'
    if (status === 'preview_ready') return 'Preview готов'
    if (status === 'committed') return 'Завершён'
    return status
  })()

  const closeAssetDetail = () => {
    setSelectedAssetId(null)
    setSelectedAssetFallback(null)
  }

  const showImportedAssets = async () => {
    setSourceFilter('excel_import')
    setActiveAssetsMode('registry')
    await queryClient.invalidateQueries({ queryKey: ['assets'] })
  }

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

      {activeAssetsMode === 'registry' ? (
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
      ) : null}

      {activeAssetsMode === 'import' && canPreviewImport ? (
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
              {uploadMutation.isPending || previewMutation.isPending ? 'Проверяем...' : 'Загрузить и проверить'}
            </button>
            <button
              type="button"
              className="ghost-button"
              disabled={!canRefreshPreview || previewMutation.isPending}
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
              disabled={!canCommitValidRows || commitMutation.isPending}
              onClick={() => {
                if (!activeBatchId) return
                const confirmed = window.confirm(`Будет импортировано ${previewMetrics.willImportRows} валидных активов. Продолжить?`)
                if (!confirmed) return
                commitMutation.mutate(activeBatchId)
              }}
            >
              Импортировать валидные
            </button>
            <button
              type="button"
              className="ghost-button"
              disabled={!canDownloadErrors}
              onClick={() => downloadErrorRows(importRows)}
            >
              {canDownloadErrors ? 'Скачать отчёт ошибок' : 'Ошибок нет'}
            </button>
            <button
              type="button"
              className="ghost-button"
              onClick={() => {
                setSelectedFile(null)
                setActiveBatchId(null)
                setPreviewFilter('ALL')
              }}
            >
              Отменить импорт
            </button>
            <button type="button" className="ghost-button" onClick={() => setActiveAssetsMode('registry')}>
              Назад к реестру активов
            </button>
          </div>
          <div className="import-context">
            <p className="muted">Выбран файл: {selectedFile?.name ?? 'Файл не выбран'}</p>
            {hasPreviewContext ? (
              <>
                <p className="muted">Загружен файл: {activeBatch?.original_file_name ?? selectedFile?.name ?? '—'}</p>
                <p className="muted">Batch: {activeBatch?.id ?? activeBatchId}</p>
                <p className="muted">Статус: {activeBatchStatusLabel}</p>
              </>
            ) : null}
          </div>
          {uploadMutation.isError || previewMutation.isError || commitMutation.isError ? (
            <p className="error-message">Не удалось выполнить импорт. Проверьте формат файла и права доступа.</p>
          ) : null}
          {hasPreviewContext ? (
            <div className="metric-grid assets-metrics import-summary-grid">
              <article className="metric-card"><span>Всего строк</span><strong>{previewMetrics.totalRows}</strong></article>
              <article className="metric-card"><span>Валидные</span><strong>{previewMetrics.validRows}</strong></article>
              <article className="metric-card"><span>Ошибки</span><strong>{previewMetrics.errorRows}</strong></article>
              <article className="metric-card"><span>Дубликаты</span><strong>{previewMetrics.duplicateRows}</strong></article>
              <article className="metric-card"><span>Без кабинета</span><strong>{previewMetrics.missingLocationRows}</strong></article>
              <article className="metric-card"><span>Списано</span><strong>{previewMetrics.disposedRows}</strong></article>
              <article className="metric-card"><span>В запасах</span><strong>{previewMetrics.inStockRows}</strong></article>
              <article className="metric-card"><span>Будет импортировано</span><strong>{previewMetrics.willImportRows}</strong></article>
            </div>
          ) : null}
          <div className="import-preview-filter-row">
            <button type="button" className={`ghost-button ${previewFilter === 'ALL' ? 'admin-tab-active' : ''}`} onClick={() => setPreviewFilter('ALL')}>Все</button>
            <button type="button" className={`ghost-button ${previewFilter === 'VALID' ? 'admin-tab-active' : ''}`} onClick={() => setPreviewFilter('VALID')}>Только валидные</button>
            <button type="button" className={`ghost-button ${previewFilter === 'ERROR' ? 'admin-tab-active' : ''}`} onClick={() => setPreviewFilter('ERROR')}>Ошибки</button>
            <button type="button" className={`ghost-button ${previewFilter === 'DUPLICATE' ? 'admin-tab-active' : ''}`} onClick={() => setPreviewFilter('DUPLICATE')}>Дубликаты</button>
            <button type="button" className={`ghost-button ${previewFilter === 'MISSING_LOCATION' ? 'admin-tab-active' : ''}`} onClick={() => setPreviewFilter('MISSING_LOCATION')}>Без кабинета</button>
            <button type="button" className={`ghost-button ${previewFilter === 'DISPOSED' ? 'admin-tab-active' : ''}`} onClick={() => setPreviewFilter('DISPOSED')}>Списанные</button>
            <button type="button" className={`ghost-button ${previewFilter === 'IN_STOCK' ? 'admin-tab-active' : ''}`} onClick={() => setPreviewFilter('IN_STOCK')}>В запасах</button>
          </div>
          <div className="ticket-table-wrap analytics-table-space import-preview-table-wrap">
            <table className="ticket-table import-preview-table">
              <thead>
                <tr>
                  <th>№ строки</th>
                  <th>Инв. номер</th>
                  <th>Наименование</th>
                  <th>Тип</th>
                  <th>Статус</th>
                  <th>МОЛ</th>
                  <th>Кабинет</th>
                  <th>Год</th>
                  <th>Ошибка</th>
                </tr>
              </thead>
              <tbody>
                {filteredImportRows.map((row) => {
                  const normalizedStatus = String(row.normalized.status ?? '').toLowerCase()
                  const needsLocation = isMissingLocation(row.normalized)
                  const isDisposed = hasDisposedMarker(row.raw, normalizedStatus)
                  const isInStock = hasInStockMarker(row.raw, normalizedStatus)
                  return (
                  <tr key={row.id}>
                    <td>{row.row_number}</td>
                    <td>{String(row.normalized.inventory_number ?? '—')}</td>
                    <td className="import-name-cell" title={String(row.normalized.name ?? '—')}>{String(row.normalized.name ?? '—')}</td>
                    <td>{typeLabels[String(row.normalized.asset_type ?? '')] ?? String(row.normalized.asset_type ?? '—')}</td>
                    <td>
                      <div className="import-status-cell">
                        <ImportRowStatusBadge status={String(row.status)} />
                        {isDisposed ? <ImportFlagBadge kind="disposed" /> : null}
                        {isInStock ? <ImportFlagBadge kind="in_stock" /> : null}
                        {needsLocation ? <ImportFlagBadge kind="needs_location" /> : null}
                      </div>
                    </td>
                    <td>{String(row.normalized.assigned_to_name ?? '—')}</td>
                    <td>{normalizeLocationValue(row.normalized.location)}</td>
                    <td>{String(row.normalized.purchase_year ?? '—')}</td>
                    <td>{row.error_message ?? '—'}</td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
            {!hasPreviewRows ? <p className="muted import-empty-note">Строки preview появятся после проверки файла.</p> : null}
          </div>
          {commitMutation.data ? (
            <div className="import-commit-summary">
              <p className="muted">Batch завершён: {activeBatch?.status === 'committed' ? 'да' : 'в процессе'}</p>
              <p className="muted">Создано: {previewMetrics.createdRows}</p>
              <p className="muted">Обновлено: {previewMetrics.updatedRows}</p>
              <p className="muted">Пропущено: {commitMutation.data.skipped_rows ?? 0}</p>
              <p className="muted">Ошибки: {commitMutation.data.error_rows ?? 0}</p>
              <p className="muted">Дубликаты: {previewMetrics.duplicateRows}</p>
            </div>
          ) : null}
          {commitMutation.data ? (
            <div className="analytics-actions">
              <button type="button" onClick={() => void showImportedAssets()}>Показать импортированные активы</button>
              <button type="button" className="ghost-button" onClick={() => setActiveAssetsMode('import')}>Остаться в импорте</button>
            </div>
          ) : null}
          <p className="state-panel state-panel-empty">После импорта активы появятся в реестре. Нажмите «Назад к реестру активов».</p>
        </section>
      ) : null}

      {activeAssetsMode === 'import' && !canPreviewImport ? (
        <section className="foundation-card admin-panel">
          <p className="state-panel state-panel-error">У вашей роли нет прав на импорт активов из Excel.</p>
          <button type="button" className="ghost-button" onClick={() => setActiveAssetsMode('registry')}>Назад к реестру активов</button>
        </section>
      ) : null}

      {activeAssetsMode === 'registry' ? (
        <>
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
            <button
              type="button"
              className="ghost-button tickets-create-button"
              disabled={!canPreviewImport}
              onClick={() => setActiveAssetsMode('import')}
            >
              Импорт из Excel
            </button>
          </section>

          <section className="asset-list-shell">
            {assetsQuery.isPending ? (
              <p className="muted">Загрузка активов…</p>
            ) : assetsQuery.isError ? (
              <p className="error-message">Не удалось получить список активов.</p>
            ) : (
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
                  {filteredAssets.length === 0 ? (
                    <tr>
                      <td colSpan={7}>
                        <p className="state-panel state-panel-empty">По текущим фильтрам активы не найдены.</p>
                      </td>
                    </tr>
                  ) : null}
                  {filteredAssets.map((asset) => (
                    <tr key={asset.id} className={selectedAssetId === asset.id ? 'row-selected' : ''}>
                      <td>
                        <strong>{asset.asset_tag}</strong>
                        <p className="table-subtext asset-name-cell" title={asset.name}>{asset.name}</p>
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
                        <button
                          type="button"
                          className="ghost-button row-action"
                          onClick={() => {
                            setSelectedAssetId(asset.id)
                            setSelectedAssetFallback(asset)
                          }}
                        >
                          Детали
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      ) : null}

      {selectedAssetId ? (
        <div className="modal-backdrop" role="presentation" onClick={closeAssetDetail}>
          <section className="modal-card modal-card-xl" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <div>
                <p className="eyebrow">КАРТОЧКА АКТИВА</p>
                <h2>{selectedAsset?.asset_tag ?? 'Загрузка...'}</h2>
                <p className="modal-subtitle asset-detail-title">{selectedAsset?.name ?? 'Получаем детальную информацию по активу...'}</p>
              </div>
              <button type="button" className="ghost-button" onClick={closeAssetDetail}>Закрыть</button>
            </div>

            {selectedAssetQuery.isPending && !selectedAsset ? <p className="state-panel state-panel-loading">Загрузка карточки актива…</p> : null}
            {selectedAssetQuery.isError && !selectedAsset ? <p className="error-message">Не удалось загрузить карточку актива.</p> : null}
            {selectedAssetQuery.isError && selectedAsset ? (
              <p className="state-panel state-panel-error">Детальная карточка временно недоступна. Показаны данные из таблицы активов.</p>
            ) : null}

            {selectedAsset ? (
              <div className="ticket-detail-grid">
                <section className="ticket-detail-panel">
                  <h3>Основные данные</h3>
                  <div className="detail-fields">
                    <div><span>Asset tag</span><strong>{selectedAsset.asset_tag}</strong></div>
                    <div><span>Инвентарный номер</span><strong>{selectedAsset.inventory_number ?? '—'}</strong></div>
                    <div><span>Наименование</span><strong className="asset-detail-value-long">{selectedAsset.name}</strong></div>
                    <div><span>Тип</span><strong>{typeLabels[selectedAsset.type ?? selectedAsset.asset_type] ?? selectedAsset.type ?? selectedAsset.asset_type}</strong></div>
                    <div><span>Оригинальный тип</span><strong>{selectedAsset.original_type ?? '—'}</strong></div>
                    <div><span>Производитель</span><strong>{selectedAsset.manufacturer ?? '—'}</strong></div>
                    <div><span>Модель</span><strong>{selectedAsset.model ?? '—'}</strong></div>
                    <div><span>Серийный номер</span><strong>{selectedAsset.serial_number ?? '—'}</strong></div>
                    <div><span>Источник</span><strong>{sourceLabel(selectedAsset.source)}</strong></div>
                    <div><span>Назначен</span><strong>{selectedAsset.assigned_to_name ?? 'Не назначен'}</strong></div>
                    <div><span>МОЛ / отдел</span><strong>{selectedAsset.department ?? '—'}</strong></div>
                    <div><span>Локация</span><strong>{normalizeLocationValue(selectedAsset.location)}</strong></div>
                    <div><span>Год закупки</span><strong>{selectedAsset.purchase_year ?? '—'}</strong></div>
                    <div><span>Статус</span><strong><AssetStatusBadge status={selectedAsset.status} /></strong></div>
                    <div>
                      <span>Verification</span>
                      <strong className="asset-detail-inline-badges">
                        {verificationLabel(selectedAsset.verification_status)}
                        {String(selectedAsset.verification_status ?? '').toLowerCase() === 'needs_location' ? (
                          <span className="badge badge-warning">Требует кабинета</span>
                        ) : null}
                      </strong>
                    </div>
                    <div><span>Здоровье</span><strong>{selectedAsset.health ?? '—'}</strong></div>
                    <div><span>Гарантия до</span><strong>{formatDate(selectedAsset.warranty_until)}</strong></div>
                    <div><span>Импортирован</span><strong>{formatDateTime(selectedAsset.imported_at)}</strong></div>
                    <div><span>Source batch ID</span><strong className="asset-detail-value-long">{selectedAsset.source_batch_id ?? '—'}</strong></div>
                  </div>
                </section>

                <section className="ticket-detail-panel">
                  <h3>Связанные заявки</h3>
                  {relatedTicketsQuery.isPending ? <p className="state-panel state-panel-loading">Загрузка связанных заявок…</p> : null}
                  {relatedTicketsQuery.isError ? <p className="error-message">Не удалось получить связанные заявки.</p> : null}
                  {!relatedTicketsQuery.isPending && !relatedTicketsQuery.isError && relatedTickets.length === 0 ? (
                    <p className="state-panel state-panel-empty">Связанных заявок пока нет.</p>
                  ) : null}
                  {!relatedTicketsQuery.isPending && !relatedTicketsQuery.isError && relatedTickets.length > 0 ? (
                    <div className="activity-list">
                      {relatedTickets.map((ticket) => (
                        <article className="activity-item" key={ticket.id}>
                          <header>
                            <strong>{ticket.ticket_number ?? ticket.id.slice(0, 8)}</strong>
                            <span>{ticket.sla_status ?? '—'}</span>
                          </header>
                          <p>{ticket.title}</p>
                          <small>{ticket.priority} · {ticket.status}</small>
                        </article>
                      ))}
                    </div>
                  ) : null}
                </section>
              </div>
            ) : null}
          </section>
        </div>
      ) : null}
    </AppShell>
  )
}
