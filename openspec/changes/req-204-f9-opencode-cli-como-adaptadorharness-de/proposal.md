# Proposal

## Why

F9 define una integración futura para que mini me pueda invocar OpenCode como CLI desacoplado y reutilizar la capacidad de ejecución interactiva de modelos conectados por API, sin construir otro runner, shell o implementación paralela de OpenSpec dentro del núcleo. La capacidad cuenta con la autorización explícita del operador para su implementación en el proyecto mini-me bajo confinamiento en worktree aislado, permaneciendo disabled por defecto en configuración.

## What Changes

- Introducir el contrato de un adaptador CLI de OpenCode invocable por mini me en el worktree administrado del proyecto.
- Permitir que el adaptador exponga lectura/edición de archivos y ejecución de bash, linters y tests mediante las capacidades nativas de OpenCode, preservando los límites del worktree y del repositorio.
- Permitir su uso futuro para roles configurables `execution` e `independent_review`, sin conferir al adaptador autoridad de merge, cierre, aprobación o lifecycle.
- Mantener compatibilidad con los workflows oficiales de OpenSpec (`explore`, `propose`, `apply` y `verify`) sin reimplementarlos.
- Registrar invocación, resultado, artefactos y evidencias bajo una identidad de candidato/SHA inmutable.
- Aplicar fail-closed ante cuota, timeout, error de OpenRouter u otro fallo del proveedor, delegando la decisión a la política de proveedores existente.
- Implementar OpenCodeAdapter con autorización explícita del operador confirmada para el Issue #204, manteniendo deshabilitada por defecto la capacidad para otros proyectos.
- No crear cola paralela, scheduler, shell, runner, generador de artefactos OpenSpec ni motor de revisión alternativo.

## Capabilities

### New Capabilities

- `opencode-cli-adapter`: contrato para invocar OpenCode como harness CLI desacoplado, aislado al worktree, compatible con OpenSpec, roles configurables, evidencia inmutable y fallos fail-closed.

### Modified Capabilities

- Ninguna. Los contratos existentes de configuración de proyectos, worktrees, proveedores, OpenSpec, revisión, evidencia y cierre permanecen como autoridades que el nuevo adaptador deberá respetar.

## Impact

- Afectará, cuando F9 sea autorizada, la configuración de capacidades CLI/proveedor por proyecto y el despacho de agentes de ejecución y revisión.
- Deberá integrarse con los contratos existentes de binding de repositorio/worktree, identidad de candidato, evidencia, continuidad de OpenSpec y política de proveedores; no sustituirá esas autoridades.
- Requerirá verificar la disponibilidad real de OpenCode y de los modelos API en el host, sin asumir que un proveedor o credencial existe.
- No modifica actualmente código de aplicación, base de datos, scheduler, despliegues, tickets remotos ni cuotas. La implementación queda fuera de este workflow de planificación y bloqueada mientras F9 conserve `disabled`.
