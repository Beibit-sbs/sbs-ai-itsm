import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createSoftwareInstallation,
  createSoftwareLicense,
  createSoftwareProduct,
  fetchAssets,
  fetchSoftwareAssetDashboard,
  fetchSoftwareInstallations,
  fetchSoftwareLicenses,
  fetchSoftwareProducts,
  fetchTenants,
  reconcileSoftwareAssets,
  updateSoftwareInstallation,
  updateSoftwareProduct,
  type SoftwareComplianceState,
  type SoftwareInstallation,
  type SoftwareProduct,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import type { UiMessageKey } from '../i18n/catalog'

type View = 'OVERVIEW' | 'CATALOG' | 'LICENSES' | 'INSTALLATIONS' | 'COMPLIANCE'

const statusKeys: Record<SoftwareComplianceState, UiMessageKey> = {
  COMPLIANT: 'sam.status.COMPLIANT',
  UNDERUTILIZED: 'sam.status.UNDERUTILIZED',
  OVER_DEPLOYED: 'sam.status.OVER_DEPLOYED',
  UNLICENSED: 'sam.status.UNLICENSED',
  EXPIRED: 'sam.status.EXPIRED',
  UNAUTHORIZED: 'sam.status.UNAUTHORIZED',
  PROHIBITED: 'sam.status.PROHIBITED',
}

function badgeClass(status: string) {
  if (status === 'COMPLIANT' || status === 'AUTHORIZED') return 'badge badge-positive'
  if (status === 'UNDERUTILIZED' || status === 'EXEMPTED' || status === 'UPCOMING') return 'badge badge-warning'
  return 'badge badge-danger'
}

function dateValue(value: string) {
  return value ? new Date(`${value}T12:00:00`).toISOString() : undefined
}

export default function SoftwareAssetsPage() {
  const { session } = useAuth()
  const { t, formatDateTime, formatCurrency } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const root = session?.user.role === 'saas_root'
  const permissions = useMemo(() => new Set(session?.user.permissions ?? []), [session?.user.permissions])
  const can = (permission: string) => root || permissions.has(permission)
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [view, setView] = useState<View>('OVERVIEW')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')

  const [productForm, setProductForm] = useState({
    name: '', publisher: '', version: '', edition: '', category: '',
    is_prohibited: false, prohibited_reason: '',
  })
  const [licenseForm, setLicenseForm] = useState({
    product_id: '', license_reference: '', license_type: 'DEVICE',
    purchased_quantity: '1', vendor: '', contract_reference: '',
    expires_at: '', renewal_at: '', unit_cost: '0', currency: 'KZT', auto_renew: false,
  })
  const [installationForm, setInstallationForm] = useState({
    product_id: '', asset_id: '', detected_version: '', source: 'MANUAL',
    authorization_status: 'AUTHORIZED' as SoftwareInstallation['authorization_status'],
    authorization_reason: '',
  })

  const tenantsQuery = useQuery({
    queryKey: ['sam-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token) && root,
    retry: false,
  })

  useEffect(() => {
    if (root && !tenantId && tenantsQuery.data?.[0]) setTenantId(tenantsQuery.data[0].id)
  }, [root, tenantId, tenantsQuery.data])

  const queryEnabled = Boolean(token) && (!root || Boolean(tenantId))
  const selectedTenant = root ? tenantId : undefined
  const dashboardQuery = useQuery({
    queryKey: ['sam-dashboard', token, selectedTenant],
    queryFn: () => fetchSoftwareAssetDashboard(token, selectedTenant),
    enabled: queryEnabled && can('sam.read'),
    retry: false,
  })
  const productsQuery = useQuery({
    queryKey: ['sam-products', token, selectedTenant],
    queryFn: () => fetchSoftwareProducts(token, selectedTenant),
    enabled: queryEnabled && can('sam.read'),
    retry: false,
  })
  const licensesQuery = useQuery({
    queryKey: ['sam-licenses', token, selectedTenant],
    queryFn: () => fetchSoftwareLicenses(token, selectedTenant),
    enabled: queryEnabled && can('sam.read'),
    retry: false,
  })
  const installationsQuery = useQuery({
    queryKey: ['sam-installations', token, selectedTenant],
    queryFn: () => fetchSoftwareInstallations(token, selectedTenant),
    enabled: queryEnabled && can('sam.read'),
    retry: false,
  })
  const assetsQuery = useQuery({
    queryKey: ['sam-assets', token, tenantId],
    queryFn: () => fetchAssets(token, { page_size: 200 }),
    enabled: queryEnabled && can('sam.installations.manage'),
    retry: false,
  })

  const assets = useMemo(
    () => (assetsQuery.data ?? []).filter((item) => !root || item.tenant_id === tenantId),
    [assetsQuery.data, root, tenantId],
  )
  const products = productsQuery.data ?? []

  useEffect(() => {
    if (!licenseForm.product_id && products[0]) {
      setLicenseForm((current) => ({ ...current, product_id: products[0].id }))
    }
    if (!installationForm.product_id && products[0]) {
      setInstallationForm((current) => ({ ...current, product_id: products[0].id }))
    }
  }, [products, licenseForm.product_id, installationForm.product_id])

  useEffect(() => {
    if (!installationForm.asset_id && assets[0]) {
      setInstallationForm((current) => ({ ...current, asset_id: assets[0].id }))
    }
  }, [assets, installationForm.asset_id])

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['sam-dashboard'] }),
      queryClient.invalidateQueries({ queryKey: ['sam-products'] }),
      queryClient.invalidateQueries({ queryKey: ['sam-licenses'] }),
      queryClient.invalidateQueries({ queryKey: ['sam-installations'] }),
    ])
  }
  const success = async (message = t('sam.operationSaved')) => {
    setError('')
    setNotice(message)
    await refresh()
  }
  const failure = (value: unknown) => {
    setNotice('')
    setError(value instanceof Error ? value.message : t('sam.operationFailed'))
  }

  const productMutation = useMutation({
    mutationFn: () => createSoftwareProduct(token, {
      tenant_id: selectedTenant,
      name: productForm.name,
      publisher: productForm.publisher,
      version: productForm.version,
      edition: productForm.edition || undefined,
      category: productForm.category || undefined,
      is_prohibited: productForm.is_prohibited,
      prohibited_reason: productForm.prohibited_reason || undefined,
    }),
    onSuccess: async () => {
      setProductForm({ name: '', publisher: '', version: '', edition: '', category: '', is_prohibited: false, prohibited_reason: '' })
      await success()
    },
    onError: failure,
  })
  const productPolicyMutation = useMutation({
    mutationFn: (product: SoftwareProduct) => updateSoftwareProduct(token, product, {
      is_prohibited: !product.is_prohibited,
      prohibited_reason: product.is_prohibited ? undefined : product.prohibited_reason || t('sam.prohibited'),
      reason: product.is_prohibited ? t('sam.allow') : t('sam.prohibit'),
    }),
    onSuccess: () => success(),
    onError: failure,
  })
  const licenseMutation = useMutation({
    mutationFn: () => createSoftwareLicense(token, {
      tenant_id: selectedTenant,
      product_id: licenseForm.product_id,
      license_reference: licenseForm.license_reference,
      license_type: licenseForm.license_type,
      purchased_quantity: Number(licenseForm.purchased_quantity),
      vendor: licenseForm.vendor || undefined,
      contract_reference: licenseForm.contract_reference || undefined,
      expires_at: dateValue(licenseForm.expires_at),
      renewal_at: dateValue(licenseForm.renewal_at),
      unit_cost: Number(licenseForm.unit_cost),
      currency: licenseForm.currency.toUpperCase(),
      auto_renew: licenseForm.auto_renew,
    }),
    onSuccess: async () => {
      setLicenseForm((current) => ({ ...current, license_reference: '', purchased_quantity: '1', vendor: '', contract_reference: '', expires_at: '', renewal_at: '', unit_cost: '0' }))
      await success()
    },
    onError: failure,
  })
  const installationMutation = useMutation({
    mutationFn: () => createSoftwareInstallation(token, {
      tenant_id: selectedTenant,
      product_id: installationForm.product_id,
      asset_id: installationForm.asset_id,
      detected_version: installationForm.detected_version || undefined,
      source: installationForm.source,
      authorization_status: installationForm.authorization_status,
      authorization_reason: installationForm.authorization_reason || undefined,
    }),
    onSuccess: async () => {
      setInstallationForm((current) => ({ ...current, detected_version: '', authorization_reason: '' }))
      await success()
    },
    onError: failure,
  })
  const installationUpdateMutation = useMutation({
    mutationFn: ({ item, action }: { item: SoftwareInstallation; action: 'AUTHORIZE' | 'REMOVE' }) => (
      updateSoftwareInstallation(token, item, action === 'AUTHORIZE'
        ? { authorization_status: 'AUTHORIZED', authorization_reason: t('sam.authorize'), reason: t('sam.authorize') }
        : { status: 'REMOVED', reason: t('sam.remove') })
    ),
    onSuccess: () => success(),
    onError: failure,
  })
  const reconcileMutation = useMutation({
    mutationFn: () => reconcileSoftwareAssets(token, selectedTenant),
    onSuccess: (result) => success(t('sam.expiredUpdated', { count: result.expired_licenses_updated })),
    onError: failure,
  })

  const submit = (event: FormEvent, mutation: { mutate: () => void }) => {
    event.preventDefault()
    mutation.mutate()
  }
  const views: Array<{ id: View; key: UiMessageKey }> = [
    { id: 'OVERVIEW', key: 'sam.overview' },
    { id: 'CATALOG', key: 'sam.catalog' },
    { id: 'LICENSES', key: 'sam.licenses' },
    { id: 'INSTALLATIONS', key: 'sam.installations' },
    { id: 'COMPLIANCE', key: 'sam.compliance' },
  ]
  const summary = dashboardQuery.data?.summary
  const costLines = (values: Record<string, number> | undefined) => (
    Object.entries(values ?? {}).map(([currency, value]) => formatCurrency(value, currency)).join(' · ') || '—'
  )

  return (
    <AppShell title={t('page.sam.title')} subtitle={t('page.sam.subtitle')}>
      <div className="module-content sam-page">
        {root && (
          <section className="section-card">
            <label>
              <span>{t('sam.organization')}</span>
              <select value={tenantId} onChange={(event) => setTenantId(event.target.value)}>
                <option value="">—</option>
                {(tenantsQuery.data ?? []).map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}
              </select>
            </label>
          </section>
        )}

        <QueryFailureNotice
          title={t('sam.operationFailed')}
          sources={[
            { label: t('sam.overview'), query: dashboardQuery },
            { label: t('sam.catalog'), query: productsQuery },
            { label: t('sam.licenses'), query: licensesQuery },
            { label: t('sam.installations'), query: installationsQuery },
          ]}
        />
        {notice && <div className="alert alert-success" role="status">{notice}</div>}
        {error && <div className="alert alert-danger" role="alert">{error}</div>}

        <div className="module-subnav" role="tablist" aria-label={t('page.sam.title')}>
          {views.map((item) => (
            <button key={item.id} type="button" role="tab" aria-selected={view === item.id} className={`module-subnav-tab ${view === item.id ? 'active' : ''}`} onClick={() => setView(item.id)}>
              {t(item.key)}
            </button>
          ))}
          {can('sam.reconcile') && (
            <button type="button" className="primary-button" disabled={reconcileMutation.isPending || !queryEnabled} onClick={() => reconcileMutation.mutate()}>
              {t('sam.reconcile')}
            </button>
          )}
        </div>

        {view === 'OVERVIEW' && (
          <>
            <div className="metric-grid">
              <article className="metric-card"><span>{t('sam.products')}</span><strong>{summary?.products ?? 0}</strong></article>
              <article className="metric-card"><span>{t('sam.activeInstallations')}</span><strong>{summary?.active_installations ?? 0}</strong></article>
              <article className="metric-card"><span>{t('sam.noncompliant')}</span><strong>{summary?.noncompliant_products ?? 0}</strong></article>
              <article className="metric-card"><span>{t('sam.unauthorized')}</span><strong>{summary?.unauthorized_installations ?? 0}</strong></article>
              <article className="metric-card"><span>{t('sam.renewals')}</span><strong>{summary?.upcoming_renewals ?? 0}</strong></article>
              <article className="metric-card"><span>{t('sam.purchaseCost')}</span><strong>{costLines(summary?.purchase_cost_by_currency)}</strong></article>
              <article className="metric-card"><span>{t('sam.costAtRisk')}</span><strong>{costLines(summary?.cost_at_risk_by_currency)}</strong></article>
            </div>
            <section className="section-card">
              <h2 className="section-title">{t('sam.upcomingRenewals')}</h2>
              {(dashboardQuery.data?.renewals.length ?? 0) === 0 ? <p className="empty-state">{t('sam.noData')}</p> : (
                <div className="ticket-table-wrap"><table className="ticket-table"><thead><tr><th>{t('sam.product')}</th><th>{t('sam.licenseReference')}</th><th>{t('sam.renewal')}</th><th>{t('common.status')}</th><th>{t('common.cost')}</th></tr></thead><tbody>
                  {dashboardQuery.data?.renewals.map((item) => <tr key={item.license_id}><td>{item.product_name}</td><td>{item.license_reference}</td><td>{formatDateTime(item.due_at)}</td><td><span className={badgeClass(item.status)}>{item.status}</span></td><td>{formatCurrency(item.unit_cost * item.purchased_quantity, item.currency)}</td></tr>)}
                </tbody></table></div>
              )}
            </section>
          </>
        )}

        {view === 'CATALOG' && (
          <>
            {can('sam.catalog.manage') && <section className="section-card"><h2 className="section-title">{t('sam.createProduct')}</h2><form className="form-grid" onSubmit={(event) => submit(event, productMutation)}>
              <label><span>{t('sam.name')}</span><input required value={productForm.name} onChange={(event) => setProductForm({ ...productForm, name: event.target.value })} /></label>
              <label><span>{t('sam.publisher')}</span><input required value={productForm.publisher} onChange={(event) => setProductForm({ ...productForm, publisher: event.target.value })} /></label>
              <label><span>{t('sam.version')}</span><input required value={productForm.version} onChange={(event) => setProductForm({ ...productForm, version: event.target.value })} /></label>
              <label><span>{t('sam.edition')}</span><input value={productForm.edition} onChange={(event) => setProductForm({ ...productForm, edition: event.target.value })} /></label>
              <label><span>{t('sam.category')}</span><input value={productForm.category} onChange={(event) => setProductForm({ ...productForm, category: event.target.value })} /></label>
              <label><span>{t('sam.prohibited')}</span><input type="checkbox" checked={productForm.is_prohibited} onChange={(event) => setProductForm({ ...productForm, is_prohibited: event.target.checked })} /></label>
              {productForm.is_prohibited && <label><span>{t('sam.reason')}</span><input required value={productForm.prohibited_reason} onChange={(event) => setProductForm({ ...productForm, prohibited_reason: event.target.value })} /></label>}
              <button type="submit" className="primary-button" disabled={productMutation.isPending}>{t('sam.createProduct')}</button>
            </form></section>}
            <section className="section-card"><div className="ticket-table-wrap"><table className="ticket-table"><thead><tr><th>{t('sam.name')}</th><th>{t('sam.publisher')}</th><th>{t('sam.version')}</th><th>{t('sam.category')}</th><th>{t('common.status')}</th><th></th></tr></thead><tbody>
              {products.map((product) => <tr key={product.id}><td>{product.name}{product.edition ? ` · ${product.edition}` : ''}</td><td>{product.publisher}</td><td>{product.version}</td><td>{product.category ?? '—'}</td><td><span className={product.is_prohibited ? 'badge badge-danger' : 'badge badge-positive'}>{product.is_prohibited ? t('sam.prohibited') : product.status}</span></td><td>{can('sam.catalog.manage') && <button type="button" className="ghost-button" onClick={() => productPolicyMutation.mutate(product)}>{product.is_prohibited ? t('sam.allow') : t('sam.prohibit')}</button>}</td></tr>)}
            </tbody></table></div>{products.length === 0 && <p className="empty-state">{t('sam.noData')}</p>}</section>
          </>
        )}

        {view === 'LICENSES' && (
          <>
            {can('sam.licenses.manage') && <section className="section-card"><h2 className="section-title">{t('sam.createLicense')}</h2><form className="form-grid" onSubmit={(event) => submit(event, licenseMutation)}>
              <label><span>{t('sam.product')}</span><select required value={licenseForm.product_id} onChange={(event) => setLicenseForm({ ...licenseForm, product_id: event.target.value })}>{products.map((product) => <option key={product.id} value={product.id}>{product.name} · {product.version}</option>)}</select></label>
              <label><span>{t('sam.licenseReference')}</span><input required value={licenseForm.license_reference} onChange={(event) => setLicenseForm({ ...licenseForm, license_reference: event.target.value })} /></label>
              <label><span>{t('sam.licenseType')}</span><select value={licenseForm.license_type} onChange={(event) => setLicenseForm({ ...licenseForm, license_type: event.target.value })}>{['DEVICE', 'NAMED_USER', 'CONCURRENT', 'SUBSCRIPTION', 'PERPETUAL', 'OEM', 'ENTERPRISE'].map((type) => <option key={type}>{type}</option>)}</select></label>
              <label><span>{t('sam.quantity')}</span><input required type="number" min="0" value={licenseForm.purchased_quantity} onChange={(event) => setLicenseForm({ ...licenseForm, purchased_quantity: event.target.value })} /></label>
              <label><span>{t('sam.vendor')}</span><input value={licenseForm.vendor} onChange={(event) => setLicenseForm({ ...licenseForm, vendor: event.target.value })} /></label>
              <label><span>{t('sam.contract')}</span><input value={licenseForm.contract_reference} onChange={(event) => setLicenseForm({ ...licenseForm, contract_reference: event.target.value })} /></label>
              <label><span>{t('sam.expiry')}</span><input type="date" value={licenseForm.expires_at} onChange={(event) => setLicenseForm({ ...licenseForm, expires_at: event.target.value })} /></label>
              <label><span>{t('sam.renewal')}</span><input type="date" value={licenseForm.renewal_at} onChange={(event) => setLicenseForm({ ...licenseForm, renewal_at: event.target.value })} /></label>
              <label><span>{t('sam.unitCost')}</span><input type="number" min="0" step="0.01" value={licenseForm.unit_cost} onChange={(event) => setLicenseForm({ ...licenseForm, unit_cost: event.target.value })} /></label>
              <label><span>{t('sam.currency')}</span><select value={licenseForm.currency} onChange={(event) => setLicenseForm({ ...licenseForm, currency: event.target.value })}>{['KZT', 'USD', 'EUR', 'RUB'].map((currency) => <option key={currency}>{currency}</option>)}</select></label>
              <label><span>{t('sam.autoRenew')}</span><input type="checkbox" checked={licenseForm.auto_renew} onChange={(event) => setLicenseForm({ ...licenseForm, auto_renew: event.target.checked })} /></label>
              <button type="submit" className="primary-button" disabled={licenseMutation.isPending || !licenseForm.product_id}>{t('sam.createLicense')}</button>
            </form></section>}
            <section className="section-card"><div className="ticket-table-wrap"><table className="ticket-table"><thead><tr><th>{t('sam.product')}</th><th>{t('sam.licenseReference')}</th><th>{t('sam.licenseType')}</th><th>{t('sam.purchased')}</th><th>{t('sam.expiry')}</th><th>{t('common.cost')}</th><th>{t('common.status')}</th></tr></thead><tbody>
              {(licensesQuery.data ?? []).map((item) => <tr key={item.id}><td>{item.product_name}</td><td>{item.license_reference}<small className="table-subtext">{item.contract_reference ?? item.vendor ?? ''}</small></td><td>{item.license_type}</td><td>{item.purchased_quantity}</td><td>{formatDateTime(item.expires_at)}</td><td>{formatCurrency(Number(item.unit_cost) * item.purchased_quantity, item.currency)}</td><td><span className={item.status === 'ACTIVE' ? 'badge badge-positive' : 'badge badge-danger'}>{item.status}</span></td></tr>)}
            </tbody></table></div>{licensesQuery.data?.length === 0 && <p className="empty-state">{t('sam.noData')}</p>}</section>
          </>
        )}

        {view === 'INSTALLATIONS' && (
          <>
            {can('sam.installations.manage') && <section className="section-card"><h2 className="section-title">{t('sam.createInstallation')}</h2><form className="form-grid" onSubmit={(event) => submit(event, installationMutation)}>
              <label><span>{t('sam.product')}</span><select required value={installationForm.product_id} onChange={(event) => setInstallationForm({ ...installationForm, product_id: event.target.value })}>{products.map((product) => <option key={product.id} value={product.id}>{product.name} · {product.version}</option>)}</select></label>
              <label><span>{t('sam.asset')}</span><select required value={installationForm.asset_id} onChange={(event) => setInstallationForm({ ...installationForm, asset_id: event.target.value })}>{assets.map((asset) => <option key={asset.id} value={asset.id}>{asset.asset_tag} · {asset.name}</option>)}</select></label>
              <label><span>{t('sam.version')}</span><input value={installationForm.detected_version} onChange={(event) => setInstallationForm({ ...installationForm, detected_version: event.target.value })} /></label>
              <label><span>{t('sam.source')}</span><select value={installationForm.source} onChange={(event) => setInstallationForm({ ...installationForm, source: event.target.value })}>{['MANUAL', 'INTUNE', 'SCCM', 'LANSWEEPER', 'IMPORT'].map((source) => <option key={source}>{source}</option>)}</select></label>
              <label><span>{t('sam.authorization')}</span><select value={installationForm.authorization_status} onChange={(event) => setInstallationForm({ ...installationForm, authorization_status: event.target.value as SoftwareInstallation['authorization_status'] })}>{['AUTHORIZED', 'UNAUTHORIZED', 'EXEMPTED'].map((value) => <option key={value}>{value}</option>)}</select></label>
              <label><span>{t('sam.reason')}</span><input value={installationForm.authorization_reason} onChange={(event) => setInstallationForm({ ...installationForm, authorization_reason: event.target.value })} /></label>
              <button type="submit" className="primary-button" disabled={installationMutation.isPending || !installationForm.product_id || !installationForm.asset_id}>{t('sam.createInstallation')}</button>
            </form></section>}
            <section className="section-card"><div className="ticket-table-wrap"><table className="ticket-table"><thead><tr><th>{t('sam.product')}</th><th>{t('sam.asset')}</th><th>{t('sam.version')}</th><th>{t('sam.source')}</th><th>{t('sam.authorization')}</th><th>{t('sam.lastSeen')}</th><th></th></tr></thead><tbody>
              {(installationsQuery.data ?? []).map((item) => <tr key={item.id}><td>{item.product_name}</td><td>{item.asset_tag} · {item.asset_name}</td><td>{item.detected_version ?? '—'}</td><td>{item.source}</td><td><span className={badgeClass(item.authorization_status)}>{t(`sam.status.${item.authorization_status}` as UiMessageKey)}</span></td><td>{formatDateTime(item.last_seen_at)}</td><td>{can('sam.installations.manage') && item.status === 'ACTIVE' && <div className="button-row">{item.authorization_status === 'UNAUTHORIZED' && <button type="button" className="ghost-button" onClick={() => installationUpdateMutation.mutate({ item, action: 'AUTHORIZE' })}>{t('sam.authorize')}</button>}<button type="button" className="ghost-button" onClick={() => installationUpdateMutation.mutate({ item, action: 'REMOVE' })}>{t('sam.remove')}</button></div>}</td></tr>)}
            </tbody></table></div>{installationsQuery.data?.length === 0 && <p className="empty-state">{t('sam.noData')}</p>}</section>
          </>
        )}

        {view === 'COMPLIANCE' && <section className="section-card"><div className="ticket-table-wrap"><table className="ticket-table"><thead><tr><th>{t('sam.product')}</th><th>{t('sam.purchased')}</th><th>{t('sam.assigned')}</th><th>{t('sam.detected')}</th><th>{t('sam.available')}</th><th>{t('sam.shortfall')}</th><th>{t('common.status')}</th><th>{t('sam.costAtRisk')}</th></tr></thead><tbody>
          {(dashboardQuery.data?.positions ?? []).map((item) => <tr key={item.product_id}><td>{item.name}<small className="table-subtext">{item.publisher} · {item.version}</small></td><td>{item.purchased_quantity}</td><td>{item.assigned_quantity}</td><td>{item.detected_quantity}</td><td>{item.available_quantity}</td><td>{item.shortfall_quantity}</td><td><span className={badgeClass(item.compliance_state)}>{t(statusKeys[item.compliance_state])}</span></td><td>{costLines(item.cost_at_risk_by_currency)}</td></tr>)}
        </tbody></table></div>{dashboardQuery.data?.positions.length === 0 && <p className="empty-state">{t('sam.allCompliant')}</p>}</section>}
      </div>
    </AppShell>
  )
}
