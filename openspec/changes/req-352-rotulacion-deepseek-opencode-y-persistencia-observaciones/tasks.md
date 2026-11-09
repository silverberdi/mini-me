## 1. Rotulación explícita en Frontend

- [x] 1.1 En `frontend/src/app/features/proyectos/proyectos.component.ts`, actualizar `formatModelEntry` para que `isDirectDeepseek` devuelva `group: 'DeepSeek — API directa (vía OpenCode)'` y `label: DeepSeek — ${cleanName || 'V4 Pro'} (API directa vía OpenCode)`.
- [x] 1.2 Actualizar las descripciones en `getRoleModel` para reflejar la rotulación canónica.

## 2. Eliminación de expiración de observaciones en Backend

- [x] 2.1 En `src/minime/services/provider_registry.py`, modificar `CanonicalProfileResolver` para aceptar `freshness: timedelta | None = None` y omitir la verificación de caducidad cuando sea `None`.
- [x] 2.2 En `src/minime/api/app.py`, asegurar que `_validate_live_canonical_profiles` invoque el resolver con `freshness=None`.

## 3. Pruebas y Verificación

- [x] 3.1 Actualizar y ejecutar las pruebas unitarias de frontend (`npm --prefix frontend test`).
- [x] 3.2 Ejecutar las pruebas de backend (`pytest tests/test_provider_model_registry.py`).
- [x] 3.3 Compilar frontend (`npm --prefix frontend run build`) y validar Playwright E2E.
- [x] 3.4 Verificar en vivo contra producción con Playwright tras el despliegue de PR2.
