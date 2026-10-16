import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { useAuth } from './useAuth'
import { AuthContext } from '@/context/AuthContext'
import type { AuthContextValue } from '@/types'

describe('useAuth Hook', () => {
  let container: HTMLDivElement | null = null
  let root: Root | null = null

  beforeEach(() => {
    container = document.createElement('div')
    document.body.appendChild(container)
    root = createRoot(container)
  })

  afterEach(() => {
    if (root) {
      act(() => {
        root?.unmount()
      })
    }
    if (container && container.parentNode) {
      container.parentNode.removeChild(container)
    }
    container = null
    root = null
  })

  it('lanza un error descriptivo si se utiliza fuera del AuthProvider', () => {
    let capturedError: Error | undefined

    function ConsumerOutsideProvider() {
      try {
        useAuth()
      } catch (err) {
        capturedError = err as Error
      }
      return null
    }

    act(() => {
      root?.render(<ConsumerOutsideProvider />)
    })

    expect(capturedError).toBeDefined()
    expect(capturedError!.message).toBe(
      'useAuth debe ser utilizado dentro de un AuthProvider'
    )
  })

  it('expone el contexto correctamente cuando está dentro del proveedor', () => {
    let capturedValue: AuthContextValue | undefined

    const mockAuthValue: AuthContextValue = {
      token: 'jwt-token-777',
      companyName: 'Empresa Test',
      expiresAt: new Date('2026-12-31T00:00:00Z'),
      login: () => {},
      logout: () => {},
      isAuthenticated: () => true,
    }

    function ConsumerInsideProvider() {
      capturedValue = useAuth()
      return <div>Authenticated</div>
    }

    act(() => {
      root?.render(
        <AuthContext.Provider value={mockAuthValue}>
          <ConsumerInsideProvider />
        </AuthContext.Provider>
      )
    })

    expect(capturedValue).toBeDefined()
    expect(capturedValue!.token).toBe('jwt-token-777')
    expect(capturedValue!.companyName).toBe('Empresa Test')
    expect(capturedValue!.expiresAt?.toISOString()).toBe('2026-12-31T00:00:00.000Z')
    expect(capturedValue!.isAuthenticated()).toBe(true)
  })
})
