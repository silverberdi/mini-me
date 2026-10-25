# F4 — intento Greenfield autorizado

Fecha: 2026-10-24

## Preflight y entrada

- Proyecto aislado: `f4-e2e-gacela-20261024`.
- Repositorio: `silverberdi/mini-me-f2-e2e-20261023`.
- ZIP: `console-sorter-context.zip`, SHA-256 `3eed0aacf1f3cbe4361805b914d4fe659dbca69266f55279cdc55c10eef12e81`.
- Ejecución bajo `minime`, checkout F4 aislado y base `minime_f3_e2e_20261024`.
- Perfiles Codex/Antigravity, GitHub App, OpenSpec aislado, cuota incluida y controles económicos ya validados antes del despacho.

## Resultado

El bootstrap validó identidad y permisos GitHub, estableció el proyecto y creó el worktree aislado. Antes de cualquier invocación de agente, la instalación oficial OpenSpec detectó un conflicto material: `main` ya contiene integraciones `.agents/skills/openspec-*` heredadas de recorridos F2, incompatibles con el conjunto oficial que resolvería el checkout F4 (`delivery=both`, Continue y Verify incluidos).

La implementación conserva esos archivos y falla cerrado con `RuntimeError` para no sobrescribir contenido existente no autorizado. El proyecto quedó en `BLOCKED` con el ZIP y su procedencia persistidos.

Comprobaciones posteriores de solo lectura:

- No existe rama bootstrap ni PR para `minime/bootstrap/f4-e2e-gacela-20261024-3eed0aacf1f3`.
- No existe candidato ni `thinking_agent_attempt` en el checkpoint.
- No se ejecutó Codex ni Antigravity: invocaciones `0`, consumo `0`, costo observado `USD 0,00`.
- No se modificó `main`, producción, Brownfield, PostgreSQL operativo ni scheduler.

## Bloqueo exacto

El único recorrido autorizado no puede continuar con este repositorio porque su `main` contiene integraciones OpenSpec previas que la instalación F4 no puede sustituir silenciosamente. Resolverlo requiere una decisión explícita sobre el destino de esos archivos (preservar la historia y preparar una base Greenfield limpia, o autorizar su reemplazo en el repositorio E2E). No se borró ni modificó historia remota.
