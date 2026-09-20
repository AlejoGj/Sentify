import type { FileValidationResult, FormValidationErrors } from '@/types'

export const MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024 // 10,485,760 bytes (10 MB)

/**
 * Decodifica el payload Base64 del JWT sin verificar la firma
 * y compara el campo `exp` con el timestamp actual (Date.now() / 1000).
 * Retorna true si el token está ausente, malformado o expirado.
 */
export function isTokenExpired(token: string): boolean {
  if (!token || typeof token !== 'string') {
    return true
  }

  const parts = token.split('.')
  if (parts.length !== 3) {
    return true
  }

  try {
    const base64Url = parts[1]
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/')
    let padded = base64
    while (padded.length % 4 !== 0) {
      padded += '='
    }

    let decodedJson: string
    if (typeof atob === 'function') {
      decodedJson = atob(padded)
    } else {
      const globalBuf = (
        globalThis as unknown as {
          Buffer?: {
            from: (str: string, enc: string) => { toString: (enc: string) => string }
          }
        }
      ).Buffer
      if (globalBuf) {
        decodedJson = globalBuf.from(padded, 'base64').toString('utf-8')
      } else {
        return true
      }
    }

    const payload = JSON.parse(decodedJson)
    if (!payload || typeof payload.exp !== 'number') {
      return true
    }

    const nowInSeconds = Math.floor(Date.now() / 1000)
    return nowInSeconds >= payload.exp
  } catch {
    return true
  }
}

/**
 * Valida un archivo antes de enviarlo al backend:
 * - Rechaza extensiones distintas a .csv
 * - Rechaza archivos cuyo tamaño exceda 10 MB (10 485 760 bytes)
 * - Rechaza archivos vacíos (0 bytes)
 */
export function validateFileBeforeUpload(file: {
  name: string
  size: number
}): FileValidationResult {
  if (!file || typeof file.name !== 'string' || typeof file.size !== 'number') {
    return { valid: false, error: 'Archivo inválido' }
  }

  const isCsv = file.name.toLowerCase().endsWith('.csv')
  if (!isCsv) {
    return {
      valid: false,
      error: 'Solo se permiten archivos con extensión .csv',
    }
  }

  if (file.size > MAX_FILE_SIZE_BYTES) {
    return {
      valid: false,
      error: 'El archivo supera el tamaño máximo permitido de 10 MB',
    }
  }

  if (file.size <= 0) {
    return {
      valid: false,
      error: 'El archivo está vacío',
    }
  }

  return { valid: true }
}

/**
 * Valida los campos del formulario de inicio de sesión:
 * - Email requerido y con formato que incluya '@'
 * - Contraseña requerida y con al menos 8 caracteres
 */
export function validateLoginForm(
  email: string,
  password: string
): FormValidationErrors {
  const errors: FormValidationErrors = {}

  const trimmedEmail = typeof email === 'string' ? email.trim() : ''
  if (!trimmedEmail) {
    errors.email = 'El correo electrónico es obligatorio'
  } else if (!trimmedEmail.includes('@')) {
    errors.email = 'El formato del correo electrónico debe ser válido y contener un "@"'
  }

  if (!password || password.length < 8) {
    errors.password = 'La contraseña debe tener al menos 8 caracteres'
  }

  return errors
}

/**
 * Valida los campos del formulario de registro:
 * - Mismas validaciones que login (email y contraseña)
 * - Nombre de empresa requerido (no vacío)
 */
export function validateRegisterForm(
  email: string,
  password: string,
  companyName: string
): FormValidationErrors {
  const errors: FormValidationErrors = validateLoginForm(email, password)

  const trimmedCompany =
    typeof companyName === 'string' ? companyName.trim() : ''
  if (!trimmedCompany) {
    errors.companyName = 'El nombre de la empresa es obligatorio'
  }

  return errors
}
