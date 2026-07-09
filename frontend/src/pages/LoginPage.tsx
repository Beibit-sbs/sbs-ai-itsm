import { FormEvent, useEffect, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import HealthBadge from '../components/HealthBadge'
import { DEMO_CREDENTIALS, useAuth } from '../auth/AuthContext'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { session, login } = useAuth()
  const [email, setEmail] = useState(DEMO_CREDENTIALS.email)
  const [password, setPassword] = useState(DEMO_CREDENTIALS.password)
  const [error, setError] = useState('')
  const target = (location.state as { from?: string } | null)?.from ?? '/dashboard'

  useEffect(() => {
    if (session) {
      navigate(target, { replace: true })
    }
  }, [navigate, session, target])

  if (session) {
    return <Navigate to={target} replace />
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')

    void login(email, password)
      .then(() => {
        navigate(target, { replace: true })
      })
      .catch((loginError: unknown) => {
        setError(loginError instanceof Error ? loginError.message : 'Не удалось выполнить вход')
      })
  }

  return (
    <main className="login-page">
      <section className="brand-panel">
        <div className="brand-mark">SBS</div>
        <div>
          <p className="eyebrow">SMART BUSINESS SYSTEMS</p>
          <h1>AI ITSM</h1>
          <p className="lead">Интеллектуальное управление ИТ-службой, активами и качеством сервиса.</p>
        </div>
        <div className="feature-grid">
          <article><strong>Service Desk</strong><span>Заявки и единая история работы</span></article>
          <article><strong>AI Copilot</strong><span>Классификация и рекомендации</span></article>
          <article><strong>SLA Control</strong><span>Контроль реакции и решения</span></article>
          <article><strong>Asset Map</strong><span>Оборудование и связи</span></article>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-card">
          <HealthBadge />
          <div>
            <p className="eyebrow">FOUNDATION-001</p>
            <h2>Вход в платформу</h2>
            <p className="muted">Демо-доступ: {DEMO_CREDENTIALS.email} / {DEMO_CREDENTIALS.password}</p>
          </div>
          <form onSubmit={submit}>
            <label>
              Корпоративная почта
              <input
                type="email"
                placeholder="name@company.kz"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label>
              Пароль
              <input
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </label>
            {error ? <p className="error-message">{error}</p> : null}
            <button type="submit">Войти в демонстрационный кабинет</button>
          </form>
          <p className="security-note">Защищённый multi-tenant контур · Audit ready</p>
        </div>
      </section>
    </main>
  )
}
