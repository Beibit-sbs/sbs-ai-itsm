import { FormEvent, useEffect, useRef, useState } from 'react'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import HealthBadge from '../components/HealthBadge'
import { DEMO_CREDENTIALS, DEMO_ROLE_ACCOUNTS, useAuth } from '../auth/AuthContext'
import { buildSsoLoginUrl, fetchSsoConfig, type MfaChallenge, type SsoConfig } from '../api/client'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import { isUiLocale, localeLabelKey } from '../i18n/catalog'

export default function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { session, login, verifyMfaLogin, completeSsoLogin } = useAuth()
  const {
    uiLocale,
    supportedUiLocales,
    setUiLocale,
    t,
  } = useTenantExperience()
  const [email, setEmail] = useState(DEMO_CREDENTIALS.email)
  const [password, setPassword] = useState(DEMO_CREDENTIALS.password)
  const [mfaChallenge, setMfaChallenge] = useState<MfaChallenge | null>(null)
  const [mfaCode, setMfaCode] = useState('')
  const [error, setError] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [ssoConfig, setSsoConfig] = useState<SsoConfig | null>(null)
  const ssoHandledRef = useRef(false)
  const target = (location.state as { from?: string } | null)?.from ?? '/dashboard'
  const hasDemoAccess = Boolean(DEMO_CREDENTIALS.email && DEMO_CREDENTIALS.password)

  useEffect(() => {
    if (session) {
      navigate(target, { replace: true })
    }
  }, [navigate, session, target])

  useEffect(() => {
    let cancelled = false
    void fetchSsoConfig()
      .then((config) => {
        if (!cancelled) setSsoConfig(config)
      })
      .catch(() => {
        if (!cancelled) setSsoConfig({ enabled: false, provider_name: null, button_label: null, login_path: null })
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const ssoStatus = params.get('sso')
    if (!ssoStatus || ssoHandledRef.current || session) return
    ssoHandledRef.current = true
    if (ssoStatus === 'error') {
      setError(t('login.error.sso'))
      return
    }
    if (ssoStatus !== 'success') return
    const requestedTarget = params.get('return_to')
    const ssoTarget = requestedTarget?.startsWith('/') && !requestedTarget.startsWith('//')
      ? requestedTarget
      : '/dashboard'
    setIsSubmitting(true)
    void completeSsoLogin()
      .then(() => navigate(ssoTarget, { replace: true }))
      .catch((loginError: unknown) => {
        setError(loginError instanceof Error ? loginError.message : t('login.error.ssoComplete'))
      })
      .finally(() => setIsSubmitting(false))
  }, [completeSsoLogin, location.search, navigate, session, t])

  if (session) {
    return <Navigate to={target} replace />
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setIsSubmitting(true)

    void login(email, password)
      .then((challenge) => {
        if (challenge) {
          setMfaChallenge(challenge)
          return
        }
        setEmail('')
        setPassword('')
        navigate(target, { replace: true })
      })
      .catch((loginError: unknown) => {
        setError(loginError instanceof Error ? loginError.message : t('login.error.signIn'))
      })
      .finally(() => {
        setPassword('')
        setIsSubmitting(false)
      })
  }

  function loginAsRole(emailValue: string, passwordValue: string) {
    setError('')
    setIsSubmitting(true)
    setEmail(emailValue)
    setPassword(passwordValue)

    void login(emailValue, passwordValue)
      .then((challenge) => {
        if (challenge) {
          setMfaChallenge(challenge)
          return
        }
        setEmail('')
        setPassword('')
        navigate(target, { replace: true })
      })
      .catch((loginError: unknown) => {
        setError(loginError instanceof Error ? loginError.message : t('login.error.signIn'))
      })
      .finally(() => {
        setPassword('')
        setIsSubmitting(false)
      })
  }

  function submitMfa(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!mfaChallenge) return
    setError('')
    setIsSubmitting(true)
    void verifyMfaLogin(mfaChallenge.challenge_token, mfaCode.trim())
      .then(() => {
        setEmail('')
        setPassword('')
        setMfaCode('')
        navigate(target, { replace: true })
      })
      .catch((loginError: unknown) => {
        setError(loginError instanceof Error ? loginError.message : t('login.error.mfa'))
      })
      .finally(() => setIsSubmitting(false))
  }

  return (
    <main className="login-page">
      <section className="brand-panel">
        <div className="brand-mark">SBS</div>
        <div>
          <p className="eyebrow">SMART BUSINESS SYSTEMS</p>
          <h1>AI ITSM</h1>
          <p className="lead">{t('login.lead')}</p>
        </div>
        <div className="feature-grid">
          <article><strong>Service Desk</strong><span>{t('login.serviceDesk')}</span></article>
          <article><strong>AI Copilot</strong><span>{t('login.copilot')}</span></article>
          <article><strong>{t('login.slaControlLabel')}</strong><span>{t('login.sla')}</span></article>
          <article><strong>{t('login.assetMapLabel')}</strong><span>{t('login.assets')}</span></article>
        </div>
      </section>

      <section className="login-panel">
        <div className="login-card">
          <div className="login-language-row">
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
          </div>
          <HealthBadge />
          <div>
            <p className="eyebrow">{t(hasDemoAccess ? 'login.demoAccess' : 'login.secureAccess')}</p>
            <h2>{t('login.title')}</h2>
            {hasDemoAccess ? (
              <p className="muted">{t('login.demoCredentials')}: {DEMO_CREDENTIALS.email} / {DEMO_CREDENTIALS.password}</p>
            ) : null}
          </div>
          {!mfaChallenge && DEMO_ROLE_ACCOUNTS.length > 0 ? (
            <div className="role-login-grid">
              {DEMO_ROLE_ACCOUNTS.map((account) => (
                <button
                  key={account.email}
                  type="button"
                  className="role-login-button"
                  onClick={() => loginAsRole(account.email, account.password)}
                  disabled={isSubmitting}
                >
                  <span>{account.role}</span>
                  <small>{account.email}</small>
                </button>
              ))}
            </div>
          ) : null}
          {mfaChallenge ? (
            <form onSubmit={submitMfa}>
              <div>
                <p className="eyebrow">{t('login.mfaEyebrow')}</p>
                <h2>{t('login.mfaTitle')}</h2>
                <p className="muted">
                  {t('login.mfaHelp', {
                    minutes: Math.max(1, Math.floor(mfaChallenge.expires_in_seconds / 60)),
                  })}
                </p>
              </div>
              <label>
                {t('login.oneTimeCode')}
                <input
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  autoFocus
                  placeholder={t('login.codePlaceholder')}
                  value={mfaCode}
                  onChange={(event) => setMfaCode(event.target.value)}
                  required
                  minLength={6}
                  maxLength={64}
                  disabled={isSubmitting}
                />
              </label>
              {error ? <p className="error-message" role="alert">{error}</p> : null}
              <button type="submit" disabled={isSubmitting || mfaCode.trim().length < 6}>
                {isSubmitting ? t('login.verifying') : t('login.verify')}
              </button>
              <button
                type="button"
                className="sso-login-button"
                disabled={isSubmitting}
                onClick={() => {
                  setMfaChallenge(null)
                  setMfaCode('')
                  setError('')
                }}
              >
                {t('login.backToPassword')}
              </button>
            </form>
          ) : (
          <form onSubmit={submit}>
            <label>
              {t('login.email')}
              <input
                type="email"
                placeholder="name@company.kz"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                disabled={isSubmitting}
              />
            </label>
            <label>
              {t('login.password')}
              <input
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                disabled={isSubmitting}
              />
            </label>
            {error ? <p className="error-message" role="alert">{error}</p> : null}
            <button type="submit" disabled={isSubmitting}>
              {isSubmitting
                ? t('login.signingIn')
                : hasDemoAccess
                  ? t('login.signInDemo')
                  : t('login.signIn')}
            </button>
          </form>
          )}
          {!mfaChallenge && ssoConfig?.enabled && ssoConfig.login_path ? (
            <>
              <div className="login-divider"><span>{t('login.or')}</span></div>
              <button
                type="button"
                className="sso-login-button"
                disabled={isSubmitting}
                onClick={() => {
                  window.location.assign(buildSsoLoginUrl(ssoConfig.login_path ?? '', target))
                }}
              >
                {ssoConfig.button_label ?? t('login.sso')}
              </button>
            </>
          ) : null}
          <p className="security-note">{t('login.securityNote')}</p>
        </div>
      </section>
    </main>
  )
}
