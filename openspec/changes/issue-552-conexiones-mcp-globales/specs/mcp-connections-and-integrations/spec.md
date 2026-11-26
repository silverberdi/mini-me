## ADDED Requirements

### Requirement: Alcance global de conexiones MCP
El sistema SHALL permitir que una conexión MCP pertenezca a un proyecto o tenga alcance global para todos los proyectos registrados. Las conexiones globales SHALL conservar credenciales cifradas y referencias de capacidad sin quedar subordinadas al ciclo de vida de un proyecto; la API SHALL indicar explícitamente el alcance y SHALL NOT exponer secretos.

#### Scenario: Persistir una conexión global
- **WHEN** el operador registra una conexión y selecciona alcance global
- **THEN** mini me la persiste como global con credenciales cifradas y la distingue de una conexión local

#### Scenario: Mantener conexiones locales existentes
- **WHEN** una conexión registrada antes de esta capacidad se consulta o migra
- **THEN** conserva su proyecto, credenciales, capacidades y disponibilidad local sin cambio de alcance

### Requirement: Resolver capacidades locales y globales
Para un proyecto, el catálogo de capacidades SHALL combinar las conexiones activas propias del proyecto y todas las conexiones globales activas. SHALL deduplicar herramientas y recursos por tipo y nombre exacto; ante una colisión local/global, SHALL conservar la capacidad local; ante una colisión entre conexiones del mismo alcance, SHALL elegir la conexión de menor ID en orden lexicográfico.

#### Scenario: Combinar capacidades sin duplicados
- **WHEN** un proyecto tiene capacidades locales y conexiones globales activas con capacidades observadas
- **THEN** la resolución devuelve la unión de capacidades y cada tipo/nombre aparece una sola vez

#### Scenario: Priorizar capacidad local coincidente
- **WHEN** una conexión local y una global exponen una herramienta o recurso con el mismo tipo y nombre
- **THEN** la capacidad local conserva la resolución y no se anuncia una segunda entrada duplicada

#### Scenario: Resolver colisión entre conexiones del mismo alcance
- **WHEN** varias conexiones activas del mismo alcance exponen el mismo tipo y nombre
- **THEN** la resolución elige de forma estable la conexión con menor ID lexicográfico y publica una sola entrada

#### Scenario: Excluir conexiones globales no activas
- **WHEN** una conexión global está pendiente, revocada, desconectada o en error
- **THEN** sus capacidades no aparecen disponibles para el proyecto

### Requirement: Factibilidad con capacidades MCP globales
La evaluación de factibilidad SHALL reconocer las herramientas observadas de conexiones globales activas como capacidades disponibles para cualquier proyecto. SHALL conservar el bloqueo cuando la capacidad requerida no está realmente disponible.

#### Scenario: Reconocer una herramienta global requerida
- **WHEN** una tarea requiere una herramienta MCP observada en una conexión global activa
- **THEN** la factibilidad reconoce su referencia como disponible y no genera un bloqueo por ausencia de capacidad

#### Scenario: No inferir una herramienta ausente
- **WHEN** ninguna conexión local o global activa proporciona la herramienta requerida
- **THEN** la factibilidad conserva el diagnóstico de capacidad ausente

### Requirement: Uso transversal de MCP en Runs
Al preparar una invocación autorizada de agente, el runtime SHALL poner a disposición del proyecto las conexiones globales activas, además de la conexión local explícitamente seleccionada cuando exista. SHALL exponerlas mediante un puente MCP stdio efímero sobre socket Unix con permisos `0600`, enrutar cada llamada por `connection_id` dentro del proceso mini me, conservar el cifrado en reposo y fallar de forma cerrada ante errores de autorización o preparación. Las credenciales remotas SHALL NOT aparecer en argumentos, entorno del agente, worktree ni logs; la configuración efímera del CLI solo contiene el comando adaptador y la ruta del socket.

#### Scenario: Inyectar conexiones globales sin duplicar credenciales
- **WHEN** se prepara un Run para un proyecto con conexiones globales activas
- **THEN** el agente autorizado puede descubrir e invocar sus herramientas por el canal efímero del runtime sin clonar conexiones o credenciales al proyecto

#### Scenario: Invocar una herramienta MCP por el puente local
- **WHEN** el CLI solicita `tools/list` y `tools/call` durante una invocación con conexiones globales o locales autorizadas
- **THEN** el adaptador stdio entrega la llamada al relay del Run, mini me invoca la conexión seleccionada y devuelve el resultado real, sin entregar credenciales remotas al CLI

#### Scenario: Run sin conexiones globales activas
- **WHEN** se prepara un Run y no hay conexiones globales activas ni una conexión local seleccionada
- **THEN** el Run mantiene el comportamiento existente sin crear una sesión MCP vacía ni una compuerta de capacidad falsa

#### Scenario: Fallo de una conexión requerida
- **WHEN** la conexión necesaria para una invocación fue revocada, no responde o no puede renovarse
- **THEN** mini me bloquea la invocación dependiente, conserva un diagnóstico sanitizado y no simula éxito

### Requirement: Administración visual del alcance MCP
La vista `/conexiones-mcp` SHALL distinguir las conexiones globales de las locales, mostrar en un proyecto las conexiones globales heredadas junto con las locales, permitir filtrar el catálogo por alcance y registrar una conexión nueva con alcance global o de proyecto.

#### Scenario: Identificar conexiones heredadas
- **WHEN** el operador consulta conexiones MCP desde un proyecto
- **THEN** ve sus conexiones locales y las conexiones globales, con un distintivo claro para el alcance de cada una

#### Scenario: Elegir alcance al registrar
- **WHEN** el operador registra una integración desde la vista MCP
- **THEN** puede elegir alcance global o el proyecto actual y el catálogo refleja el alcance elegido

#### Scenario: Filtrar por alcance
- **WHEN** el operador selecciona el filtro global o local
- **THEN** el catálogo muestra solo conexiones del alcance elegido sin ocultar el alcance al limpiar el filtro

### Requirement: Evidencia de integración global real
La verificación de este Change SHALL demostrar la migración PostgreSQL, la resolución combinada y su efecto en factibilidad y runtime, y la gestión visual del alcance en Playwright. La evidencia SHALL corresponder al candidato verificado y SHALL mostrar invocación, resultado y efecto observables; pruebas simuladas SHALL NOT presentarse como E2E real.

#### Scenario: Verificación completa de capacidades globales
- **WHEN** se ejecutan las verificaciones focalizadas de persistencia, resolución, factibilidad, runtime y vista MCP
- **THEN** se conserva evidencia reproducible de los resultados y efectos de cada recorrido contra el candidato verificado
