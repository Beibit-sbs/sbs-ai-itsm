import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchAsset, fetchAssetTickets, fetchAssets, type AssetTicket } from '../api/client'
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
}

const typeLabels: Record<string, string> = {
  Laptop: 'Ноутбук',
  Desktop: 'Компьютер',
  Printer: 'Принтер',
  Monitor: 'Монитор',
  Server: 'Сервер',
  'Network Switch': 'Коммутатор',
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('ru-RU', { dateStyle: 'medium' }).format(new Date(value))
}

function AssetStatusBadge({ status }: { status: string }) {
  return <span className={`asset-status asset-status-${status}`}>{statusLabels[status] ?? status}</span>
}

export default function AssetsPage() {
  const { session } = useAuth()
  const [search, setSearch] = useState('')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [statusFilter, setStatusFilter] = useState('ALL')
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null)

  const assetsQuery = useQuery({
    queryKey: ['assets', session?.access_token],
    queryFn: () => fetchAssets(session?.access_token ?? ''),
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

  const assets = assetsQuery.data ?? []

  useEffect(() => {
    if (!selectedAssetId && assets.length > 0) {
      setSelectedAssetId(assets[0].id)
    }
  }, [assets, selectedAssetId])

  const filteredAssets = useMemo(() => {
    const query = search.trim().toLowerCase()
    return assets.filter((asset) => {
      const matchesSearch =
        !query ||
        [asset.asset_tag, asset.name, asset.serial_number, asset.inventory_number, asset.manufacturer, asset.model, asset.assigned_to_name, asset.department]
          .filter(Boolean)
          .some((value) => String(value).toLowerCase().includes(query))
      const matchesType = typeFilter === 'ALL' || (asset.type ?? asset.asset_type) === typeFilter
      const matchesStatus = statusFilter === 'ALL' || asset.status === statusFilter
      return matchesSearch && matchesType && matchesStatus
    })
  }, [assets, search, typeFilter, statusFilter])

  const typeOptions = useMemo(() => Array.from(new Set(assets.map((asset) => asset.type ?? asset.asset_type))).sort(), [assets])
  const problemAssets = assets.filter((asset) => ['broken', 'in_repair', 'maintenance'].includes(asset.status)).length
  const warrantySoon = assets.filter((asset) => asset.warranty_until && new Date(asset.warranty_until).getTime() < Date.now() + 1000 * 60 * 60 * 24 * 45).length

  const selectedAsset = selectedAssetQuery.data
  const relatedTickets: AssetTicket[] = relatedTicketsQuery.data ?? []

  return (
    <AppShell title="Активы" subtitle="Инвентаризация, привязка к заявкам и срокам обслуживания уже читаются из backend.">
      <section className="foundation-card">
        <div>
          <p className="eyebrow">ASSET MANAGEMENT</p>
          <h2>Реестр оборудования</h2>
          <p>Этот раздел показывает не только список, но и контекст: кто назначен на актив, когда заканчивается гарантия и какие заявки связаны с ним.</p>
        </div>
        <div className="status-column">
          <HealthBadge />
          <div className="status-list">
            <span>✓ Asset detail view</span>
            <span>✓ Warranty awareness</span>
            <span>✓ Tickets linked to equipment</span>
          </div>
        </div>
      </section>

      <section className="metric-grid assets-metrics">
        <article className="metric-card">
          <span>Проблемные активы</span>
          <strong>{assetsQuery.isPending ? '…' : problemAssets}</strong>
          <p>Неисправные или находящиеся в ремонте устройства.</p>
        </article>
        <article className="metric-card">
          <span>Скоро окончится гарантия</span>
          <strong>{assetsQuery.isPending ? '…' : warrantySoon}</strong>
          <p>Активы с окном гарантии менее 45 дней.</p>
        </article>
        <article className="metric-card">
          <span>Всего</span>
          <strong>{assetsQuery.isPending ? '…' : assets.length}</strong>
          <p>Текущий инвентарный срез.</p>
        </article>
        <article className="metric-card">
          <span>Статус API</span>
          <strong>{assetsQuery.isError ? 'Ошибка' : 'OK'}</strong>
          <p>{assetsQuery.isError ? 'Не удалось загрузить активы.' : 'Backend вернул свежие данные.'}</p>
        </article>
      </section>

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
              {Object.keys(statusLabels).map((status) => (
                <option key={status} value={status}>
                  {statusLabels[status]}
                </option>
              ))}
            </select>
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
                    <div><span>Серийный номер</span><strong>{selectedAsset.serial_number ?? '—'}</strong></div>
                    <div><span>Инв. номер</span><strong>{selectedAsset.inventory_number ?? '—'}</strong></div>
                    <div><span>Производитель</span><strong>{selectedAsset.manufacturer ?? '—'}</strong></div>
                    <div><span>Модель</span><strong>{selectedAsset.model ?? '—'}</strong></div>
                    <div><span>Назначен</span><strong>{selectedAsset.assigned_to_name ?? '—'}</strong></div>
                    <div><span>Отдел</span><strong>{selectedAsset.department ?? '—'}</strong></div>
                    <div><span>Локация</span><strong>{selectedAsset.location}</strong></div>
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
