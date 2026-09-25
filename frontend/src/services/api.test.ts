import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api, showToast, API_BASE_URL } from './api'
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios'

describe('api.ts — Axios Client & Interceptors', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    document.body.innerHTML = ''
  })

  it('debe inicializarse con la URL base esperada', () => {
    expect(API_BASE_URL).toBeDefined()
    expect(api.defaults.baseURL).toBe(API_BASE_URL)
  })

  describe('Request Interceptor', () => {
    it('debe adjuntar Authorization: Bearer {token} si existe en localStorage', async () => {
      localStorage.setItem('token', 'fake-jwt-token-123')

      // Obtenemos los interceptores registrados
      /* ts-expect-error accessing internal axios handlers for testing*/
      const requestHandler = api.interceptors.request.handlers[0]

      const setMock = vi.fn()
      const config = {
        headers: {
          set: setMock,
        },
      } as unknown as InternalAxiosRequestConfig

      const modifiedConfig = await requestHandler.fulfilled(config)
      expect(setMock).toHaveBeenCalledWith(
        'Authorization',
        'Bearer fake-jwt-token-123'
      )
      expect(modifiedConfig).toBe(config)
    })

    it('no debe adjuntar Authorization si no existe token en localStorage', async () => {
      // ts-expect-error accessing internal axios handlers
      const requestHandler = api.interceptors.request.handlers[0]

      const setMock = vi.fn()
      const config = {
        headers: { set: setMock },
      } as unknown as InternalAxiosRequestConfig

      await requestHandler.fulfilled(config)
      expect(setMock).not.toHaveBeenCalled()
    })
  })

  describe('Response Interceptor', () => {
    it('debe retornar la respuesta intacta si no hay error', async () => {
      // ts-expect-error accessing internal axios handlers
      const responseHandler = api.interceptors.response.handlers[0]
      const fakeResponse = { status: 200, data: { success: true } } as AxiosResponse

      const res = await responseHandler.fulfilled(fakeResponse)
      expect(res).toBe(fakeResponse)
    })

    it('debe manejar error 401 limpiando localStorage y redirigiendo a /login', async () => {
      localStorage.setItem('token', 'token-to-remove')
      localStorage.setItem('expires_at', '2026-01-01')
      localStorage.setItem('company_name', 'Test Corp')

      // ts-expect-error mock window.location
      delete window.location
      // @ts-expect-error assign window.location mock
      window.location = { href: '' }

      // ts-expect-error accessing internal axios handlers
      const responseHandler = api.interceptors.response.handlers[0]
      const error401 = {
        response: { status: 401, data: { detail: 'Unauthorized' } },
      }

      await expect(responseHandler.rejected!(error401)).rejects.toEqual(error401)
      expect(localStorage.getItem('token')).toBeNull()
      expect(localStorage.getItem('expires_at')).toBeNull()
      expect(localStorage.getItem('company_name')).toBeNull()
      expect(window.location.href).toBe('/login')
    })

    it('debe mostrar toast en caso de error 500', async () => {
      // ts-expect-error accessing internal axios handlers
      const responseHandler = api.interceptors.response.handlers[0]
      const error500 = {
        response: { status: 500, data: { detail: 'Internal Server Error' } },
      }

      await expect(responseHandler.rejected!(error500)).rejects.toEqual(error500)
      const toast = document.querySelector('.sentify-toast')
      expect(toast).not.toBeNull()
      expect(toast?.textContent).toContain('Ocurrió un error inesperado')
    })

    it('debe mostrar toast de conexión en caso de error de red sin response', async () => {
      // ts-expect-error accessing internal axios handlers
      const responseHandler = api.interceptors.response.handlers[0]
      const networkError = {
        message: 'Network Error',
      }

      await expect(responseHandler.rejected!(networkError)).rejects.toEqual(networkError)
      const toast = document.querySelector('.sentify-toast')
      expect(toast).not.toBeNull()
      expect(toast?.textContent).toContain('No se pudo conectar con el servidor')
    })

    it('no debe limpiar localStorage en errores 422 o 409', async () => {
      localStorage.setItem('token', 'persist-token')

      // ts-expect-error accessing internal axios handlers
      const responseHandler = api.interceptors.response.handlers[0]
      const error422 = {
        response: { status: 422, data: { detail: 'Validation Error' } },
      }

      await expect(responseHandler.rejected!(error422)).rejects.toEqual(error422)
      expect(localStorage.getItem('token')).toBe('persist-token')
    })
  })

  describe('showToast', () => {
    it('debe insertar un elemento con role="alert" en el DOM', () => {
      showToast('Mensaje de prueba')
      const container = document.getElementById('sentify-toast-container')
      expect(container).not.toBeNull()

      const toast = container?.querySelector('[role="alert"]')
      expect(toast).not.toBeNull()
      expect(toast?.textContent).toBe('Mensaje de prueba')
    })
  })
})
