# Previews y validación humana

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md) v2.0. mini me no administra despliegues productivos; corresponden al CI/CD del proyecto.

## Validación humana

La validación humana aplica al comportamiento de UI cuando el Change la requiera. Los artefactos OpenSpec deben definir la superficie, escenarios, precondiciones, pasos de usuario y resultados visibles. El resultado se liga al repositorio, base y SHA del candidato; si el candidato cambia, la validación anterior puede quedar obsoleta.

## Preview

Un Change de UI puede usar un preview temporal cuando aporte evidencia útil. El proyecto define su mecanismo seguro de build/ejecución; mini me solo lo coordina si está autorizado para ese proyecto. El preflight debe impedir el uso accidental de bases de producción o datos reales. La URL de preview no es evidencia suficiente: validar el comportamiento funcional del candidato.

## Ciclo recomendado para cambios de UI

1. Construir el candidato desde el SHA identificado.
2. Ejecutar Verify nativo, checks pertinentes y E2E funcional aplicable.
3. Publicar el candidato/PR bajo las reglas Git y obtener validación humana para los escenarios UX requeridos.
4. Si se usa preview, comprobar identidad de candidato e imagen inmutable cuando aplique; repetir la validación si cambia la identidad.
5. Registrar resultado, hallazgos y decisión humana junto al candidato.

La autorización y merge de implementación siguen la política del contrato según complejidad. Las operaciones OpenSpec sync/archive y cierre del Issue continúan por el flujo de entrega.

## Producción

El despliegue y rollback productivos pertenecen al CI/CD y a las políticas operativas del proyecto. No son gates universales de Done de mini me. Si el Issue requiere verificar un comportamiento productivo, esa evidencia se define dentro del alcance y se obtiene por el mecanismo autorizado del proyecto; no se presume que mini me despliegue ni ejecute postdeploy.
