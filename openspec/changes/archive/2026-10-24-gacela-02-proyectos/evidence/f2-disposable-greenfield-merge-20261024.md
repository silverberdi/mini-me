# F2 — merge real del Greenfield E2E desechable

**Evidencia remota observada directamente en GitHub**, 2026-10-24.
Este registro no afirma que el coordinador de mini me haya observado
ya el merge ni que el proyecto haya pasado a `PREPARED`.

## Identidad exacta

- Repositorio **desechable**: `silverberdi/mini-me-f2-e2e-20261023`.
- PR documental Greenfield: https://github.com/silverberdi/mini-me-f2-e2e-20261023/pull/2
- Rama del candidato: `minime/bootstrap/f2-e2e-gacela-20261023e-3eed0aacf1f3`.
- Base `main` antes de fusionar: `fa4eb55699b2169e5ff88059504872f17df617ce`.
- Head de candidato: `16dd7f3ad84800c242d57790aea895881734edc9`.
- Merge autorizado por el contexto de **prueba desechable**, ejecutado
  mediante API de GitHub con precondición de head SHA exacto.
- Resultado GitHub: `merged=true`, PR `closed`.
- Merge commit: `89297274076dd1dd4aa377da9950a69da6c8a40a`.
- Consulta posterior a `main`: HEAD
  `89297274076dd1dd4aa377da9950a69da6c8a40a`, igual al merge SHA.
- PR de permisos #1: **open / not merged**; no se utilizó como bootstrap.

## Alcance y control

El PR #2 incorporó 31 archivos documentales y scaffolds oficiales:
fuente preservada bajo `context/incoming/3eed0aacf1f3cbe4361805b914d4fe659dbca69266f55279cdc55c10eef12e81/`,
documentos canónicos, `context/INDEX.md` y `context/fuentes/INDEX.md`,
instrucciones de agente y OpenSpec oficial. No contiene código de producto.

La invocación real Greenfield (evidencia del ejecutor) utilizó
Codex `gpt-5.6-luna`, esfuerzo `medium`,
`222562` tokens de entrada y `6535` de salida; este merge
**no invocó** ningún modelo ni consumió una nueva concesión.

**Excepción estricta de E2E:** el PR pertenecía al repositorio desechable
que existe exclusivamente para verificar F2. Se fusionó tras cotejar
identidad de repo, SHA de base y head y la revisión del contenido documental.
La exigencia de aprobación humana permanece para PRs de proyectos reales;
no se autorizó un merge general automático en el producto mini me.

## Seguimiento obligatorio

1. En runtime F2 aislado, invocar el observador de bootstrap ya existente
   sobre el proyecto de prueba y confirmar `PREPARED` **solo después**
   de validar identidad y merge SHA exactos. No reconstruir proyecto, ZIP
   ni llamar otra vez a Codex.
2. Con el estado realmente `PREPARED`, procesar el **ZIP incremental**
   con su concesión propia, si sigue válida; no intercambiar concesiones.
3. Publicar segundo PR incremental desechable. Antes del merge demostrar
   que `main` sigue en `89297274076dd1dd4aa377da9950a69da6c8a40a`
   y que el contexto aprobado sigue anclado a ese SHA. Fusionar desde el
   test harness tras verificaciones y volver a observar el merge exacto.
4. Reconciliar 7.1b y 8.5 con evidencia individual. La tarea 8.4
   **sigue pendiente** hasta que se complete todo el recorrido incremental
   y los checkpoints de mini me corroboren ambas fusiones.

No se modificó el repositorio operativo ni su base de datos y no se activó
el scheduler.

## Observación del merge por el servicio F2

El 2026-10-24, en el runtime F2 aislado y contra PostgreSQL desechable, se
ejecutó `ProjectService.observe_bootstrap_merge` para
`f2-e2e-gacela-20261023e`. La identidad persistida coincidió con el repositorio,
PR, rama, base SHA y head SHA del PR #2; la consulta GitHub confirmó `merged`
con merge SHA `89297274076dd1dd4aa377da9950a69da6c8a40a`. El coordinador
persistió el estado `PREPARED` y `merge_commit_sha` sin invocar ningún agente ni
modificar `main` directamente.

El checkpoint no contiene todavía un `pending_context`, hash de ZIP
incremental ni una concesión incremental identificable. En los artefactos
locales y en el workspace aislado solo está disponible el ZIP Greenfield
`3eed0a…eef12e81`; no se fabricó ni se reutilizó como ZIP incremental. Por
tanto, el segundo dispatch y el PR incremental no se ejecutaron: hacerlo ahora
no tendría paquete y autorización independientes verificables.

## E2E incremental real observado

El 2026-10-24 se registró una concesión incremental única y auditable para el
proyecto `f2-e2e-gacela-20261023e`, repositorio exacto y ZIP SHA-256
`2dc14bf0d2d203c8c44bc33686f5a697d85d252882c07548ddf494becb9bde41`.
La reserva comprobó `PREPARED`, base aprobada
`89297274076dd1dd4aa377da9950a69da6c8a40a`, perfil `codex`, modelo
`gpt-5.6-luna`, esfuerzo `medium`, una invocación y sin fallback. El checkpoint
marcó la concesión como usada al persistir la admisión del agente.

La única invocación incremental real terminó con código 0, duración 91,140 ms
(91.140 s),
uso observado de 312.545 tokens de entrada (286.336 cacheados) y 12.016 de
salida. El candidato incorporó las fuentes originales y las adiciones
`contexto-incremental-e2e.md`,
`diagramas/flujo-incremental-e2e.svg` y
`observacion-contradictoria-e2e.md`; el delta no propuso reemplazos. Las
validaciones de alcance, procedencia, índice, secretos, enlaces y OpenSpec
pasaron antes de publicar.

Se publicó el PR incremental #3:
https://github.com/silverberdi/mini-me-f2-e2e-20261023/pull/3

- base: `89297274076dd1dd4aa377da9950a69da6c8a40a`
- head: `def5c13c6c0abd27c29092e0eefb504d4f988f06`
- merge: `4a3a5b985150dab1bc1018e781a6ca187f15ed0d`

Antes del merge se verificó que `main` seguía en el SHA Greenfield y que el PR
tenía el repositorio, rama, base y head exactos. El PR desechable se fusionó
automáticamente con la GitHub App usando el head como precondición; después
`main` coincidió con el merge SHA, las fuentes incrementales estuvieron
presentes y el servicio F2 observó el merge. El checkpoint eliminó
`pending_context` y promovió `approved_context_sha` a
`4a3a5b985150dab1bc1018e781a6ca187f15ed0d`. No se modificó producción, no se
activó scheduler y no se ejecutó una segunda invocación.

## Correcciones deterministas de continuidad

Durante esta ejecución se corrigieron y probaron cuatro defectos sin repetir
inferencias: el delta incremental recibía un directorio como `str` en lugar de
`Path`; una rama local huérfana exactamente en el SHA base no podía reconciliarse
si el `main` local aún no la contenía; el checkpoint incremental omitía
`base_branch`; y una observación incremental bloqueada por identidad incompleta
no podía reobservar el mismo PR ni restaurar `PREPARED`. También se añadió la
reserva durable de concesión incremental, ligada a proyecto, repositorio, ZIP,
SHA base, agente, modelo, esfuerzo y uso único. Las pruebas focalizadas de
coordinador/configuración pasan **77**, Ruff de los archivos afectados pasa,
OpenSpec strict y `git diff --check` pasan.

La tarea 7.1b sigue pendiente: la continuidad histórica ya está probada en
PostgreSQL desechable y los workspaces/34 bindings se conservaron, pero no se
han configurado en producción perfiles y conexiones F2 verificables. La tarea
8.5 queda pendiente de esa reconciliación histórica; no se marca completa por
inferencia.
