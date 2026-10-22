# Política de agentes, compatibilidad y costo (v1.2)

**Prevalece:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md). Se retira la asignación fija histórica por producto que exigía Codex/Antigravity o DeepSeek para todas las etapas.

## Configuración por proyecto
- **Pensamiento:** modelo y CLI compatibles con propose/update/verify/sync/archive.
- **Ejecutor:** modelo y CLI compatibles con apply y correcciones.
- **Revisor independiente:** proveedor/modelo de solo lectura distinto del autor; obligatorio para propuesta, condicional para código según política sencilla.
- **Respaldo:** compatibilidad verificada con la etapa y autorización de gasto; no autoriza inicio de trabajo nuevo por sí solo.

Esfuerzo por defecto **medio** para propuesta/ejecución/verificación/revisión. **Mínimo compatible** para sync/archive. No router optimizador, clasificación inteligente, upgrade premium por defecto ni roles codificados en condiciones Python para proveedores concretos.

## Ejecución y cuotas
Validar solo lo necesario: instalación/compatibilidad real de CLI o API, skill instalada, acceso/capacidad cuando comprobable, permiso para leer repo y política de costo; si no se puede operar de forma segura, preservar trabajo y esperar o pedir autorización. No son intercambiables capacidades de un CLI coding agent y una API chat-only.

Guardar solo evidencia mínima indispensable de uso y gasto. Una autorización previa de presupuesto aplicable puede cubrir llamadas ordinarias; no volver a pedir permiso en cada llamada ni gastar por encima de un límite configurado.

## Independencia y autoridad
Ningún autor revisa autoritativamente su propio candidato; review read-only. Decisiones de gasto extraordinario, modificación de política, seguridad y merge de código requieren humano. Una revisión de texto no puede afirmar que se ejecutó una skill OpenSpec real.

## Legado
Los expedientes de capacidad, fallback y políticas históricas quedan como material de inspección/migración; no extender mecanismos antiguos por inercia. Retener salvaguardas esenciales, no burocracia duplicada.