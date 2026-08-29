import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  fetchTenantExperience,
  type TenantExperience,
  type TenantTerminology,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import {
  UI_LOCALES,
  isUiLocale,
  translateMessage,
  translateSource,
  type TranslationValues,
  type UiLocale,
  type UiMessageKey,
} from '../i18n/catalog'

const CACHE_PREFIX = 'sbs-ai-itsm-experience'
const UI_LOCALE_STORAGE_KEY = 'sbs-ai-itsm-ui-locale'
const CACHE_MAX_AGE_MS = 6 * 60 * 60 * 1000
const HEX_COLOR = /^#[0-9A-Fa-f]{6}$/

const defaultTerminology: TenantTerminology = {
  incident_singular: 'Инцидент',
  incident_plural: 'Инциденты',
  request_singular: 'Запрос услуги',
  request_plural: 'Запросы услуг',
  asset_singular: 'Актив',
  asset_plural: 'Активы',
  service_singular: 'Услуга',
  service_plural: 'Услуги',
  knowledge_base: 'База знаний',
}

export const defaultTenantExperience: TenantExperience = {
  tenant_id: null,
  revision: 0,
  is_default: true,
  product_name: 'SBS AI ITSM',
  short_name: 'SBS',
  primary_color: '#40A8FF',
  accent_color: '#7FE2FF',
  surface_color: '#07111F',
  text_color: '#E8F0FA',
  ui_locale: 'ru-RU',
  format_locale: 'ru-RU',
  timezone: 'Asia/Qyzylorda',
  currency_code: 'KZT',
  date_style: 'medium',
  hour_cycle: 'h23',
  first_day_of_week: 1,
  terminology: defaultTerminology,
  logo: null,
  contrast: {
    text_on_surface: 16.48,
    primary_on_surface: 7.45,
    accent_on_surface: 12.83,
    on_primary_color: '#03121E',
    on_accent_color: '#03121E',
  },
  etag: 'platform-default',
  updated_at: null,
  capabilities: {
    ui_locales: ['ru-RU', 'kk-KZ', 'en-US'],
    format_locales: ['ru-RU', 'kk-KZ', 'en-US'],
    currencies: ['KZT', 'RUB', 'USD', 'EUR'],
    date_styles: ['short', 'medium', 'long'],
    hour_cycles: ['h23', 'h12'],
    first_days_of_week: [1, 7],
    suggested_timezones: [
      'Asia/Qyzylorda',
      'Asia/Almaty',
      'UTC',
      'Europe/Moscow',
      'Europe/London',
      'America/New_York',
    ],
    logo_content_types: ['image/png'],
    logo_max_bytes: 524288,
  },
}

type TenantExperienceContextValue = {
  profile: TenantExperience
  uiLocale: UiLocale
  supportedUiLocales: readonly UiLocale[]
  setUiLocale: (locale: UiLocale) => void
  t: (key: UiMessageKey, values?: TranslationValues) => string
  translate: (source: string) => string
  isFallback: boolean
  isLoading: boolean
  term: (key: keyof TenantTerminology) => string
  formatDateTime: (
    value: string | Date | null | undefined,
    options?: Intl.DateTimeFormatOptions,
  ) => string
  formatNumber: (
    value: number,
    options?: Intl.NumberFormatOptions,
  ) => string
  formatCurrency: (value: number, currency?: string) => string
  refresh: () => Promise<void>
}

const TenantExperienceContext =
  createContext<TenantExperienceContextValue | null>(null)

function cacheKey(tenantId: string | null | undefined) {
  return `${CACHE_PREFIX}:${tenantId ?? 'global'}`
}

function isTerminology(value: unknown): value is TenantTerminology {
  if (!value || typeof value !== 'object') return false
  return Object.keys(defaultTerminology).every((key) => {
    const term = (value as Record<string, unknown>)[key]
    return typeof term === 'string' && term.length >= 2 && term.length <= 40
  })
}

function isSafeProfile(
  value: unknown,
  expectedTenantId: string | null | undefined,
): value is TenantExperience {
  if (!value || typeof value !== 'object') return false
  const profile = value as Partial<TenantExperience>
  if (profile.tenant_id !== (expectedTenantId ?? null)) return false
  if (
    typeof profile.revision !== 'number'
    || typeof profile.product_name !== 'string'
    || profile.product_name.length > 80
    || typeof profile.short_name !== 'string'
    || profile.short_name.length > 24
    || !HEX_COLOR.test(profile.primary_color ?? '')
    || !HEX_COLOR.test(profile.accent_color ?? '')
    || !HEX_COLOR.test(profile.surface_color ?? '')
    || !HEX_COLOR.test(profile.text_color ?? '')
    || !isUiLocale(profile.ui_locale)
    || typeof profile.format_locale !== 'string'
    || typeof profile.timezone !== 'string'
    || !isTerminology(profile.terminology)
    || !profile.capabilities
  ) {
    return false
  }
  if (
    profile.logo
    && (
      !profile.logo.data_url.startsWith('data:image/png;base64,')
      || profile.logo.size_bytes > 524288
    )
  ) {
    return false
  }
  return true
}

function readCachedProfile(
  tenantId: string | null | undefined,
): TenantExperience | null {
  try {
    const raw = window.sessionStorage.getItem(cacheKey(tenantId))
    if (!raw) return null
    const cached = JSON.parse(raw) as {
      cached_at?: number
      profile?: unknown
    }
    if (
      typeof cached.cached_at !== 'number'
      || Date.now() - cached.cached_at > CACHE_MAX_AGE_MS
      || !isSafeProfile(cached.profile, tenantId)
    ) {
      window.sessionStorage.removeItem(cacheKey(tenantId))
      return null
    }
    return cached.profile
  } catch {
    window.sessionStorage.removeItem(cacheKey(tenantId))
    return null
  }
}

function writeCachedProfile(profile: TenantExperience) {
  try {
    window.sessionStorage.setItem(
      cacheKey(profile.tenant_id),
      JSON.stringify({ cached_at: Date.now(), profile }),
    )
  } catch {
    // A full or disabled storage area must never block application rendering.
  }
}

function readPreferredUiLocale(): UiLocale | null {
  try {
    const stored = window.localStorage.getItem(UI_LOCALE_STORAGE_KEY)
    return isUiLocale(stored) ? stored : null
  } catch {
    return null
  }
}

function writePreferredUiLocale(locale: UiLocale) {
  try {
    window.localStorage.setItem(UI_LOCALE_STORAGE_KEY, locale)
  } catch {
    // A disabled storage area must not block language switching.
  }
}

function applyProfileToDocument(
  profile: TenantExperience,
  uiLocale: UiLocale,
) {
  const root = document.documentElement
  root.lang = uiLocale.split('-')[0] || 'ru'
  root.style.setProperty('--brand-primary', profile.primary_color)
  root.style.setProperty('--brand-accent', profile.accent_color)
  root.style.setProperty('--brand-surface', profile.surface_color)
  root.style.setProperty('--brand-text', profile.text_color)
  root.style.setProperty(
    '--brand-on-primary',
    String(profile.contrast.on_primary_color ?? '#03121E'),
  )
  root.style.setProperty(
    '--brand-on-accent',
    String(profile.contrast.on_accent_color ?? '#03121E'),
  )
  document.title = profile.product_name
}

export function TenantExperienceProvider({
  children,
}: {
  children: ReactNode
}) {
  const { session } = useAuth()
  const tenantId = session?.user.tenant_id ?? null
  const [fallback, setFallback] = useState<TenantExperience>(
    () => readCachedProfile(tenantId) ?? defaultTenantExperience,
  )
  const [uiLocale, setUiLocaleState] = useState<UiLocale>(
    () => readPreferredUiLocale() ?? 'ru-RU',
  )

  useEffect(() => {
    setFallback(readCachedProfile(tenantId) ?? {
      ...defaultTenantExperience,
      tenant_id: tenantId,
    })
  }, [tenantId])

  const query = useQuery({
    queryKey: ['tenant-experience-bootstrap', session?.access_token, tenantId],
    queryFn: () =>
      fetchTenantExperience(session?.access_token ?? '', tenantId),
    enabled: Boolean(session?.access_token),
    staleTime: 60_000,
    retry: 1,
  })
  const profile = query.data ?? fallback

  useEffect(() => {
    if (readPreferredUiLocale() || !isUiLocale(profile.ui_locale)) return
    setUiLocaleState(profile.ui_locale)
  }, [profile.ui_locale])

  useEffect(() => {
    if (!query.data) return
    writeCachedProfile(query.data)
    setFallback(query.data)
  }, [query.data])

  useEffect(() => {
    applyProfileToDocument(profile, uiLocale)
  }, [profile, uiLocale])

  const value = useMemo<TenantExperienceContextValue>(() => {
    const formatDateTime = (
      input: string | Date | null | undefined,
      options: Intl.DateTimeFormatOptions = {},
    ) => {
      if (!input) return '—'
      const date = input instanceof Date ? input : new Date(input)
      if (Number.isNaN(date.getTime())) return '—'
      try {
        return new Intl.DateTimeFormat(uiLocale, {
          dateStyle: profile.date_style,
          timeStyle: 'short',
          timeZone: profile.timezone,
          hourCycle: profile.hour_cycle,
          ...options,
        }).format(date)
      } catch {
        return new Intl.DateTimeFormat(uiLocale, {
          dateStyle: 'medium',
          timeStyle: 'short',
          timeZone: 'UTC',
        }).format(date)
      }
    }
    const formatNumber = (
      input: number,
      options: Intl.NumberFormatOptions = {},
    ) => {
      try {
        return new Intl.NumberFormat(
          uiLocale,
          options,
        ).format(input)
      } catch {
        return String(input)
      }
    }
    const formatCurrency = (input: number, currency?: string) =>
      formatNumber(input, {
        style: 'currency',
        currency: currency ?? profile.currency_code,
      })
    return {
      profile,
      uiLocale,
      supportedUiLocales: UI_LOCALES,
      setUiLocale: (locale) => {
        if (!isUiLocale(locale)) return
        writePreferredUiLocale(locale)
        setUiLocaleState(locale)
      },
      t: (key, values) => translateMessage(uiLocale, key, values),
      translate: (source) => translateSource(uiLocale, source),
      isFallback: !query.data,
      isLoading: query.isLoading,
      term: (key) => translateSource(
        uiLocale,
        profile.terminology[key] ?? defaultTerminology[key],
      ),
      formatDateTime,
      formatNumber,
      formatCurrency,
      refresh: async () => {
        await query.refetch()
      },
    }
  }, [profile, query, uiLocale])

  return (
    <TenantExperienceContext.Provider value={value}>
      {children}
    </TenantExperienceContext.Provider>
  )
}

export function useTenantExperience() {
  const context = useContext(TenantExperienceContext)
  if (!context) {
    throw new Error(
      'useTenantExperience must be used inside TenantExperienceProvider',
    )
  }
  return context
}
