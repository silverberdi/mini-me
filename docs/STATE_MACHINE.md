# Estado operativo mínimo — dirección v1.2

**Fuente:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md). La máquina de estados heredada describe código histórico; NO es especificación obligatoria del nuevo flujo.

El flujo visible requerido es: **ticket seleccionado → Propose → revisión propuesta → Apply → Verify → revisión código condicional → PR pendiente merge humano → sync/archive en rama documental → PR documental → ticket cerrado**.

Correcciones regresan al responsable del trabajo y vuelven a la revisión pertinente, con límite de intentos. Preguntas humanas conservan el contexto y esperan respuesta sin consumir cuota. Un fallo conserva Git/worktree y reintenta solo si la operación externa no ocurrió ya.

**No introducir una máquina adicional** de subestados de capacidad, recovery, scoring o saga sin una necesidad explícita y demostrada en la fase actual. DB guarda solo etapa/checkpoint mínimo y referencias a artefactos autoritativos externos.

La eliminación de estados/tablas históricos deberá planificarse en F1 y completarse en F6, con datos y rollback preservados.