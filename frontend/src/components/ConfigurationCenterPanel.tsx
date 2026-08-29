import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  fetchConfigurationCenter,
  fetchConfigurationSettingHistory,
  fetchTenants,
  rollbackTypedConfigurationSetting,
  type GuidedConfigurationCheck,
  type TypedConfigurationSetting,
  updateTypedConfigurationSetting,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

const GROUP_LABELS: Record<string, string> = {
  security: 'Безопасность и сессии',
  service_management: 'SLA и база знаний',
  ai: 'AI-функции tenant',
  communications: 'Уведомления',
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : 'Неизвестная ошибка'
}

function formatDate(value: string | null, locale: string) {
  return value
    ? new Intl.DateTimeFormat(locale, {
        dateStyle: 'short',
        timeStyle: 'short',
      }).format(new Date(value))
    : '—'
}

function statusLabel(status: string) {
  if (status === 'READY') return 'Готово'
  if (status === 'DEGRADED') return 'Нужна проверка'
  return 'Требуется настройка'
}

function checkStatusLabel(status: GuidedConfigurationCheck['status']) {
  if (status === 'PASS') return 'Пройдено'
  if (status === 'INFO') return 'Информация'
  if (status === 'WARNING') return 'Предупреждение'
  if (status === 'NOT_APPLICABLE') return 'Не применяется'
  return 'Требуется действие'
}

function evidenceValue(value: unknown) {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return String(value)
}

export default function ConfigurationCenterPanel() {
  const { session } = useAuth()
  const { uiLocale: locale, t, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const token = session?.access_token ?? ''
  const permissions = useMemo(
    () => new Set(session?.user.permissions ?? []),
    [session?.user.permissions],
  )
  const isRoot = session?.user.role === 'saas_root'
  const canRead = isRoot || permissions.has('admin.configuration.read')
  const canManage = isRoot || permissions.has('admin.configuration.manage')
  const canRollback =
    isRoot || permissions.has('admin.configuration.rollback')
  const [tenantId, setTenantId] = useState(session?.user.tenant_id ?? '')
  const scope = isRoot ? tenantId || undefined : session?.user.tenant_id
  const [drafts, setDrafts] = useState<Record<string, boolean | number>>({})
  const [reasons, setReasons] = useState<Record<string, string>>({})
  const [historyKey, setHistoryKey] = useState('')
  const [notice, setNotice] = useState('')
  const [guidanceFilter, setGuidanceFilter] = useState<
    'ALL' | 'ACTION_REQUIRED' | 'WARNING'
  >('ALL')

  const tenants = useQuery({
    queryKey: ['configuration-center-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot),
  })
  const center = useQuery({
    queryKey: ['configuration-center', token, scope ?? 'global'],
    queryFn: () => fetchConfigurationCenter(token, scope),
    enabled: Boolean(token && canRead),
    refetchInterval: 30_000,
  })
  const history = useQuery({
    queryKey: ['configuration-setting-history', token, scope ?? 'global', historyKey],
    queryFn: () =>
      fetchConfigurationSettingHistory(token, historyKey, scope),
    enabled: Boolean(token && canRead && historyKey),
  })

  useEffect(() => {
    if (!center.data) return
    setDrafts(
      Object.fromEntries(
        center.data.settings.map((setting) => [setting.key, setting.value]),
      ),
    )
  }, [center.data])

  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['configuration-center'] }),
      queryClient.invalidateQueries({
        queryKey: ['configuration-setting-history'],
      }),
      queryClient.invalidateQueries({ queryKey: ['admin-settings'] }),
    ])
  }

  const saveMutation = useMutation({
    mutationFn: (setting: TypedConfigurationSetting) =>
      updateTypedConfigurationSetting(token, setting.key, {
        tenant_id: isRoot ? scope : undefined,
        expected_revision: setting.revision,
        value: drafts[setting.key],
        reason: reasons[setting.key] || 'Validated change from Configuration Center',
      }),
    onSuccess: async (setting) => {
      setNotice(t('configuration.savedRevision', {
        label: setting.label,
        revision: setting.revision,
      }))
      setReasons((current) => ({ ...current, [setting.key]: '' }))
      await refresh()
    },
  })
  const rollbackMutation = useMutation({
    mutationFn: ({
      setting,
      targetRevision,
    }: {
      setting: TypedConfigurationSetting
      targetRevision: number
    }) =>
      rollbackTypedConfigurationSetting(token, setting.key, {
        tenant_id: isRoot ? scope : undefined,
        expected_revision: setting.revision,
        target_revision: targetRevision,
        reason: 'Operator rollback from Configuration Center',
      }),
    onSuccess: async (setting) => {
      setNotice(t('configuration.rollbackRevision', {
        label: setting.label,
        revision: setting.revision,
      }))
      await refresh()
    },
  })

  const grouped = useMemo(() => {
    const result: Record<string, TypedConfigurationSetting[]> = {}
    for (const setting of center.data?.settings ?? []) {
      ;(result[setting.domain] ??= []).push(setting)
    }
    return result
  }, [center.data?.settings])
  const selectedSetting = center.data?.settings.find(
    (setting) => setting.key === historyKey,
  )
  const error = center.error ?? saveMutation.error ?? rollbackMutation.error
  const openConfigurationRoute = (route: string, domainCode?: string) => {
    if (domainCode === 'platform' || route === '/admin#settings') {
      document
        .querySelector('.typed-settings')
        ?.scrollIntoView({ behavior: 'smooth' })
      return
    }
    if (domainCode === 'ai_provider') {
      document
        .querySelector('.ai-provider-console')
        ?.scrollIntoView({ behavior: 'smooth' })
      return
    }
    navigate(route)
  }
  const guidedActions = (center.data?.guide.next_actions ?? []).filter(
    (item) => guidanceFilter === 'ALL' || item.status === guidanceFilter,
  )

  if (!canRead) return null

  return (
    <LocalizedContent>
    <section className="configuration-center">
      <header className="configuration-center-hero">
        <div>
          <p className="eyebrow">UNIFIED CONFIGURATION CENTER</p>
          <h2>Настройка платформы по задачам, а не по ключам</h2>
          <p>
            Каждый раздел показывает scope, готовность, проблемы и безопасное
            действие. Значения типизированы, изменения версионируются, rollback
            и инициатор записываются в audit.
          </p>
        </div>
        <div className="configuration-readiness">
          <span>{center.data?.scope.label ?? 'Загрузка…'}</span>
          <strong>{center.data?.overall.readiness_percent ?? 0}%</strong>
          <small>
            {center.data
              ? t('configuration.readyDomains', {
                  ready: center.data.overall.ready_domains,
                  total: center.data.overall.total_domains,
                })
              : 'Проверяем конфигурацию'}
          </small>
        </div>
      </header>

      {isRoot ? (
        <label className="configuration-scope-picker">
          <span>Scope управления</span>
          <select
            value={tenantId}
            onChange={(event) => {
              setTenantId(event.target.value)
              setHistoryKey('')
            }}
          >
            <option value="">Global platform</option>
            {(tenants.data ?? []).map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
          <small>
            Global provider и системные секреты доступны только SaaS Root.
          </small>
        </label>
      ) : null}

      {center.isLoading ? (
        <p className="state-panel state-panel-loading">
          Формируем readiness и карту настроек…
        </p>
      ) : null}
      {center.data?.overall.issues.length ? (
        <details className="configuration-issues">
          <summary>
            Открытые действия: {center.data.overall.issues.length}
          </summary>
          <ul>
            {center.data.overall.issues.map((issue) => (
              <li key={issue}>{issue}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {center.data ? (
        <section className="configuration-guidance">
          <header>
            <div>
              <p className="eyebrow">ROLE-AWARE SETUP GUIDE</p>
              <h3>Приоритетные действия администратора</h3>
              <p>
                Диагностика сформирована без секретов для роли{' '}
                <strong>{center.data.guide.operator_role}</strong>. Каждое
                действие ведёт к точному control plane и содержит безопасный
                fallback, permission и SHA-256 evidence.
              </p>
            </div>
            <div className="configuration-guidance-counts">
              <span>
                <strong>{center.data.guide.action_required_checks}</strong>
                действий
              </span>
              <span>
                <strong>{center.data.guide.warning_checks}</strong>
                предупреждений
              </span>
              <small>
                guide {center.data.guide.version} ·{' '}
                {formatDate(center.data.guide.generated_at, locale)}
              </small>
            </div>
          </header>
          <div className="configuration-guidance-filters" role="group" aria-label="Фильтр рекомендаций">
            {(['ALL', 'ACTION_REQUIRED', 'WARNING'] as const).map((value) => (
              <button
                type="button"
                key={value}
                className={guidanceFilter === value ? 'active' : 'ghost-button'}
                aria-pressed={guidanceFilter === value}
                onClick={() => setGuidanceFilter(value)}
              >
                {value === 'ALL'
                  ? 'Все'
                  : value === 'ACTION_REQUIRED'
                    ? 'Требуют действия'
                    : 'Предупреждения'}
              </button>
            ))}
          </div>
          {guidedActions.length ? (
            <div className="configuration-guidance-list">
              {guidedActions.map((action) => (
                <article
                  key={`${action.domain_code}:${action.check_code}`}
                  className={`guidance-action severity-${action.severity}`}
                >
                  <header>
                    <div>
                      <span>{action.domain_title}</span>
                      <h4>{action.title}</h4>
                    </div>
                    <strong>{checkStatusLabel(action.status)}</strong>
                  </header>
                  <p>{action.diagnostic}</p>
                  <div className="guidance-remediation">
                    <strong>Что сделать</strong>
                    <span>{action.remediation}</span>
                  </div>
                  <footer>
                    <div className="configuration-guidance-actions">
                      <button
                        type="button"
                        onClick={() => openConfigurationRoute(
                          action.route,
                          action.domain_code,
                        )}
                      >
                        {action.can_manage
                          ? 'Открыть настройку'
                          : 'Открыть статус'}
                      </button>
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() => navigate(action.audit_route)}
                      >
                        Аудит
                      </button>
                    </div>
                    <details>
                      <summary>Evidence и ownership</summary>
                      <dl>
                        <div>
                          <dt>Permission</dt>
                          <dd>{action.required_permission}</dd>
                        </div>
                        <div>
                          <dt>Runbook</dt>
                          <dd><code>{action.runbook}</code></dd>
                        </div>
                        <div>
                          <dt>Evidence SHA-256</dt>
                          <dd><code>{action.evidence_sha256.slice(0, 16)}</code></dd>
                        </div>
                      </dl>
                    </details>
                  </footer>
                </article>
              ))}
            </div>
          ) : (
            <p className="state-panel state-panel-success" role="status">
              Для выбранного фильтра нет открытых действий.
            </p>
          )}
        </section>
      ) : null}

      <div className="configuration-domain-grid">
        {(center.data?.domains ?? []).map((domain) => (
          <article
            className={`configuration-domain status-${domain.status.toLowerCase()}`}
            key={domain.code}
          >
            <header>
              <div>
                <span>{domain.scope === 'global' ? 'GLOBAL' : 'TENANT'}</span>
                <h3>{domain.title}</h3>
              </div>
              <strong>{translate(statusLabel(domain.status))}</strong>
            </header>
            <p>{domain.description}</p>
            <progress max={100} value={domain.readiness_percent} />
            <div className="configuration-domain-meta">
              <span>{domain.readiness_percent}% readiness</span>
              <span>
                {domain.configured_items}/{domain.required_items} checks
              </span>
            </div>
            {domain.issues.length ? (
              <ul>
                {domain.issues.slice(0, 3).map((issue) => (
                  <li key={issue}>{issue}</li>
                ))}
              </ul>
            ) : (
              <p className="configuration-domain-ready">Проверки пройдены.</p>
            )}
            <details className="configuration-domain-checklist">
              <summary>
                Диагностика и инструкция · {domain.checks.length}
              </summary>
              <div>
                {domain.checks.map((check) => (
                  <article
                    key={check.code}
                    className={`configuration-check check-${check.status.toLowerCase()}`}
                  >
                    <header>
                      <div>
                        <strong>{check.title}</strong>
                        <small>{checkStatusLabel(check.status)}</small>
                      </div>
                      <code>{check.evidence_sha256.slice(0, 10)}</code>
                    </header>
                    <p>{check.diagnostic}</p>
                    <dl>
                      {Object.entries(check.evidence).map(([key, value]) => (
                        <div key={key}>
                          <dt>{key}</dt>
                          <dd>{evidenceValue(value)}</dd>
                        </div>
                      ))}
                    </dl>
                    <div className="configuration-safe-default">
                      <strong>Безопасное поведение</strong>
                      <span>{check.safe_default}</span>
                    </div>
                    {check.status !== 'PASS' && check.status !== 'NOT_APPLICABLE' ? (
                      <div className="configuration-check-action">
                        <p>{check.remediation}</p>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => openConfigurationRoute(
                            check.route,
                            domain.code,
                          )}
                        >
                          {check.can_manage ? 'Исправить' : 'Открыть статус'}
                        </button>
                      </div>
                    ) : null}
                    <footer>
                      <span>{check.required_permission}</span>
                      <div>
                        <code>{check.runbook}</code>
                        <button
                          type="button"
                          className="ghost-button"
                          onClick={() => navigate(check.audit_route)}
                        >
                          Аудит
                        </button>
                      </div>
                    </footer>
                  </article>
                ))}
              </div>
              <footer className="configuration-domain-evidence">
                <span>
                  Owners: {domain.owner_roles.join(', ') || 'Platform owner'}
                </span>
                <code>{domain.evidence_sha256.slice(0, 16)}</code>
              </footer>
            </details>
            <footer>
              <button
                type="button"
                className="ghost-button"
                onClick={() => openConfigurationRoute(domain.route, domain.code)}
              >
                {domain.can_manage ? 'Настроить' : 'Открыть статус'}
              </button>
              <small>
                {domain.supports_test ? 'Test connection · ' : ''}
                {domain.supports_rollback ? 'Rollback · ' : ''}
                {formatDate(domain.updated_at, locale)}
              </small>
            </footer>
          </article>
        ))}
      </div>

      <section className="typed-settings">
        <header>
          <div>
            <p className="eyebrow">VALIDATED SETTINGS</p>
            <h3>Основные параметры текущего scope</h3>
          </div>
          <p>
            Невалидное значение не сохраняется. Revision conflict защищает от
            перезаписи изменений другого администратора.
          </p>
        </header>
        {Object.entries(grouped).map(([group, settings]) => (
          <section className="typed-settings-group" key={group}>
            <h4>{GROUP_LABELS[group] ? translate(GROUP_LABELS[group]) : group}</h4>
            <div>
              {settings.map((setting) => {
                const changed = drafts[setting.key] !== setting.value
                return (
                  <article key={setting.key}>
                    <div className="typed-setting-title">
                      <div>
                        <strong>{setting.label}</strong>
                        <small>{setting.description}</small>
                      </div>
                      <span>
                        {setting.source} · rev {setting.revision}
                      </span>
                    </div>
                    <div className="typed-setting-control">
                      {setting.value_type === 'boolean' ? (
                        <label className="checkbox-row">
                          <input
                            type="checkbox"
                            checked={Boolean(drafts[setting.key])}
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [setting.key]: event.target.checked,
                              }))
                            }
                            disabled={!canManage}
                          />
                          <span>
                            {drafts[setting.key] ? 'Включено' : 'Выключено'}
                          </span>
                        </label>
                      ) : (
                        <input
                          type="number"
                          min={setting.minimum ?? undefined}
                          max={setting.maximum ?? undefined}
                          value={Number(drafts[setting.key] ?? setting.value)}
                          onChange={(event) =>
                            setDrafts((current) => ({
                              ...current,
                              [setting.key]: Number(event.target.value),
                            }))
                          }
                          disabled={!canManage}
                        />
                      )}
                      <input
                        value={reasons[setting.key] ?? ''}
                        onChange={(event) =>
                          setReasons((current) => ({
                            ...current,
                            [setting.key]: event.target.value,
                          }))
                        }
                        placeholder="Причина изменения"
                        disabled={!canManage}
                      />
                      {canManage ? (
                        <button
                          type="button"
                          disabled={!changed || saveMutation.isPending}
                          onClick={() => saveMutation.mutate(setting)}
                        >
                          Сохранить
                        </button>
                      ) : null}
                      <button
                        type="button"
                        className="ghost-button"
                        onClick={() =>
                          setHistoryKey((current) =>
                            current === setting.key ? '' : setting.key,
                          )
                        }
                      >
                        История
                      </button>
                    </div>
                    {!setting.valid ? (
                      <p className="error-message">{setting.issue}</p>
                    ) : null}
                  </article>
                )
              })}
            </div>
          </section>
        ))}
      </section>

      {selectedSetting && historyKey ? (
        <section className="configuration-history">
          <header>
            <div>
              <p className="eyebrow">REVISION HISTORY</p>
              <h3>{selectedSetting.label}</h3>
            </div>
            <button
              type="button"
              className="ghost-button"
              onClick={() => setHistoryKey('')}
            >
              Закрыть
            </button>
          </header>
          {history.isLoading ? <p>Загрузка истории…</p> : null}
          {(history.data ?? []).map((revision) => (
            <article key={revision.id}>
              <div>
                <strong>Revision {revision.revision}</strong>
                <span>
                  {String(revision.value)} · {formatDate(revision.created_at, locale)}
                </span>
                <small>{revision.change_reason}</small>
              </div>
              {canRollback &&
              revision.revision !== selectedSetting.revision ? (
                <button
                  type="button"
                  className="ghost-button"
                  disabled={rollbackMutation.isPending}
                  onClick={() => {
                    if (
                      window.confirm(t('configuration.rollbackConfirm', {
                        revision: revision.revision,
                      }))
                    ) {
                      rollbackMutation.mutate({
                        setting: selectedSetting,
                        targetRevision: revision.revision,
                      })
                    }
                  }}
                >
                  Rollback сюда
                </button>
              ) : null}
            </article>
          ))}
          {!history.isLoading && !history.data?.length ? (
            <p className="empty-state">
              История появится после первого изменения через этот центр.
            </p>
          ) : null}
        </section>
      ) : null}

      <div className="configuration-secret-note">
        <strong>Секреты не возвращаются в браузер</strong>
        <span>
          {center.data?.secret_storage.strategy ??
            'Encrypted server-side credential storage'}
        </span>
      </div>
      {notice ? <p className="state-panel state-panel-success">{notice}</p> : null}
      {error ? <p className="error-message">{errorText(error)}</p> : null}
    </section>
    </LocalizedContent>
  )
}
