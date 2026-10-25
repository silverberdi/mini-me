# F4 — preflight de facturación incremental

Referencia: Issue #172, comentario `6392630816`.

## Comprobaciones bajo `minime`

- Antigravity CLI 1.1.25 está autenticado y expone `gemini-3.8-flash-medium` con esfuerzo `medium`.
- La configuración efectiva `~/.gemini/antigravity-cli/settings.json` existe, pero `useG1Credits` está ausente. Por tanto no se puede demostrar que el uso de créditos G1 esté desactivado cuando termine la cuota incluida.
- Codex 0.159.0 está autenticado mediante ChatGPT; `account/read` identifica autenticación OpenAI/ChatGPT y `account/rateLimits/read` observa `planType=plus`, `ordinaryUsageAllowed=true`, `hasCredits=false`.
- `~/.codex/auth.json` contiene `OPENAI_API_KEY` con valor nulo; no se expuso ningún secreto. No se observaron variables de entorno de OpenAI, OpenRouter, Antigravity, créditos, facturación, pagos, overage o recarga automática.
- La configuración de mini me mantiene fallback y OpenRouter desactivados. Los perfiles del recorrido siguen fijados a Codex `gpt-5.6-luna/medium` y Antigravity `gemini-3.8-flash-medium/medium`.

## Decisión fail-closed

No se acredita `ZERO_INCREMENTAL_BILLING`:

1. Falta la evidencia efectiva `useG1Credits=false` para Antigravity.
2. El CLI/App Server de Codex no expone una observación verificable de que la recarga automática o créditos adicionales estén desactivados.

La capacidad disponible y `hasCredits=false` no demuestran por sí solas ausencia de facturación futura. El E2E no se ejecutó: invocaciones `0`, consumo `0`, costo observado `USD 0,00`, sin mutaciones remotas, PR ni cambios productivos.

## Estado

`WAITING_BUDGET`. El control concreto faltante es una señal oficial y observable de exclusión de créditos/cargos adicionales para ambos proveedores: `useG1Credits=false` efectivo en Antigravity y estado de recarga automática/overage desactivado verificable para la cuenta ChatGPT de Codex. No se modificaron credenciales ni configuración productiva.
