# Implementation Plan: Frontend Dashboard (Sentify)

## Overview

Implementación incremental de la SPA React + TypeScript + Vite del Dashboard de Sentify. Las tareas siguen el flujo natural de construcción: primero scaffolding y tipos, luego capa HTTP, autenticación, componentes de UI, hooks, tests unitarios y property-based tests con fast-check, y finalmente tests e2e con Cypress/Playwright. Cada tarea construye sobre la anterior para evitar código huérfano.

## Tasks

- [x] 1. Scaffolding del proyecto y estructura de directorios
  - Inicializar proyecto Vite con template `react-ts` en `frontend/`
  - Instalar dependencias de producción: `react-router-dom`, `axios`, `chart.js`, `react-chartjs-2`, `react-wordcloud`
  - Instalar dependencias de desarrollo: `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, `fast-check`, `vitest`, `@vitejs/plugin-react`, `cypress` o `playwright`
  - Crear la estructura de carpetas: `src/components/Auth/`, `src/components/Dashboard/`, `src/components/Upload/`, `src/components/Charts/`, `src/components/Triage/`, `src/hooks/`, `src/services/`, `src/types/`, `src/context/`, `src/routes/`, `src/utils/`
  - Configurar `vite.config.ts` con alias `@/` apuntando a `src/`
  - Configurar `vitest.config.ts` con `jsdom` como entorno de test y `setupFiles` apuntando a `@testing-library/jest-dom`
  - Crear `.env.example` con `VITE_API_BASE_URL=http://localhost:8000` como valor de ejemplo
  - _Requirements: 14.1, 14.2_

- [ ] 2. Definición de interfaces TypeScript
  - [ ] 2.1 Crear `src/types/index.ts` con todas las interfaces del dominio
    - Exportar: `LoginResponse`, `BatchStatus`, `BatchSummary`, `FeedbackItem`, `KeywordItem`, `PaginatedResponse<T>`, `BatchListItem`, `AuthState`, `AuthContextValue`, `DashboardFilters`
    - Incluir la unión `SentimentType = 'positivo' | 'neutro' | 'negativo'`
    - Incluir las interfaces de props de componentes: `EmptyStateProps`, `BatchRowProps`, `CSVUploaderProps`, `SummaryCardsProps`, `FeedbackListProps`, `TriagePanelProps`, `SentimentChartProps`, `KeywordCloudProps`
    - _Requirements: 14.3_

- [ ] 3. Funciones puras utilitarias y sus property-based tests
  - [ ] 3.1 Crear `src/utils/validators.ts` con las funciones puras
    - Implementar `isTokenExpired(token: string): boolean` — decodifica el payload Base64 del JWT sin verificar firma y compara el campo `exp` con `Date.now() / 1000`
    - Implementar `validateFileBeforeUpload(file: { name: string; size: number }): { valid: boolean; error?: string }` — rechaza extensión no `.csv` o tamaño mayor a 10 485 760 bytes
    - Implementar `validateLoginForm(email: string, password: string): Record<string, string>` — email inválido o password con menos de 8 chars produce errores
    - Implementar `validateRegisterForm(email: string, password: string, companyName: string): Record<string, string>` — igual que login más companyName vacío
    - _Requirements: 1.5, 1.6, 2.5, 4.2, 4.3_

  - [ ]* 3.2 Escribir property test — Property 1: JWT expirado siempre detectado
    - **Property 1: Las rutas protegidas redirigen a /login sin token válido**
    - Generar con `fc.integer({ max: Math.floor(Date.now() / 1000) - 1 })` un timestamp `exp` en el pasado, construir un JWT con ese payload y verificar que `isTokenExpired` retorna `true`
    - Generar con `fc.integer({ min: Math.floor(Date.now() / 1000) + 3600 })` un timestamp en el futuro y verificar que retorna `false`
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 1.5, 1.6, 11.3**

  - [ ]* 3.3 Escribir property test — Property 2: Validación de archivo rechaza entradas inválidas
    - **Property 2: La validación de archivo rechaza cualquier archivo inválido**
    - Generar nombres sin extensión `.csv` con tamaño arbitrario y verificar que `valid === false`
    - Generar nombres `.csv` con `size > 10_485_760` y verificar que `valid === false`
    - Generar nombres `.csv` con `size` entre 1 y 10 485 760 y verificar que `valid === true`
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 4.2, 4.3**

  - [ ]* 3.4 Escribir property test — Property 9: Validación de formulario rechaza entradas inválidas
    - **Property 9: La validación de formulario rechaza cualquier entrada inválida**
    - Generar emails sin `@` o vacíos, passwords con `maxLength: 7` y verificar que `Object.keys(errors).length > 0`
    - Generar `companyName` vacío en `validateRegisterForm` y verificar que produce al menos un error
    - Generar entradas válidas (email con `@`, password de 8+ chars, companyName no vacío) y verificar que el objeto de errores está vacío
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 1, 2.5**

- [ ] 4. Capa de servicios HTTP (`api.ts`)
  - [ ] 4.1 Crear `src/services/api.ts` con la instancia Axios y los interceptores
    - Inicializar instancia con `baseURL: import.meta.env.VITE_API_BASE_URL`
    - Interceptor de request: leer `token` de `localStorage` y adjuntar `Authorization: Bearer {token}` si existe
    - Interceptor de response: manejar 401 (limpiar localStorage y redirigir a `/login`), 500 (toast genérico), error de red sin `response` (toast de conexión)
    - Exportar función `showToast(message: string)` como utilidad ligera de notificaciones
    - _Requirements: 3.1, 3.2, 3.3, 3.6_

  - [ ] 4.2 Agregar funciones tipadas por endpoint en `api.ts`
    - `loginUser(email, password): Promise<LoginResponse>`
    - `registerUser(email, password, companyName): Promise<void>`
    - `uploadCSV(file: File): Promise<{ batch_id: string }>`
    - `getBatchStatus(batchId): Promise<BatchStatus>`
    - `getBatches(page, pageSize): Promise<PaginatedResponse<BatchListItem>>`
    - `getBatchSummary(batchId): Promise<BatchSummary>`
    - `getBatchFeedbacks(batchId, page, pageSize, sentiment?, keyword?): Promise<PaginatedResponse<FeedbackItem>>`
    - `getBatchKeywords(batchId): Promise<KeywordItem[]>`
    - `getBatchTriage(batchId, page, pageSize): Promise<PaginatedResponse<FeedbackItem>>`
    - _Requirements: 3.1, 3.2, 4.4, 5.1, 6.1, 7.1, 8.1, 9.1, 10.2_

- [ ] 5. AuthContext, useAuth y ProtectedRoute
  - [ ] 5.1 Crear `src/context/AuthContext.tsx`
    - Implementar `AuthReducer` con acciones `LOGIN` y `LOGOUT`
    - `login(token, expiresAt, companyName)` escribe en `localStorage` y despacha `LOGIN`
    - `logout()` limpia `localStorage` y despacha `LOGOUT`
    - `isAuthenticated()` verifica que el token no sea null y que no esté expirado
    - Leer estado inicial desde `localStorage` al montar el provider para persistir sesión entre recargas
    - _Requirements: 1.1, 1.2, 1.8, 11.2_

  - [ ] 5.2 Crear `src/hooks/useAuth.ts`
    - Consumir `AuthContext` y exponer `{ token, companyName, expiresAt, login, logout, isAuthenticated }`
    - Lanzar error si se usa fuera del provider
    - _Requirements: 1.2_

  - [ ] 5.3 Crear `src/routes/ProtectedRoute.tsx`
    - Usar `useAuth().isAuthenticated()` para decidir si renderiza `<Outlet />` o redirige a `/login`
    - Si el token existe pero está expirado, llamar a `logout()` antes de redirigir
    - _Requirements: 1.5, 1.6_

  - [ ]* 5.4 Escribir tests unitarios para AuthContext y ProtectedRoute
    - Sin token: `ProtectedRoute` redirige a `/login`
    - Token expirado: `ProtectedRoute` llama a `logout()` y redirige a `/login`
    - Token válido: `ProtectedRoute` renderiza el outlet
    - `login()` persiste en localStorage; `logout()` limpia localStorage
    - _Requirements: 1.5, 1.6_

- [ ] 6. Configuración del router principal (`App.tsx`)
  - Crear `src/App.tsx` con `<BrowserRouter>` y `<AuthProvider>` como wrappers raíz
  - Definir rutas: `/login` para `LoginForm`, `/register` para `RegisterForm`, `/` para redirect condicional, rutas protegidas con `ProtectedRoute` para `/dashboard` y `/upload`, `*` para página 404
  - Crear componente `NotFound.tsx` con mensaje "Página no encontrada" y enlace a `/dashboard`
  - _Requirements: 11.1, 11.3, 11.4_

- [ ] 7. Formularios de autenticación
  - [ ] 7.1 Crear `src/components/Auth/LoginForm.tsx`
    - Campos: `email` (type="email") y `password` (type="password") con etiquetas ARIA
    - Validación cliente con `validateLoginForm` antes de enviar; mostrar errores inline
    - Llamar a `loginUser()` de `api.ts`; en éxito, llamar a `auth.login()` y navegar a `/dashboard`
    - Manejar 401 con mensaje genérico y 423 con mensaje de cuenta bloqueada
    - Mostrar spinner mientras la solicitud está en curso
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 2.5, 13.3_

  - [ ]* 7.2 Escribir tests unitarios para LoginForm
    - Login exitoso: guarda token, redirige a `/dashboard`, muestra `company_name`
    - 401: muestra "Credenciales inválidas. Por favor, inténtalo de nuevo."
    - 423: muestra mensaje de cuenta bloqueada temporalmente
    - Campos vacíos: no envía solicitud HTTP y muestra errores de validación
    - Spinner visible durante la solicitud
    - _Requirements: 1.1, 1.2, 1.3, 1.4_

  - [ ] 7.3 Crear `src/components/Auth/RegisterForm.tsx`
    - Campos: `email`, `password`, `companyName` con etiquetas ARIA
    - Validación cliente con `validateRegisterForm`; mostrar errores inline
    - Llamar a `registerUser()` de `api.ts`; en éxito, navegar a `/login` con mensaje de confirmación
    - Manejar 409 (email ya existe) y 422 (error de validación del backend)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

  - [ ]* 7.4 Escribir tests unitarios para RegisterForm
    - Registro exitoso: redirige a `/login` con mensaje de confirmación
    - 409: muestra error en campo email indicando que el correo ya existe
    - 422: muestra mensaje específico devuelto por el backend
    - Campos vacíos: no envía y muestra errores de validación
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5_

- [ ] 8. Checkpoint — Autenticación y capa HTTP completas
  - Asegurarse de que todos los tests de los pasos 3, 5 y 7 pasan. Consultar al usuario si hay dudas antes de continuar.

- [ ] 9. Hooks de datos
  - [ ] 9.1 Crear `src/hooks/usePolling.ts`
    - Parámetros: `fetchFn: () => Promise<T>`, `intervalMs: number`, `shouldStop: (result: T) => boolean`, `onError?: (err: unknown) => void`
    - Usar `setInterval` internamente; limpiar en el `useEffect` cleanup para evitar fugas de memoria
    - Reintentar hasta 3 veces con back-off exponencial (2 s, 4 s, 8 s) ante errores de red
    - Detener el polling cuando `shouldStop(result) === true`
    - _Requirements: 4.5, 4.7, 4.8_

  - [ ]* 9.2 Escribir property test — Property 3: Polling cesa en estado terminal
    - **Property 3: El polling cesa en cualquier estado terminal del lote**
    - Generar secuencias de estados `('pending' | 'processing' | 'completed' | 'error')[]` con al menos un estado terminal
    - Verificar que `shouldStop` retorna `true` para `'completed'` y `'error'`, y `false` para `'pending'` y `'processing'`
    - Verificar que el contador de llamadas no incrementa después de que `shouldStop` retorna `true`
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 4.7, 4.8**

  - [ ] 9.3 Crear `src/hooks/useBatches.ts`
    - Encapsular `getBatches(page, pageSize)` con estado `{ data, loading, error, page, setPage }`
    - Recargar automáticamente al cambiar `page`
    - _Requirements: 5.1, 5.6_

  - [ ] 9.4 Crear `src/hooks/useDashboard.ts`
    - Parámetro: `batchId: string | null`
    - Llamar en paralelo a `getBatchSummary`, `getBatchKeywords` y `getBatchFeedbacks`
    - Exponer `{ summary, keywords, feedbacks, loading, error, filters, setFilters }`
    - Al cambiar `filters.sentimentFilter` o `filters.keywordFilter`, re-ejecutar el fetch de feedbacks
    - _Requirements: 6.1, 7.1, 8.1, 9.1_

- [ ] 10. Componente EmptyState y tests de propiedad
  - [ ] 10.1 Crear `src/components/Dashboard/EmptyState.tsx`
    - Props: `message: string`, `cta?: React.ReactNode`
    - Renderizar siempre el `message` en un elemento con `role="status"`
    - Renderizar el `cta` únicamente si fue provisto como prop
    - _Requirements: 12.4_

  - [ ]* 10.2 Escribir property test — Property 10: EmptyState renderiza message y CTA
    - **Property 10: EmptyState renderiza siempre el mensaje y el CTA si se proporciona**
    - Generar `fc.string()` arbitrarios como `message` y verificar que el texto aparece en el DOM
    - Proveer un elemento React como `cta` y verificar que aparece en el DOM
    - Omitir `cta` y verificar que no existe elemento CTA en el DOM
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 12.4**

- [ ] 11. CSVUploader con drag & drop y polling
  - [ ] 11.1 Crear `src/components/Upload/CSVUploader.tsx`
    - Área de drag & drop con handlers `onDrop` y `onDragOver`; también `<input type="file" accept=".csv" />`
    - Validar con `validateFileBeforeUpload` antes de enviar; mostrar errores inline
    - Llamar a `uploadCSV(file)`, obtener `batch_id` y arrancar `usePolling`
    - Mientras el estado es `pending` o `processing`, mostrar spinner con texto traducido al español
    - En `completed`: navegar a `/dashboard?batch={batch_id}`
    - En `error`: mostrar mensaje de fallo del procesamiento
    - En error HTTP 422: mostrar mensaje específico devuelto por el backend
    - Todos los elementos interactivos con atributos `aria-label` apropiados
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 4.9, 13.1, 13.3_

  - [ ]* 11.2 Escribir tests unitarios para CSVUploader
    - Archivo no-CSV: muestra error, no llama a `uploadCSV`
    - Archivo mayor a 10 MB: muestra error, no llama a `uploadCSV`
    - Upload exitoso: inicia polling, muestra estado "en progreso"
    - Estado `completed`: navega a `/dashboard`
    - Estado `error`: muestra mensaje de fallo
    - _Requirements: 4.2, 4.3, 4.5, 4.7, 4.8_

- [ ] 12. BatchHistory con paginación y Badge_Urgencia
  - [ ] 12.1 Crear `src/components/Dashboard/BatchHistory.tsx`
    - Usar `useBatches` para obtener la lista paginada
    - Mostrar por fila: nombre de archivo, fecha de carga formateada, estado traducido al español, total/procesadas/error de filas
    - Si `urgent_count > 0`, renderizar Badge_Urgencia (span rojo con `role="status"` y `aria-label`)
    - Click en fila llama a `onSelect(batch.id)`
    - Si la lista está vacía, renderizar `<EmptyState>` con CTA a `/upload`
    - Controles de paginación: botones Anterior y Siguiente con `aria-label`
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 10.5, 13.1_

  - [ ]* 12.2 Escribir property test — Property 8: Badge_Urgencia visible si y solo si urgent_count > 0
    - **Property 8: El Badge_Urgencia es visible si y solo si urgent_count > 0**
    - Generar `BatchListItem` con `fc.nat()` como `urgent_count`
    - Si `urgent_count > 0`: verificar que el badge está presente en el DOM
    - Si `urgent_count === 0`: verificar que el badge no está en el DOM
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 5.3, 10.5**

  - [ ]* 12.3 Escribir tests unitarios para BatchHistory
    - Lista renderiza todos los campos requeridos por cada fila
    - Badge visible con `urgent_count > 0`; badge ausente con `urgent_count === 0`
    - EmptyState visible si la lista está vacía
    - Click en fila dispara `onSelect` con el `id` correcto
    - Paginación: botón Siguiente incrementa página; botón Anterior la decrementa
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

- [ ] 13. SummaryCards
  - [ ] 13.1 Crear `src/components/Dashboard/SummaryCards.tsx`
    - Mostrar: total de feedbacks, porcentaje positivos, porcentaje neutros, porcentaje negativos, cantidad urgentes
    - Si `summary.total_feedbacks === 0`, renderizar `<EmptyState />`
    - Usar semántica correcta con `aria-label` descriptivos en cada tarjeta
    - _Requirements: 6.1, 6.3, 12.2_

  - [ ]* 13.2 Escribir tests unitarios para SummaryCards
    - Todos los campos de `BatchSummary` visibles en el DOM
    - EmptyState renderizado cuando `total_feedbacks === 0`
    - _Requirements: 6.1, 6.3_

- [ ] 14. Gráficos de sentimiento (Chart.js)
  - [ ] 14.1 Crear `src/components/Charts/SentimentBarChart.tsx`
    - Usar `react-chartjs-2` con componente `<Bar>` y distribución absoluta de sentimientos
    - Colores: verde para positivo, amarillo para neutro, rojo para negativo — verificar contraste WCAG AA
    - Handler `onClick` del dataset mapea segmento seleccionado a `onSegmentClick(sentiment)`
    - `aria-label` descriptivo en el elemento `<canvas>`
    - _Requirements: 7.1, 7.4, 13.2_

  - [ ] 14.2 Crear `src/components/Charts/SentimentPieChart.tsx`
    - Usar `react-chartjs-2` con componente `<Pie>` y distribución porcentual
    - Tooltip con conteo exacto y porcentaje configurado vía `plugins.tooltip` de Chart.js
    - Handler `onClick` del segmento llama a `onSegmentClick`
    - _Requirements: 7.2, 7.3, 7.4_

  - [ ]* 14.3 Escribir property test — Property 4: Filtro por sentimiento garantiza consistencia
    - **Property 4: El filtro por sentimiento garantiza consistencia en la lista de feedbacks**
    - Generar arrays de `FeedbackItem[]` con sentimientos aleatorios usando `fc.array` y `fc.record`
    - Para cada `SentimentType` filtrado, verificar que todos los items resultantes tienen `sentiment === filtro`
    - Verificar que ningún item con sentimiento diferente al filtro aparece en la lista filtrada
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 7.4, 9.3**

  - [ ]* 14.4 Escribir property test — Property 5: Toggle de filtro restaura el estado original
    - **Property 5: El toggle de filtro restaura el estado original (round-trip)**
    - Generar un estado inicial con `sentimentFilter` activo y aplicar el mismo filtro; verificar que `sentimentFilter` vuelve a `null`
    - Igual para `keywordFilter`: activar y volver a activar la misma keyword debe limpiar el filtro
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 7.5, 8.4**

- [ ] 15. Nube de palabras clave
  - [ ] 15.1 Crear `src/components/Charts/KeywordCloud.tsx`
    - Usar `react-wordcloud` con las 20 `KeywordItem` más frecuentes pasadas como prop
    - Tamaño de fuente proporcional a `frequency` configurado vía `fontSizes` de react-wordcloud
    - Click en palabra llama a `onWordClick(word)` si no estaba seleccionada, o `onWordClick(null)` si ya lo estaba
    - `aria-label` en el contenedor del componente
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ]* 15.2 Escribir property test — Property 6: Filtro por keyword adjunta parámetro correcto
    - **Property 6: El filtro por keyword adjunta el parámetro correcto al endpoint**
    - Generar `fc.string({ minLength: 1 })` como palabra clave
    - Verificar que la URL construida por `getBatchFeedbacks` con ese keyword incluye exactamente `?keyword={palabra}`
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 8.3, 9.4**

- [ ] 16. FeedbackList con filtros y paginación
  - [ ] 16.1 Crear `src/components/Dashboard/FeedbackList.tsx`
    - Usar `getBatchFeedbacks(batchId, page, pageSize, sentimentFilter, keywordFilter)` de `api.ts`
    - Mostrar por ítem: texto original completo, badge de sentimiento con color diferenciado y contraste WCAG AA, score numérico, keywords asociadas
    - Paginación: mantener los filtros activos al navegar entre páginas
    - Si sin resultados, renderizar `<EmptyState />`
    - Mostrar skeleton de contenido mientras carga (estado `loading`)
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6, 12.2, 13.3_

  - [ ]* 16.2 Escribir property test — Property 7: Renderizado de feedbacks incluye todos los campos
    - **Property 7: El renderizado de feedbacks incluye todos los campos requeridos**
    - Generar `FeedbackItem[]` con valores arbitrarios usando `fc.record`
    - Verificar que para cada item el DOM contiene: texto original, badge de sentimiento, score y keywords
    - Verificar que ningún campo requerido está ausente del DOM
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 9.2, 10.3**

  - [ ]* 16.3 Escribir tests unitarios para FeedbackList
    - Filtro sentimiento: solo feedbacks con ese sentimiento visibles en el DOM
    - Filtro keyword: llama al endpoint con el parámetro correcto
    - Paginación: mantiene el filtro activo al cambiar de página
    - EmptyState visible si no hay resultados
    - Skeleton visible durante el estado de carga
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

- [ ] 17. Panel de Triaje
  - [ ] 17.1 Crear `src/components/Triage/TriagePanel.tsx`
    - Usar `getBatchTriage(batchId, page, 10)` para obtener feedbacks urgentes
    - Mostrar por ítem: texto original completo, score numérico, keywords asociadas
    - Ordenar por score ascendente (el backend ya devuelve el orden correcto)
    - Paginación con máximo 10 feedbacks por página
    - Si sin urgentes, renderizar `<EmptyState message="No se detectaron comentarios urgentes" />`
    - _Requirements: 10.1, 10.2, 10.3, 10.4_

  - [ ]* 17.2 Escribir tests unitarios para TriagePanel
    - Solo feedbacks con score menor a -0.7 visibles
    - EmptyState con mensaje correcto si no hay urgentes
    - Renderiza texto original, score y keywords de cada feedback
    - _Requirements: 10.2, 10.3, 10.4_

- [ ] 18. Checkpoint — Componentes de datos completos
  - Asegurarse de que todos los tests de los pasos 9 al 17 pasan. Consultar al usuario si hay dudas antes de continuar.

- [ ] 19. Barra de navegación e integración del dashboard analítico
  - [ ] 19.1 Crear `src/components/Navbar.tsx`
    - Mostrar `company_name` desde `useAuth()`
    - Links a `/dashboard`, `/upload`, Panel_Triaje con Badge_Urgencia del lote activo
    - Botón "Cerrar sesión" llama a `auth.logout()` y navega a `/login`
    - Navegación por teclado con `tabIndex` correcto en todos los elementos interactivos
    - _Requirements: 1.8, 11.2_

  - [ ] 19.2 Crear `src/pages/DashboardPage.tsx` integrando todos los componentes analíticos
    - Leer `batchId` activo desde query params (`?batch=...`) o desde el último lote del historial
    - Componer: `<BatchHistory>` + `<SummaryCards>` + `<SentimentBarChart>` + `<SentimentPieChart>` + `<KeywordCloud>` + `<FeedbackList>` + `<TriagePanel>`
    - Propagar `filters` desde `useDashboard` hacia gráficos y lista de feedbacks
    - Gestionar `onSegmentClick` y `onWordClick` para actualizar `filters`
    - _Requirements: 5.1, 6.1, 7.1, 8.1, 9.1, 10.1, 11.1_

  - [ ]* 19.3 Escribir property test — Property 11: Indicador de carga durante operaciones asíncronas
    - **Property 11: Las operaciones asíncronas muestran un indicador de carga**
    - Para cada componente que hace fetch, cuando `loading === true` verificar que existe un elemento con `role="status"` o `aria-busy="true"` en el DOM
    - Verificar que el indicador desaparece cuando `loading === false`
    - Usar `fc.assert` con `numRuns: 100`
    - **Validates: Requirements 13.3**

  - [ ]* 19.4 Escribir tests unitarios para DashboardPage y Navbar
    - Navbar muestra `company_name` y Badge_Urgencia correcto
    - Click en "Cerrar sesión": limpia localStorage y redirige a `/login`
    - Click en segmento de gráfico: actualiza `sentimentFilter` en los filtros
    - Segundo click en mismo segmento: quita el filtro
    - Click en keyword: actualiza `keywordFilter`; segundo click quita el filtro
    - _Requirements: 1.8, 7.4, 7.5, 8.3, 8.4_

- [ ] 20. Accesibilidad y responsividad
  - [ ] 20.1 Auditar y completar atributos ARIA en todos los componentes interactivos
    - Verificar `aria-label` en botones sin texto visible, `aria-describedby` en campos con error, `role="alert"` en mensajes de error dinámicos
    - Asegurar que el orden de tabulación es lógico en formularios y controles de paginación
    - _Requirements: 13.1_

  - [ ] 20.2 Verificar y ajustar contraste de color WCAG AA en badges y estados
    - Badge sentimiento positivo (verde sobre blanco): mínimo 4.5:1
    - Badge sentimiento negativo (rojo sobre blanco): mínimo 4.5:1
    - Badge_Urgencia (rojo sobre blanco): mínimo 4.5:1
    - Ajustar los tonos de color si alguno no supera el umbral
    - _Requirements: 13.2_

  - [ ] 20.3 Agregar layout responsivo en los componentes principales
    - Viewport mínimo soportado: 1024 px
    - Grid de SummaryCards colapsa en una sola columna en 1024 px
    - BatchHistory y FeedbackList tienen scroll horizontal en viewports estrechos
    - _Requirements: 13.4_

- [ ] 21. Tests end-to-end (Cypress o Playwright)
  - [ ]* 21.1 Escribir e2e: flujo de autenticación completo
    - Registro → Login → verificar `company_name` en navbar → Logout → verificar redirección a `/login`
    - _Requirements: 1.1, 1.2, 1.8, 2.1, 2.2_

  - [ ]* 21.2 Escribir e2e: upload de CSV y polling
    - Subir CSV válido → ver polling en progreso → estado `completed` → verificar navegación automática a resultados
    - _Requirements: 4.1, 4.4, 4.5, 4.6, 4.7_

  - [ ]* 21.3 Escribir e2e: dashboard analítico completo
    - Seleccionar lote → verificar que tarjetas, gráficos y nube de palabras cargan en menos de 3 segundos
    - _Requirements: 6.1, 6.2, 7.1, 7.2, 8.1_

  - [ ]* 21.4 Escribir e2e: filtros de sentimiento y keyword
    - Click en segmento del gráfico → lista filtrada → segundo click → lista sin filtro
    - Click en keyword → lista filtrada → segundo click → lista sin filtro
    - _Requirements: 7.4, 7.5, 8.3, 8.4_

  - [ ]* 21.5 Escribir e2e: Panel de Triaje
    - Navegar a Panel_Triaje → solo feedbacks con score menor a -0.7 visibles
    - EmptyState visible si no hay feedbacks urgentes
    - _Requirements: 10.2, 10.4_

  - [ ]* 21.6 Escribir e2e: rutas protegidas y 404
    - Acceder a `/dashboard` sin token → redirige a `/login`
    - Token expirado → redirige a `/login`
    - Ruta inexistente → página 404 con enlace de retorno
    - _Requirements: 1.5, 1.6, 11.4_

- [ ] 22. Checkpoint final — Todos los tests pasan
  - Ejecutar `npm run test` (Vitest + React Testing Library + fast-check) y verificar que todos los tests unitarios y de propiedades pasan
  - Ejecutar `npm run e2e` y verificar que todos los tests end-to-end pasan
  - Ejecutar `npm run build` y verificar que no hay errores de compilación TypeScript
  - Consultar al usuario si queda algún ajuste pendiente antes de cerrar

## Notes

- Las tareas marcadas con `*` son opcionales y pueden omitirse para un MVP más rápido
- Cada tarea referencia requisitos específicos para trazabilidad completa
- Los checkpoints en los pasos 8, 18 y 22 garantizan validación incremental del trabajo
- Las property tests con fast-check usan `numRuns: 100` como mínimo, alineado con la convención del proyecto (Hypothesis también usa 100 ejemplos en el backend)
- Las funciones puras en `src/utils/validators.ts` son las candidatas principales a PBT; los componentes React con propiedades universales (Properties 4, 5, 6, 7, 8, 10, 11) se testean con fast-check generando props aleatorias y verificando el DOM con React Testing Library
- El proyecto frontend vive en `frontend/` siguiendo la estructura definida en el steering de arquitectura

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["2.1"] },
    { "id": 1, "tasks": ["3.1"] },
    { "id": 2, "tasks": ["3.2", "3.3", "3.4", "4.1"] },
    { "id": 3, "tasks": ["4.2", "5.1"] },
    { "id": 4, "tasks": ["5.2", "5.3"] },
    { "id": 5, "tasks": ["5.4", "9.1", "10.1"] },
    { "id": 6, "tasks": ["9.2", "9.3", "9.4", "10.2", "11.1"] },
    { "id": 7, "tasks": ["11.2", "12.1", "13.1"] },
    { "id": 8, "tasks": ["12.2", "12.3", "13.2", "14.1", "14.2"] },
    { "id": 9, "tasks": ["14.3", "14.4", "15.1"] },
    { "id": 10, "tasks": ["15.2", "16.1"] },
    { "id": 11, "tasks": ["16.2", "16.3", "17.1"] },
    { "id": 12, "tasks": ["17.2", "19.1", "19.2"] },
    { "id": 13, "tasks": ["19.3", "19.4", "20.1", "20.2", "20.3"] },
    { "id": 14, "tasks": ["21.1", "21.2", "21.3", "21.4", "21.5", "21.6"] }
  ]
}
```
