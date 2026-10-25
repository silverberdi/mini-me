# F4 — preflight Ubuntu bajo `minime`

Fecha: 2026-10-25

## Controles que pasan

- SSH verificado a `silverman@192.168.0.194`; Ubuntu 26.04 LTS.
- Delegación administrativa acotada a `minime` comprobada (`uid=994`, grupo Docker), sin credenciales nuevas.
- Servicio `minime-api` activo; el proceso ejecuta `/opt/minime/runtime/venv` y no se reinició.
- Checkout aislado creado en `/var/lib/minime/f4-e2e-checkout.z5CVDG`, bajo `minime`, en SHA `856e3996347a0ae967b97589cf28a53191f84b42`. `/opt/minime/app` no fue modificado.
- La GitHub App, verificada mediante el adapter F4 bajo `minime`, devuelve `contents=write` y `pull_requests=write` para `silverberdi/mini-me-r01-e2e-20261014` y `silverberdi/mini-me-f2-e2e-20261023`.
- El repositorio desechable `silverberdi/mini-me-f2-e2e-20261023` existe; `main` se observó en `4a3a5b985150dab1bc1018e781a6ca187f15ed0d` y no tiene Issues abiertos. No se creó ni modificó un Issue.
- PostgreSQL responde en el contenedor existente `local-ai-stack-postgres-1`; la base `minime_f3_e2e_20261024` es accesible en modo lectura con el usuario de servicio. No se creó base ni se escribieron datos.
- Codex bajo `minime`: `gpt-5.6-luna` y esfuerzo `medium` observados; `account/rateLimits/read` informó `ordinary_usage_allowed=true`.
- Antigravity bajo `minime`: `gemini-3.8-flash-medium` observado mediante `agy models`.
- Fallback y OpenRouter están desactivados; scheduler no se inició.

## Bloqueo antes de inferencia

La autorización del Issue #172 permite un único recorrido con techo agregado de USD 1,00. El camino Greenfield actual (`GreenfieldBootstrapCoordinator._run_thinking_agent`) persiste un intento y registra uso observado/desconocido después de lanzar el proceso, pero no consulta `BudgetService`, no crea una reserva F4 ni aplica un límite agregado antes de la invocación. El runtime no puede demostrar que hará cumplir USD 1,00.

La configuración OpenSpec de servicio también declara `delivery=skills` y no incluye Verify/Continue en su lista de workflows. El checkout candidato contiene las skills oficiales, pero no se afirma que la configuración global incompleta sea una instalación oficial completa.

Por fail-closed, el E2E no se ejecutó: consumo `0`, costo `USD 0,00`, sin repositorio/Issue mutados, sin PR y sin cambios de producción.

## Acción necesaria

Habilitar en el runtime aislado un mecanismo verificable que reserve y haga cumplir el techo agregado de USD 1,00 para el recorrido Greenfield, y una configuración OpenSpec aislada con las capacidades oficiales requeridas. No se requieren nuevas credenciales ni un nuevo Change; después podrá reanudarse el mismo checkout sin reintentos pagados.
