import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  api,
  showToast,
  API_BASE_URL,
  loginUser,
  registerUser,
  uploadCSV,
  getBatchStatus,
  getBatches,
  getBatchSummary,
  getBatchFeedbacks,
  getBatchKeywords,
  getBatchTriage,
} from './api'
import type { AxiosResponse, InternalAxiosRequestConfig } from 'axios'
import type {
  LoginResponse,
  BatchStatus,
  BatchSummary,
  FeedbackItem,
  KeywordItem,
  PaginatedResponse,
  BatchListItem,
} from '@/types'

describe('api.ts — Axios Client, Interceptors & Endpoint Functions', () => {
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

      const interceptor = (api.interceptors.request as unknown as { handlers: Array<{ fulfilled: (c: InternalAxiosRequestConfig) => Promise<InternalAxiosRequestConfig> }> }).handlers[0]

      const setMock = vi.fn()
      const config = {
        headers: {
          set: setMock,
        },
      } as unknown as InternalAxiosRequestConfig

      const modifiedConfig = await interceptor.fulfilled(config)
      expect(setMock).toHaveBeenCalledWith(
        'Authorization',
        'Bearer fake-jwt-token-123'
      )
      expect(modifiedConfig).toBe(config)
    })

    it('no debe adjuntar Authorization si no existe token en localStorage', async () => {
      const interceptor = (api.interceptors.request as unknown as { handlers: Array<{ fulfilled: (c: InternalAxiosRequestConfig) => Promise<InternalAxiosRequestConfig> }> }).handlers[0]

      const setMock = vi.fn()
      const config = {
        headers: { set: setMock },
      } as unknown as InternalAxiosRequestConfig

      await interceptor.fulfilled(config)
      expect(setMock).not.toHaveBeenCalled()
    })
  })

  describe('Response Interceptor', () => {
    it('debe retornar la respuesta intacta si no hay error', async () => {
      const interceptor = (api.interceptors.response as unknown as { handlers: Array<{ fulfilled: (r: AxiosResponse) => Promise<AxiosResponse> }> }).handlers[0]
      const fakeResponse = { status: 200, data: { success: true } } as AxiosResponse

      const res = await interceptor.fulfilled(fakeResponse)
      expect(res).toBe(fakeResponse)
    })

    it('debe manejar error 401 limpiando localStorage y redirigiendo a /login', async () => {
      localStorage.setItem('token', 'token-to-remove')
      localStorage.setItem('expires_at', '2026-01-01')
      localStorage.setItem('company_name', 'Test Corp')

      const locationMock = { href: '' }
      Object.defineProperty(window, 'location', {
        writable: true,
        value: locationMock,
      })

      const interceptor = (api.interceptors.response as unknown as { handlers: Array<{ rejected: (err: unknown) => Promise<never> }> }).handlers[0]
      const error401 = {
        response: { status: 401, data: { detail: 'Unauthorized' } },
      }

      await expect(interceptor.rejected(error401)).rejects.toEqual(error401)
      expect(localStorage.getItem('token')).toBeNull()
      expect(localStorage.getItem('expires_at')).toBeNull()
      expect(localStorage.getItem('company_name')).toBeNull()
      expect(window.location.href).toBe('/login')
    })

    it('debe mostrar toast en caso de error 500', async () => {
      const interceptor = (api.interceptors.response as unknown as { handlers: Array<{ rejected: (err: unknown) => Promise<never> }> }).handlers[0]
      const error500 = {
        response: { status: 500, data: { detail: 'Internal Server Error' } },
      }

      await expect(interceptor.rejected(error500)).rejects.toEqual(error500)
      const toast = document.querySelector('.sentify-toast')
      expect(toast).not.toBeNull()
      expect(toast?.textContent).toContain('Ocurrió un error inesperado')
    })

    it('debe mostrar toast de conexión en caso de error de red sin response', async () => {
      const interceptor = (api.interceptors.response as unknown as { handlers: Array<{ rejected: (err: unknown) => Promise<never> }> }).handlers[0]
      const networkError = {
        message: 'Network Error',
      }

      await expect(interceptor.rejected(networkError)).rejects.toEqual(networkError)
      const toast = document.querySelector('.sentify-toast')
      expect(toast).not.toBeNull()
      expect(toast?.textContent).toContain('No se pudo conectar con el servidor')
    })

    it('no debe limpiar localStorage en errores 422 o 409', async () => {
      localStorage.setItem('token', 'persist-token')

      const interceptor = (api.interceptors.response as unknown as { handlers: Array<{ rejected: (err: unknown) => Promise<never> }> }).handlers[0]
      const error422 = {
        response: { status: 422, data: { detail: 'Validation Error' } },
      }

      await expect(interceptor.rejected(error422)).rejects.toEqual(error422)
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

  describe('Endpoint Functions', () => {
    it('loginUser: envía credenciales y retorna LoginResponse', async () => {
      const mockResponse: LoginResponse = {
        token: 'token-abc',
        expires_at: '2026-10-01T00:00:00Z',
        company_name: 'Acme Corp',
      }
      const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ data: mockResponse })

      const result = await loginUser('test@acme.com', 'password123')
      expect(postSpy).toHaveBeenCalledWith('/api/v1/auth/login', {
        email: 'test@acme.com',
        password: 'password123',
      })
      expect(result).toEqual(mockResponse)
    })

    it('registerUser: envía datos de registro con company_name', async () => {
      const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ data: {} })

      await registerUser('admin@empresa.com', 'pass12345', 'Empresa S.A.')
      expect(postSpy).toHaveBeenCalledWith('/api/v1/auth/register', {
        email: 'admin@empresa.com',
        password: 'pass12345',
        company_name: 'Empresa S.A.',
      })
    })

    it('uploadCSV: envía FormData con header multipart/form-data', async () => {
      const mockResult = { batch_id: 'batch-999' }
      const postSpy = vi.spyOn(api, 'post').mockResolvedValueOnce({ data: mockResult })

      const fakeFile = new File(['text,sentiment\nbueno,positivo'], 'reviews.csv', {
        type: 'text/csv',
      })

      const result = await uploadCSV(fakeFile)
      expect(postSpy).toHaveBeenCalledWith(
        '/api/v1/batches/upload',
        expect.any(FormData),
        expect.objectContaining({
          headers: { 'Content-Type': 'multipart/form-data' },
        })
      )
      expect(result).toEqual(mockResult)
    })

    it('getBatchStatus: consulta estado de lote por ID', async () => {
      const mockStatus: BatchStatus = {
        batch_id: 'batch-1',
        status: 'processing',
        total_rows: 100,
        processed_rows: 50,
        error_rows: 0,
        uploaded_at: '2026-09-28T00:00:00Z',
        completed_at: null,
      }
      const getSpy = vi.spyOn(api, 'get').mockResolvedValueOnce({ data: mockStatus })

      const result = await getBatchStatus('batch-1')
      expect(getSpy).toHaveBeenCalledWith('/api/v1/batches/batch-1/status')
      expect(result).toEqual(mockStatus)
    })

    it('getBatches: consulta lotes paginados con parámetros por defecto', async () => {
      const mockBatches: PaginatedResponse<BatchListItem> = {
        items: [],
        total: 0,
        page: 1,
        page_size: 10,
        total_pages: 0,
      }
      const getSpy = vi.spyOn(api, 'get').mockResolvedValueOnce({ data: mockBatches })

      const result = await getBatches(2, 5)
      expect(getSpy).toHaveBeenCalledWith('/api/v1/batches', {
        params: { page: 2, page_size: 5 },
      })
      expect(result).toEqual(mockBatches)
    })

    it('getBatchSummary: consulta resumen de sentimiento de lote', async () => {
      const mockSummary: BatchSummary = {
        batch_id: 'batch-1',
        total_feedbacks: 50,
        sentiment_distribution: { positivo: 30, neutro: 15, negativo: 5 },
        sentiment_percentages: { positivo: 60, neutro: 30, negativo: 10 },
        urgent_count: 2,
      }
      const getSpy = vi.spyOn(api, 'get').mockResolvedValueOnce({ data: mockSummary })

      const result = await getBatchSummary('batch-1')
      expect(getSpy).toHaveBeenCalledWith('/api/v1/batches/batch-1/summary')
      expect(result).toEqual(mockSummary)
    })

    it('getBatchKeywords: consulta lista de palabras clave', async () => {
      const mockKeywords: KeywordItem[] = [
        { word: 'servicio', frequency: 12 },
        { word: 'atención', frequency: 8 },
      ]
      const getSpy = vi.spyOn(api, 'get').mockResolvedValueOnce({ data: mockKeywords })

      const result = await getBatchKeywords('batch-1')
      expect(getSpy).toHaveBeenCalledWith('/api/v1/batches/batch-1/keywords')
      expect(result).toEqual(mockKeywords)
    })

    it('getBatchFeedbacks: consulta comentarios con filtros de sentimiento y keyword', async () => {
      const mockFeedbacks: PaginatedResponse<FeedbackItem> = {
        items: [
          {
            id: 'fb-1',
            original_text: 'Excelente servicio',
            sentiment: 'positivo',
            score: 0.85,
            keywords: ['servicio'],
            analyzed_at: '2026-09-28T00:00:00Z',
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
        total_pages: 1,
      }
      const getSpy = vi.spyOn(api, 'get').mockResolvedValueOnce({ data: mockFeedbacks })

      const result = await getBatchFeedbacks('batch-1', 1, 20, 'positivo', 'servicio')
      expect(getSpy).toHaveBeenCalledWith('/api/v1/batches/batch-1/feedbacks', {
        params: {
          page: 1,
          page_size: 20,
          sentiment: 'positivo',
          keyword: 'servicio',
        },
      })
      expect(result).toEqual(mockFeedbacks)
    })

    it('getBatchTriage: consulta comentarios urgentes paginados', async () => {
      const mockTriage: PaginatedResponse<FeedbackItem> = {
        items: [
          {
            id: 'fb-2',
            original_text: 'Pésimo servicio y trato grosero',
            sentiment: 'negativo',
            score: -0.92,
            keywords: ['servicio', 'grosero'],
            analyzed_at: '2026-09-28T00:00:00Z',
          },
        ],
        total: 1,
        page: 1,
        page_size: 10,
        total_pages: 1,
      }
      const getSpy = vi.spyOn(api, 'get').mockResolvedValueOnce({ data: mockTriage })

      const result = await getBatchTriage('batch-1', 1, 10)
      expect(getSpy).toHaveBeenCalledWith('/api/v1/batches/batch-1/triage', {
        params: { page: 1, page_size: 10 },
      })
      expect(result).toEqual(mockTriage)
    })
  })
})
