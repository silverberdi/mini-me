# F5 — excepción de mantenimiento: integridad de resultados de agentes

## Autoridad y límites

Este directorio contiene una **copia inalterada de los artefactos OpenSpec aprobados** de la reparación transversal F5. El Change `f5-agent-result-integrity-design` es una **envoltura de validación documental aislada**, NO un Change operativo adicional. `gacela-05-ui-self-hosted` sigue siendo el único Change ejecutable de F5.

- Contrato rector vigente: `docs/CONTRATO_RECTOR.md` v1.3.
- Run original, Issue #173, rama y worktree de autoejecución: intocables.
- Ninguna autorización implícita para merge, despliegue, modelos o reanudación.
- No modificar `openspec/changes/gacela-05-ui-self-hosted` antes de la reentrada nativa autorizada.

## Validación formal del borrador (solo en checkout desechable)

Desde un clon **desechable** de la rama de este PR:

```bash
cp -a docs/maintenance/f5-agent-result-integrity/openspec/changes/f5-agent-result-integrity-design \
  openspec/changes/f5-agent-result-integrity-design
openspec validate f5-agent-result-integrity-design --strict --type change
```

El resultado válido debe ser exit code 0, stdout de cambio válido, stderr vacío.
Eliminar únicamente el checkout desechable al finalizar, nunca el worktree del Run F5.

La misma validación OpenSpec 1.9.0 se ejecutó antes de programar y dio PASS; cualquier revisión de las specs debe repetirla. Los tests, lint y E2E del **código de este PR** todavía requieren evidencia separada; no se declaran PASS por el éxito documental.

## Secuencia de gobierno

1. Validar estrictamente el contrato y revisar código, consumidores y pruebas.
2. Ejecutar regresiones y E2E offline en entorno aislado; documentar límites y riesgos.
3. Dejar PR listo solo con resultados verificables; solicitar merge explícito.
4. No desplegar ni reanudar F5 sin autorizaciones nuevas, separadas y registradas.
