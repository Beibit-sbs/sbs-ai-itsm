import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchTenantExperience,
  fetchTenantExperienceRevisions,
  fetchTenants,
  removeTenantLogo,
  rollbackTenantExperience,
  updateTenantExperience,
  uploadTenantLogo,
  type TenantExperience,
  type TenantExperienceSettings,
  type TenantTerminology,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { isUiLocale, localeLabelKey } from '../i18n/catalog'
import LocalizedContent from '../experience/LocalizedContent'

const terminologyLabels: Record<keyof TenantTerminology, string> = {
  incident_singular: 'Инцидент — единственное',
  incident_plural: 'Инциденты — множественное',
  request_singular: 'Запрос услуги — единственное',
  request_plural: 'Запросы услуг — множественное',
  asset_singular: 'Актив — единственное',
  asset_plural: 'Активы — множественное',
  service_singular: 'Услуга — единственное',
  service_plural: 'Услуги — множественное',
  knowledge_base: 'Название базы знаний',
}

function profileSettings(profile: TenantExperience): TenantExperienceSettings {
  return {
    product_name: profile.product_name,
    short_name: profile.short_name,
    primary_color: profile.primary_color,
    accent_color: profile.accent_color,
    surface_color: profile.surface_color,
    text_color: profile.text_color,
    ui_locale: profile.ui_locale,
    format_locale: profile.format_locale,
    timezone: profile.timezone,
    currency_code: profile.currency_code,
    date_style: profile.date_style,
    hour_cycle: profile.hour_cycle,
    first_day_of_week: profile.first_day_of_week,
    terminology: { ...profile.terminology },
  }
}

function luminance(color: string) {
  const channels = color
    .slice(1)
    .match(/../g)
    ?.map((value) => {
      const normalized = Number.parseInt(value, 16) / 255
      return normalized <= 0.04045
        ? normalized / 12.92
        : ((normalized + 0.055) / 1.055) ** 2.4
    }) ?? [0, 0, 0]
  return (
    0.2126 * channels[0]
    + 0.7152 * channels[1]
    + 0.0722 * channels[2]
  )
}

function contrast(first: string, second: string) {
  const firstLuminance = luminance(first)
  const secondLuminance = luminance(second)
  return (
    (Math.max(firstLuminance, secondLuminance) + 0.05)
    / (Math.min(firstLuminance, secondLuminance) + 0.05)
  )
}

function bestForeground(background: string) {
  return contrast('#03121E', background) >= contrast('#FFFFFF', background)
    ? '#03121E'
    : '#FFFFFF'
}

export default function TenantExperiencePanel() {
  const { session } = useAuth()
  const { formatDateTime, t, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const token = session?.access_token ?? ''
  const isRoot = session?.user.role === 'saas_root'
  const permissions = new Set(session?.user.permissions ?? [])
  const canManage = isRoot || permissions.has('tenant.experience.manage')
  const canRollback = isRoot || permissions.has('tenant.experience.rollback')
  const [selectedTenantId, setSelectedTenantId] = useState(
    session?.user.tenant_id ?? '',
  )
  const tenantId = isRoot
    ? selectedTenantId || null
    : session?.user.tenant_id ?? null
  const [draft, setDraft] = useState<TenantExperienceSettings | null>(null)
  const [changeReason, setChangeReason] = useState('')
  const [logoFile, setLogoFile] = useState<File | null>(null)
  const [feedback, setFeedback] = useState<{
    kind: 'success' | 'error'
    message: string
  } | null>(null)

  const tenantsQuery = useQuery({
    queryKey: ['tenant-experience-tenants', token],
    queryFn: () => fetchTenants(token),
    enabled: Boolean(token && isRoot),
  })
  const profileQuery = useQuery({
    queryKey: ['tenant-experience-admin', token, tenantId],
    queryFn: () => fetchTenantExperience(token, tenantId),
    enabled: Boolean(token && tenantId),
  })
  const revisionsQuery = useQuery({
    queryKey: ['tenant-experience-revisions', token, tenantId],
    queryFn: () => fetchTenantExperienceRevisions(token, tenantId),
    enabled: Boolean(token && tenantId && canRollback),
  })
  const profile = profileQuery.data

  useEffect(() => {
    if (!profile) {
      setDraft(null)
      return
    }
    setDraft(profileSettings(profile))
  }, [profile])

  useEffect(() => {
    if (!isRoot || selectedTenantId || !(tenantsQuery.data ?? []).length) return
    setSelectedTenantId(tenantsQuery.data?.[0]?.id ?? '')
  }, [isRoot, selectedTenantId, tenantsQuery.data])

  const syncResult = async (result: TenantExperience) => {
    queryClient.setQueryData(
      ['tenant-experience-admin', token, result.tenant_id],
      result,
    )
    queryClient.setQueryData(
      ['tenant-experience-bootstrap', token, result.tenant_id],
      result,
    )
    setDraft(profileSettings(result))
    setChangeReason('')
    setLogoFile(null)
    await queryClient.invalidateQueries({
      queryKey: ['tenant-experience-revisions', token, result.tenant_id],
    })
  }

  const updateMutation = useMutation({
    mutationFn: () => {
      if (!profile || !draft) throw new Error('Профиль не загружен.')
      return updateTenantExperience(
        token,
        {
          expected_revision: profile.revision,
          change_reason: changeReason,
          settings: draft,
        },
        tenantId,
      )
    },
    onSuccess: async (result) => {
      await syncResult(result)
      setFeedback({
        kind: 'success',
        message: `Опубликована версия ${result.revision}.`,
      })
    },
    onError: (error) => setFeedback({
      kind: 'error',
      message: error instanceof Error ? error.message : 'Не удалось сохранить профиль.',
    }),
  })
  const logoMutation = useMutation({
    mutationFn: () => {
      if (!profile || !logoFile) throw new Error('Выберите PNG-файл.')
      return uploadTenantLogo(
        token,
        logoFile,
        profile.revision,
        changeReason,
        tenantId,
      )
    },
    onSuccess: async (result) => {
      await syncResult(result)
      setFeedback({
        kind: 'success',
        message: `Логотип опубликован в версии ${result.revision}.`,
      })
    },
    onError: (error) => setFeedback({
      kind: 'error',
      message: error instanceof Error ? error.message : 'Не удалось загрузить логотип.',
    }),
  })
  const removeLogoMutation = useMutation({
    mutationFn: () => {
      if (!profile) throw new Error('Профиль не загружен.')
      return removeTenantLogo(
        token,
        profile.revision,
        changeReason,
        tenantId,
      )
    },
    onSuccess: async (result) => {
      await syncResult(result)
      setFeedback({
        kind: 'success',
        message: `Логотип отключён в версии ${result.revision}.`,
      })
    },
    onError: (error) => setFeedback({
      kind: 'error',
      message: error instanceof Error ? error.message : 'Не удалось отключить логотип.',
    }),
  })
  const rollbackMutation = useMutation({
    mutationFn: (targetRevision: number) => {
      if (!profile) throw new Error('Профиль не загружен.')
      return rollbackTenantExperience(
        token,
        {
          expected_revision: profile.revision,
          target_revision: targetRevision,
          change_reason: changeReason,
        },
        tenantId,
      )
    },
    onSuccess: async (result) => {
      await syncResult(result)
      setFeedback({
        kind: 'success',
        message: `Версия восстановлена как новая ревизия ${result.revision}.`,
      })
    },
    onError: (error) => setFeedback({
      kind: 'error',
      message: error instanceof Error ? error.message : 'Rollback отклонён.',
    }),
  })
  const busy =
    updateMutation.isPending
    || logoMutation.isPending
    || removeLogoMutation.isPending
    || rollbackMutation.isPending
  const hasReason = changeReason.trim().length >= 5
  const previewStyle = useMemo(
    () => draft
      ? {
          '--preview-primary': draft.primary_color,
          '--preview-accent': draft.accent_color,
          '--preview-surface': draft.surface_color,
          '--preview-text': draft.text_color,
          '--preview-on-primary': bestForeground(draft.primary_color),
        } as React.CSSProperties
      : undefined,
    [draft],
  )
  const draftContrast = useMemo(
    () => draft
      ? {
          text: contrast(draft.text_color, draft.surface_color).toFixed(2),
          primary: contrast(
            draft.primary_color,
            draft.surface_color,
          ).toFixed(2),
          accent: contrast(
            draft.accent_color,
            draft.surface_color,
          ).toFixed(2),
        }
      : { text: '—', primary: '—', accent: '—' },
    [draft],
  )

  return (
    <LocalizedContent>
    <section className="foundation-card admin-panel tenant-experience-panel">
      <header className="tenant-experience-header">
        <div>
          <p className="eyebrow">BRAND / LOCALE / TERMINOLOGY</p>
          <h2>Опыт организации</h2>
          <p className="muted">
            Проверяемые theme-токены, PNG-логотип, IANA timezone, форматы и
            контролируемая ITSM-терминология. Произвольные CSS/HTML запрещены.
          </p>
        </div>
        {profile ? (
          <div className="tenant-experience-revision">
            <span>Revision</span>
            <strong>{profile.revision}</strong>
            <small>{profile.etag.slice(0, 12)}</small>
          </div>
        ) : null}
      </header>

      {isRoot ? (
        <label className="tenant-experience-scope">
          <span>Организация</span>
          <select
            value={selectedTenantId}
            onChange={(event) => {
              setSelectedTenantId(event.target.value)
              setFeedback(null)
            }}
          >
            <option value="">Выберите tenant</option>
            {(tenantsQuery.data ?? []).map((tenant) => (
              <option key={tenant.id} value={tenant.id}>
                {tenant.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {!tenantId ? (
        <p className="state-panel state-panel-empty">
          Выберите организацию для настройки.
        </p>
      ) : null}
      {profileQuery.isPending && tenantId ? (
        <p className="state-panel state-panel-loading" role="status">
          Загрузка experience-профиля…
        </p>
      ) : null}
      {profileQuery.isError ? (
        <div className="state-panel state-panel-error" role="alert">
          <p>
            {profileQuery.error instanceof Error
              ? profileQuery.error.message
              : 'Не удалось загрузить профиль.'}
          </p>
          <button type="button" onClick={() => profileQuery.refetch()}>
            Повторить
          </button>
        </div>
      ) : null}
      {feedback ? (
        <div
          className={feedback.kind === 'error' ? 'error-banner' : 'success-banner'}
          role={feedback.kind === 'error' ? 'alert' : 'status'}
        >
          {feedback.message}
        </div>
      ) : null}

      {profile && draft ? (
        <>
          <div className="tenant-experience-layout">
            <form
              className="tenant-experience-form"
              onSubmit={(event) => {
                event.preventDefault()
                setFeedback(null)
                updateMutation.mutate()
              }}
            >
              <section>
                <h3>Идентичность</h3>
                <div className="tenant-experience-fields">
                  <label>
                    <span>Название продукта</span>
                    <input
                      value={draft.product_name}
                      minLength={2}
                      maxLength={80}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        product_name: event.target.value,
                      })}
                    />
                  </label>
                  <label>
                    <span>Короткое имя</span>
                    <input
                      value={draft.short_name}
                      minLength={2}
                      maxLength={24}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        short_name: event.target.value,
                      })}
                    />
                  </label>
                </div>
              </section>

              <section>
                <h3>Безопасная палитра</h3>
                <div className="tenant-color-grid">
                  {([
                    ['primary_color', 'Основной'],
                    ['accent_color', 'Акцент'],
                    ['surface_color', 'Фон'],
                    ['text_color', 'Текст'],
                  ] as const).map(([key, label]) => (
                    <label key={key}>
                      <span>{label}</span>
                      <div>
                        <input
                          type="color"
                          value={draft[key]}
                          disabled={!canManage}
                          onChange={(event) => setDraft({
                            ...draft,
                            [key]: event.target.value.toUpperCase(),
                          })}
                        />
                        <code>{draft[key]}</code>
                      </div>
                    </label>
                  ))}
                </div>
                <small className="muted">
                  Сервер требует 4.5:1 для текста и 3:1 для primary/accent
                  относительно поверхности.
                </small>
              </section>

              <section>
                <h3>{t('tenantExperience.localeTime')}</h3>
                <div className="tenant-experience-fields">
                  <label>
                    <span>{t('tenantExperience.defaultUiLanguage')}</span>
                    <select
                      value={draft.ui_locale}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        ui_locale: event.target.value,
                      })}
                    >
                      {profile.capabilities.ui_locales.map((locale) => (
                        <option key={locale} value={locale}>
                          {isUiLocale(locale)
                            ? `${t(localeLabelKey(locale))} — ${locale}`
                            : locale}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Локаль форматов</span>
                    <select
                      value={draft.format_locale}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        format_locale: event.target.value,
                      })}
                    >
                      {profile.capabilities.format_locales.map((locale) => (
                        <option key={locale}>{locale}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>IANA timezone</span>
                    <input
                      list="tenant-experience-timezones"
                      value={draft.timezone}
                      maxLength={80}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        timezone: event.target.value,
                      })}
                    />
                    <datalist id="tenant-experience-timezones">
                      {profile.capabilities.suggested_timezones.map((timezone) => (
                        <option key={timezone} value={timezone} />
                      ))}
                    </datalist>
                  </label>
                  <label>
                    <span>Валюта</span>
                    <select
                      value={draft.currency_code}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        currency_code: event.target.value,
                      })}
                    >
                      {profile.capabilities.currencies.map((currency) => (
                        <option key={currency}>{currency}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Стиль даты</span>
                    <select
                      value={draft.date_style}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        date_style: event.target.value as TenantExperienceSettings['date_style'],
                      })}
                    >
                      {profile.capabilities.date_styles.map((style) => (
                        <option key={style}>{style}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Часы</span>
                    <select
                      value={draft.hour_cycle}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        hour_cycle: event.target.value as TenantExperienceSettings['hour_cycle'],
                      })}
                    >
                      {profile.capabilities.hour_cycles.map((cycle) => (
                        <option key={cycle}>{cycle}</option>
                      ))}
                    </select>
                  </label>
                  <label>
                    <span>Первый день недели</span>
                    <select
                      value={draft.first_day_of_week}
                      disabled={!canManage}
                      onChange={(event) => setDraft({
                        ...draft,
                        first_day_of_week: Number(event.target.value),
                      })}
                    >
                      <option value={1}>Понедельник</option>
                      <option value={7}>Воскресенье</option>
                    </select>
                  </label>
                </div>
              </section>

              <section>
                <h3>Контролируемая терминология</h3>
                <div className="tenant-terminology-grid">
                  {(Object.keys(terminologyLabels) as Array<keyof TenantTerminology>).map((key) => (
                    <label key={key}>
                      <span>{translate(terminologyLabels[key])}</span>
                      <input
                        value={draft.terminology[key]}
                        minLength={2}
                        maxLength={40}
                        disabled={!canManage}
                        onChange={(event) => setDraft({
                          ...draft,
                          terminology: {
                            ...draft.terminology,
                            [key]: event.target.value,
                          },
                        })}
                      />
                    </label>
                  ))}
                </div>
              </section>

              <label>
                <span>Причина изменения</span>
                <textarea
                  value={changeReason}
                  minLength={5}
                  maxLength={500}
                  disabled={!canManage}
                  placeholder="Например: утверждённый брендбук организации"
                  onChange={(event) => setChangeReason(event.target.value)}
                />
              </label>
              <div className="tenant-experience-actions">
                <button
                  type="submit"
                  disabled={!canManage || !hasReason || busy}
                >
                  {updateMutation.isPending
                    ? 'Проверка и публикация…'
                    : 'Опубликовать новую версию'}
                </button>
                <button
                  type="button"
                  className="ghost-button"
                  disabled={busy}
                  onClick={() => {
                    setDraft(profileSettings(profile))
                    setFeedback(null)
                  }}
                >
                  Сбросить черновик
                </button>
              </div>
            </form>

            <aside className="tenant-experience-preview">
              <div className="tenant-brand-preview" style={previewStyle}>
                <header>
                  {profile.logo ? (
                    <img src={profile.logo.data_url} alt="" />
                  ) : (
                    <span>{draft.short_name}</span>
                  )}
                  <strong>{draft.product_name}</strong>
                </header>
                <h3>{draft.terminology.incident_plural}</h3>
                <p>
                  {draft.terminology.service_plural} · {draft.terminology.knowledge_base}
                </p>
                <span className="tenant-brand-preview-action" aria-hidden="true">
                  Основное действие
                </span>
              </div>
              <dl className="tenant-contrast-evidence">
                <div>
                  <dt>Текст / фон</dt>
                  <dd>{draftContrast.text}:1</dd>
                </div>
                <div>
                  <dt>Primary / фон</dt>
                  <dd>{draftContrast.primary}:1</dd>
                </div>
                <div>
                  <dt>Accent / фон</dt>
                  <dd>{draftContrast.accent}:1</dd>
                </div>
              </dl>

              <section className="tenant-logo-control">
                <h3>PNG-логотип</h3>
                {profile.logo ? (
                  <p>
                    {profile.logo.width}×{profile.logo.height} ·{' '}
                    {Math.ceil(profile.logo.size_bytes / 1024)} KB ·{' '}
                    <code>{profile.logo.sha256.slice(0, 12)}</code>
                  </p>
                ) : (
                  <p className="muted">Используется короткое имя.</p>
                )}
                <input
                  type="file"
                  accept="image/png,.png"
                  disabled={!canManage || busy}
                  onChange={(event) => setLogoFile(event.target.files?.[0] ?? null)}
                />
                <div className="tenant-experience-actions">
                  <button
                    type="button"
                    disabled={!canManage || !hasReason || !logoFile || busy}
                    onClick={() => logoMutation.mutate()}
                  >
                    Загрузить PNG
                  </button>
                  <button
                    type="button"
                    className="ghost-button"
                    disabled={!canManage || !hasReason || !profile.logo || busy}
                    onClick={() => removeLogoMutation.mutate()}
                  >
                    Отключить
                  </button>
                </div>
                <small>
                  До {Math.floor(profile.capabilities.logo_max_bytes / 1024)} KB,
                  32–2048 px. SVG, внешние URL и executable content запрещены.
                </small>
              </section>
            </aside>
          </div>

          {canRollback ? (
            <section className="tenant-experience-history">
              <header>
                <div>
                  <h3>Неизменяемая история версий</h3>
                  <p className="muted">
                    Rollback создаёт новую ревизию и не переписывает прошлое.
                  </p>
                </div>
                {revisionsQuery.isFetching ? <span role="status">Обновление…</span> : null}
              </header>
              <div className="ticket-table-wrap">
                <table className="ticket-table">
                  <caption className="sr-only">История experience-профиля организации</caption>
                  <thead>
                    <tr>
                      <th>Версия</th>
                      <th>Создана</th>
                      <th>Причина</th>
                      <th>Hash</th>
                      <th>Integrity</th>
                      <th>Действие</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(revisionsQuery.data ?? []).map((revision) => (
                      <tr key={revision.revision}>
                        <td>
                          <strong>v{revision.revision}</strong>
                          {revision.rolled_back_from_revision
                            ? <small>из v{revision.rolled_back_from_revision}</small>
                            : null}
                        </td>
                        <td>{formatDateTime(revision.created_at)}</td>
                        <td>{revision.change_reason}</td>
                        <td><code>{revision.snapshot_sha256.slice(0, 12)}</code></td>
                        <td>
                          <span className={revision.integrity_valid ? 'badge badge-positive' : 'badge badge-danger'}>
                            {revision.integrity_valid ? 'VALID' : 'INVALID'}
                          </span>
                        </td>
                        <td>
                          <button
                            type="button"
                            className="ghost-button"
                            disabled={
                              busy
                              || !hasReason
                              || !revision.integrity_valid
                              || revision.revision === profile.revision
                            }
                            onClick={() => rollbackMutation.mutate(revision.revision)}
                          >
                            Восстановить
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
        </>
      ) : null}
    </section>
    </LocalizedContent>
  )
}
