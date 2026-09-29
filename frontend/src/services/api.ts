import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'
import type {
  LoginResponse,
  BatchStatus,
  BatchSummary,
  FeedbackItem,
  KeywordItem,
  PaginatedResponse,
  BatchListItem,
  SentimentType,
} from '@/types'

export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string) || 'http://localhost:8000'

/**
 * Utilidad ligera para mostrar notificaciones toast en pantalla sin dependencias externas.
 * Inserta un elemento flotante en el DOM con atributo role="alert".
 */
export function showToast(message: string): void {
  if (typeof document === 'undefined') {
    return
  }

  let container = document.getElementById('sentify-toast-container')
  if (!container) {
    container = document.createElement('div')
    container.id = 'sentify-toast-container'
    container.style.position = 'fixed'
    container.style.bottom = '24px'
    container.style.right = '24px'
    container.style.zIndex = '9999'
    container.style.display = 'flex'
    container.style.flexDirection = 'column'
    container.style.gap = '10px'
    container.style.pointerEvents = 'none'
    container.setAttribute('aria-live', 'polite')
    document.body.appendChild(container)
  }

  const toast = document.createElement('div')
  toast.className = 'sentify-toast'
  toast.setAttribute('role', 'alert')
  toast.textContent = message
  toast.style.backgroundColor = '#1e293b'
  toast.style.color = '#f8fafc'
  toast.style.padding = '12px 18px'
  toast.style.borderRadius = '8px'
  toast.style.border = '1px solid #334155'
  toast.style.boxShadow =
    '0 10px 15px -3px rgba(0, 0, 0, 0.3), 0 4px 6px -4px rgba(0, 0, 0, 0.2)'
  toast.style.fontSize = '14px'
  toast.style.fontWeight = '500'
  toast.style.maxWidth = '380px'
  toast.style.pointerEvents = 'auto'
  toast.style.transition = 'opacity 0.25s ease-out, transform 0.25s ease-out'
  toast.style.opacity = '0'
  toast.style.transform = 'translateY(10px)'

  container.appendChild(toast)

  // Animación de entrada
  requestAnimationFrame(() => {
    toast.style.opacity = '1'
    toast.style.transform = 'translateY(0)'
  })

  // Desvanecimiento y remoción
  setTimeout(() => {
    toast.style.opacity = '0'
    toast.style.transform = 'translateY(10px)'
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast)
      }
    }, 250)
  }, 4000)
}

/**
 * Instancia central de Axios para toda la aplicación Sentify.
 */
export const api: AxiosInstance = axios.create({
  baseURL: API_BASE_URL,
})

/**
 * Interceptor de Request:
 * Lee el JWT desde localStorage y lo adjunta en Authorization: Bearer {token}
 */
api.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => {
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('token') : null
    if (token) {
      if (config.headers && typeof config.headers.set === 'function') {
        config.headers.set('Authorization', `Bearer ${token}`)
      } else if (config.headers) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }
    return config
  },
  (error: unknown) => {
    return Promise.reject(error)
  }
)

/**
 * Interceptor de Response:
 * - 401: Limpia sesión en localStorage y redirige a /login
 * - 500: Muestra toast genérico de error interno
 * - Error de red sin response: Muestra toast de error de conexión
 * - Los demás códigos (409, 422, 423) se propagan al componente invocador
 */
api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem('token')
        localStorage.removeItem('expires_at')
        localStorage.removeItem('company_name')
      }
      if (typeof window !== 'undefined' && window.location) {
        window.location.href = '/login'
      }
    } else if (error.response?.status === 500) {
      showToast('Ocurrió un error inesperado. Por favor, inténtalo de nuevo.')
    } else if (!error.response) {
      showToast('No se pudo conectar con el servidor. Verifica tu conexión.')
    }

    return Promise.reject(error)
  }
)

// ─── Funciones Tipadas por Endpoint ──────────────────────────────────────────

/**
 * Inicia sesión con correo y contraseña.
 * POST /api/v1/auth/login
 */
export async function loginUser(
  email: string,
  password: string
): Promise<LoginResponse> {
  const response = await api.post<LoginResponse>('/api/v1/auth/login', {
    email,
    password,
  })
  return response.data
}

/**
 * Registra una nueva cuenta de empresa.
 * POST /api/v1/auth/register
 */
export async function registerUser(
  email: string,
  password: string,
  companyName: string
): Promise<void> {
  await api.post('/api/v1/auth/register', {
    email,
    password,
    company_name: companyName,
  })
}

/**
 * Sube un archivo CSV mediante multipart/form-data.
 * POST /api/v1/batches/upload
 */
export async function uploadCSV(file: File): Promise<{ batch_id: string }> {
  const formData = new FormData()
  formData.append('file', file)

  const response = await api.post<{ batch_id: string }>(
    '/api/v1/batches/upload',
    formData,
    {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    }
  )
  return response.data
}

/**
 * Obtiene el estado de procesamiento de un lote específico.
 * GET /api/v1/batches/{batch_id}/status
 */
export async function getBatchStatus(batchId: string): Promise<BatchStatus> {
  const response = await api.get<BatchStatus>(`/api/v1/batches/${batchId}/status`)
  return response.data
}

/**
 * Obtiene el historial paginado de lotes del usuario autenticado.
 * GET /api/v1/batches
 */
export async function getBatches(
  page: number = 1,
  pageSize: number = 10
): Promise<PaginatedResponse<BatchListItem>> {
  const response = await api.get<PaginatedResponse<BatchListItem>>(
    '/api/v1/batches',
    {
      params: { page, page_size: pageSize },
    }
  )
  return response.data
}

/**
 * Obtiene el resumen de distribución de sentimiento de un lote.
 * GET /api/v1/batches/{batch_id}/summary
 */
export async function getBatchSummary(batchId: string): Promise<BatchSummary> {
  const response = await api.get<BatchSummary>(
    `/api/v1/batches/${batchId}/summary`
  )
  return response.data
}

/**
 * Obtiene la lista paginada de comentarios analizados con filtros opcionales.
 * GET /api/v1/batches/{batch_id}/feedbacks
 */
export async function getBatchFeedbacks(
  batchId: string,
  page: number = 1,
  pageSize: number = 20,
  sentiment?: SentimentType | null,
  keyword?: string | null
): Promise<PaginatedResponse<FeedbackItem>> {
  const params: Record<string, string | number> = {
    page,
    page_size: pageSize,
  }
  if (sentiment) {
    params.sentiment = sentiment
  }
  if (keyword && keyword.trim().length > 0) {
    params.keyword = keyword.trim()
  }

  const response = await api.get<PaginatedResponse<FeedbackItem>>(
    `/api/v1/batches/${batchId}/feedbacks`,
    { params }
  )
  return response.data
}

/**
 * Obtiene las 20 palabras clave más frecuentes de un lote.
 * GET /api/v1/batches/{batch_id}/keywords
 */
export async function getBatchKeywords(
  batchId: string
): Promise<KeywordItem[]> {
  const response = await api.get<KeywordItem[]>(
    `/api/v1/batches/${batchId}/keywords`
  )
  return response.data
}

/**
 * Obtiene los comentarios urgentes (score < -0.7) ordenados de más a menos negativo.
 * GET /api/v1/batches/{batch_id}/triage
 */
export async function getBatchTriage(
  batchId: string,
  page: number = 1,
  pageSize: number = 10
): Promise<PaginatedResponse<FeedbackItem>> {
  const response = await api.get<PaginatedResponse<FeedbackItem>>(
    `/api/v1/batches/${batchId}/triage`,
    {
      params: { page, page_size: pageSize },
    }
  )
  return response.data
}

export default api
