import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  confirmMfaEnrollment,
  disableMfa,
  fetchMfaStatus,
  regenerateMfaRecoveryCodes,
  startMfaEnrollment,
  type MfaEnrollment,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import LocalizedContent from '../experience/LocalizedContent'
import { useTenantExperience } from '../experience/TenantExperienceContext'

export default function MfaEnrollmentPanel() {
  const { session, logout } = useAuth()
  const { formatDateTime, translate } = useTenantExperience()
  const queryClient = useQueryClient()
  const [currentPassword, setCurrentPassword] = useState('')
  const [verificationCode, setVerificationCode] = useState('')
  const [enrollment, setEnrollment] = useState<MfaEnrollment | null>(null)
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([])
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const statusQuery = useQuery({
    queryKey: ['mfa-status', session?.access_token],
    queryFn: () => fetchMfaStatus(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const beginMutation = useMutation({
    mutationFn: () => startMfaEnrollment(session?.access_token ?? '', currentPassword),
    onSuccess: (result) => {
      setEnrollment(result)
      setCurrentPassword('')
      setVerificationCode('')
      setRecoveryCodes([])
      setMessage('Секрет создан. Добавьте его в приложение-аутентификатор и подтвердите текущим кодом.')
      setError('')
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : 'Не удалось начать регистрацию MFA'),
  })

  const confirmMutation = useMutation({
    mutationFn: () => confirmMfaEnrollment(session?.access_token ?? '', verificationCode.trim()),
    onSuccess: async (result) => {
      setRecoveryCodes(result.recovery_codes)
      setEnrollment(null)
      setVerificationCode('')
      setMessage('MFA включена. Сохраните recovery-коды сейчас: повторно они не отображаются.')
      setError('')
      await queryClient.invalidateQueries({ queryKey: ['mfa-status'] })
      await queryClient.invalidateQueries({ queryKey: ['security-mfa-overview'] })
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : 'Код не принят'),
  })

  const regenerateMutation = useMutation({
    mutationFn: () => regenerateMfaRecoveryCodes(session?.access_token ?? '', verificationCode.trim()),
    onSuccess: async (result) => {
      setRecoveryCodes(result.recovery_codes)
      setVerificationCode('')
      setMessage('Предыдущие recovery-коды аннулированы. Сохраните новый комплект.')
      setError('')
      await queryClient.invalidateQueries({ queryKey: ['mfa-status'] })
      await queryClient.invalidateQueries({ queryKey: ['security-mfa-overview'] })
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : 'Не удалось выпустить recovery-коды'),
  })

  const disableMutation = useMutation({
    mutationFn: () => disableMfa(session?.access_token ?? '', currentPassword, verificationCode.trim()),
    onSuccess: () => {
      logout()
    },
    onError: (reason) => setError(reason instanceof Error ? reason.message : 'Не удалось отключить MFA'),
  })

  const status = statusQuery.data
  const isBusy = beginMutation.isPending || confirmMutation.isPending || regenerateMutation.isPending || disableMutation.isPending

  async function copyText(value: string, successMessage: string) {
    try {
      await navigator.clipboard.writeText(value)
      setMessage(successMessage)
      setError('')
    } catch {
      setError('Браузер не разрешил копирование. Выделите значение и скопируйте вручную.')
    }
  }

  function submitEnrollment(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    beginMutation.mutate()
  }

  function submitConfirmation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    confirmMutation.mutate()
  }

  return (
    <LocalizedContent>
    <section className="foundation-card admin-panel mfa-panel">
      <div className="admin-section-heading">
        <div>
          <p className="eyebrow">MY MULTI-FACTOR AUTHENTICATION</p>
          <h2>Защита моей учётной записи</h2>
          <p className="muted">
            TOTP работает с Microsoft Authenticator, Google Authenticator, 1Password и другими совместимыми приложениями.
          </p>
        </div>
        {status ? (
          <span className={status.enabled ? 'badge badge-positive' : status.required_for_role ? 'badge badge-danger' : 'badge badge-warning'}>
            {status.enabled ? 'MFA ENABLED' : status.required_for_role ? 'MFA REQUIRED' : 'MFA DISABLED'}
          </span>
        ) : null}
      </div>

      {statusQuery.isPending ? <p className="state-panel state-panel-loading">Проверяем статус MFA…</p> : null}
      {statusQuery.isError ? (
        <div className="state-panel state-panel-error">
          <p>Не удалось получить статус MFA.</p>
          <button type="button" className="ghost-button" onClick={() => statusQuery.refetch()}>Повторить</button>
        </div>
      ) : null}

      {status ? (
        <div className="mfa-status-grid">
          <div><span>Политика</span><strong>{status.policy_enforced ? 'Применяется' : 'Не включена'}</strong></div>
          <div><span>Для моей роли</span><strong>{status.required_for_role ? 'Обязательна' : 'Опциональна'}</strong></div>
          <div><span>Текущая сессия</span><strong>{status.current_session_verified ? 'MFA verified' : 'Password / SSO'}</strong></div>
          <div><span>Recovery-коды</span><strong>{status.enabled ? status.recovery_codes_remaining : '—'}</strong></div>
          <div><span>Подтверждена</span><strong>{formatDateTime(status.verified_at)}</strong></div>
          <div><span>Блокировка</span><strong>{status.locked ? 'Временно заблокирована' : 'Нет'}</strong></div>
        </div>
      ) : null}

      {message ? <p className="state-panel state-panel-success">{message}</p> : null}
      {error ? <p className="error-message">{error}</p> : null}

      {recoveryCodes.length > 0 ? (
        <div className="mfa-recovery-box">
          <div>
            <p className="eyebrow">ONE-TIME RECOVERY CODES</p>
            <h3>Сохраните вне платформы</h3>
            <p className="muted">Каждый код работает один раз. Новый выпуск немедленно аннулирует предыдущий комплект.</p>
          </div>
          <div className="mfa-code-grid">
            {recoveryCodes.map((code) => <code key={code}>{code}</code>)}
          </div>
          <button type="button" className="ghost-button" onClick={() => copyText(recoveryCodes.join('\n'), 'Recovery-коды скопированы.')}>
            Копировать все коды
          </button>
        </div>
      ) : null}

      {status && !status.enabled && !enrollment ? (
        <form className="mfa-action-form" onSubmit={submitEnrollment}>
          <label>
            <span>Текущий пароль</span>
            <input
              type="password"
              autoComplete="current-password"
              value={currentPassword}
              onChange={(event) => setCurrentPassword(event.target.value)}
              required
              disabled={isBusy}
            />
          </label>
          <button type="submit" disabled={isBusy || !currentPassword}>
            {beginMutation.isPending ? 'Создаём секрет…' : 'Настроить MFA'}
          </button>
        </form>
      ) : null}

      {enrollment ? (
        <div className="mfa-enrollment-box">
          <div>
            <p className="eyebrow">ENROLLMENT</p>
            <h3>Добавьте учётную запись в аутентификатор</h3>
            <ol className="mfa-steps">
              <li>Откройте приложение-аутентификатор и выберите ручной ввод ключа.</li>
              <li>Тип ключа: time-based / TOTP. Название: {enrollment.issuer}.</li>
              <li>Введите код, появившийся в приложении.</li>
            </ol>
          </div>
          <label>
            <span>Секретный ключ</span>
            <div className="mfa-copy-row">
              <input value={enrollment.secret} readOnly />
              <button type="button" className="ghost-button" onClick={() => copyText(enrollment.secret, 'Секрет скопирован.')}>Копировать</button>
            </div>
          </label>
          <details>
            <summary>Показать otpauth URI для импорта</summary>
            <div className="mfa-copy-row">
              <input value={enrollment.otpauth_uri} readOnly />
              <button type="button" className="ghost-button" onClick={() => copyText(enrollment.otpauth_uri, 'URI скопирован.')}>Копировать</button>
            </div>
          </details>
          <form className="mfa-action-form" onSubmit={submitConfirmation}>
            <label>
              <span>Шестизначный TOTP-код</span>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                value={verificationCode}
                onChange={(event) => setVerificationCode(event.target.value)}
                minLength={6}
                maxLength={6}
                required
                disabled={isBusy}
              />
            </label>
            <button type="submit" disabled={isBusy || verificationCode.trim().length !== 6}>
              {confirmMutation.isPending ? 'Проверяем…' : 'Подтвердить и включить'}
            </button>
            <button type="button" className="ghost-button" disabled={isBusy} onClick={() => setEnrollment(null)}>Отмена</button>
          </form>
        </div>
      ) : null}

      {status?.enabled ? (
        <div className="mfa-enabled-actions">
          <form
            className="mfa-action-form"
            onSubmit={(event) => {
              event.preventDefault()
              setError('')
              regenerateMutation.mutate()
            }}
          >
            <div>
              <h3>Обновить recovery-коды</h3>
              <p className="muted">Понадобится свежий TOTP-код. Старые recovery-коды перестанут работать.</p>
            </div>
            <label>
              <span>TOTP-код</span>
              <input
                inputMode="numeric"
                autoComplete="one-time-code"
                value={verificationCode}
                onChange={(event) => setVerificationCode(event.target.value)}
                minLength={6}
                maxLength={6}
                required
                disabled={isBusy}
              />
            </label>
            <button type="submit" className="ghost-button" disabled={isBusy || verificationCode.trim().length !== 6}>
              {regenerateMutation.isPending ? 'Выпускаем…' : 'Выпустить новый комплект'}
            </button>
          </form>

          <form
            className="mfa-action-form mfa-danger-form"
            onSubmit={(event) => {
              event.preventDefault()
              if (window.confirm(translate('Отключить MFA? Все ваши активные сессии будут отозваны.'))) {
                setError('')
                disableMutation.mutate()
              }
            }}
          >
            <div>
              <h3>Отключить MFA</h3>
              <p className="muted">Требуются текущий пароль и TOTP либо неиспользованный recovery-код. После операции потребуется новый вход.</p>
            </div>
            <label>
              <span>Текущий пароль</span>
              <input
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                required
                disabled={isBusy}
              />
            </label>
            <label>
              <span>TOTP или recovery-код</span>
              <input
                autoComplete="one-time-code"
                value={verificationCode}
                onChange={(event) => setVerificationCode(event.target.value)}
                minLength={6}
                maxLength={64}
                required
                disabled={isBusy}
              />
            </label>
            <button type="submit" className="ghost-button danger-button" disabled={isBusy || !currentPassword || verificationCode.trim().length < 6}>
              {disableMutation.isPending ? 'Отключаем…' : 'Отключить MFA и завершить сессии'}
            </button>
          </form>
        </div>
      ) : null}
    </section>
    </LocalizedContent>
  )
}
