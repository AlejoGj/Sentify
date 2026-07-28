# Requirements Document

## Introduction

Este documento especifica los requisitos del frontend web de Sentify: una Single Page Application (SPA) en React + TypeScript que permite a usuarios corporativos autenticarse, cargar archivos CSV de reseñas, y visualizar los resultados del análisis de sentimiento a través de gráficos interactivos, una nube de palabras clave y un panel de triaje de urgencia.

El frontend se comunica exclusivamente con el backend AWS desplegado (API Gateway + Lambda), autenticándose mediante tokens JWT emitidos por AWS Cognito. No existe lógica de negocio en el frontend: toda la clasificación de sentimiento, extracción de palabras clave y persistencia ocurre en el backend.

## Glossary

- **Dashboard**: La interfaz web React SPA que el Usuario_Corporativo utiliza para interactuar con la plataforma
- **Usuario_Corporativo**: Persona de la empresa que utiliza el Dashboard para analizar feedback de clientes
- **Token_JWT**: Token de acceso RS256 emitido por AWS Cognito, almacenado en `localStorage` y adjunto en la cabecera `Authorization: Bearer {token}` en todas las solicitudes protegidas
- **Instancia_Axios**: Cliente HTTP configurado con la URL base del backend y el interceptor de JWT; lee la URL base de la variable de entorno `VITE_API_BASE_URL`
- **Lote_Analisis**: Agrupación de un archivo CSV cargado con sus feedbacks analizados, identificada por un `batch_id` único
- **Feedback**: Comentario individual de un cliente procesado por el backend, con sentimiento, score y palabras clave
- **Score**: Valor numérico de polaridad en el rango -1.0 a 1.0 asignado a cada Feedback
- **Sentimiento**: Clasificación del tono emocional de un Feedback: `positivo`, `neutro` o `negativo`
- **Palabra_Clave**: Término relevante extraído automáticamente de un Feedback por el backend
- **Panel_Triaje**: Sección del Dashboard que muestra los Feedbacks con Score < -0.7, ordenados del más negativo al menos negativo
- **Estado_Vacio**: Componente reutilizable que muestra un mensaje informativo y un CTA cuando no hay datos disponibles
- **Polling**: Mecanismo de consulta periódica al backend cada 2 segundos para conocer el estado de procesamiento de un Lote_Analisis
- **Badge_Urgencia**: Indicador visual de color rojo que muestra el recuento de Feedbacks urgentes (Score < -0.7) de un Lote_Analisis

---

## Requirements

### Requisito 1: Autenticación — Inicio de Sesión

**User Story:** Como Usuario_Corporativo, quiero iniciar sesión con mi correo electrónico y contraseña, para que solo yo pueda acceder a los datos de análisis de mi empresa.

#### Criterios de Aceptación

1. WHEN el Usuario_Corporativo envía un formulario de login con un correo electrónico con formato válido y una contraseña de entre 8 y 128 caracteres, THE Dashboard SHALL enviar una solicitud `POST /api/v1/auth/login` y, al recibir una respuesta exitosa, almacenar el Token_JWT en `localStorage` y redirigir al Usuario_Corporativo a la ruta `/dashboard`
2. WHEN el login es exitoso, THE Dashboard SHALL extraer el campo `company_name` de la respuesta del backend y mostrarlo en la barra de navegación durante toda la sesión
3. IF el backend devuelve un código HTTP 401 (credenciales inválidas), THEN THE Dashboard SHALL mostrar un mensaje de error genérico que no indique qué campo es incorrecto (ej. "Credenciales inválidas. Por favor, inténtalo de nuevo.")
4. IF el backend devuelve un código HTTP 423 (cuenta bloqueada), THEN THE Dashboard SHALL mostrar un mensaje que informe al usuario que la cuenta ha sido bloqueada temporalmente
5. WHILE el Usuario_Corporativo no dispone de un Token_JWT válido en `localStorage`, THE Dashboard SHALL redirigir automáticamente cualquier intento de acceso a rutas protegidas hacia la ruta `/login`
6. IF el Token_JWT presente en `localStorage` ha superado su tiempo de expiración (campo `exp` del payload JWT), THEN THE Dashboard SHALL redirigir al Usuario_Corporativo a `/login` y eliminar el token expirado de `localStorage`
7. THE Dashboard SHALL intentar refrescar el Token_JWT llamando al endpoint de refresco antes de que expire; IF el refresco falla, THEN THE Dashboard SHALL redirigir al Usuario_Corporativo a `/login`
8. WHEN el Usuario_Corporativo hace clic en "Cerrar sesión", THE Dashboard SHALL eliminar el Token_JWT de `localStorage` y redirigir a `/login`

---

### Requisito 2: Autenticación — Registro de Cuenta

**User Story:** Como nuevo Usuario_Corporativo, quiero registrar una cuenta con mi correo electrónico, contraseña y nombre de empresa, para poder acceder a la plataforma.

#### Criterios de Aceptación

1. WHEN el Usuario_Corporativo envía el formulario de registro con un correo electrónico válido, contraseña de entre 8 y 128 caracteres, y un nombre de empresa no vacío, THE Dashboard SHALL enviar una solicitud `POST /api/v1/auth/register` al backend
2. WHEN el registro es exitoso, THE Dashboard SHALL redirigir al Usuario_Corporativo a la ruta `/login` con un mensaje de confirmación indicando que la cuenta fue creada correctamente
3. IF el backend devuelve un error indicando que el correo electrónico ya está registrado, THEN THE Dashboard SHALL mostrar un mensaje de error en el formulario indicando que el correo ya existe
4. IF el backend devuelve un error de validación HTTP 422, THEN THE Dashboard SHALL mostrar el mensaje de error específico retornado por el backend junto al campo correspondiente
5. THE Dashboard SHALL validar en el cliente que los campos del formulario no estén vacíos antes de enviar la solicitud; IF algún campo requerido está vacío, THEN THE Dashboard SHALL mostrar un mensaje de validación junto al campo afectado y no enviar la solicitud

---

### Requisito 3: Configuración del Cliente HTTP

**User Story:** Como equipo de desarrollo, queremos una Instancia_Axios centralizada con interceptores de JWT y manejo de errores HTTP, para que todas las solicitudes al backend estén correctamente autenticadas y los errores se gestionen de forma uniforme.

#### Criterios de Aceptación

1. THE Dashboard SHALL inicializar la Instancia_Axios con la URL base leída de la variable de entorno `VITE_API_BASE_URL`
2. WHEN la Instancia_Axios realiza cualquier solicitud a una ruta protegida, THE Dashboard SHALL adjuntar automáticamente la cabecera `Authorization: Bearer {token}` usando el Token_JWT almacenado en `localStorage`
3. IF la Instancia_Axios recibe una respuesta HTTP 401 (token ausente, inválido o expirado), THEN THE Dashboard SHALL redirigir automáticamente al Usuario_Corporativo a `/login` y eliminar el Token_JWT de `localStorage`
4. IF la Instancia_Axios recibe una respuesta HTTP 423 (cuenta bloqueada), THEN THE Dashboard SHALL mostrar un mensaje de error indicando que la cuenta está bloqueada y redirigir a `/login`
5. IF la Instancia_Axios recibe una respuesta HTTP 422 (errores de validación del backend), THEN THE Dashboard SHALL exponer los mensajes de error detallados devueltos por el backend al componente que realizó la solicitud
6. IF la Instancia_Axios recibe una respuesta HTTP 500 (error interno del servidor), THEN THE Dashboard SHALL mostrar una notificación (toast) genérica indicando que ocurrió un error inesperado y que el usuario puede intentar de nuevo más tarde

---

### Requisito 4: Carga de Archivo CSV

**User Story:** Como Usuario_Corporativo, quiero cargar un archivo CSV mediante arrastrar y soltar o un selector de archivos, para enviar mis reseñas de clientes al sistema de análisis.

#### Criterios de Aceptación

1. THE Dashboard SHALL presentar un área de carga que acepte archivos mediante arrastrar y soltar (drag & drop) o selección mediante el explorador de archivos del sistema operativo
2. WHEN el Usuario_Corporativo selecciona o suelta un archivo, THE Dashboard SHALL verificar en el cliente que la extensión del archivo sea `.csv`; IF la extensión no es `.csv`, THEN THE Dashboard SHALL mostrar un mensaje de error indicando que solo se permiten archivos CSV y no enviará el archivo al backend
3. WHEN el Usuario_Corporativo selecciona o suelta un archivo `.csv`, THE Dashboard SHALL verificar en el cliente que el tamaño del archivo no supere 10 MB; IF el tamaño supera 10 MB, THEN THE Dashboard SHALL mostrar un mensaje de error indicando el límite máximo y no enviará el archivo al backend
4. WHEN el archivo pasa las validaciones del cliente, THE Dashboard SHALL enviar el archivo al backend mediante una solicitud `POST /api/v1/batches/upload` con codificación `multipart/form-data` y el Token_JWT adjunto
5. WHEN el backend devuelve un `batch_id` en respuesta a la carga exitosa, THE Dashboard SHALL iniciar el Polling del estado de procesamiento del lote consultando `GET /api/v1/batches/{batch_id}/status` cada 2 segundos
6. WHILE el estado del Lote_Analisis es `pending` o `processing`, THE Dashboard SHALL mostrar el estado actual traducido al español: "pendiente" o "en progreso"
7. WHEN el estado del Lote_Analisis cambia a `completed`, THE Dashboard SHALL detener el Polling y navegar automáticamente a la vista de resultados del lote
8. WHEN el estado del Lote_Analisis cambia a `error`, THE Dashboard SHALL detener el Polling y mostrar un mensaje de error indicando que el procesamiento del lote ha fallado
9. IF el backend devuelve un error HTTP 422 durante la carga (formato incorrecto, tamaño excedido, columna faltante, límite de filas), THEN THE Dashboard SHALL mostrar el mensaje de error específico devuelto por el backend

---

### Requisito 5: Historial de Lotes

**User Story:** Como Usuario_Corporativo, quiero ver una lista de todos mis archivos CSV cargados anteriormente con su estado y métricas, para poder acceder al historial de análisis y hacer seguimiento de los lotes en curso.

#### Criterios de Aceptación

1. WHEN el Usuario_Corporativo navega a `/dashboard`, THE Dashboard SHALL consultar `GET /api/v1/batches` y mostrar la lista de Lotes_Analisis del usuario, ordenada por fecha de carga de más reciente a más antiguo
2. THE Dashboard SHALL mostrar por cada Lote_Analisis en la lista: nombre del archivo, fecha de carga, estado actual traducido al español, total de filas, filas procesadas y filas con error
3. WHEN un Lote_Analisis contiene Feedbacks urgentes (Score < -0.7), THE Dashboard SHALL mostrar un Badge_Urgencia de color rojo junto al nombre del lote en el historial, indicando la cantidad de Feedbacks urgentes
4. WHEN el Usuario_Corporativo hace clic sobre un Lote_Analisis en el historial, THE Dashboard SHALL cargar y mostrar los resultados de ese lote en el Dashboard analítico
5. IF el Usuario_Corporativo no tiene ningún Lote_Analisis cargado, THEN THE Dashboard SHALL mostrar un Estado_Vacio con un mensaje indicando que aún no hay lotes y un CTA que dirija al Usuario_Corporativo a `/upload`
6. THE Dashboard SHALL soportar paginación en el historial de lotes según la respuesta paginada devuelta por el backend

---

### Requisito 6: Dashboard Analítico — Tarjetas de Resumen

**User Story:** Como Usuario_Corporativo, quiero ver un resumen numérico del análisis de sentimiento de un lote, para obtener una visión rápida del estado de satisfacción de mis clientes.

#### Criterios de Aceptación

1. WHEN el Usuario_Corporativo selecciona un Lote_Analisis completado, THE Dashboard SHALL consultar `GET /api/v1/batches/{id}/summary` y mostrar las siguientes tarjetas de resumen: total de Feedbacks, porcentaje de Feedbacks positivos, porcentaje de Feedbacks neutros, porcentaje de Feedbacks negativos, y cantidad de Feedbacks urgentes
2. THE Dashboard SHALL mostrar el conjunto de tarjetas de resumen en un tiempo máximo de 3 segundos desde la navegación al lote seleccionado
3. IF el Lote_Analisis no contiene Feedbacks procesados exitosamente, THEN THE Dashboard SHALL mostrar un Estado_Vacio con un mensaje indicando que no hay resultados disponibles y un CTA para cargar un nuevo archivo

---

### Requisito 7: Dashboard Analítico — Gráficos de Sentimiento

**User Story:** Como Usuario_Corporativo, quiero visualizar la distribución de sentimientos en gráficos interactivos, para comprender de forma visual la proporción de comentarios positivos, neutros y negativos.

#### Criterios de Aceptación

1. WHEN el Dashboard muestra los resultados de un Lote_Analisis, THE Dashboard SHALL renderizar un gráfico de barras (Chart.js) con la distribución de sentimientos mostrando los conteos absolutos de `positivo`, `neutro` y `negativo`
2. WHEN el Dashboard muestra los resultados de un Lote_Analisis, THE Dashboard SHALL renderizar un gráfico de torta (Chart.js) con la distribución porcentual de sentimientos
3. WHEN el Usuario_Corporativo coloca el cursor sobre un segmento del gráfico de torta, THE Dashboard SHALL mostrar un tooltip con el conteo exacto y el porcentaje del segmento correspondiente
4. WHEN el Usuario_Corporativo hace clic en un segmento del gráfico de barras o de torta, THE Dashboard SHALL aplicar un filtro por esa categoría de Sentimiento sobre la lista de Feedbacks del lote activo
5. WHEN el Usuario_Corporativo hace clic en un segmento ya seleccionado como filtro activo, THE Dashboard SHALL eliminar el filtro y mostrar todos los Feedbacks del lote sin filtrar

---

### Requisito 8: Dashboard Analítico — Nube de Palabras Clave

**User Story:** Como Usuario_Corporativo, quiero ver una nube de palabras con los términos más mencionados, para identificar rápidamente los temas dominantes en el feedback de mis clientes.

#### Criterios de Aceptación

1. WHEN el Dashboard muestra los resultados de un Lote_Analisis, THE Dashboard SHALL consultar `GET /api/v1/batches/{id}/keywords` y renderizar una nube de palabras (react-wordcloud) con las 20 Palabras_Clave más frecuentes del lote
2. THE Dashboard SHALL mostrar cada Palabra_Clave con un tamaño de fuente proporcional a su frecuencia de aparición en el lote
3. WHEN el Usuario_Corporativo hace clic en una Palabra_Clave de la nube, THE Dashboard SHALL aplicar un filtro por esa palabra sobre la lista de Feedbacks, consultando `GET /api/v1/batches/{id}/feedbacks?keyword={palabra}`
4. WHEN el Usuario_Corporativo hace clic en una Palabra_Clave ya seleccionada como filtro activo, THE Dashboard SHALL eliminar el filtro y mostrar todos los Feedbacks del lote sin filtrar

---

### Requisito 9: Dashboard Analítico — Lista de Feedbacks

**User Story:** Como Usuario_Corporativo, quiero explorar los comentarios individuales de un lote con opciones de filtrado y paginación, para revisar en detalle los feedbacks de mis clientes.

#### Criterios de Aceptación

1. WHEN el Dashboard muestra los resultados de un Lote_Analisis, THE Dashboard SHALL consultar `GET /api/v1/batches/{id}/feedbacks` y mostrar los Feedbacks en una lista paginada con un máximo de 20 Feedbacks por página
2. THE Dashboard SHALL mostrar por cada Feedback: el texto original completo, un badge de Sentimiento con color diferenciado (verde para positivo, amarillo para neutro, rojo para negativo), el Score numérico y las Palabras_Clave asociadas
3. WHEN el Usuario_Corporativo aplica un filtro de Sentimiento (desde el gráfico), THE Dashboard SHALL mostrar únicamente los Feedbacks con ese Sentimiento y actualizar la paginación en consecuencia
4. WHEN el Usuario_Corporativo aplica un filtro de Palabra_Clave (desde la nube de palabras), THE Dashboard SHALL consultar `GET /api/v1/batches/{id}/feedbacks?keyword={palabra}` y mostrar únicamente los Feedbacks que contienen esa Palabra_Clave
5. WHEN el Usuario_Corporativo navega entre páginas de la lista, THE Dashboard SHALL solicitar la página correspondiente al backend manteniendo el filtro activo
6. IF el Lote_Analisis no contiene Feedbacks procesados exitosamente, THEN THE Dashboard SHALL mostrar un Estado_Vacio con un mensaje indicando la ausencia de resultados y un CTA para cargar un nuevo archivo

---

### Requisito 10: Panel de Triaje de Urgencia

**User Story:** Como Usuario_Corporativo, quiero identificar rápidamente los comentarios extremadamente negativos (Score < -0.7) en un panel dedicado, para actuar de inmediato ante situaciones críticas de insatisfacción.

#### Criterios de Aceptación

1. THE Dashboard SHALL exponer el Panel_Triaje como una sección accesible desde la barra de navegación principal, con un Badge_Urgencia numérico que indique la cantidad de Feedbacks urgentes del Lote_Analisis activo
2. WHEN el Usuario_Corporativo accede al Panel_Triaje, THE Dashboard SHALL consultar `GET /api/v1/batches/{id}/triage` y mostrar los Feedbacks urgentes del lote activo, ordenados de menor a mayor Score (más negativo primero), en una lista paginada con un máximo de 10 Feedbacks por página
3. THE Dashboard SHALL mostrar por cada Feedback urgente: el texto original completo, el Score numérico y las Palabras_Clave asociadas
4. IF el Lote_Analisis no contiene Feedbacks con Score < -0.7, THEN THE Dashboard SHALL mostrar un Estado_Vacio en el Panel_Triaje con el mensaje "No se detectaron comentarios urgentes"
5. WHEN un Lote_Analisis contiene Feedbacks urgentes, THE Dashboard SHALL mostrar un Badge_Urgencia de color rojo junto al nombre del lote en el historial de lotes indicando la cantidad de Feedbacks urgentes

---

### Requisito 11: Navegación y Enrutamiento

**User Story:** Como Usuario_Corporativo, quiero que la aplicación tenga rutas claras y navegación coherente, para poder acceder fácilmente a cada funcionalidad sin perder el contexto de trabajo.

#### Criterios de Aceptación

1. THE Dashboard SHALL implementar las siguientes rutas con react-router-dom: `/login` (formulario de inicio de sesión), `/register` (formulario de registro), `/dashboard` (historial de lotes y vista de resultados), `/upload` (carga de archivos CSV)
2. WHILE el Usuario_Corporativo tiene una sesión activa con un Token_JWT válido, THE Dashboard SHALL mostrar una barra de navegación con acceso a: el historial de lotes (`/dashboard`), la carga de archivos (`/upload`), el Panel_Triaje del lote activo con su Badge_Urgencia, y el botón de cerrar sesión
3. WHEN el Usuario_Corporativo navega a la ruta raíz `/`, THE Dashboard SHALL redirigir a `/dashboard` si existe un Token_JWT válido en `localStorage`, o a `/login` en caso contrario
4. IF el Usuario_Corporativo intenta acceder a una ruta inexistente, THEN THE Dashboard SHALL mostrar una página de error con un mensaje indicando que la página no fue encontrada y un enlace para regresar al Dashboard

---

### Requisito 12: Estados Vacíos

**User Story:** Como Usuario_Corporativo, quiero que la aplicación me guíe de forma clara cuando no hay datos disponibles, para entender qué debo hacer a continuación.

#### Criterios de Aceptación

1. IF el Usuario_Corporativo no tiene ningún Lote_Analisis cargado, THEN THE Dashboard SHALL mostrar un Estado_Vacio en la vista de historial con un mensaje informativo y un CTA que dirija a `/upload`
2. IF el Lote_Analisis seleccionado no contiene Feedbacks procesados exitosamente, THEN THE Dashboard SHALL mostrar un Estado_Vacio en la vista de resultados con un mensaje indicando que no hay datos disponibles y un CTA para cargar un nuevo archivo
3. IF el Panel_Triaje del lote activo no contiene Feedbacks urgentes, THEN THE Dashboard SHALL mostrar el Estado_Vacio con el mensaje "No se detectaron comentarios urgentes"
4. THE Estado_Vacio SHALL ser un componente reutilizable que acepte como parámetros un mensaje personalizable y un elemento CTA opcional

---

### Requisito 13: Accesibilidad y Experiencia de Usuario

**User Story:** Como Usuario_Corporativo, quiero que la interfaz sea accesible y usable desde diferentes dispositivos, para poder trabajar cómodamente en distintos entornos.

#### Criterios de Aceptación

1. THE Dashboard SHALL garantizar que todos los elementos interactivos (botones, enlaces, campos de formulario) sean navegables mediante teclado y tengan atributos ARIA descriptivos
2. THE Dashboard SHALL garantizar que los colores utilizados para los badges de sentimiento y urgencia tengan una relación de contraste mínima de 4.5:1 conforme al estándar WCAG AA
3. WHEN el Dashboard realiza una operación asíncrona (carga de datos, envío de formulario, polling), THE Dashboard SHALL mostrar un indicador de carga visible (spinner o esqueleto de contenido) mientras la operación está en curso
4. THE Dashboard SHALL ser responsivo y mantener la usabilidad en viewports de mínimo 1024 píxeles de ancho

---

### Requisito 14: Estructura del Proyecto Frontend

**User Story:** Como equipo de desarrollo, queremos que el proyecto frontend siga la estructura de directorios y el stack tecnológico acordados, para mantener consistencia con el resto del proyecto Sentify.

#### Criterios de Aceptación

1. THE Dashboard SHALL estar desarrollado con React, TypeScript y Vite, siguiendo la estructura de directorios definida: `frontend/src/components/`, `frontend/src/services/`, `frontend/src/hooks/`, `frontend/src/types/`
2. THE Dashboard SHALL usar react-router-dom para el enrutamiento, Axios para las solicitudes HTTP, Chart.js con react-chartjs-2 para los gráficos, y react-wordcloud para la nube de palabras
3. THE Dashboard SHALL definir interfaces TypeScript para todos los esquemas de respuesta del backend en `frontend/src/types/`, incluyendo: `LoginResponse`, `BatchStatus`, `BatchSummary`, `FeedbackItem`, `KeywordItem` y `PaginatedResponse`
4. THE Dashboard SHALL centralizar toda la lógica de comunicación con el backend en `frontend/src/services/api.ts`, exponiendo funciones tipadas para cada endpoint disponible
5. THE Dashboard SHALL incluir tests de componentes con React Testing Library y tests de extremo a extremo (e2e) con Cypress o Playwright
