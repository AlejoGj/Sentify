import React, { createContext, useReducer, type ReactNode } from 'react'
import type { AuthState, AuthContextValue } from '@/types'
import { isTokenExpired } from '@/utils/validators'

// ─── Tipos de Acciones del Reducer ───────────────────────────────────────────

export type AuthAction =
  | {
      type: 'LOGIN'
      payload: {
        token: string
        expiresAt: Date | null
        companyName: string
      }
    }
  | { type: 'LOGOUT' }

// ─── Reducer de Autenticación ────────────────────────────────────────────────

export function authReducer(state: AuthState, action: AuthAction): AuthState {
  switch (action.type) {
    case 'LOGIN':
      return {
        token: action.payload.token,
        expiresAt: action.payload.expiresAt,
        companyName: action.payload.companyName,
      }
    case 'LOGOUT':
      return {
        token: null,
        expiresAt: null,
        companyName: null,
      }
    default:
      return state
  }
}

// ─── Estado Inicial desde localStorage ───────────────────────────────────────

export function getInitialAuthState(): AuthState {
  if (typeof localStorage === 'undefined') {
    return {
      token: null,
      companyName: null,
      expiresAt: null,
    }
  }

  const token = localStorage.getItem('token')
  const companyName = localStorage.getItem('company_name')
  const expiresAtStr = localStorage.getItem('expires_at')

  if (!token) {
    return {
      token: null,
      companyName: null,
      expiresAt: null,
    }
  }

  // Si el token almacenado ya expiró, se purga la sesión
  if (isTokenExpired(token)) {
    localStorage.removeItem('token')
    localStorage.removeItem('expires_at')
    localStorage.removeItem('company_name')
    return {
      token: null,
      companyName: null,
      expiresAt: null,
    }
  }

  return {
    token,
    companyName,
    expiresAt: expiresAtStr ? new Date(expiresAtStr) : null,
  }
}

// ─── Contexto de Autenticación ───────────────────────────────────────────────

export const AuthContext = createContext<AuthContextValue | undefined>(undefined)

export interface AuthProviderProps {
  children: ReactNode
  initialState?: AuthState
}

/**
 * Proveedor de contexto global de autenticación para Sentify.
 * Maneja persistencia en localStorage y expone métodos de sesión.
 */
export const AuthProvider: React.FC<AuthProviderProps> = ({
  children,
  initialState,
}) => {
  const [state, dispatch] = useReducer(
    authReducer,
    initialState ?? getInitialAuthState()
  )

  const login = (token: string, expiresAt: string, companyName: string): void => {
    const expiresAtDate = expiresAt ? new Date(expiresAt) : null

    if (typeof localStorage !== 'undefined') {
      localStorage.setItem('token', token)
      localStorage.setItem('expires_at', expiresAt)
      localStorage.setItem('company_name', companyName)
    }

    dispatch({
      type: 'LOGIN',
      payload: {
        token,
        expiresAt: expiresAtDate,
        companyName,
      },
    })
  }

  const logout = (): void => {
    if (typeof localStorage !== 'undefined') {
      localStorage.removeItem('token')
      localStorage.removeItem('expires_at')
      localStorage.removeItem('company_name')
    }

    dispatch({ type: 'LOGOUT' })
  }

  const isAuthenticated = (): boolean => {
    if (!state.token) {
      return false
    }

    if (state.expiresAt && Date.now() >= state.expiresAt.getTime()) {
      return false
    }

    return !isTokenExpired(state.token)
  }

  const contextValue: AuthContextValue = {
    token: state.token,
    companyName: state.companyName,
    expiresAt: state.expiresAt,
    login,
    logout,
    isAuthenticated,
  }

  return (
    <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>
  )
}
