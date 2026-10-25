# F4 — control económico y OpenSpec aislado

Fecha: 2026-10-24

## Observaciones de solo lectura

- La comprobación se ejecutó en Ubuntu bajo la identidad de servicio `minime`.
- Codex 0.159.0 confirmó autenticación ChatGPT, modelo `gpt-5.6-luna`, esfuerzo `medium`, `ordinaryUsageAllowed=true` y `planType=plus` en `account/rateLimits/read`.
- La respuesta de Codex no mostró créditos adicionales disponibles (`hasCredits=false`) ni una garantía contractual de ausencia de cargos fuera de cuota.
- Antigravity 1.1.25 confirmó `gemini-3.8-flash-medium` y la variante de esfuerzo `medium` mediante `agy models`. El CLI no expone, mediante sus comandos de lectura disponibles, un estado de facturación, overage o límite monetario aplicable al recorrido.
- La configuración del servicio mantiene fallback desactivado y OpenRouter desactivado; no se modificó.

## OpenSpec oficial en aislamiento

Se creó un directorio temporal bajo `/var/lib/minime` y un `XDG_CONFIG_HOME` temporal, ambos propiedad de `minime`. No se modificaron `HOME`, autenticación, configuración global del servicio ni `/opt/minime/app`.

Con OpenSpec 1.13.1 se ejecutaron únicamente comandos oficiales:

1. `openspec init --tools codex,antigravity --no-animation <directorio aislado>`.
2. `openspec config set profile custom`.
3. `openspec config set delivery both`.
4. `openspec config set workflows [propose,explore,continue,apply,update,sync,archive,verify]`.
5. `openspec update --force <directorio aislado>`.

La configuración aislada quedó resuelta con `profile=custom`, `delivery=both` y los ocho workflows indicados. El inicializador y la actualización generaron los artefactos oficiales en `.agents/skills` y `.agents/workflows`, incluidos `openspec-continue-change` y `opsx-continue`, además de `openspec-verify-change` y `opsx-verify`. No se fabricaron archivos equivalentes.

## Resultado fail-closed

OpenSpec aislado: **PASS**.

Control económico: **UNKNOWN/BLOCKED**. No puede demostrarse que el único recorrido tenga gasto facturable máximo USD 0, ni existe en el camino Greenfield una reserva previa que haga cumplir el techo agregado autorizado de USD 1,00. La capacidad de cuota observada no equivale a una garantía de facturación.

Por esta razón no se ejecutó Codex, Antigravity ni ningún otro agente de inferencia: invocaciones `0`, consumo `0`, costo observado `USD 0,00`, sin cambios remotos, sin PR y sin alteraciones productivas.

## Dependencia concreta

Para reanudar el mismo recorrido hacen falta ambas garantías verificables: (a) una señal de facturación/overage de los proveedores o una política prepagada que limite el gasto a `USD 0`, y (b) una reserva previa del techo `USD 1,00` aplicada al camino Greenfield, con reconciliación posterior. No requiere otro Change ni nuevas credenciales.
