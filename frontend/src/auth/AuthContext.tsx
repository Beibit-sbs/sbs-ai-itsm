import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  fetchCurrentUser,
  loginWithPassword,
  logoutSession,
  refreshAuthSession,
  verifyMfaLogin as verifyMfaLoginRequest,
  type AuthSession,
  type MfaChallenge,
} from '../api/client'

const STORAGE_KEY = 'sbs-ai-itsm-session'

// Demo credentials must be explicitly supplied at build time and are never
// embedded in the production source tree.
export const DEMO_CREDENTIALS = {
  email: import.meta.env.VITE_DEMO_EMAIL ?? '',
  password: import.meta.env.VITE_DEMO_PASSWORD ?? '',
}

export const DEMO_ROLE_ACCOUNTS: ReadonlyArray<{
  role: string
  email: string
  password: string
}> = []

type AuthContextValue = {
  session: AuthSession | null
  login: (email: string, password: string) => Promise<MfaChallenge | null>
  verifyMfaLogin: (challengeToken: string, code: string) => Promise<void>
  completeSsoLogin: () => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null)
  const validatedAccessTokenRef = useRef<string | null>(null)

  useEffect(() => {
    const storedSession = window.sessionStorage.getItem(STORAGE_KEY)
    if (!storedSession) return

    try {
      setSession(JSON.parse(storedSession) as AuthSession)
    } catch {
      window.sessionStorage.removeItem(STORAGE_KEY)
    }
  }, [])

  useEffect(() => {
    const syncSession = () => {
      const storedSession = window.sessionStorage.getItem(STORAGE_KEY)
      if (!storedSession) {
        validatedAccessTokenRef.current = null
        setSession(null)
        return
      }

      try {
        const parsedSession = JSON.parse(storedSession) as AuthSession
        validatedAccessTokenRef.current = parsedSession.access_token
        setSession(parsedSession)
      } catch {
        validatedAccessTokenRef.current = null
        setSession(null)
        window.sessionStorage.removeItem(STORAGE_KEY)
      }
    }

    window.addEventListener('sbs-auth-session-updated', syncSession)
    window.addEventListener('storage', syncSession)
    return () => {
      window.removeEventListener('sbs-auth-session-updated', syncSession)
      window.removeEventListener('storage', syncSession)
    }
  }, [])

  useEffect(() => {
    let isCancelled = false

    async function validateSession() {
      if (!session) return
      if (validatedAccessTokenRef.current === session.access_token) return

      try {
        const currentUser = await fetchCurrentUser(session.access_token)
        if (isCancelled) return
        const validatedSession = { ...session, user: currentUser }
        validatedAccessTokenRef.current = session.access_token
        setSession(validatedSession)
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(validatedSession))
      } catch {
        try {
          const refreshedSession = await refreshAuthSession()
          if (isCancelled) return
          validatedAccessTokenRef.current = refreshedSession.access_token
          setSession(refreshedSession)
          window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(refreshedSession))
        } catch {
          if (isCancelled) return
          validatedAccessTokenRef.current = null
          setSession(null)
          window.sessionStorage.removeItem(STORAGE_KEY)
        }
      }
    }

    void validateSession()

    return () => {
      isCancelled = true
    }
  }, [session])

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      login: async (email: string, password: string) => {
        const result = await loginWithPassword({ email, password })
        if ('mfa_required' in result) {
          return result
        }
        const nextSession = result
        validatedAccessTokenRef.current = nextSession.access_token
        setSession(nextSession)
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession))
        return null
      },
      verifyMfaLogin: async (challengeToken: string, code: string) => {
        const nextSession = await verifyMfaLoginRequest(challengeToken, code)
        validatedAccessTokenRef.current = nextSession.access_token
        setSession(nextSession)
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession))
      },
      completeSsoLogin: async () => {
        const nextSession = await refreshAuthSession()
        validatedAccessTokenRef.current = nextSession.access_token
        setSession(nextSession)
        window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession))
      },
      logout: () => {
        void logoutSession(session?.access_token)
        setSession(null)
        window.sessionStorage.removeItem(STORAGE_KEY)
      },
    }),
    [session],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used inside AuthProvider')
  }

  return context
}
