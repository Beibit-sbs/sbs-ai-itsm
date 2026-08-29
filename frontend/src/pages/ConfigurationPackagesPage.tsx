import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  applyConfigurationDeployment,
  buildConfigurationPackageVersion,
  createConfigurationDeployment,
  createConfigurationPackage,
  decideConfigurationDeployment,
  exportConfigurationPackageVersion,
  fetchConfigurationDeployments,
  fetchConfigurationPackageDashboard,
  fetchConfigurationPackageMeta,
  fetchConfigurationPackages,
  fetchConfigurationPackageVersions,
  fetchTenants,
  importConfigurationPackageArtifact,
  requestConfigurationDeploymentApproval,
  rollbackConfigurationDeployment,
  sealConfigurationPackageVersion,
  type ConfigurationArtifact,
  type ConfigurationDeployment,
  type ConfigurationPackageVersion,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import AppShell from '../components/AppShell'
import QueryFailureNotice from '../components/QueryFailureNotice'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { useLocalizedDefaultState } from '../experience/useLocalizedDefaultState'

type View = 'packages' | 'deployments' | 'import'

const componentLabels: Record<string, string> = {
  catalog_category: 'Категории каталога',
  catalog_service: 'Сервисы каталога',
  catalog_offering: 'Предложения услуг',
  catalog_item: 'Элементы каталога',
  sla_calendar: 'Рабочие календари SLA',
  sla_policy: 'Политики SLA',
  notification_template: 'Шаблоны уведомлений',
  external_system: 'Внешние системы без секретов',
  integration_mapping: 'Маппинги интеграций',
  webhook_endpoint: 'Webhook endpoints без секретов',
  workflow: 'Опубликованные workflows',
  custom_field_set: 'Опубликованные custom fields',
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Операция не выполнена'
}

function shortHash(value: string | null | undefined) {
  return value ? `${value.slice(0, 10)}…${value.slice(-6)}` : '—'
}

function downloadArtifact(artifact: ConfigurationArtifact) {
  const code = artifact.manifest.package.code.replace(/[^a-z0-9_.-]/gi, '-')
  const blob = new Blob([JSON.stringify(artifact, null, 2)], {
    type: 'application/json',
  })
  const href = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = href
  link.download = `${code}-v${artifact.manifest.package.version}.sbs-config.json`
  link.click()
  URL.revokeObjectURL(href)
}

export default function ConfigurationPackagesPage() {
  const { session } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const can = (permission: string) => isRoot || permissions.has(permission)
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const [view, setView] = useState<View>('packages')
  const [selectedPackageId, setSelectedPackageId] = useState('')
  const [selectedVersionId, setSelectedVersionId] = useState('')
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [createForm, setCreateForm] = useState({
    code: '',
    name: '',
    description: '',
  })
  const [sourceEnvironment, setSourceEnvironment] = useState('local')
  const [changeSummary, setChangeSummary] = useLocalizedDefaultState(
    'Подготовка конфигурации для переноса на сервер',
  )
  const [selectedTypes, setSelectedTypes] = useState<string[]>([])
  const [targetEnvironment, setTargetEnvironment] = useState('staging')
  const [deploymentReason, setDeploymentReason] = useLocalizedDefaultState(
    'Продвижение проверенной конфигурации',
  )
  const [artifactText, setArtifactText] = useState('')
  const [importSummary, setImportSummary] = useLocalizedDefaultState(
    'Импорт подписанного пакета конфигурации',
  )

  const tenantsQuery = useQuery({
    queryKey: ['configuration-packages-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot),
  })
  useEffect(() => {
    if (isRoot && !tenantId && tenantsQuery.data?.length) {
      setTenantId(tenantsQuery.data[0].id)
    }
  }, [isRoot, tenantId, tenantsQuery.data])
  const scopedTenant = isRoot ? tenantId || null : session?.user.tenant_id ?? null
  const scopeReady = Boolean(token && scopedTenant)

  const metaQuery = useQuery({
    queryKey: ['configuration-package-meta', token],
    queryFn: () => fetchConfigurationPackageMeta(token),
    enabled: Boolean(token) && can('configuration.packages.read'),
    staleTime: 300_000,
  })
  useEffect(() => {
    if (!selectedTypes.length && metaQuery.data?.supported_component_types.length) {
      setSelectedTypes(metaQuery.data.supported_component_types)
    }
  }, [metaQuery.data, selectedTypes.length])
  const dashboardQuery = useQuery({
    queryKey: ['configuration-package-dashboard', token, scopedTenant],
    queryFn: () => fetchConfigurationPackageDashboard(token, scopedTenant),
    enabled: scopeReady && can('configuration.packages.read'),
  })
  const packagesQuery = useQuery({
    queryKey: ['configuration-packages', token, scopedTenant],
    queryFn: () => fetchConfigurationPackages(token, scopedTenant),
    enabled: scopeReady && can('configuration.packages.read'),
  })
  const packages = packagesQuery.data?.items ?? []
  useEffect(() => {
    if (!selectedPackageId && packages.length) {
      setSelectedPackageId(packages[0].id)
    } else if (
      selectedPackageId &&
      !packages.some((item) => item.id === selectedPackageId)
    ) {
      setSelectedPackageId(packages[0]?.id ?? '')
    }
  }, [packages, selectedPackageId])
  const selectedPackage = useMemo(
    () => packages.find((item) => item.id === selectedPackageId) ?? null,
    [packages, selectedPackageId],
  )
  const versionsQuery = useQuery({
    queryKey: ['configuration-package-versions', token, selectedPackageId],
    queryFn: () => fetchConfigurationPackageVersions(token, selectedPackageId),
    enabled: Boolean(token && selectedPackageId),
  })
  const versions = versionsQuery.data?.items ?? []
  useEffect(() => {
    if (!selectedVersionId && versions.length) {
      setSelectedVersionId(versions[0].id)
    } else if (
      selectedVersionId &&
      !versions.some((item) => item.id === selectedVersionId)
    ) {
      setSelectedVersionId(versions[0]?.id ?? '')
    }
  }, [selectedVersionId, versions])
  const selectedVersion = useMemo(
    () => versions.find((item) => item.id === selectedVersionId) ?? null,
    [selectedVersionId, versions],
  )
  const deploymentsQuery = useQuery({
    queryKey: ['configuration-deployments', token, scopedTenant],
    queryFn: () => fetchConfigurationDeployments(token, scopedTenant),
    enabled: scopeReady && can('configuration.deployments.read'),
  })
  const deployments = deploymentsQuery.data?.items ?? []

  async function refresh() {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['configuration-packages'] }),
      queryClient.invalidateQueries({
        queryKey: ['configuration-package-versions'],
      }),
      queryClient.invalidateQueries({
        queryKey: ['configuration-deployments'],
      }),
      queryClient.invalidateQueries({
        queryKey: ['configuration-package-dashboard'],
      }),
    ])
  }

  async function run(label: string, operation: () => Promise<unknown>) {
    setBusy(label)
    setError('')
    setNotice('')
    try {
      await operation()
      await refresh()
    } catch (caught) {
      setError(errorText(caught))
    } finally {
      setBusy('')
    }
  }

  const dashboard = dashboardQuery.data
  const componentTypes = metaQuery.data?.supported_component_types ?? []

  return (
    <LocalizedContent>
    <AppShell
      title="Пакеты конфигурации"
      subtitle="Версионирование, перенос локальной настройки на сервер, dry-run, независимое одобрение и доказуемый rollback."
    >
      <section className="config-packages-hero">
        <div>
          <p className="eyebrow">CONFIGURATION AS A CONTROLLED PRODUCT</p>
          <h2>От локальной настройки к production без ручного копирования</h2>
          <p>
            Пакет фиксирует только переносимую конфигурацию. Учетные данные и
            секреты никогда не экспортируются и привязываются отдельно на
            целевом сервере.
          </p>
        </div>
        {isRoot ? (
          <label>
            Организация
            <select
              value={tenantId}
              onChange={(event) => {
                setTenantId(event.target.value)
                setSelectedPackageId('')
                setSelectedVersionId('')
              }}
            >
              {(tenantsQuery.data ?? []).map((tenant) => (
                <option key={tenant.id} value={tenant.id}>
                  {tenant.name}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </section>

      <section className="config-packages-flow" aria-label="Promotion flow">
        {['Собрать', 'Проверить', 'Запечатать', 'Dry-run', 'Одобрить', 'Применить'].map(
          (label, index) => (
            <div key={label}>
              <span>{index + 1}</span>
              <strong>{label}</strong>
            </div>
          ),
        )}
      </section>

      <section className="config-packages-metrics">
        <article>
          <span>Активные пакеты</span>
          <strong>{dashboard?.active_packages ?? 0}</strong>
        </article>
        <article>
          <span>Запечатанные версии</span>
          <strong>{dashboard?.sealed_versions ?? 0}</strong>
        </article>
        <article>
          <span>Ждут одобрения</span>
          <strong>{dashboard?.pending_approvals ?? 0}</strong>
        </article>
        <article>
          <span>Применено</span>
          <strong>{dashboard?.applied_deployments ?? 0}</strong>
        </article>
        <article>
          <span>Rollback</span>
          <strong>{dashboard?.rolled_back_deployments ?? 0}</strong>
        </article>
      </section>

      <div className="config-packages-tabs">
        {(
          [
            ['packages', 'Пакеты и версии'],
            ['deployments', 'Продвижение'],
            ['import', 'Импорт артефакта'],
          ] as Array<[View, string]>
        ).map(([key, label]) => (
          <button
            className={view === key ? 'active' : ''}
            key={key}
            type="button"
            onClick={() => setView(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {notice ? <div className="success">{notice}</div> : null}
      <QueryFailureNotice
        title="Часть данных Configuration Packages недоступна."
        sources={[
          { label: translate('организации'), query: tenantsQuery },
          { label: 'metadata', query: metaQuery },
          { label: translate('оперативная сводка'), query: dashboardQuery },
          { label: translate('пакеты'), query: packagesQuery },
          { label: translate('версии'), query: versionsQuery },
          { label: 'deployments', query: deploymentsQuery },
        ]}
      />
      {error ? <div className="error" role="alert">{error}</div> : null}

      {view === 'packages' ? (
        <>
          <section className="config-packages-toolbar">
            <div>
              <h3>Управляемые пакеты</h3>
              <p>Каждая версия неизменяема после криптографического seal.</p>
            </div>
            {can('configuration.packages.build') ? (
              <button
                type="button"
                className="primary-button"
                onClick={() => setCreateOpen((value) => !value)}
              >
                {createOpen ? 'Закрыть' : 'Новый пакет'}
              </button>
            ) : null}
          </section>

          {createOpen ? (
            <form
              className="config-packages-create"
              onSubmit={(event) => {
                event.preventDefault()
                void run('create-package', async () => {
                  const created = await createConfigurationPackage(token, {
                    tenant_id: scopedTenant,
                    ...createForm,
                  })
                  setSelectedPackageId(created.id)
                  setCreateOpen(false)
                  setCreateForm({ code: '', name: '', description: '' })
                  setNotice('Пакет создан.')
                })
              }}
            >
              <label>
                Код
                <input
                  required
                  minLength={3}
                  pattern="[a-z][a-z0-9_.-]+"
                  placeholder="service-desk-core"
                  value={createForm.code}
                  onChange={(event) =>
                    setCreateForm((value) => ({
                      ...value,
                      code: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Название
                <input
                  required
                  minLength={2}
                  value={createForm.name}
                  onChange={(event) =>
                    setCreateForm((value) => ({
                      ...value,
                      name: event.target.value,
                    }))
                  }
                />
              </label>
              <label>
                Описание
                <input
                  value={createForm.description}
                  onChange={(event) =>
                    setCreateForm((value) => ({
                      ...value,
                      description: event.target.value,
                    }))
                  }
                />
              </label>
              <button
                type="submit"
                className="primary-button"
                disabled={Boolean(busy)}
              >
                Создать
              </button>
            </form>
          ) : null}

          <section className="config-packages-layout">
            <aside className="config-packages-list">
              {packagesQuery.isLoading ? <p>Загрузка…</p> : null}
              {!packagesQuery.isLoading && !packages.length ? (
                <p className="empty-state">Создайте первый пакет конфигурации.</p>
              ) : null}
              {packages.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  className={item.id === selectedPackageId ? 'selected' : ''}
                  onClick={() => {
                    setSelectedPackageId(item.id)
                    setSelectedVersionId('')
                  }}
                >
                  <span>
                    <strong>{item.name}</strong>
                    <small>{item.code}</small>
                  </span>
                  <span>
                    v{item.latest_version_number}
                    <small>{item.status}</small>
                  </span>
                </button>
              ))}
            </aside>

            <div className="config-packages-workspace">
              {selectedPackage ? (
                <>
                  <header>
                    <div>
                      <p className="eyebrow">{selectedPackage.code}</p>
                      <h3>{selectedPackage.name}</h3>
                      <p>{selectedPackage.description || 'Без описания'}</p>
                    </div>
                    <span className={`status-pill ${selectedPackage.status.toLowerCase()}`}>
                      {selectedPackage.status}
                    </span>
                  </header>

                  {can('configuration.packages.build') &&
                  selectedPackage.status === 'ACTIVE' ? (
                    <section className="config-packages-builder">
                      <div>
                        <h4>Состав новой версии</h4>
                        <p>
                          Выберите области. Зависимые объекты должны входить в
                          этот же пакет.
                        </p>
                      </div>
                      <div className="config-packages-checks">
                        {componentTypes.map((componentType) => (
                          <label key={componentType}>
                            <input
                              type="checkbox"
                              checked={selectedTypes.includes(componentType)}
                              onChange={(event) =>
                                setSelectedTypes((current) =>
                                  event.target.checked
                                    ? [...current, componentType]
                                    : current.filter(
                                        (item) => item !== componentType,
                                      ),
                                )
                              }
                            />
                            <span>
                              {componentLabels[componentType] ? translate(componentLabels[componentType]) : componentType}
                              <small>{componentType}</small>
                            </span>
                          </label>
                        ))}
                      </div>
                      <div className="config-packages-build-fields">
                        <label>
                          Исходная среда
                          <input
                            value={sourceEnvironment}
                            onChange={(event) =>
                              setSourceEnvironment(event.target.value)
                            }
                          />
                        </label>
                        <label>
                          Описание изменения
                          <input
                            value={changeSummary}
                            onChange={(event) =>
                              setChangeSummary(event.target.value)
                            }
                          />
                        </label>
                        <button
                          type="button"
                          className="primary-button"
                          disabled={Boolean(busy) || !selectedTypes.length}
                          onClick={() =>
                            void run('build-version', async () => {
                              const created =
                                await buildConfigurationPackageVersion(
                                  token,
                                  selectedPackage,
                                  {
                                    source_environment: sourceEnvironment,
                                    component_types: selectedTypes,
                                    change_summary: changeSummary,
                                  },
                                )
                              setSelectedVersionId(created.id)
                              setNotice(
                                `${translate('Версия v')}${created.version_number} ${translate('собрана и проверена.')}`,
                              )
                            })
                          }
                        >
                          Собрать версию
                        </button>
                      </div>
                    </section>
                  ) : null}

                  <section className="config-packages-versions">
                    <div className="config-packages-version-list">
                      <h4>Версии</h4>
                      {versions.map((version) => (
                        <button
                          key={version.id}
                          type="button"
                          className={
                            selectedVersionId === version.id ? 'selected' : ''
                          }
                          onClick={() => setSelectedVersionId(version.id)}
                        >
                          <span>
                            <strong>v{version.version_number}</strong>
                            <small>{version.source_environment}</small>
                          </span>
                          <span>
                            {version.status}
                            <small>{version.component_count} компонентов</small>
                          </span>
                        </button>
                      ))}
                    </div>
                    <VersionDetails
                      version={selectedVersion}
                      busy={busy}
                      canSeal={can('configuration.packages.seal')}
                      canExport={can('configuration.packages.export')}
                      canPlan={can('configuration.deployments.plan')}
                      targetEnvironment={targetEnvironment}
                      deploymentReason={deploymentReason}
                      onTargetEnvironment={setTargetEnvironment}
                      onDeploymentReason={setDeploymentReason}
                      onSeal={(version) =>
                        void run('seal-version', async () => {
                          await sealConfigurationPackageVersion(
                            token,
                            version,
                            changeSummary,
                          )
                          setNotice(
                            `${translate('Версия v')}${version.version_number} ${translate('запечатана.')}`,
                          )
                        })
                      }
                      onExport={(version) =>
                        void run('export-version', async () => {
                          const artifact =
                            await exportConfigurationPackageVersion(
                              token,
                              version.id,
                            )
                          downloadArtifact(artifact)
                          setNotice('Подписанный артефакт сохранен.')
                        })
                      }
                      onPlan={(version) =>
                        void run('plan-deployment', async () => {
                          const deployment =
                            await createConfigurationDeployment(token, {
                              tenant_id: scopedTenant,
                              package_version_id: version.id,
                              target_environment: targetEnvironment,
                              idempotency_key: crypto.randomUUID(),
                              reason: deploymentReason,
                            })
                          setView('deployments')
                          setNotice(
                            `${translate('Dry-run готов:')} ${deployment.plan.summary.CREATE} create, ${deployment.plan.summary.UPDATE} update, ${deployment.plan.summary.NOOP} noop.`,
                          )
                        })
                      }
                    />
                  </section>
                </>
              ) : (
                <p className="empty-state">Выберите пакет слева.</p>
              )}
            </div>
          </section>
        </>
      ) : null}

      {view === 'deployments' ? (
        <section className="config-deployments">
          <header>
            <div>
              <h3>История продвижения</h3>
              <p>
                План, fingerprint целевой среды, четыре глаза, результат и
                rollback evidence хранятся вместе.
              </p>
            </div>
            <label className="config-deployment-reason">
              Комментарий операции
              <input
                value={deploymentReason}
                minLength={3}
                onChange={(event) => setDeploymentReason(event.target.value)}
              />
            </label>
          </header>
          {!deployments.length ? (
            <p className="empty-state">Пока нет dry-run планов.</p>
          ) : (
            <div className="config-deployment-list">
              {deployments.map((deployment) => (
                <DeploymentCard
                  key={deployment.id}
                  deployment={deployment}
                  currentUserId={session?.user.id ?? ''}
                  busy={busy}
                  canPlan={can('configuration.deployments.plan')}
                  canApprove={can('configuration.deployments.approve')}
                  canApply={can('configuration.deployments.apply')}
                  canRollback={can('configuration.deployments.rollback')}
                  onRequest={() =>
                    void run('request-approval', async () => {
                      await requestConfigurationDeploymentApproval(
                        token,
                        deployment,
                        deploymentReason,
                      )
                      setNotice('Запрос независимого одобрения отправлен.')
                    })
                  }
                  onDecision={(decision) =>
                    void run(`decision-${decision}`, async () => {
                      await decideConfigurationDeployment(
                        token,
                        deployment,
                        decision,
                        decision === 'APPROVED'
                          ? translate('План и контрольные суммы проверены')
                          : translate('План отклонен после проверки'),
                      )
                      setNotice(
                        decision === 'APPROVED'
                          ? 'Продвижение одобрено.'
                          : 'Продвижение отклонено.',
                      )
                    })
                  }
                  onApply={() =>
                    window.confirm(
                      `${translate('Применить конфигурацию в')} ${deployment.target_environment}${translate('? Перед записью будет повторно проверен target fingerprint.')}`,
                    )
                      ? void run('apply-deployment', async () => {
                      await applyConfigurationDeployment(
                        token,
                        deployment,
                        deploymentReason,
                      )
                      setNotice('Конфигурация применена, snapshot сохранен.')
                        })
                      : undefined
                  }
                  onRollback={() =>
                    window.confirm(
                      translate('Выполнить rollback? Предыдущие объекты будут восстановлены новыми версиями, а впервые созданные — безопасно выключены.'),
                    )
                      ? void run('rollback-deployment', async () => {
                      await rollbackConfigurationDeployment(
                        token,
                        deployment,
                        deploymentReason,
                      )
                      setNotice('Конфигурация безопасно откачена.')
                        })
                      : undefined
                  }
                />
              ))}
            </div>
          )}
        </section>
      ) : null}

      {view === 'import' ? (
        <section className="config-artifact-import">
          <header>
            <div>
              <h3>Проверка и импорт артефакта</h3>
              <p>
                До сохранения проверяются формат, размер, component hashes,
                зависимости, запрещенные секреты и HMAC-подпись.
              </p>
            </div>
          </header>
          <label>
            JSON артефакта
            <textarea
              value={artifactText}
              onChange={(event) => setArtifactText(event.target.value)}
              placeholder='{"artifact_format":"sbs-itsm-configuration-package", ...}'
              spellCheck={false}
            />
          </label>
          <label>
            Основание импорта
            <input
              value={importSummary}
              onChange={(event) => setImportSummary(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary-button"
            disabled={
              Boolean(busy) ||
              !artifactText.trim() ||
              !can('configuration.packages.import')
            }
            onClick={() =>
              void run('import-artifact', async () => {
                const artifact = JSON.parse(artifactText) as ConfigurationArtifact
                const imported = await importConfigurationPackageArtifact(
                  token,
                  artifact,
                  importSummary,
                  scopedTenant,
                )
                setArtifactText('')
                setView('packages')
                setSelectedPackageId(imported.package_id)
                setSelectedVersionId(imported.id)
                setNotice(
                  `${translate('Подписанная версия импортирована как v')}${imported.version_number}.`,
                )
              })
            }
          >
            Проверить и импортировать
          </button>
          <aside>
            <strong>Что не переносится</strong>
            <ul>
              <li>API tokens, client secrets и пароли</li>
              <li>Webhook signing secrets и credential references</li>
              <li>Локальные user IDs и владельцы объектов</li>
              <li>Технические счетчики, health state и runtime history</li>
            </ul>
          </aside>
        </section>
      ) : null}
    </AppShell>
    </LocalizedContent>
  )
}

function VersionDetails({
  version,
  busy,
  canSeal,
  canExport,
  canPlan,
  targetEnvironment,
  deploymentReason,
  onTargetEnvironment,
  onDeploymentReason,
  onSeal,
  onExport,
  onPlan,
}: {
  version: ConfigurationPackageVersion | null
  busy: string
  canSeal: boolean
  canExport: boolean
  canPlan: boolean
  targetEnvironment: string
  deploymentReason: string
  onTargetEnvironment: (value: string) => void
  onDeploymentReason: (value: string) => void
  onSeal: (version: ConfigurationPackageVersion) => void
  onExport: (version: ConfigurationPackageVersion) => void
  onPlan: (version: ConfigurationPackageVersion) => void
}) {
  const { formatDateTime } = useTenantExperience()
  if (!version) {
    return <LocalizedContent><div className="empty-state">Выберите версию.</div></LocalizedContent>
  }
  return (
    <LocalizedContent>
    <article className="config-version-details">
      <header>
        <div>
          <p className="eyebrow">VERSION {version.version_number}</p>
          <h4>{version.change_summary || 'Без описания'}</h4>
        </div>
        <span className={`status-pill ${version.status.toLowerCase()}`}>
          {version.status}
        </span>
      </header>
      <dl>
        <div>
          <dt>Проверка</dt>
          <dd>{version.validation_status}</dd>
        </div>
        <div>
          <dt>Компоненты</dt>
          <dd>{version.component_count}</dd>
        </div>
        <div>
          <dt>Зависимости</dt>
          <dd>{version.dependency_count}</dd>
        </div>
        <div>
          <dt>Manifest SHA-256</dt>
          <dd title={version.manifest_sha256}>
            {shortHash(version.manifest_sha256)}
          </dd>
        </div>
        <div>
          <dt>Целостность</dt>
          <dd>{version.integrity_valid ? 'OK' : 'НАРУШЕНА'}</dd>
        </div>
        <div>
          <dt>Создана</dt>
          <dd>{formatDateTime(version.created_at)}</dd>
        </div>
      </dl>
      {version.validation.errors.length ? (
        <div className="config-validation-errors">
          {version.validation.errors.map((item) => (
            <p key={item}>{item}</p>
          ))}
        </div>
      ) : null}
      <div className="config-version-actions">
        {version.status === 'DRAFT' && canSeal ? (
          <button
            type="button"
            className="primary-button"
            disabled={Boolean(busy) || version.validation_status !== 'VALID'}
            onClick={() => onSeal(version)}
          >
            Проверить и запечатать
          </button>
        ) : null}
        {version.status === 'SEALED' && canExport ? (
          <button
            type="button"
            className="ghost-button"
            disabled={Boolean(busy)}
            onClick={() => onExport(version)}
          >
            Скачать артефакт
          </button>
        ) : null}
      </div>
      {version.status === 'SEALED' && canPlan ? (
        <div className="config-deployment-create">
          <label>
            Целевая среда
            <select
              value={targetEnvironment}
              onChange={(event) => onTargetEnvironment(event.target.value)}
            >
              <option value="development">development</option>
              <option value="staging">staging</option>
              <option value="production">production</option>
            </select>
          </label>
          <label>
            Основание
            <input
              value={deploymentReason}
              onChange={(event) => onDeploymentReason(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="primary-button"
            disabled={Boolean(busy)}
            onClick={() => onPlan(version)}
          >
            Создать dry-run
          </button>
        </div>
      ) : null}
    </article>
    </LocalizedContent>
  )
}

function DeploymentCard({
  deployment,
  currentUserId,
  busy,
  canPlan,
  canApprove,
  canApply,
  canRollback,
  onRequest,
  onDecision,
  onApply,
  onRollback,
}: {
  deployment: ConfigurationDeployment
  currentUserId: string
  busy: string
  canPlan: boolean
  canApprove: boolean
  canApply: boolean
  canRollback: boolean
  onRequest: () => void
  onDecision: (decision: 'APPROVED' | 'REJECTED') => void
  onApply: () => void
  onRollback: () => void
}) {
  const { formatDateTime } = useTenantExperience()
  const production = ['production', 'prod'].includes(
    deployment.target_environment,
  )
  const canSelfReview = deployment.requested_by_id !== currentUserId
  return (
    <LocalizedContent>
    <article className="config-deployment-card">
      <header>
        <div>
          <p className="eyebrow">
            {deployment.target_environment} · {deployment.id.slice(0, 8)}
          </p>
          <h4>{deployment.reason}</h4>
          <small>{formatDateTime(deployment.created_at)}</small>
        </div>
        <span className={`status-pill ${deployment.status.toLowerCase()}`}>
          {deployment.status}
        </span>
      </header>
      <div className="config-deployment-summary">
        {(['CREATE', 'UPDATE', 'NOOP', 'BLOCK'] as const).map((action) => (
          <div key={action}>
            <span>{action}</span>
            <strong>{deployment.plan.summary?.[action] ?? 0}</strong>
          </div>
        ))}
      </div>
      <div className="config-evidence">
        <span>
          Plan <code>{shortHash(deployment.plan_sha256)}</code>
        </span>
        <span>
          Target <code>{shortHash(deployment.target_fingerprint_sha256)}</code>
        </span>
        <span>
          Snapshot <code>{shortHash(deployment.snapshot_before_sha256)}</code>
        </span>
        <span>
          Result <code>{shortHash(deployment.result_sha256)}</code>
        </span>
      </div>
      {deployment.error_message ? (
        <div className="error">{deployment.error_message}</div>
      ) : null}
      <div className="config-deployment-actions">
        {deployment.status === 'VALIDATED' && canPlan ? (
          <button type="button" onClick={onRequest} disabled={Boolean(busy)}>
            Запросить одобрение
          </button>
        ) : null}
        {deployment.status === 'PENDING_APPROVAL' &&
        canApprove &&
        canSelfReview ? (
          <>
            <button
              type="button"
              className="primary-button"
              onClick={() => onDecision('APPROVED')}
              disabled={Boolean(busy)}
            >
              Одобрить
            </button>
            <button
              type="button"
              className="danger-button"
              onClick={() => onDecision('REJECTED')}
              disabled={Boolean(busy)}
            >
              Отклонить
            </button>
          </>
        ) : null}
        {canApply &&
        (deployment.status === 'APPROVED' ||
          (!production && deployment.status === 'VALIDATED')) ? (
          <button
            type="button"
            className="primary-button"
            onClick={onApply}
            disabled={Boolean(busy)}
          >
            Применить
          </button>
        ) : null}
        {deployment.status === 'APPLIED' && canRollback ? (
          <button
            type="button"
            className="danger-button"
            onClick={onRollback}
            disabled={Boolean(busy)}
          >
            Rollback
          </button>
        ) : null}
      </div>
    </article>
    </LocalizedContent>
  )
}
