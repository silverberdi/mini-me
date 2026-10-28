# Gate de validación y límites de autorización

## Estado del borrador

- Únicamente artefactos OpenSpec y documentos explicativos **locales**, no publicados ni aplicados a la rama principal, al Run o a un Change ejecutable.
- La presente carpeta tiene nombre temporal `f5-agent-result-integrity-design` para poder pasar el validador de OpenSpec **en un repositorio desechable**. NO es una séptima fase ni un micro-Change autorizado; el operador decidirá la incorporación definitiva al único Change F5 o una excepción de mantenimiento formal.
- **No ejecutar `openspec apply`, modelos, migraciones, despliegue, scheduler, PR/merge o edición de PostgreSQL** al validar el diseño.

## Procedimiento de validación *sin código* en Ubuntu

1. Preparar un checkout aislado del commit de referencia `fdc97430741697ab9ca4e3485330386eea5cd1c2`, sin afectar `/opt/minime/app`, el worktree activo ni repositorios administrados.
2. Copiar **solo** `openspec/changes/f5-agent-result-integrity-design/` de este paquete al checkout aislado; no registrar un Change ejecutable en producción ni modificar el Issue #173.
3. Usar CLI OpenSpec 1.9.0 (versión verificada). Ejecutar:

```bash
openspec validate f5-agent-result-integrity-design --strict --type change
```

4. Registrar stdout, stderr, exit code, versión CLI y hashes de artefactos. Si el CLI rechaza el formato o el contenido, modificar **solo** los artefactos de especificación del borrador, no código. No afirmar PASS hasta exit code real 0.
5. Leer las reglas vigentes de un solo Change F5, validar coherencia con specs canónicas y presentar el paquete para aprobación de implementación. El resultado de esta validación no autoriza tocar código o iniciar otro Run.

## Comprobación limitada efectuada al crear el borrador

Solo se efectúan revisiones sintácticas **no equivalentes a OpenSpec CLI strict**: se comprueba que haya `proposal.md`, `design.md`, `tasks.md`, delta specs con requisitos y escenarios Gherkin, y paths UTF-8; no se consulta la infraestructura Ubuntu. La herramienta oficial CLI no está instalada en este contenedor y el registro npm no es accesible. **OpenSpec strict: PENDIENTE**.

## Sucesión de gates futuros y separados

1. Diseño y spec en discusión → revisión humana.
2. Strict PASS del borrador → decisión de ubicación canónica/autorización de implementación.
3. Implementación de código por método autorizado → tests, E2E, strict PASS del Change canónico.
4. Revisión técnica de PR → permiso de merge.
5. Despliegue gobernado → permiso de reanudación y consumo de modelos.
6. Continuación del mismo Run F5 → PR1/PR2 y cierre real del Issue.
