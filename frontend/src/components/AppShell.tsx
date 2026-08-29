import {
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { NavLink, Link, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchNotificationUnreadCount } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import GlobalSearchPalette from './GlobalSearchPalette'
import { useDialogFocusTrap } from '../accessibility/useDialogFocusTrap'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { canAccessPath } from '../auth/accessControl'
import { localizeTree } from '../experience/LocalizedContent'
import {
  isUiLocale,
  localeLabelKey,
  type UiMessageKey,
} from '../i18n/catalog'

type AppShellProps = {
  title: string
  subtitle: string
  children: ReactNode
}

type NavigationItem = {
  to: string
  labelKey: UiMessageKey
  end?: boolean
}

type NavigationGroup = {
  sectionKey: UiMessageKey
  items: readonly NavigationItem[]
}

const navigationGroups: readonly NavigationGroup[] = [
  {
    sectionKey: 'nav.core',
    items: [
      { to: '/account', labelKey: 'nav.account' },
      { to: '/problem-governance', labelKey: 'nav.problemGovernance' },
      { to: '/releases', labelKey: 'nav.releases' },
      { to: '/change-calendar', labelKey: 'nav.changeCalendar' },
      { to: '/events', labelKey: 'nav.events' },
      { to: '/major-incidents', labelKey: 'nav.majorIncidents' },
      { to: '/dashboard', labelKey: 'nav.dashboard', end: true },
      { to: '/catalog', labelKey: 'nav.catalog' },
      { to: '/requests', labelKey: 'nav.requests' },
      { to: '/tickets', labelKey: 'nav.tickets' },
      { to: '/changes', labelKey: 'nav.changes' },
      { to: '/problems', labelKey: 'nav.problems' },
      { to: '/notifications', labelKey: 'nav.notifications' },
      { to: '/assets', labelKey: 'nav.assets' },
      { to: '/software-assets', labelKey: 'nav.softwareAssets' },
      { to: '/sla', labelKey: 'nav.sla' },
    ],
  },
  {
    sectionKey: 'nav.aiKnowledge',
    items: [
      { to: '/knowledge', labelKey: 'nav.knowledge' },
      { to: '/copilot', labelKey: 'nav.copilot' },
    ],
  },
  {
    sectionKey: 'nav.executive',
    items: [
      { to: '/analytics', labelKey: 'nav.analytics' },
      { to: '/monitoring', labelKey: 'nav.monitoring' },
      { to: '/automation', labelKey: 'nav.automation' },
      { to: '/integrations', labelKey: 'nav.integrations' },
    ],
  },
  {
    sectionKey: 'nav.adminSecurity',
    items: [
      { to: '/admin/configuration-packages', labelKey: 'nav.configurationPackages' },
      { to: '/admin/custom-fields', labelKey: 'nav.customFields' },
      { to: '/admin', labelKey: 'nav.administration' },
      { to: '/admin/data-governance', labelKey: 'nav.dataGovernance' },
      { to: '/identity-provisioning', labelKey: 'nav.identityProvisioning' },
      { to: '/email-operations', labelKey: 'nav.emailOperations' },
      { to: '/teams-collaboration', labelKey: 'nav.teams' },
      { to: '/admin/system', labelKey: 'nav.system' },
    ],
  },
]

const roleLabelKeys: Record<string, UiMessageKey> = {
  saas_root: 'role.saas_root',
  organization_admin: 'role.organization_admin',
  it_manager: 'role.it_manager',
  it_agent: 'role.it_agent',
  requester: 'role.requester',
  security_officer: 'role.security_officer',
}

function shortTenantId(value: string | null | undefined) {
  if (!value) return 'global'
  return value.slice(0, 8)
}

export default function AppShell({ title, subtitle, children }: AppShellProps) {
  const { session, logout } = useAuth()
  const {
    profile,
    uiLocale,
    supportedUiLocales,
    setUiLocale,
    t,
    translate,
  } = useTenantExperience()
  const location = useLocation()
  const role = session?.user.role ?? 'guest'
  const permissions = new Set(session?.user.permissions ?? [])
  const canReadNotifications = role === 'saas_root' || permissions.has('notifications.read')
  const headingRef = useRef<HTMLHeadingElement>(null)
  const [mobileNavOpen, setMobileNavOpen] = useState(false)
  const mobileNavRef = useDialogFocusTrap<HTMLElement>(
    mobileNavOpen,
    () => setMobileNavOpen(false),
  )
  const unreadQuery = useQuery({
    queryKey: ['notifications-unread-count', session?.access_token],
    queryFn: () => fetchNotificationUnreadCount(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token && canReadNotifications),
    refetchInterval: 30000,
    refetchIntervalInBackground: false,
  })
  const unreadCount = unreadQuery.data?.unread_count ?? 0
  const roleLabel = roleLabelKeys[role] ? t(roleLabelKeys[role]) : role
  const displayTitle = translate(title)
  const displaySubtitle = translate(subtitle)
  const localizedChildren = localizeTree(children, translate)

  useEffect(() => {
    setMobileNavOpen(false)
    window.setTimeout(() => headingRef.current?.focus(), 0)
  }, [location.pathname])

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        {t('common.skipToContent')}
      </a>
      {mobileNavOpen ? (
        <button
          type="button"
          className="mobile-nav-backdrop"
          aria-label={t('common.closeNavigation')}
          onClick={() => setMobileNavOpen(false)}
        />
      ) : null}
      <aside
        ref={mobileNavRef}
        id="platform-navigation"
        className={mobileNavOpen ? 'sidebar mobile-open' : 'sidebar'}
        aria-label={t('common.platformNavigation')}
        aria-modal={mobileNavOpen || undefined}
        role={mobileNavOpen ? 'dialog' : undefined}
        tabIndex={mobileNavOpen ? -1 : undefined}
      >
        <div className="sidebar-logo" id="platform-navigation-title">
          {profile.logo ? (
            <img
              src={profile.logo.data_url}
              alt=""
              width={profile.logo.width}
              height={profile.logo.height}
            />
          ) : (
            <span>{profile.short_name}</span>
          )}
          <strong>{profile.product_name}</strong>
        </div>

        <nav aria-label={t('common.platformSections')}>
          {navigationGroups.map((group) => {
            const items = group.items.filter((item) => (
              canAccessPath({ role, permissions: Array.from(permissions) }, item.to)
            ))
            if (items.length === 0) return null
            return (
              <div className="nav-group" key={group.sectionKey}>
                <p className="nav-group-title">{t(group.sectionKey)}</p>
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={'end' in item ? item.end : undefined}
                    className={({ isActive }) => (isActive ? 'active' : '')}
                  >
                    <span className="nav-item-label">
                      {t(item.labelKey)}
                    </span>
                    {item.to === '/notifications' && unreadCount > 0 ? <span className="nav-badge">{unreadCount}</span> : null}
                  </NavLink>
                ))}
              </div>
            )
          })}
        </nav>

        <Link className="logout" to="/login" onClick={logout}>
          {t('common.logout')}
        </Link>
      </aside>

      <main
        id="main-content"
        className="dashboard module-shell"
        tabIndex={-1}
      >
        <div className="sr-only" aria-live="polite" aria-atomic="true">
          {t('common.openedPage', { title: displayTitle })}
        </div>
        <header className="topbar page-header">
          <div>
            <p className="eyebrow page-eyebrow">{t('common.operationsCenter')}</p>
            <h1 ref={headingRef} tabIndex={-1}>{displayTitle}</h1>
            <p className="page-subtitle">{displaySubtitle}</p>
          </div>
          <div className="page-actions">
            <button
              type="button"
              className="mobile-nav-toggle ghost-button"
              aria-expanded={mobileNavOpen}
              aria-controls="platform-navigation"
              onClick={() => setMobileNavOpen((current) => !current)}
            >
              {t('common.menu')}
            </button>
            <GlobalSearchPalette />
            <label className="language-switcher">
              <span className="sr-only">{t('language.label')}</span>
              <select
                aria-label={t('language.label')}
                value={uiLocale}
                onChange={(event) => {
                  if (isUiLocale(event.target.value)) setUiLocale(event.target.value)
                }}
              >
                {supportedUiLocales.map((locale) => (
                  <option key={locale} value={locale}>
                    {t(localeLabelKey(locale))}
                  </option>
                ))}
              </select>
            </label>
            <Link className="user-chip" to="/account" aria-label={t('common.openAccount')}>
              <span>{session?.user.email}</span>
              <small>{roleLabel}</small>
            </Link>
            <button type="button" className="ghost-button" onClick={logout}>
              {t('common.logout')}
            </button>
          </div>
        </header>

        <section className="page-context-strip" aria-label={t('common.sessionContext')}>
          <div className="context-chip">
            <span>{t('common.role')}</span>
            <strong>{roleLabel}</strong>
          </div>
          <div className="context-chip">
            <span>{t('common.tenant')}</span>
            <strong>{shortTenantId(session?.user.tenant_id)}</strong>
          </div>
          <div className="context-chip">
            <span>{t('common.notifications')}</span>
            <strong>{t('common.unread', { count: unreadCount })}</strong>
          </div>
          <div className="context-chip">
            <span>{t('common.status')}</span>
            <strong>{t('common.liveSession')}</strong>
          </div>
        </section>

        {localizedChildren}
      </main>
    </div>
  )
}
