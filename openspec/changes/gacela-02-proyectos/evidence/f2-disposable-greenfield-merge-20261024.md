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
