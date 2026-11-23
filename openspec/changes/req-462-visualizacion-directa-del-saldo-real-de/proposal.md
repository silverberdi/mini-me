# Proposal

## Why

La telemetría de producción ya entrega para DeepSeek un saldo monetario observado, pero el Dashboard lo interpreta como porcentaje y deja `$20.18 USD` únicamente en un tooltip. Esto oculta el dato operativo principal y muestra `—` cuando `remaining_percent` es nulo, aunque exista un balance válido.

## What Changes

- Modificar la tarjeta de capacidad de DeepSeek para presentar directamente un balance numérico observado junto con su moneda cuando `balance` es finito y está disponible.
- Permitir que el velocímetro analógico represente un valor principal no porcentual sin convertirlo en una aguja basada en un límite inventado; para saldo monetario no se mostrará `%` ni se calculará un porcentaje.
- Mantener la representación actual de porcentajes para proveedores que sí entregan `remaining_percent` y conservar el estado desconocido cuando no existe ningún valor verificable.
- Hacer que el saldo disponible sea visible en la tarjeta, sin depender de hover, y conservar metadatos de fuente/observación como información secundaria.
- No modificar el endpoint `/api/v1/providers/quotas`, su frecuencia de sondeo, el contrato de telemetría, ni reintroducir topes diarios artificiales.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `pwa-capacity-cards-and-reactive-state`: la tarjeta de capacidad debe soportar una representación visible de balance monetario observado, además de porcentajes verificados, sin inventar denominadores ni valores.

## Impact

- `frontend/src/app/features/dashboard/dashboard.component.ts`: selección y formato del valor/unidad de DeepSeek.
- `frontend/src/app/shared/analog-gauge.component.ts`: presentación de un valor textual monetario y tratamiento visual sin escala ficticia, reutilizando el componente existente.
- `frontend/src/app/core/models.ts`: se reutiliza el contrato existente `balance`/`currency`; no se prevé cambio de API.
- Pruebas frontend unitarias y E2E Playwright: el ejecutor configurado debe verificar en navegador real la tarjeta con saldo, su ausencia de `—`/`%`, y el estado sin saldo; no se delegan navegación, viewport ni asincronía al operador.
