import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'

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

export default api
