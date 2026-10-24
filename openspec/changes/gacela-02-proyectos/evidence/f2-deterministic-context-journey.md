# F2 — recorrido determinista del organizador documental

Fecha: 2026-10-24. Este recorrido no invoca Codex, Antigravity ni ningún
proveedor externo.

Prueba reproducible:

```text
tests/test_project_context_catalog.py::test_deterministic_greenfield_and_incremental_documentary_journeys
```

La prueba usa `ContextArchiveExtractor`, `OpenSpecAdapter` oficial, un agente
simulado que escribe documentos sustentados por las fuentes y un adaptador de
push/PR sobre un remoto Git local desechable.

Evidencia comprobada:

- ZIP válido → extracción privada → hash de revisión y originales en
  `context/incoming/<sha>/`.
- Instalación oficial OpenSpec para Codex, incluidos todos los artefactos que
  realmente crea la versión instalada; el marcador oficial
  `.agents/skills/.openspec-target` está permitido por el scope guard.
- El agente simulado llena rutas del catálogo fijo, añade `context/INDEX.md`,
  conserva `AGENTS.md`/`openspec/config.yaml` y deja el roadmap como contexto
  documental, sin backlog operativo.
- Validación de procedencia, índice, enlaces, secretos y scope antes de
  commit; commit y push de una rama bootstrap, con PR registrado por el
  adaptador de prueba.
- `main` conserva su SHA base hasta la fusión simulada del primer PR.
- ZIP incremental → nueva revisión `context/incoming/<sha>/`, nueva rama y
  segundo PR; el contexto aprobado y `main` conservan el SHA fusionado durante
  la preparación del segundo candidato.
- La validación usa únicamente estructura y procedencia; no evalúa calidad
  semántica ni resuelve contradicciones.

Resultados de verificación del HEAD publicado después de esta prueba:

- Focalizadas catálogo/Greenfield/OpenSpec: `38 passed`.
- Regresión completa: `745 passed, 13 skipped, 2 warnings`.
- Ruff de archivos afectados: PASS.
- OpenSpec strict para `gacela-02-proyectos`: PASS.
- `git diff --check`: PASS.

Esta evidencia local no sustituye el E2E real pendiente: no crea repositorios
GitHub, no consume cuota, no observa merges humanos y no completa las tareas
4.4, 7.1b, 8.4 ni 8.5.
