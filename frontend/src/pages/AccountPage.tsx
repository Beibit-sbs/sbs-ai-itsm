import { FormEvent, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import AppShell from '../components/AppShell'
import MfaEnrollmentPanel from '../components/MfaEnrollmentPanel'
import {
  changeMyPassword,
  fetchMyAccount,
  fetchMySessions,
  revokeMySession,
} from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { useTenantExperience } from '../experience/TenantExperienceContext'
import type { UiMessageKey } from '../i18n/catalog'

const roleLabelKeys: Record<string, UiMessageKey> = {
  saas_root: 'role.saas_root',
  organization_admin: 'role.organization_admin',
  it_manager: 'role.it_manager',
  it_agent: 'role.it_agent',
  requester: 'role.requester',
  security_officer: 'role.security_officer',
}

const provisioningLabelKeys: Record<string, UiMessageKey> = {
  LOCAL: 'account.provisioning.local',
  ACTIVE: 'account.provisioning.active',
  SUSPENDED: 'account.provisioning.suspended',
  DEPROVISIONED: 'account.provisioning.deprovisioned',
}

const authMethodLabelKeys: Record<string, UiMessageKey> = {
  pwd: 'account.authMethod.password',
  sso: 'account.authMethod.sso',
}

export default function AccountPage() {
  const { session, logout } = useAuth()
  const { t, formatDateTime } = useTenantExperience()
  const queryClient = useQueryClient()
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  const accountQuery = useQuery({
    queryKey: ['my-account', session?.access_token],
    queryFn: () => fetchMyAccount(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })
  const sessionsQuery = useQuery({
    queryKey: ['my-sessions', session?.access_token],
    queryFn: () => fetchMySessions(session?.access_token ?? ''),
    enabled: Boolean(session?.access_token),
  })

  const revokeMutation = useMutation({
    mutationFn: (sessionId: string) => revokeMySession(
      session?.access_token ?? '',
      sessionId,
    ),
    onSuccess: async (result) => {
      setError('')
      if (result.current_session_revoked) {
        logout()
        return
      }
      setMessage(t('account.session.revokedNotice'))
      await queryClient.invalidateQueries({ queryKey: ['my-sessions'] })
    },
    onError: (reason) => {
      setError(reason instanceof Error ? reason.message : t('account.session.revokeFailed'))
    },
  })

  const passwordMutation = useMutation({
    mutationFn: () => changeMyPassword(
      session?.access_token ?? '',
      currentPassword,
      newPassword,
    ),
    onSuccess: (result) => {
      setError('')
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      setMessage(t('account.password.changed', { count: result.sessions_revoked }))
      window.setTimeout(logout, 1200)
    },
    onError: (reason) => {
      setError(reason instanceof Error ? reason.message : t('account.password.changeFailed'))
    },
  })

  const account = accountQuery.data
  const sessions = sessionsQuery.data ?? []
  const activeSessions = sessions.filter((item) => item.is_active)

  function submitPassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setMessage('')
    setError('')
    if (newPassword !== confirmPassword) {
      setError(t('account.password.mismatch'))
      return
    }
    if (newPassword === currentPassword) {
      setError(t('account.password.same'))
      return
    }
    passwordMutation.mutate()
  }

  return (
    <AppShell
      title="Моя учётная запись"
      subtitle="Профиль, пароль, многофакторная защита и активные сессии"
    >
      {message ? (
        <p className="state-panel state-panel-success" role="status">{message}</p>
      ) : null}
      {error ? <p className="state-panel state-panel-error" role="alert">{error}</p> : null}
      {account?.must_change_password ? (
        <div className="state-panel state-panel-warning" role="alert">
          <strong>Требуется сменить временный пароль.</strong>
          <p>
            До смены пароля доступ к рабочим разделам ограничен. Введите выданный
            администратором временный пароль и установите собственный.
          </p>
        </div>
      ) : null}

      <section className="foundation-card account-profile-card">
        <div className="admin-section-heading">
          <div>
            <p className="eyebrow">ACCOUNT IDENTITY</p>
            <h2>Профиль и источник идентификации</h2>
          </div>
          {account ? (
            <span className={account.provisioning_state === 'ACTIVE' || account.provisioning_state === 'LOCAL' ? 'badge badge-positive' : 'badge badge-warning'}>
              {provisioningLabelKeys[account.provisioning_state]
                ? t(provisioningLabelKeys[account.provisioning_state])
                : account.provisioning_state}
            </span>
          ) : null}
        </div>
        {accountQuery.isPending ? (
          <p className="state-panel state-panel-loading">Загрузка профиля…</p>
        ) : null}
        {accountQuery.isError ? (
          <div className="state-panel state-panel-error">
            <p>Не удалось получить профиль.</p>
            <button type="button" className="ghost-button" onClick={() => accountQuery.refetch()}>
              Повторить
            </button>
          </div>
        ) : null}
        {account ? (
          <dl className="account-details-grid">
            <div><dt>Имя</dt><dd>{account.full_name}</dd></div>
            <div><dt>Email</dt><dd>{account.email}</dd></div>
            <div><dt>Роль</dt><dd>{roleLabelKeys[account.role] ? t(roleLabelKeys[account.role]) : account.role}</dd></div>
            <div><dt>Источник</dt><dd>{account.identity_source === 'LOCAL' ? t('account.identity.local') : account.identity_source}</dd></div>
            <div><dt>Организация</dt><dd>{account.tenant_id ?? 'Глобальная область'}</dd></div>
            <div><dt>Последний вход</dt><dd>{formatDateTime(account.last_login_at)}</dd></div>
          </dl>
        ) : null}
      </section>

      {account?.local_password_supported ? (
        <section className="foundation-card account-password-card">
          <div>
            <p className="eyebrow">PASSWORD SECURITY</p>
            <h2>Изменить пароль</h2>
            <p className="muted">
              После изменения все активные сессии будут отозваны. Потребуется новый вход.
            </p>
          </div>
          <form className="account-password-form" onSubmit={submitPassword}>
            <label>
              <span>Текущий пароль</span>
              <input
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                onChange={(event) => setCurrentPassword(event.target.value)}
                maxLength={512}
                required
              />
            </label>
            <label>
              <span>Новый пароль</span>
              <input
                type="password"
                autoComplete="new-password"
                value={newPassword}
                onChange={(event) => setNewPassword(event.target.value)}
                minLength={8}
                maxLength={512}
                required
              />
            </label>
            <label>
              <span>Повторите новый пароль</span>
              <input
                type="password"
                autoComplete="new-password"
                value={confirmPassword}
                onChange={(event) => setConfirmPassword(event.target.value)}
                minLength={8}
                maxLength={512}
                required
              />
            </label>
            <button
              type="submit"
              disabled={
                passwordMutation.isPending
                || !currentPassword
                || newPassword.length < 8
                || !confirmPassword
              }
            >
              {passwordMutation.isPending ? 'Изменение…' : 'Изменить пароль и выйти'}
            </button>
          </form>
        </section>
      ) : account ? (
        <section className="foundation-card account-password-card">
          <p className="eyebrow">PASSWORD SECURITY</p>
          <h2>Пароль управляется поставщиком идентификации</h2>
          <p className="muted">
            {t('account.password.externalHelp', { provider: account.identity_source })}
          </p>
        </section>
      ) : null}

      {account?.local_password_supported && !account.must_change_password ? (
        <MfaEnrollmentPanel />
      ) : null}

      <section className="foundation-card account-sessions-card">
        <div className="admin-section-heading">
          <div>
            <p className="eyebrow">MY SESSIONS</p>
            <h2>Устройства и входы</h2>
            <p className="muted">
              {t('account.sessions.help', { count: activeSessions.length })}
            </p>
          </div>
          <button
            type="button"
            className="ghost-button"
            onClick={() => sessionsQuery.refetch()}
            disabled={sessionsQuery.isFetching}
          >
            {sessionsQuery.isFetching ? 'Обновление…' : 'Обновить'}
          </button>
        </div>
        {sessionsQuery.isPending ? (
          <p className="state-panel state-panel-loading">Загрузка сессий…</p>
        ) : null}
        {sessionsQuery.isError ? (
          <p className="state-panel state-panel-error">Не удалось получить сессии.</p>
        ) : null}
        {!sessionsQuery.isPending && sessions.length === 0 ? (
          <p className="state-panel state-panel-empty">История сессий пуста.</p>
        ) : null}
        {sessions.length > 0 ? (
          <div className="table-container">
            <table>
              <thead>
                <tr>
                  <th>Статус</th>
                  <th>Создана</th>
                  <th>Адрес</th>
                  <th>Клиент</th>
                  <th>Метод</th>
                  <th><span className="sr-only">Действия</span></th>
                </tr>
              </thead>
              <tbody>
                {sessions.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <span className={item.is_active ? 'badge badge-positive' : 'badge'}>
                        {item.is_active
                          ? t('account.session.active')
                          : item.revoked_at
                            ? t('account.session.revoked')
                            : t('account.session.expired')}
                      </span>
                      {item.is_current ? <small className="account-current-session">Текущая</small> : null}
                    </td>
                    <td>{formatDateTime(item.created_at)}</td>
                    <td>{item.ip_address ?? '—'}</td>
                    <td className="account-user-agent" title={item.user_agent ?? undefined}>
                      {item.user_agent ?? '—'}
                    </td>
                    <td>{item.auth_method && authMethodLabelKeys[item.auth_method]
                      ? t(authMethodLabelKeys[item.auth_method])
                      : item.auth_method ?? '—'}</td>
                    <td>
                      {item.is_active ? (
                        <button
                          type="button"
                          className={item.is_current ? 'ghost-button danger-button' : 'ghost-button'}
                          disabled={revokeMutation.isPending}
                          onClick={() => {
                            const warning = item.is_current
                              ? t('account.sessions.confirmCurrent')
                              : t('account.sessions.confirmSelected')
                            if (window.confirm(warning)) revokeMutation.mutate(item.id)
                          }}
                        >
                          {item.is_current ? 'Завершить и выйти' : 'Завершить'}
                        </button>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
    </AppShell>
  )
}
