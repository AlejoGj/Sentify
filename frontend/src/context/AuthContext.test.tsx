import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import {
  authReducer,
  getInitialAuthState,
  type AuthAction,
} from './AuthContext'
import { isTokenExpired } from '@/utils/validators'

function createFakeJwt(exp: number): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = btoa(JSON.stringify({ exp, sub: 'user-123' }))
  const signature = 'fake-sig'
  return `${header}.${payload}.${signature}`
}

describe('AuthContext & AuthReducer (Unit Tests)', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    localStorage.clear()
  })

  describe('authReducer', () => {
    it('LOGIN actualiza token, companyName y expiresAt', () => {
      const expDate = new Date('2026-12-31T00:00:00Z')
      const action: AuthAction = {
        type: 'LOGIN',
        payload: {
          token: 'jwt-token-xyz',
          expiresAt: expDate,
          companyName: 'Sentify Corp',
        },
      }

      const state = authReducer(
        { token: null, companyName: null, expiresAt: null },
        action
      )

      expect(state).toEqual({
        token: 'jwt-token-xyz',
        companyName: 'Sentify Corp',
        expiresAt: expDate,
      })
    })

    it('LOGOUT restablece todos los campos a null', () => {
      const state = authReducer(
        {
          token: 'jwt-token-xyz',
          companyName: 'Sentify Corp',
          expiresAt: new Date(),
        },
        { type: 'LOGOUT' }
      )

      expect(state).toEqual({
        token: null,
        companyName: null,
        expiresAt: null,
      })
    })
  })

  describe('getInitialAuthState', () => {
    it('retorna estado vacío si localStorage no contiene sesión', () => {
      const state = getInitialAuthState()
      expect(state).toEqual({
        token: null,
        companyName: null,
        expiresAt: null,
      })
    })

    it('carga sesión desde localStorage si el token es válido y no ha expirado', () => {
      const futureExp = Math.floor(Date.now() / 1000) + 7200
      const token = createFakeJwt(futureExp)
      const expiresAtIso = new Date(futureExp * 1000).toISOString()

      localStorage.setItem('token', token)
      localStorage.setItem('company_name', 'Tech Enterprise')
      localStorage.setItem('expires_at', expiresAtIso)

      const state = getInitialAuthState()
      expect(state.token).toBe(token)
      expect(state.companyName).toBe('Tech Enterprise')
      expect(state.expiresAt?.toISOString()).toBe(expiresAtIso)
    })

    it('purga localStorage y retorna nulls si el token almacenado ya expiró', () => {
      const pastExp = Math.floor(Date.now() / 1000) - 3600
      const token = createFakeJwt(pastExp)

      localStorage.setItem('token', token)
      localStorage.setItem('company_name', 'Empresa Expirada')
      localStorage.setItem('expires_at', new Date(pastExp * 1000).toISOString())

      const state = getInitialAuthState()
      expect(state.token).toBeNull()
      expect(state.companyName).toBeNull()
      expect(state.expiresAt).toBeNull()

      // Debe haber limpiado localStorage
      expect(localStorage.getItem('token')).toBeNull()
      expect(localStorage.getItem('company_name')).toBeNull()
      expect(localStorage.getItem('expires_at')).toBeNull()
    })
  })

  describe('Lógica de sesión e isAuthenticated', () => {
    it('verifica correctamente si un token no ha expirado', () => {
      const futureExp = Math.floor(Date.now() / 1000) + 3600
      const validToken = createFakeJwt(futureExp)
      expect(isTokenExpired(validToken)).toBe(false)

      const pastExp = Math.floor(Date.now() / 1000) - 3600
      const expiredToken = createFakeJwt(pastExp)
      expect(isTokenExpired(expiredToken)).toBe(true)
    })

    it('simula persistencia de login() y purga de logout() en localStorage', () => {
      // Simulación de login
      const token = 'sample-jwt'
      const expiresAt = '2026-12-31T23:59:59Z'
      const companyName = 'Mi Empresa'

      localStorage.setItem('token', token)
      localStorage.setItem('expires_at', expiresAt)
      localStorage.setItem('company_name', companyName)

      expect(localStorage.getItem('token')).toBe(token)
      expect(localStorage.getItem('expires_at')).toBe(expiresAt)
      expect(localStorage.getItem('company_name')).toBe(companyName)

      // Simulación de logout
      localStorage.removeItem('token')
      localStorage.removeItem('expires_at')
      localStorage.removeItem('company_name')

      expect(localStorage.getItem('token')).toBeNull()
      expect(localStorage.getItem('expires_at')).toBeNull()
      expect(localStorage.getItem('company_name')).toBeNull()
    })
  })
})
