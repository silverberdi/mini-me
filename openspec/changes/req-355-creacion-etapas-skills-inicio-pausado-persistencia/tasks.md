## 1. Backend: Preflight de Conectividad GitHub y Creación Atómica en 4 Etapas

- [x] 1.1 Implementar `validate_repository_grants` en `GitHubAdapter` para verificar permisos sobre el repositorio (`issues`, `contents`, `pull_requests`) fallando closed con error descriptivo si la GitHub App no tiene acceso
- [x] 1.2 Extender `ProjectService.create_configured_project` para ejecutar la validación de grants y forzar el estado inicial obligatorio `PAUSED` con `effective_pause: true`
- [x] 1.3 Implementar la inicialización del clon gestionado base en `/opt/minime/repos/<project_id>`, archivo marcador `.minime-managed-project.json` y persistencia de `ProjectManagedRepositoryBinding`
- [x] 1.4 Aprovisionar en el repositorio gestionado las skills y workflows canónicos requeridos por los modelos configurados (`minime-request-normalizer`, `minime-pr-preparer`, `openspec-*`, `opsx-*`)
- [x] 1.5 Ejecutar preflight de readiness que verifique que los archivos de workflow asignados existan y sean legibles antes de confirmar la creación del proyecto

## 2. Frontend: Stepper de Creación en UI y Persistencia de Selección de Proyecto

- [x] 2.1 Persistir `selectedProjectId` en `localStorage` en `RefreshService` para que la elección manual del operador nunca se resetee automáticamente a `mini-me`
- [x] 2.2 Diseñar e implementar el stepper visual de 4 etapas en el modal de `proyectos.component.ts` (Conexión, Repositorio, Skills, Verificación)
- [x] 2.3 Mostrar errores específicos de grants de GitHub en el modal con orientación clara de autorización hacia la configuración de GitHub

## 3. Pruebas Unitarias y Verificación Playwright E2E

- [x] 3.1 Agregar pruebas unitarias en backend para la validación de grants, aprovisionamiento de skills y estado inicial `PAUSED`
- [x] 3.2 Actualizar y agregar pruebas unitarias de frontend para el stepper de creación y persistencia en `localStorage`
- [x] 3.3 Ejecutar suite de pruebas completa (`pytest`, `npm test`, `playwright`) asegurando 100% verde
