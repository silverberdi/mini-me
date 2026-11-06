# F5 — excepción de mantenimiento: integridad de resultados de agentes

> **Registro histórico:** este diseño offline documenta una propuesta de mantenimiento asociada a F5 bajo el contrato v1.3. El programa F1–F8 fue sustituido como modelo operativo por el contrato rector v2.0; este expediente no es un Change autorizado ni concede autorización para integrar, ejecutar, desplegar o reanudar el Run F5. Preservar los artefactos/evidencias sin tratarlos como instrucciones vigentes. Cualquier trabajo derivado requiere un Issue y Change OpenSpec actuales con autorización del operador.

## Autoridad y límites

Este directorio contiene una **copia inalterada de los artefactos OpenSpec aprobados** de la reparación transversal F5. El Change `f5-agent-result-integrity-design` es una **envoltura de validación documental aislada**, NO un Change operativo adicional. Estas restricciones y la secuencia de trabajo que sigue registran el gobierno vigente cuando se redactó el borrador; no autorizan operaciones actuales.

- Autoridad al momento del borrador: contrato rector v1.3 y Change F5 `gacela-05-ui-self-hosted`.
- Run original, Issue #173, rama y worktree de autoejecución: identificadores preservados como evidencia histórica.
- Este expediente no concede autorización para merge, despliegue, modelos, reanudación ni cambios en el árbol F5.

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

## Secuencia de gobierno registrada en el borrador (histórica, no operativa)

1. Validar estrictamente el contrato y revisar código, consumidores y pruebas.
2. Ejecutar regresiones y E2E offline en entorno aislado; documentar límites y riesgos.
3. Dejar PR listo solo con resultados verificables; solicitar merge explícito.
4. No desplegar ni reanudar F5 sin autorizaciones nuevas, separadas y registradas.
