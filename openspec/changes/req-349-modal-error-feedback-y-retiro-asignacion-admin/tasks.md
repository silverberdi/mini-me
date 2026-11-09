## 1. Feedback de error en modales de proyectos

- [x] 1.1 Incorporar bloque de alerta de error visible directamente dentro de los modales de «Registrar Nuevo Proyecto» y «Editar Proyecto» en `frontend/src/app/features/proyectos/proyectos.component.ts`.
- [x] 1.2 Asegurar que el modal conserve su estado y campos introducidos ante errores de validación o rechazo del servidor.

## 2. Aislamiento y canonicidad completa de perfiles en frontend

- [x] 2.1 Modificar `buildProfile` en `frontend/src/app/features/proyectos/proyectos.component.ts` para que la creación de un nuevo proyecto no herede perfiles del proyecto activo.
- [x] 2.2 Garantizar que los 4 roles (`thinking`, `execution`, `independent_review`, `fallback`) generen siempre `provider_id` y `harness_id` canónicos con la variante resuelta `model_id: targetModelId`.
- [x] 2.3 Exigir que en edición de proyectos solo se reutilicen perfiles existentes si ya cuentan con `provider_id` y `harness_id` canónicos definidos.

## 3. Reconciliación de validación en backend

- [x] 3.1 Ajustar `_validate_live_canonical_profiles` en `src/minime/api/app.py` para consultar `CanonicalProfileResolver` exclusivamente sobre modelos pertenecientes a proveedores/harnesses registrados en `provider_model_registry`, delegando los harnesses locales (`codex`, `antigravity`) a la verificación exhaustiva de `ProjectCatalogService.validate_project_profiles`.

## 4. Retiro de sección de asignación en administración

- [x] 4.1 Eliminar la sección HTML «Asignación por proyecto» en `frontend/src/app/features/admin-models/admin-models.component.ts`.
- [x] 4.2 Retirar los métodos, estados y propiedades muertas en `AdminModelsComponent` (`selectProject`, `saveRoleAssignments`, `modelsForRole`, `roleProviders`, etc.).

## 5. Verificación y pruebas deterministas

- [x] 5.1 Actualizar y ejecutar la suite unitaria de frontend (`npm --prefix frontend test`).
- [x] 5.2 Ejecutar las pruebas de backend (`pytest`) para validar la admisión de proyectos con perfiles mixtos de harnesses.
- [x] 5.3 Probar con Playwright E2E que los modales muestran errores inline y que la administración ya no presenta la sección eliminada.
