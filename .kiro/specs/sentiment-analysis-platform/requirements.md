# Requirements Document

## Introduction

Sentify es una plataforma de análisis de sentimiento y feedback de clientes diseñada para empresas que reciben grandes volúmenes de comentarios diarios. El sistema permite la carga masiva de archivos CSV con reseñas, procesa cada texto mediante NLP para clasificar su sentimiento (positivo, neutro o negativo), extrae palabras clave dominantes y presenta los resultados en un dashboard interactivo con visualización analítica y triaje de urgencia.

## Glossary

- **Sistema**: La plataforma Sentify completa (frontend + backend + base de datos)
- **Dashboard**: Interfaz web en React donde el usuario corporativo interactúa con la plataforma
- **Backend**: API REST desarrollada en Python (FastAPI/Flask) que procesa las solicitudes
- **Motor_NLP**: Módulo de procesamiento de lenguaje natural que evalúa sentimiento y extrae palabras clave
- **Base_de_Datos**: Base de datos relacional (SQLite) para persistencia de análisis e historial
- **Usuario_Corporativo**: Persona de la empresa que utiliza la plataforma para analizar feedback
- **Lote_Analisis**: Agrupación lógica de un archivo CSV cargado con sus comentarios asociados
- **Feedback**: Comentario individual de un cliente contenido en un archivo CSV
- **Sentimiento**: Clasificación del tono emocional de un texto (positivo, neutro o negativo)
- **Score**: Valor numérico de polaridad asignado a un comentario (rango -1.0 a 1.0)
- **Palabra_Clave**: Término relevante extraído automáticamente de un comentario
- **Triaje_Urgencia**: Sección del Dashboard que destaca comentarios con polaridad extremadamente negativa
- **Archivo_CSV**: Archivo de valores separados por comas que contiene las reseñas a analizar

## Requirements

### Requisito 1: Autenticación de Usuario Corporativo

**User Story:** Como usuario corporativo, quiero autenticarme en la plataforma con mis credenciales, para que solo personal autorizado de mi empresa acceda a los datos de análisis.

#### Criterios de Aceptación

1. WHEN el Usuario_Corporativo envía credenciales válidas (email con formato válido y contraseña de entre 8 y 128 caracteres), THE Sistema SHALL autenticar al Usuario_Corporativo y devolver un token de sesión con una duración de 30 minutos
2. IF el Usuario_Corporativo envía credenciales inválidas, THEN THE Sistema SHALL rechazar la solicitud con un mensaje de error genérico que indique fallo de autenticación sin revelar qué campo es incorrecto
3. IF un token de sesión ha superado los 30 minutos desde su emisión, THEN THE Sistema SHALL rechazar la solicitud y solicitar re-autenticación
4. THE Sistema SHALL almacenar las contraseñas usando un algoritmo de hash seguro (bcrypt)
5. WHILE el Usuario_Corporativo tiene una sesión activa, THE Dashboard SHALL mostrar el nombre de la empresa asociada al usuario
6. IF el Usuario_Corporativo acumula 5 intentos fallidos consecutivos de autenticación, THEN THE Sistema SHALL bloquear temporalmente la cuenta durante 15 minutos y devolver un mensaje indicando que la cuenta ha sido bloqueada temporalmente

### Requisito 2: Carga Masiva de Archivo CSV

**User Story:** Como usuario corporativo, quiero cargar un archivo CSV con reseñas de clientes, para que el sistema analice múltiples comentarios en una sola operación.

#### Criterios de Aceptación

1. WHEN el Usuario_Corporativo selecciona un Archivo_CSV válido desde el Dashboard, THE Sistema SHALL aceptar el archivo y crear un nuevo Lote_Analisis asociado al usuario
2. WHEN el Archivo_CSV contiene una columna con encabezado reconocido ("texto", "comentario", "review", "comment" o "feedback") y al menos una fila de datos, THE Backend SHALL validar el formato y confirmar la recepción al Dashboard
3. IF el Archivo_CSV tiene un formato inválido (extensión distinta a .csv, codificación distinta a UTF-8 o Latin-1, o sin columna de texto reconocida), THEN THE Backend SHALL rechazar el archivo y devolver un mensaje indicando el motivo específico del rechazo
4. IF el Archivo_CSV excede el tamaño máximo permitido (10 MB) o contiene más de 50,000 filas, THEN THE Backend SHALL rechazar el archivo e informar al Usuario_Corporativo del límite excedido
5. WHEN el Archivo_CSV es recibido por el Backend, THE Sistema SHALL registrar la fecha de carga y el nombre del archivo origen en el Lote_Analisis
6. WHILE el archivo se está procesando, THE Dashboard SHALL mostrar un indicador de progreso con el estado actual (pendiente, en progreso, completado o error)
7. IF una o más filas del Archivo_CSV carecen de la columna de texto requerida, THEN THE Backend SHALL procesar las filas válidas y reportar la cantidad de filas omitidas al Usuario_Corporativo

### Requisito 3: Procesamiento NLP de Sentimiento

**User Story:** Como usuario corporativo, quiero que el sistema analice automáticamente el sentimiento de cada comentario, para obtener una clasificación objetiva sin leer cada texto manualmente.

#### Criterios de Aceptación

1. WHEN el Backend recibe un Lote_Analisis válido, THE Motor_NLP SHALL evaluar el sentimiento de cada Feedback contenido en el lote en un tiempo máximo de 2 segundos por Feedback individual
2. THE Motor_NLP SHALL clasificar cada Feedback en exactamente una categoría de Sentimiento: positivo, neutro o negativo
3. THE Motor_NLP SHALL asignar un Score numérico a cada Feedback en el rango de -1.0 (extremadamente negativo) a 1.0 (extremadamente positivo), con una precisión de 2 decimales
4. WHEN el Motor_NLP clasifica un Feedback como positivo, THE Score SHALL ser mayor a 0.2
5. WHEN el Motor_NLP clasifica un Feedback como negativo, THE Score SHALL ser menor a -0.2
6. WHEN el Motor_NLP clasifica un Feedback como neutro, THE Score SHALL estar en el rango de -0.2 a 0.2 inclusive
7. IF el Motor_NLP no puede procesar un Feedback porque el texto está vacío (0 caracteres o solo espacios en blanco), contiene menos de 2 palabras significativas (excluyendo stopwords), o está en un idioma no soportado, THEN THE Backend SHALL marcar ese Feedback con estado de error indicando el motivo de fallo y continuar procesando los restantes del Lote_Analisis
8. THE Motor_NLP SHALL procesar textos escritos en español; IF un Feedback contiene texto en un idioma distinto al español, THEN THE Backend SHALL marcar ese Feedback con estado de error indicando idioma no soportado

### Requisito 4: Extracción de Palabras Clave

**User Story:** Como usuario corporativo, quiero que el sistema extraiga las palabras clave de cada comentario, para identificar rápidamente los temas más mencionados por los clientes.

#### Criterios de Aceptación

1. WHEN el Motor_NLP procesa un Feedback con estado exitoso, THE Motor_NLP SHALL extraer entre 1 y 10 Palabras_Clave relevantes del texto, donde "relevante" se define como sustantivos, adjetivos o verbos con mayor frecuencia TF-IDF dentro del texto
2. THE Motor_NLP SHALL excluir palabras vacías (stopwords del idioma español) y palabras con 2 caracteres o menos del conjunto de Palabras_Clave extraídas
3. WHEN un Feedback contiene menos de 3 palabras significativas (no stopwords, más de 2 caracteres), THE Motor_NLP SHALL extraer todas las palabras significativas disponibles como Palabras_Clave
4. THE Base_de_Datos SHALL almacenar cada Palabra_Clave asociada al Feedback del cual fue extraída, preservando el texto original de la palabra en minúsculas
5. IF el Motor_NLP no puede extraer ninguna Palabra_Clave de un Feedback (texto compuesto únicamente por stopwords o caracteres especiales), THEN THE Backend SHALL registrar el Feedback sin Palabras_Clave asociadas y continuar el procesamiento del Lote_Analisis

### Requisito 5: Persistencia de Resultados

**User Story:** Como usuario corporativo, quiero que los resultados del análisis se almacenen permanentemente, para poder consultar el historial de análisis en cualquier momento.

#### Criterios de Aceptación

1. WHEN el Motor_NLP completa el procesamiento de un Lote_Analisis, THE Base_de_Datos SHALL almacenar el texto original, el Sentimiento, el Score y la fecha de finalización del análisis de cada Feedback
2. THE Base_de_Datos SHALL mantener la relación entre cada Feedback y su Lote_Analisis correspondiente
3. THE Base_de_Datos SHALL mantener la relación entre cada Lote_Analisis y el Usuario_Corporativo que lo cargó
4. WHEN se almacena un Feedback, THE Base_de_Datos SHALL preservar el texto original sin modificaciones y con una longitud máxima de 5000 caracteres
5. IF ocurre un error durante la persistencia de uno o más Feedbacks de un Lote_Analisis, THEN THE Backend SHALL conservar los Feedbacks almacenados exitosamente, registrar el error en el log y notificar al Usuario_Corporativo a través del Dashboard indicando la cantidad de Feedbacks que no pudieron almacenarse
6. WHEN el Usuario_Corporativo consulta el historial, THE Base_de_Datos SHALL devolver los Lotes_Analisis ordenados por fecha de finalización del análisis de más reciente a más antiguo

### Requisito 6: Visualización del Dashboard Analítico

**User Story:** Como usuario corporativo, quiero visualizar un resumen analítico interactivo de los resultados, para entender rápidamente el "pulso" de la satisfacción de mis clientes.

#### Criterios de Aceptación

1. WHEN el análisis de un Lote_Analisis se completa, THE Dashboard SHALL mostrar un resumen con la distribución porcentual de sentimientos (positivo, neutro, negativo) en un tiempo máximo de 3 segundos desde la navegación del usuario
2. THE Dashboard SHALL presentar los resultados mediante al menos un gráfico de barras con la distribución de sentimientos y un gráfico de torta con la proporción porcentual, donde cada segmento responde a eventos hover mostrando el valor exacto y a eventos clic aplicando un filtro por esa categoría
3. WHEN el Usuario_Corporativo hace clic en una Palabra_Clave, THE Dashboard SHALL filtrar y mostrar los Feedbacks asociados a esa Palabra_Clave en una lista paginada con un máximo de 20 Feedbacks por página
4. THE Dashboard SHALL mostrar las 20 Palabras_Clave más frecuentes del Lote_Analisis en una nube de palabras donde el tamaño de cada palabra es proporcional a su frecuencia de aparición
5. WHEN el Usuario_Corporativo selecciona un Lote_Analisis del historial, THE Dashboard SHALL cargar y mostrar los resultados almacenados de ese lote en un tiempo máximo de 3 segundos
6. IF un Lote_Analisis no contiene Feedbacks procesados exitosamente, THEN THE Dashboard SHALL mostrar un estado vacío con un mensaje indicando que no hay resultados disponibles y un enlace para cargar un nuevo archivo

### Requisito 7: Triaje de Urgencia

**User Story:** Como usuario corporativo, quiero identificar rápidamente los comentarios extremadamente negativos, para poder actuar de inmediato ante situaciones críticas de insatisfacción.

#### Criterios de Aceptación

1. WHEN un Feedback tiene un Score menor a -0.7, THE Dashboard SHALL clasificar ese Feedback como urgente en la sección de Triaje_Urgencia
2. THE Dashboard SHALL mostrar la sección de Triaje_Urgencia como una pestaña o panel accesible desde la barra de navegación principal del Dashboard, con un badge numérico que indique la cantidad de Feedbacks urgentes del Lote_Analisis activo
3. WHEN existen Feedbacks urgentes en un Lote_Analisis, THE Dashboard SHALL mostrar un indicador visual de alerta (ícono o badge de color rojo) junto al nombre del Lote_Analisis en la vista principal con la cantidad de comentarios urgentes
4. THE Dashboard SHALL ordenar los Feedbacks urgentes por Score de menor a mayor (más negativo primero) en una lista paginada con un máximo de 10 Feedbacks por página
5. WHEN el Usuario_Corporativo accede a la sección de Triaje_Urgencia, THE Dashboard SHALL mostrar el texto original completo de cada Feedback urgente junto con su Score numérico y sus Palabras_Clave asociadas
6. IF un Lote_Analisis no contiene Feedbacks con Score menor a -0.7, THEN THE Dashboard SHALL mostrar un estado vacío en la sección de Triaje_Urgencia con un mensaje indicando que no se detectaron comentarios urgentes

### Requisito 8: Modularidad para Migración Cloud

**User Story:** Como equipo de desarrollo, quiero que la arquitectura sea modular y desacoplada, para poder migrar componentes individuales a servicios cloud (AWS) sin reescribir la lógica de negocio.

#### Criterios de Aceptación

1. THE Backend SHALL exponer el procesamiento NLP a través de una interfaz abstracta con firmas de entrada y salida definidas (texto de entrada, sentimiento y score de salida), de modo que la implementación local y un servicio cloud (Amazon Comprehend) sean intercambiables sin modificar los módulos que consumen dicha interfaz
2. THE Backend SHALL separar la lógica de autenticación en un módulo independiente que no importe ni sea importado directamente por los módulos de lógica de negocio, de forma que pueda reemplazarse por un proveedor externo (Amazon Cognito) modificando únicamente la configuración de inyección de dependencias
3. THE Backend SHALL utilizar una capa de abstracción para el acceso a Base_de_Datos con operaciones definidas (crear, leer, actualizar, eliminar registros de Lote_Analisis y Feedback), de modo que cambiar el motor de almacenamiento no requiera modificar ningún archivo fuera del módulo de persistencia
4. THE Sistema SHALL documentar los contratos de API REST entre el Frontend y el Backend mediante una especificación OpenAPI accesible en un endpoint del Backend, que incluya rutas, métodos HTTP, esquemas de request/response y códigos de estado
5. WHEN se reemplaza una implementación de un módulo (Motor_NLP, autenticación o Base_de_Datos) por una implementación alternativa que cumpla la misma interfaz, THEN THE Backend SHALL pasar la misma suite de tests de integración sin modificar los tests ni la lógica de negocio
