import { useContext } from 'react'
import { AuthContext } from '@/context/AuthContext'
import type { AuthContextValue } from '@/types'

/**
 * Hook para consumir el contexto global de autenticación de Sentify.
 * Expone: { token, companyName, expiresAt, login, logout, isAuthenticated }
 *
 * @throws Error si se utiliza fuera del componente AuthProvider
 */
export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth debe ser utilizado dentro de un AuthProvider')
  }
  return context
}

export default useAuth
