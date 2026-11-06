## Context

See `proposal.md` for the observed problem. `frontend/src/main.ts` already registers `ngsw-worker.js`; `ngsw-config.json` precaches the public shell only. `AppComponent` is the root shell and `VersionService` already displays build metadata. The affected requirement is `pwa-responsive-and-offline-pwa`.

## Goals / Non-Goals

**Goals:** Surface a real Angular service-worker update once its new shell is ready, and let the operator load it from the current PWA shell.

**Non-Goals:** Change caching, backend/API behavior, deployment, build metadata, or add a second update polling mechanism.

## Decisions

- Subscribe to Angular `SwUpdate.versionUpdates` and show the notice only for the `VERSION_READY` event. This uses the service worker already registered by the application. Do not compare `version.json` or poll a parallel endpoint; those mechanisms are unnecessary for this issue.
- Render the Spanish notice in the root application shell with an accessible status announcement and a single «Recargar» action. Do not reload automatically: the operator may be entering a human-gate response or other information, and the Issue explicitly accepts an update notice as an alternative to an automatic reload.
- On the action, activate the ready version through Angular's service-worker API and reload the page after activation succeeds. If updates are disabled or no ready event arrives, keep the notice hidden and leave the existing app usable.
- Keep the existing shell-only cache policy intact. No authenticated data is added to the service worker.

## Risks / Trade-offs

- [The browser or service worker may not support updates in a development/unsupported context] → Gate the notice on Angular's actual enabled state and a ready-version event; do not claim an update is available otherwise.
- [The operator may postpone loading the update] → Keep the notice visible until the page reloads; the new shell is loaded through the explicit action.
