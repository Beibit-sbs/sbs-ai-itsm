import type { ReactNode } from 'react'
import { NavLink, Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { fetchNotificationUnreadCount } from '../api/client'
import { useAuth } from '../auth/AuthContext'

type AppShellProps = {
  title: string
  subtitle: string
  children: ReactNode
}

const navigationGroups = [
  {
    section: 'Core',
    items: [
      { to: '/dashboard', label: 'Обзор', end: true },
      { to: '/tickets', label: 'Заявки' },
      { to: '/notifications', label: 'Уведомления' },
      { to: '/assets', label: 'Активы' },
      { to: '/sla', label: 'SLA' },
    ],
  },
  {
    section: 'AI & Knowledge',
    items: [
      { to: '/knowledge', label: 'База знаний' },
      { to: '/copilot', label: 'AI Copilot' },
    ],
  },
  {
    section: 'Executive',
    items: [
      { to: '/analytics', label: 'Аналитика' },
      { to: '/automation', label: 'Автоматизация' },
      { to: '/integrations', label: 'Интеграции' },
    ],
  },
  {
    section: 'Admin & Security',
    items: [{ to: '/admin', label: 'Администрирование' }],
  },
] as const

export default function AppShell({ title, subtitle, children }: AppShellProps) {
  const { session, logout } = useAuth()
  const unreadQuery = useQuery({
    queryKey: ['notifications-unread-count', session?.access_token],
    queryFn: () => fetchNotificationUnreadCount(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
    refetchInterval: 15000,
  })
  const unreadCount = unreadQuery.data?.unread_count ?? 0
  const role = session?.user.role ?? 'guest'

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="sidebar-logo">
          <span>SBS</span>
          <strong>AI ITSM</strong>
        </div>

        <nav>
          {navigationGroups.map((group) => {
            const items = group.items.filter((item) => {
              if (item.to === '/admin') {
                return ['saas_root', 'organization_admin', 'security_officer'].includes(role)
              }
              if (item.to === '/analytics') {
                return ['saas_root', 'organization_admin', 'it_manager', 'security_officer'].includes(role)
              }
              if (item.to === '/integrations') {
                return ['saas_root', 'organization_admin', 'it_manager', 'security_officer'].includes(role)
              }
              if (item.to === '/automation') {
                return ['saas_root', 'organization_admin', 'it_manager', 'it_agent', 'security_officer'].includes(role)
              }
              if (item.to === '/copilot') {
                return role !== 'requester'
              }
              return true
            })
            if (items.length === 0) return null
            return (
              <div className="nav-group" key={group.section}>
                <p className="nav-group-title">{group.section}</p>
                {items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={'end' in item ? item.end : undefined}
                    className={({ isActive }) => (isActive ? 'active' : '')}
                  >
                    <span className="nav-item-label">{item.label}</span>
                    {item.to === '/notifications' && unreadCount > 0 ? <span className="nav-badge">{unreadCount}</span> : null}
                  </NavLink>
                ))}
              </div>
            )
          })}
        </nav>

        <Link className="logout" to="/login">
          Выйти
        </Link>
      </aside>

      <main className="dashboard">
        <header className="topbar">
          <div>
            <p className="eyebrow">ОПЕРАЦИОННЫЙ ЦЕНТР</p>
            <h1>{title}</h1>
            <p className="page-subtitle">{subtitle}</p>
          </div>
          <div className="user-chip">
            <span>{session?.user.email}</span>
            <button type="button" className="ghost-button" onClick={logout}>
              Выйти
            </button>
          </div>
        </header>

        {children}
      </main>
    </div>
  )
}