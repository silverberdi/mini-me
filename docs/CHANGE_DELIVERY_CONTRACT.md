# Contrato de entrega por Change — mini me

**Prevalece:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0. Un Issue corresponde a un Change OpenSpec de alcance cohesivo. No se subdivide en micro-Changes ni se agrupan cambios independientes. El operador autoriza cada cambio.

## Antes de proponer

- Leer el contrato rector, el Issue autorizado, `AGENTS.md`, `openspec/config.yaml` y el código/documentación/DB pertinentes.
- Censar componentes, consumidores, escritores, capacidades instaladas y evidencia existente; elegir qué reutilizar, cambiar o retirar.
- Mantener alcance y criterios verificables ligados al Issue. No inventar decisiones ni extender el trabajo a mejoras colaterales.
- Usar OpenSpec nativo para proposal, update, continue, apply, verify, sync y archive.
- La revisión independiente de propuesta y código corresponde únicamente a cambios de complejidad alta; debe ser read-only, distinta del autor y ligada al SHA revisado.

## Apply, verify y entrega

- El ejecutor debe tener Verify nativo disponible; si no, detenerse fail-closed.
- Ejecutar pruebas proporcionadas al riesgo y E2E auténticos cuando se afirme una integración real. Los mocks y health checks no prueban por sí solos el resultado.
- Recuperar Apply sobre el mismo candidato con contexto correctivo basado en Git/pruebas observados; detenerse ante regresión o identidad ambigua.
- Vincular diff, pruebas, workflow, revisión y autorización al SHA exacto. No afirmar cierre si falta evidencia observable.
- Tras el merge de implementación, usar rama fresca desde `main` para sync/archive nativos; crear el PR documental y cerrar el Issue solo tras comprobar el merge documental.

## Persistencia y retiro

- PostgreSQL es para configuración y estado indispensable de continuidad, idempotencia, decisiones y gasto; no replica la cartera de tickets.
- Para cambios de persistencia, usar Alembic y preservar datos/historial; no retirar tablas ni escritores sin censo de consumidores y evidencia.
- No agregar estados, servicios, tablas, motores o dependencias sin necesidad vigente demostrable.

## Operación

Activar administrativamente un proyecto no autoriza por sí mismo la admisión de trabajo, el uso de agentes, el scheduler ni despliegues. mini me no administra despliegues productivos; pertenecen al CI/CD del proyecto. Los nombres F1–F8 se mantienen como historia de entrega y no definen el flujo operativo actual.
