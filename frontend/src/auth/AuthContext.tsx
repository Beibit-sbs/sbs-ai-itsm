import { createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { fetchCurrentUser, loginWithPassword, logoutSession, refreshAuthSession, type AuthSession } from '../api/client'

const STORAGE_KEY = 'sbs-ai-itsm-session'

export const DEMO_CREDENTIALS = {
  email: 'admin@sbs.local',
  password: 'Sbs!2026',
}

type AuthContextValue = {
  session: AuthSession | null
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null)
  const validatedAccessTokenRef = useRef<string | null>(null)

  useEffect(() => {
    const storedSession = window.localStorage.getItem(STORAGE_KEY)
    if (!storedSession) return

    try {
      setSession(JSON.parse(storedSession) as AuthSession)
    } catch {
      window.localStorage.removeItem(STORAGE_KEY)
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
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(validatedSession))
      } catch {
        try {
          const refreshedSession = await refreshAuthSession({ refresh_token: session.refresh_token })
          if (isCancelled) return
          validatedAccessTokenRef.current = refreshedSession.access_token
          setSession(refreshedSession)
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(refreshedSession))
        } catch {
          if (isCancelled) return
          validatedAccessTokenRef.current = null
          setSession(null)
          window.localStorage.removeItem(STORAGE_KEY)
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
        const nextSession = await loginWithPassword({ email, password })
        setSession(nextSession)
        window.localStorage.setItem(STORAGE_KEY, JSON.stringify(nextSession))
      },
      logout: () => {
        void logoutSession(session?.access_token, { refresh_token: session?.refresh_token })
        setSession(null)
        window.localStorage.removeItem(STORAGE_KEY)
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