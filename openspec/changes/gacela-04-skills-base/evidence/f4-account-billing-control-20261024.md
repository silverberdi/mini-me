# F4 — control de facturación de cuenta

Referencia: Issue #172, comentario `6392692300`.

## Resultado

- Antigravity bajo `minime` usa `~/.gemini/antigravity-cli/settings.json`. La clave `useG1Credits` está omitida. Según la semántica oficial del CLI, la configuración persiste solo valores distintos del predeterminado; el valor efectivo omitido es `false`. No se observó un override efectivo `true`.
- Codex bajo `minime` conserva autenticación ChatGPT Plus, `OPENAI_API_KEY` nulo, `hasCredits=false` y `ordinaryUsageAllowed=true`. `codex login status` confirma la sesión ChatGPT.
- Codex CLI/App Server no expone el estado de `Automatic reload`. Esa comprobación pertenece a `ChatGPT > Settings > Usage` o `Codex app > Usage & Billing`, y no existe una observación equivalente disponible desde la identidad de servicio en este entorno.

## Decisión

`WAITING_ACCOUNT_BILLING_CONTROL`. Antigravity está acreditado; falta únicamente confirmar en la cuenta ChatGPT de `minime` que `Automatic reload` esté desactivado y que no exista otra vía de pago adicional.

No se ejecutó E2E ni se consumió cuota. Invocaciones reales: `0`; costo observado: `USD 0,00`; sin mutaciones remotas, PR ni cambios productivos.
