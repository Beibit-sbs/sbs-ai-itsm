import type { ReactElement } from 'react'
import { Link, Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import { canAccessPath } from './accessControl'
import LocalizedContent from '../experience/LocalizedContent'

export default function RequireAuth({ children }: { children: ReactElement }) {
  const { session } = useAuth()
  const location = useLocation()

  if (!session) {
    const returnTo = `${location.pathname}${location.search}${location.hash}`
    return <Navigate to="/login" replace state={{ from: returnTo }} />
  }

  if (session.user.must_change_password && location.pathname !== '/account') {
    return <Navigate to="/account" replace state={{ passwordChangeRequired: true }} />
  }

  if (!canAccessPath(session.user, location.pathname)) {
    return (
      <LocalizedContent>
      <main className="access-denied-page">
        <section className="access-denied-card" role="alert" aria-labelledby="access-denied-title">
          <p className="eyebrow">ACCESS CONTROL</p>
          <h1 id="access-denied-title">Недостаточно прав</h1>
          <p>
            Этот раздел не входит в разрешения вашей учётной записи. Запросите нужную роль
            у администратора организации или вернитесь в доступную рабочую область.
          </p>
          <div className="button-row">
            <Link className="primary-button" to="/dashboard">Вернуться в обзор</Link>
            <Link className="secondary-button" to="/account">Проверить учётную запись</Link>
          </div>
        </section>
      </main>
      </LocalizedContent>
    )
  }

  return children
}
