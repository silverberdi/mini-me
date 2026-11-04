## Why

El Issue #269 autoriza exponer en el Backlog Angular operaciones que el backend ya implementa. La vista ya llama a los endpoints existentes para desactivar y reactivar Requests, pero compara su estado con `PAUSED`; la API clasifica el label remoto como `DISABLED`. Por eso el control de reactivación no aparece para un Request desactivado y la vista no representa claramente su estado lógico.

## What Changes

- Ajustar el Backlog para ofrecer Desactivar a Requests no iniciados activos y Reactivar a Requests desactivados, usando únicamente los endpoints existentes.
- Representar el estado lógico activo/desactivado y el motivo solo cuando el payload autoritativo disponible lo incluya.
- Refrescar la vista desde la fuente existente tras la operación para reflejar el estado remoto y su efecto en la admisión FIFO.

## Capabilities

### New Capabilities

Ninguna.

### Modified Capabilities

- `f5-projects-and-backlog`: habilita en el Backlog los controles de desactivación/reactivación ya respaldados por el backend y define su representación del estado remoto.

## Impact

Afecta la vista Angular `frontend/src/app/features/backlog/`, sus modelos/servicio de lectura solo si el payload existente lo requiere, y pruebas focalizadas de UI/API ya existentes. Reutiliza `POST .../deactivate`, `POST .../reactivate` y el listado actual de Requests. No cambia backend, endpoints, otras vistas ni operaciones.
