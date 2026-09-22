import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import {
  isTokenExpired,
  validateFileBeforeUpload,
  validateLoginForm,
  validateRegisterForm,
  MAX_FILE_SIZE_BYTES,
} from './validators'

function createFakeJwt(exp: number): string {
  const header = btoa(JSON.stringify({ alg: 'HS256', typ: 'JWT' }))
  const payload = btoa(JSON.stringify({ exp, sub: 'user-123' }))
  const signature = 'fake-sig'
  return `${header}.${payload}.${signature}`
}

describe('validators.ts — Unit & Property Tests', () => {
  describe('isTokenExpired', () => {
    it('debe retornar true para tokens nulos, vacíos o malformados', () => {
      expect(isTokenExpired('')).toBe(true)
      expect(isTokenExpired('invalido')).toBe(true)
      expect(isTokenExpired('a.b')).toBe(true)
      expect(isTokenExpired('a.b.c.d')).toBe(true)
      expect(isTokenExpired(null as unknown as string)).toBe(true)
      expect(isTokenExpired(undefined as unknown as string)).toBe(true)
    })

    it('Property 1: JWT expirado siempre detectado (past -> true, future -> false)', () => {
      // Past exp -> isTokenExpired === true
      fc.assert(
        fc.property(
          fc.integer({ min: 1, max: Math.floor(Date.now() / 1000) - 1 }),
          (pastExp) => {
            const token = createFakeJwt(pastExp)
            return isTokenExpired(token) === true
          }
        ),
        { numRuns: 100 }
      )

      // Future exp -> isTokenExpired === false
      fc.assert(
        fc.property(
          fc.integer({
            min: Math.floor(Date.now() / 1000) + 3600,
            max: Math.floor(Date.now() / 1000) + 1_000_000,
          }),
          (futureExp) => {
            const token = createFakeJwt(futureExp)
            return isTokenExpired(token) === false
          }
        ),
        { numRuns: 100 }
      )
    })
  })

  describe('validateFileBeforeUpload', () => {
    it('debe rechazar archivos nulos o inválidos', () => {
      expect(validateFileBeforeUpload(null as unknown as { name: string; size: number })).toEqual({
        valid: false,
        error: 'Archivo inválido',
      })
    })

    it('Property 2: Validación de archivo rechaza entradas inválidas', () => {
      // Nombres sin extensión .csv con tamaño arbitrario -> valid === false
      fc.assert(
        fc.property(
          fc.string().filter((s) => !s.toLowerCase().endsWith('.csv')),
          fc.integer({ min: 1, max: 20_000_000 }),
          (name, size) => {
            const result = validateFileBeforeUpload({ name, size })
            return result.valid === false && typeof result.error === 'string'
          }
        ),
        { numRuns: 100 }
      )

      // Nombres .csv con size > 10_485_760 -> valid === false
      fc.assert(
        fc.property(
          fc.string().map((s) => `${s}.csv`),
          fc.integer({ min: MAX_FILE_SIZE_BYTES + 1, max: 100_000_000 }),
          (name, size) => {
            const result = validateFileBeforeUpload({ name, size })
            return result.valid === false && typeof result.error === 'string'
          }
        ),
        { numRuns: 100 }
      )

      // Nombres .csv con size entre 1 y 10_485_760 -> valid === true
      fc.assert(
        fc.property(
          fc.string({ minLength: 1 }).map((s) => `${s}.csv`),
          fc.integer({ min: 1, max: MAX_FILE_SIZE_BYTES }),
          (name, size) => {
            const result = validateFileBeforeUpload({ name, size })
            return result.valid === true && result.error === undefined
          }
        ),
        { numRuns: 100 }
      )
    })
  })

  describe('validateLoginForm & validateRegisterForm', () => {
    it('Property 9: Validación de formulario rechaza cualquier entrada inválida', () => {
      // Emails sin '@' o vacíos -> error presente
      fc.assert(
        fc.property(
          fc.string().filter((s) => !s.includes('@')),
          fc.string({ minLength: 8 }),
          (invalidEmail, validPassword) => {
            const errors = validateLoginForm(invalidEmail, validPassword)
            return Object.keys(errors).length > 0 && typeof errors.email === 'string'
          }
        ),
        { numRuns: 100 }
      )

      // Contraseñas con menos de 8 caracteres -> error presente
      fc.assert(
        fc.property(
          fc.tuple(fc.string({ minLength: 1 }), fc.string({ minLength: 1 })).map(([u, d]) => `${u}@${d}.com`),
          fc.string({ maxLength: 7 }),
          (validEmail, shortPassword) => {
            const errors = validateLoginForm(validEmail, shortPassword)
            return Object.keys(errors).length > 0 && typeof errors.password === 'string'
          }
        ),
        { numRuns: 100 }
      )

      // companyName vacío en validateRegisterForm -> produce al menos un error
      fc.assert(
        fc.property(
          fc.tuple(fc.string({ minLength: 1 }), fc.string({ minLength: 1 })).map(([u, d]) => `${u}@${d}.com`),
          fc.string({ minLength: 8 }),
          fc.constantFrom('', '   ', '\t', '\n'),
          (email, password, emptyCompany) => {
            const errors = validateRegisterForm(email, password, emptyCompany)
            return Object.keys(errors).length > 0 && typeof errors.companyName === 'string'
          }
        ),
        { numRuns: 100 }
      )

      // Entradas válidas: email con '@', password 8+ chars, companyName no vacío -> sin errores
      fc.assert(
        fc.property(
          fc
            .tuple(fc.string({ minLength: 1 }), fc.string({ minLength: 1 }))
            .map(([u, d]) => `${u.replace(/@/g, '')}@${d.replace(/@/g, '') || 'domain.com'}`)
            .filter((e) => e.includes('@') && e.trim().length > 0),
          fc.string({ minLength: 8 }),
          fc.string({ minLength: 1 }).filter((s) => s.trim().length > 0),
          (validEmail, validPassword, validCompany) => {
            const loginErrors = validateLoginForm(validEmail, validPassword)
            const registerErrors = validateRegisterForm(validEmail, validPassword, validCompany)
            return Object.keys(loginErrors).length === 0 && Object.keys(registerErrors).length === 0
          }
        ),
        { numRuns: 100 }
      )
    })
  })
})
