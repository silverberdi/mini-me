# mcp-connections-and-integrations Specification

## Purpose

Permite al operador registrar y administrar servidores MCP desde el Centro de Control, con autorización interactiva única, credenciales confinadas a PostgreSQL, descubrimiento verificable y consumo desasistido y fail-closed por agentes autorizados.

## Requirements

### Requirement: Admisión autorizada del Change

El sistema SHALL impedir Propose y ejecución del Issue cuando permanezca marcado `disabled` sin una validación expresa vigente del propietario. Una solicitud explícita del operador SHALL constituir esa autorización para este Change y SHALL conservarse como decisión auditable.

#### Scenario: Issue disabled sin autorización expresa
- **WHEN** se evalúa la admisión de un Issue con etiqueta `disabled` y no existe una validación expresa vigente del propietario
- **THEN** el sistema rechaza la admisión y no invoca Propose ni ejecución

#### Scenario: Operador autoriza el Issue
- **WHEN** el operador solicita expresamente este Change
- **THEN** el sistema puede admitir el Change y conserva la autorización asociada al Issue sin convertirla en autorización de otros cambios

### Requirement: Navegación dedicada y catálogo MCP

El Centro de Control SHALL mostrar una entrada «Conexiones MCP» separada de «Administración», SHALL servirla en `/conexiones-mcp` y SHALL mostrar un catálogo de integraciones con estado conectado, desconectado o error, acción disponible y capacidades descubiertas. La vista SHALL permanecer dentro de la autorización de operador existente y no SHALL exponer secretos.

#### Scenario: Abrir la vista dedicada
- **WHEN** un operador autenticado selecciona «Conexiones MCP» en la barra lateral
- **THEN** navega a `/conexiones-mcp` y observa la vista de integraciones fuera de Administración

#### Scenario: Mostrar catálogo sin secretos
- **WHEN** el operador consulta el catálogo
- **THEN** cada conexión muestra identidad segura, transporte, estado, diagnóstico sanitizado, acción permitida y herramientas/recursos descubiertos sin mostrar credenciales ni tokens

### Requirement: Registro y validación de conexiones

El sistema SHALL permitir registrar conexiones MCP genéricas por HTTP/SSE u stdio. Para OAuth2 SHALL iniciar un flujo de autorización interactivo en el proveedor y, tras retorno válido, validar el handshake MCP y descubrir capacidades. Para API Key o Bearer token SHALL aceptar endpoint y credencial mediante el Centro de Control, ejecutar el saludo inicial MCP y marcar la conexión ACTIVA solo si la conectividad y autenticación son válidas.

#### Scenario: Registrar servidor OAuth2
- **WHEN** el operador proporciona un endpoint OAuth2 y confirma la conexión
- **THEN** el sistema inicia el consentimiento del proveedor, valida el retorno autorizado, persiste de forma segura el refresh token, completa el handshake y registra la conexión como ACTIVA si el descubrimiento tiene éxito

#### Scenario: Registrar servidor con token
- **WHEN** el operador proporciona endpoint y API Key o Bearer token
- **THEN** el sistema ejecuta el saludo inicial MCP con esa credencial, guarda la credencial de forma segura y marca ACTIVA solo tras una respuesta autenticada válida

#### Scenario: Registro inválido
- **WHEN** el endpoint, transporte, credencial o handshake no es válido
- **THEN** la conexión queda en ERROR o DESCONECTADA con diagnóstico sanitizado, no se anuncia como ACTIVA y no se habilita para Runs

### Requirement: Persistencia y confinamiento de secretos

El sistema SHALL persistir el estado, la configuración no secreta y el material de credencial cifrado en PostgreSQL mediante evolución Alembic. SHALL separar los secretos del frontend, repositorios Git, repositorio destino, logs, evidencias y respuestas API, y SHALL devolver únicamente metadatos sanitizados.

#### Scenario: Persistir credencial cifrada
- **WHEN** una conexión OAuth2 o basada en token se guarda o renueva
- **THEN** el material secreto se almacena cifrado y vinculado al registro MCP de mini me, y una lectura posterior no devuelve el secreto en claro

#### Scenario: Detectar exposición prohibida
- **WHEN** una excepción, diagnóstico o evento contiene una credencial, token o cabecera de autorización
- **THEN** el sistema la redacciona antes de persistirla, registrarla o devolverla

### Requirement: Descubrimiento de capacidades

Tras un handshake MCP exitoso el sistema SHALL ejecutar el descubrimiento aplicable, incluido `tools/list`, y SHALL registrar herramientas y recursos con nombre, descripción segura, versión/observación y vínculo a la conexión. El catálogo SHALL reflejar únicamente capacidades observadas en el servidor.

#### Scenario: Descubrir herramientas
- **WHEN** un servidor completa correctamente el handshake y responde a `tools/list`
- **THEN** el catálogo registra las herramientas observadas, incluyendo capacidades como `stitch_get` o `stitch_find` cuando el servidor las proporciona

#### Scenario: Descubrimiento parcial o fallido
- **WHEN** el handshake o el descubrimiento falla o devuelve datos inválidos
- **THEN** el sistema no inventa capacidades, conserva el diagnóstico sanitizado y no habilita como ACTIVA una conexión que no pueda validarse

### Requirement: Uso desasistido y renovación OAuth2

Durante un Run autorizado, el sistema SHALL resolver la credencial activa, renovar automáticamente el access token cuando exista un refresh token válido y entregar al perfil de invocación solo la configuración MCP efímera necesaria para el agente autorizado. SHALL seleccionar un mecanismo de inyección aprobado por el propietario (argumentos de configuración o socket local de retransmisión) sin requerir navegador ni consentimiento interactivo durante el Run.

#### Scenario: Ejecutar herramienta sin interacción
- **WHEN** el orquestador prepara un Run para un agente autorizado y existe una conexión ACTIVA
- **THEN** el agente recibe las herramientas descubiertas y credenciales efímeras resueltas, invoca una herramienta MCP en el runtime real y no requiere abrir un navegador

#### Scenario: Renovar access token expirado
- **WHEN** el access token expiró y el refresh token sigue siendo válido
- **THEN** el backend obtiene un access token nuevo, actualiza de forma segura la credencial activa y continúa la preparación del Run sin reautorización

### Requirement: Fail-closed y diagnóstico operativo

El sistema SHALL bloquear la acción dependiente de una conexión cuando la credencial esté revocada, el endpoint no responda, falle el handshake, falle la renovación o la herramienta no esté disponible. SHALL registrar un diagnóstico sanitizado y notificar al operador, y SHALL prohibir respuestas inventadas o confirmaciones ficticias de éxito.

#### Scenario: Endpoint caído durante un Run
- **WHEN** el agente intenta utilizar una herramienta y el endpoint MCP no responde
- **THEN** mini me bloquea esa acción, registra el motivo observable, notifica al operador y no continúa simulando que la herramienta funcionó

#### Scenario: Credencial revocada sin refresh válido
- **WHEN** el proveedor rechaza la credencial y no existe renovación válida
- **THEN** la conexión deja de estar disponible para ejecuciones y el Run recibe un fallo determinista que requiere intervención autorizada

### Requirement: Revocación y eliminación por el operador

El sistema SHALL permitir al operador revocar o eliminar una conexión ACTIVA. La operación SHALL purgar los tokens y credenciales almacenados, cancelar el catálogo asociado, impedir nuevos usos y dejar evidencia auditable de la acción sin conservar secretos.

#### Scenario: Revocar conexión activa
- **WHEN** el operador confirma revocar una conexión
- **THEN** el sistema purga el material secreto, invalida las herramientas descubiertas, cambia el estado a no disponible y bloquea su uso en futuros Runs

#### Scenario: Eliminar conexión ya desconectada
- **WHEN** el operador elimina una conexión DESCONECTADA o ERROR
- **THEN** el sistema elimina su configuración y caché permitiendo conservar solo el diagnóstico no secreto exigido por auditoría

### Requirement: Evidencia de integración real

La verificación del Change SHALL demostrar con evidencia observable y reproducible la navegación, la autorización y persistencia segura de un servidor OAuth2 y uno basado en token, el handshake y `tools/list`, una invocación desasistida exitosa en el runtime real y el fail-closed ante credencial inválida o endpoint caído. Las pruebas simuladas SHALL NOT presentarse como evidencia E2E.

#### Scenario: Verificación completa del recorrido
- **WHEN** se ejecutan las comprobaciones focalizadas del Change en navegador, backend, PostgreSQL y runtime de agente
- **THEN** se conservan invocación, resultado y efectos observables de cada recorrido, con comandos y artefactos suficientes para contrastarlos contra el candidato verificado
