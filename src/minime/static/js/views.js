function text(tag, content, className = "") {
  const el = document.createElement(tag);
  el.textContent = content;
  if (className) el.className = className;
  return el;
}

function card(title, content) {
  const section = document.createElement("section");
  section.className = "panel";
  section.append(text("h2", title));
  if (typeof content === "string") section.append(text("p", content));
  else if (content) section.append(content);
  return section;
}

function link(href, label, navigate) {
  const a = document.createElement("a");
  a.href = href;
  a.textContent = label;
  a.className = "btn btn-secondary";
  a.addEventListener("click", (e) => {
    e.preventDefault();
    navigate(href);
  });
  return a;
}

function list(items, emptyLabel = "Sin elementos") {
  if (!Array.isArray(items) || items.length === 0) {
    return text("p", emptyLabel, "text-muted");
  }
  const ul = document.createElement("ul");
  ul.className = "data-list";
  for (const item of items) {
    const li = document.createElement("li");
    if (typeof item === "string") {
      li.textContent = item;
    } else {
      const title = item.title || item.name || item.run_id || item.project_id || item.id || "Elemento";
      const body = item.body || item.status || item.current_stage || item.display_name || "";
      li.append(text("strong", String(title)));
      if (body) li.append(text("span", ` — ${body}`, "text-muted"));
    }
    ul.append(li);
  }
  return ul;
}

function projectSelect(state, navigate) {
  const select = document.createElement("select");
  select.className = "form-control select-project";
  select.setAttribute("aria-label", "Seleccionar proyecto");
  const projects = state.data.get("projects")?.data || [];
  const defaultOpt = document.createElement("option");
  defaultOpt.value = "";
  defaultOpt.textContent = "Todos los proyectos";
  select.append(defaultOpt);
  for (const p of projects) {
    const opt = document.createElement("option");
    opt.value = p.project_id;
    opt.textContent = p.display_name || p.project_id;
    if (state.context.project === p.project_id) opt.selected = true;
    select.append(opt);
  }
  select.addEventListener("change", (e) => {
    const val = e.target.value;
    const url = val ? `${state.route}?project=${encodeURIComponent(val)}` : state.route;
    navigate(url);
  });
  return select;
}

function source(dataResult) {
  if (!dataResult) return text("p", "Cargando…", "text-muted");
  if (!dataResult.ok) return text("p", `Error: ${dataResult.error || "No disponible"}`, "text-danger");
  const count = Array.isArray(dataResult.data) ? dataResult.data.length : 0;
  return text("p", `${count} registrado(s) en autoridad duradera.`);
}

function dashboard({ state, navigate }) {
  const root = document.createElement("div");
  root.className = "view-stack";

  const projects = state.data.get("projects");
  const runs = state.data.get("runs");
  const allRuns = runs?.data || [];
  const activeRuns = allRuns.filter((r) => r.is_active);
  const attention = allRuns.filter(
    (run) => run.human_gate === "HUMAN_REQUIRED" || run.stop_details?.human_payload
  );

  const heading = document.createElement("div");
  heading.className = "view-heading";
  heading.append(text("h1", "Dashboard"), projectSelect(state, navigate));
  root.append(heading);

  // KPI Grid with visual analog gauges + textual equivalent
  const health = document.createElement("div");
  health.className = "kpi-grid";

  // Proyecto en foco
  health.append(card("Proyecto en foco", source(projects)));

  // Trabajo actual KPI
  health.append(card("Trabajo actual", text("p", `${activeRuns.length} Run(s) observados`)));

  // Atención humana KPI
  health.append(
    card(
      "Atención humana",
      text(
        "p",
        attention.length
          ? `${attention.length} pregunta(s) pendiente(s)`
          : "No disponible: no hay HUMAN_REQUIRED durable"
      )
    )
  );

  // Cuota por modelo gauge
  const quotaCard = document.createElement("section");
  quotaCard.className = "panel kpi-gauge-panel";
  quotaCard.append(text("h2", "Cuota por modelo"));
  const gaugeBox = document.createElement("div");
  gaugeBox.className = "analog-gauge-container";
  const gaugeSvg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  gaugeSvg.setAttribute("viewBox", "0 0 100 50");
  gaugeSvg.setAttribute("class", "analog-gauge");
  gaugeSvg.setAttribute("role", "img");
  gaugeSvg.setAttribute("aria-label", "Indicador analógico de cuota");
  const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
  path.setAttribute("d", "M 10 50 A 40 40 0 0 1 90 50");
  path.setAttribute("fill", "none");
  path.setAttribute("stroke", "currentColor");
  path.setAttribute("stroke-width", "8");
  path.setAttribute("opacity", "0.2");
  gaugeSvg.append(path);
  gaugeBox.append(gaugeSvg);
  gaugeBox.append(text("p", "No disponible: faltan límite y período verificables", "gauge-equivalent"));
  quotaCard.append(gaugeBox);
  health.append(quotaCard);

  root.append(health);

  // Attention banner
  if (attention.length) {
    const banner = document.createElement("section");
    banner.className = "panel attention-banner";
    banner.append(text("h2", "Atención requerida"), text("p", "Existe una solicitud durable de HUMAN_REQUIRED."));
    const run = attention[0];
    banner.append(
      link(
        `/trabajo-actual?project=${encodeURIComponent(run.project_id)}&run=${encodeURIComponent(run.run_id)}`,
        "Abrir Trabajo actual",
        navigate
      )
    );
    root.append(banner);
  }

  // Effectiveness Dimensions for Completed Requests
  const chartSection = document.createElement("section");
  chartSection.className = "panel effectiveness-panel";
  chartSection.append(text("h2", "Efectividad de Requests terminados"));
  const dimSelector = document.createElement("div");
  dimSelector.className = "dimension-selector";
  dimSelector.append(text("span", "Dimensión: "));
  const selectDim = document.createElement("select");
  selectDim.className = "form-control select-dimension";
  selectDim.setAttribute("aria-label", "Seleccionar dimensión de efectividad");
  for (const opt of [
    { id: "quality", label: "Calidad y autonomía" },
    { id: "time", label: "Tiempo total y activo" },
    { id: "resources", label: "Recursos IA medidos" },
  ]) {
    const o = document.createElement("option");
    o.value = opt.id;
    o.textContent = opt.label;
    selectDim.append(o);
  }
  dimSelector.append(selectDim);
  chartSection.append(dimSelector);
  const chartBox = document.createElement("div");
  chartBox.className = "chart-box";
  chartBox.append(
    text(
      "p",
      "Pendiente de datos — F7. No hay instrumentación verificable para graficar.",
      "text-muted"
    )
  );
  chartSection.append(chartBox);
  root.append(chartSection);

  // Global pause
  root.append(
    card(
      "Pausar mini me",
      text(
        "p",
        "Disponible en F7: la pausa diferida requiere Change, PR2 y cierre. No se envió ninguna solicitud."
      )
    )
  );

  // Navigation actions
  const actions = document.createElement("div");
  actions.className = "action-toolbar";
  actions.append(
    link(
      `/trabajo${state.context.project ? `?project=${encodeURIComponent(state.context.project)}` : ""}`,
      "Ver Trabajo",
      navigate
    ),
    link(
      `/proyectos${state.context.project ? `?project=${encodeURIComponent(state.context.project)}` : ""}`,
      "Ver Proyectos",
      navigate
    )
  );
  root.append(actions);

  return root;
}

function trabajo({ state, navigate }) {
  const root = document.createElement("div");
  root.className = "view-stack";
  root.append(text("h1", "Trabajo"));

  const runs = state.data.get("runs")?.data || [];
  const completed = runs.filter((r) => !r.is_active);
  const active = runs.filter((r) => r.is_active);

  root.append(
    card(
      "Último terminado",
      completed.length
        ? list(completed.slice(-1), "Sin trabajo terminado.")
        : text("p", "Se muestra solo con resultado y cierre remoto verificables.")
    ),
    card("En ejecución", list(active, "No hay Run activo verificable.")),
    card(
      "Siguiente trabajo",
      text(
        "p",
        "La elegibilidad FIFO se lee del proveedor remoto; no se selecciona trabajo desde el navegador."
      )
    )
  );

  if (active.length > 0) {
    const cur = active[0];
    root.append(
      link(
        `/trabajo-actual?project=${encodeURIComponent(cur.project_id)}&run=${encodeURIComponent(cur.run_id)}`,
        "Abrir Run actual",
        navigate
      )
    );
  }

  return root;
}

function current({ state, api, navigate }) {
  const root = document.createElement("div");
  root.className = "view-stack";
  root.append(text("h1", "Trabajo actual"));

  const runs = state.data.get("runs")?.data || [];
  const run =
    runs.find((item) => item.run_id === state.context.run) ||
    (state.context.run ? null : runs.find((item) => item.is_active));

  if (!run) {
    root.append(
      card(
        "Run no disponible",
        text(
          "p",
          "La identidad solicitada no fue expuesta o no está autorizada; no se seleccionó otro Run silenciosamente."
        )
      )
    );
    return root;
  }

  // Stepper Visual de Etapas del Pipeline
  const stages = [
    { key: "ADMITTED", label: "Admisión" },
    { key: "EXPLORING", label: "Exploración" },
    { key: "PROPOSING", label: "Propuesta" },
    { key: "PROPOSAL_REVIEW", label: "Review Propuesta" },
    { key: "IMPLEMENTING", label: "Implementación" },
    { key: "RUNNING_TESTS", label: "Tests" },
    { key: "VERIFYING", label: "Verificación" },
    { key: "CODE_REVIEW", label: "Review Código" },
    { key: "PREPARING_PR", label: "Preparar PR" },
    { key: "COMPLETED", label: "Cierre" },
  ];

  const stepperCard = document.createElement("section");
  stepperCard.className = "panel pipeline-stepper-panel";
  stepperCard.append(text("h2", "Fases del Pipeline"));
  const stepper = document.createElement("div");
  stepper.className = "pipeline-stepper";

  const currentIdx = stages.findIndex((s) => s.key === run.current_stage);

  for (let i = 0; i < stages.length; i++) {
    const st = stages[i];
    const stepEl = document.createElement("div");
    stepEl.className = "stepper-step";
    if (st.key === run.current_stage) {
      stepEl.classList.add("active");
    } else if (currentIdx !== -1 && i < currentIdx) {
      stepEl.classList.add("completed");
    } else {
      stepEl.classList.add("pending");
    }
    const badge = document.createElement("span");
    badge.className = "step-badge";
    badge.textContent = String(i + 1);
    const label = document.createElement("span");
    label.className = "step-label";
    label.textContent = st.label;
    stepEl.append(badge, label);
    stepper.append(stepEl);
  }
  stepperCard.append(stepper);

  // Stage details area
  const stageDetail = document.createElement("div");
  stageDetail.className = "stage-detail-box";
  stageDetail.append(
    text(
      "p",
      `Etapa actual observada: ${run.current_stage || "Desconocida"}. Salida y evidencias vinculadas a SHA duradero.`,
      "text-muted"
    )
  );
  stepperCard.append(stageDetail);
  root.append(stepperCard);

  // Identidad
  root.append(
    card(
      "Identidad",
      list(
        [
          {
            run_id: run.run_id,
            change_name: run.change_name,
            current_stage: run.current_stage,
            status: run.is_active ? "Activo" : "Terminado",
            base_sha: run.base_sha,
            candidate_sha: run.candidate_sha || run.current_candidate_sha || "No disponible",
          },
        ],
        "Sin identidad"
      )
    )
  );

  // HUMAN_REQUIRED Gate
  const gate = run.stop_details?.human_payload || run.stop_details?.human_request;
  if (run.human_gate === "HUMAN_REQUIRED" || gate) {
    const panel = card(
      "Pregunta del workflow",
      text("p", gate?.question || gate?.prompt || "La pregunta literal no está expuesta por la API.")
    );
    if (Array.isArray(gate?.options)) {
      panel.append(
        list(
          gate.options.map((option) => ({
            title: option.label || option.id || option,
            body: option.description || "Opción original",
          })),
          "No hay opciones."
        )
      );
    }
    const form = document.createElement("form");
    form.className = "human-form";
    const answer = document.createElement("textarea");
    answer.required = true;
    answer.rows = 4;
    answer.placeholder = "Respuesta explícita del operador";
    answer.setAttribute("aria-label", "Respuesta al workflow");
    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn btn-primary";
    submit.textContent = "Enviar respuesta";
    const message = text("p", "La pregunta se conserva hasta confirmación durable.", "text-muted");
    form.append(answer, submit, message);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      submit.disabled = true;
      const response = await api.post(
        `/api/v1/projects/${encodeURIComponent(run.project_id)}/requests/run`,
        { operator_clarification: answer.value }
      );
      message.textContent = response.ok
        ? "Respuesta aceptada por el backend; actualizando autoridad…"
        : `No se confirmó la respuesta: ${response.error || "error"}`;
      if (!response.ok) submit.disabled = false;
    });
    panel.append(form);
    root.append(panel);
  } else {
    root.append(
      card(
        "Atención",
        text("p", "No existe HUMAN_REQUIRED durable. WAITING_CAPACITY/UNKNOWN no crean una pregunta.")
      )
    );
  }

  root.append(link(`/trabajo?project=${encodeURIComponent(run.project_id)}`, "Volver a Trabajo", navigate));
  return root;
}

function projects({ state, navigate }) {
  const root = document.createElement("div");
  root.className = "view-stack";
  root.append(text("h1", "Proyectos"));

  const projectsResult = state.data.get("projects");
  const projectsList = projectsResult?.data || [];
  const listNode = list(
    projectsList,
    projectsResult?.ok === false ? "No se pudo leer proyectos." : "No hay proyectos autorizados."
  );
  root.append(card("Configuración F2", listNode));

  const selected = state.context.project || projectsList[0]?.project_id;
  if (selected) {
    const detail = projectsList.find((p) => p.project_id === selected);
    const panel = card(
      "Detalle de proyecto",
      list([
        {
          title: detail?.display_name || selected,
          body: `Estado administrativo: ${detail?.status || "No disponible"}`,
        },
      ])
    );
    panel.append(
      link(`/backlog?project=${encodeURIComponent(selected)}`, "Abrir Backlog", navigate),
      text(
        "p",
        "Gestión de requests disponible: crear, editar, pausar, reactivar y eliminar lógico.",
        "text-muted"
      )
    );
    root.append(panel);
  }

  return root;
}

function backlog({ state }) {
  const root = document.createElement("div");
  root.className = "view-stack";
  root.append(text("h1", "Backlog"));

  const requests = state.data.get("requests");
  const items = requests?.data?.eligible_requests || [];

  // Pestañas separadas de Backlog: Pendientes y Terminados
  const tabsContainer = document.createElement("div");
  tabsContainer.className = "backlog-tabs";

  const tabPending = document.createElement("button");
  tabPending.className = "btn btn-secondary active";
  tabPending.textContent = "Pendientes";
  tabPending.setAttribute("aria-selected", "true");

  const tabDone = document.createElement("button");
  tabDone.className = "btn btn-secondary";
  tabDone.textContent = "Terminados";
  tabDone.setAttribute("aria-selected", "false");

  tabsContainer.append(tabPending, tabDone);
  root.append(tabsContainer);

  const pendingContent = document.createElement("div");
  pendingContent.className = "tab-content tab-pending";
  pendingContent.append(
    card(
      "Requests Pendientes",
      list(
        items,
        requests
          ? "No hay elegibles abiertos observados o la fuente está parcialmente disponible."
          : "Selecciona un proyecto para leer el backlog remoto."
      )
    )
  );

  // Acciones contextuales por estado del backlog
  const mgmtSection = document.createElement("section");
  mgmtSection.className = "panel backlog-management-panel";
  mgmtSection.append(text("h2", "Gestión lógica de Requests"));
  mgmtSection.append(
    text(
      "p",
      "Controles contextuales: Editar, Desactivar, Reactivar y Eliminar lógicamente aplican solo a Requests no admitidos. Trabajo admitido solo cambia vía HUMAN_REQUIRED; trabajo finalizado es inmutable; eliminación lógica preserva historia.",
      "text-muted"
    )
  );

  const selectedProject = state.selectedProject;
  const actionGroup = document.createElement("div");
  actionGroup.className = "btn-group";

  const editBtn = document.createElement("button");
  editBtn.type = "button";
  editBtn.className = "btn btn-secondary";
  editBtn.textContent = "Editar Request";
  editBtn.title = "Editar un Request no admitido";
  editBtn.addEventListener("click", async () => {
    const issueNum = prompt("Número de issue a editar:");
    if (!issueNum) return;
    const newTitle = prompt("Nuevo título (opcional):");
    const newBody = prompt("Nuevo cuerpo (opcional):");
    if (!newTitle && !newBody) return;
    try {
      const resp = await fetch('/api/v1/projects/' + encodeURIComponent(selectedProject) + '/requests/' + issueNum, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: newTitle || undefined, body: newBody || undefined }),
      });
      if (resp.ok) {
        alert("Request actualizado con éxito.");
        window.location.reload();
      } else {
        const err = await resp.json();
        alert();
      }
    } catch (e) {
      alert();
    }
  });

  const deactBtn = document.createElement("button");
  deactBtn.type = "button";
  deactBtn.className = "btn btn-secondary";
  deactBtn.textContent = "Desactivar Request";
  deactBtn.title = "Desactivar Request (excluye de FIFO)";
  deactBtn.addEventListener("click", async () => {
    const issueNum = prompt("Número de issue a desactivar:");
    if (!issueNum) return;
    try {
      const resp = await fetch('/api/v1/projects/' + encodeURIComponent(selectedProject) + '/requests/' + issueNum + '/deactivate', {
        method: "POST",
      });
      if (resp.ok) {
        alert("Request desactivado.");
        window.location.reload();
      } else {
        const err = await resp.json();
        alert();
      }
    } catch (e) {
      alert();
    }
  });

  const reactBtn = document.createElement("button");
  reactBtn.type = "button";
  reactBtn.className = "btn btn-secondary";
  reactBtn.textContent = "Reactivar Request";
  reactBtn.title = "Reactivar Request previamente desactivado";
  reactBtn.addEventListener("click", async () => {
    const issueNum = prompt("Número de issue a reactivar:");
    if (!issueNum) return;
    try {
      const resp = await fetch('/api/v1/projects/' + encodeURIComponent(selectedProject) + '/requests/' + issueNum + '/reactivate', {
        method: "POST",
      });
      if (resp.ok) {
        alert("Request reactivado.");
        window.location.reload();
      } else {
        const err = await resp.json();
        alert();
      }
    } catch (e) {
      alert();
    }
  });

  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "btn btn-secondary";
  delBtn.textContent = "Eliminar lógicamente";
  delBtn.title = "Eliminar lógicamente (preserva historia)";
  delBtn.addEventListener("click", async () => {
    const issueNum = prompt("Número de issue a eliminar lógicamente:");
    if (!issueNum) return;
    if (!confirm()) return;
    try {
      const resp = await fetch('/api/v1/projects/' + encodeURIComponent(selectedProject) + '/requests/' + issueNum, {
        method: "DELETE",
      });
      if (resp.ok) {
        alert("Request eliminado lógicamente.");
        window.location.reload();
      } else {
        const err = await resp.json();
        alert();
      }
    } catch (e) {
      alert();
    }
  });

  actionGroup.append(editBtn, deactBtn, reactBtn, delBtn);
  mgmtSection.append(actionGroup);
  pendingContent.append(mgmtSection);

  const doneContent = document.createElement("div");
  doneContent.className = "tab-content tab-done";
  doneContent.hidden = true;
  doneContent.append(
    card(
      "Requests Terminados",
      text(
        "p",
        "No disponible: el contrato actual no expone el historial cerrado desde esta superficie (Disponible en F7)."
      )
    )
  );

  tabPending.addEventListener("click", () => {
    tabPending.classList.add("active");
    tabDone.classList.remove("active");
    tabPending.setAttribute("aria-selected", "true");
    tabDone.setAttribute("aria-selected", "false");
    pendingContent.hidden = false;
    doneContent.hidden = true;
  });

  tabDone.addEventListener("click", () => {
    tabDone.classList.add("active");
    tabPending.classList.remove("active");
    tabDone.setAttribute("aria-selected", "true");
    tabPending.setAttribute("aria-selected", "false");
    doneContent.hidden = false;
    pendingContent.hidden = true;
  });

  root.append(pendingContent, doneContent);

  // Formulario visual "Nuevo Request" activo (F7)
  const newReqSection = document.createElement("section");
  newReqSection.className = "panel new-request-panel";
  newReqSection.append(text("h2", "Nuevo Request"));
  newReqSection.append(
    text(
      "p",
      "Crea un requerimiento en lenguaje natural. Se normalizará a Gherkin antes de admisión.",
      "text-muted"
    )
  );

  const form = document.createElement("form");
  form.className = "new-request-form";

  const titleGroup = document.createElement("div");
  titleGroup.className = "form-group";
  const titleLabel = text("label", "Título del Request *");
  titleLabel.setAttribute("for", "newRequestTitle");
  const titleInput = document.createElement("input");
  titleInput.type = "text";
  titleInput.id = "newRequestTitle";
  titleInput.className = "form-control";
  titleInput.placeholder = "Título en lenguaje natural";
  titleInput.required = true;
  titleGroup.append(titleLabel, titleInput);

  const descGroup = document.createElement("div");
  descGroup.className = "form-group";
  const descLabel = text("label", "Descripción detallada *");
  descLabel.setAttribute("for", "newRequestDesc");
  const descInput = document.createElement("textarea");
  descInput.id = "newRequestDesc";
  descInput.className = "form-control";
  descInput.rows = 3;
  descInput.placeholder = "Descripción del requerimiento";
  descInput.required = true;
  descGroup.append(descLabel, descInput);

  const critGroup = document.createElement("div");
  critGroup.className = "form-group";
  const critLabel = text("label", "Criterios de aceptación *");
  critLabel.setAttribute("for", "newRequestCrit");
  const critInput = document.createElement("textarea");
  critInput.id = "newRequestCrit";
  critInput.className = "form-control";
  critInput.rows = 3;
  critInput.placeholder = "Criterios observables de verificación";
  critInput.required = true;
  critGroup.append(critLabel, critInput);

  const submitBtn = document.createElement("button");
  submitBtn.type = "submit";
  submitBtn.className = "btn btn-primary";
  submitBtn.textContent = "Crear Request";

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!selectedProject) {
      alert("Selecciona un proyecto primero.");
      return;
    }
    const tVal = titleInput.value.trim();
    const dVal = descInput.value.trim();
    const cVal = critInput.value.trim();
    if (!tVal || !dVal || !cVal) {
      alert("Todos los campos marcados con * son obligatorios.");
      return;
    }
    submitBtn.disabled = true;
    submitBtn.textContent = "Creando y normalizando...";
    try {
      const resp = await fetch('/api/v1/projects/' + encodeURIComponent(selectedProject) + '/requests', {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: tVal,
          description: dVal,
          acceptance_criteria: cVal,
        }),
      });
      if (resp.ok) {
        alert("Request creado con éxito.");
        titleInput.value = "";
        descInput.value = "";
        critInput.value = "";
        window.location.reload();
      } else {
        const err = await resp.json();
        alert();
      }
    } catch (err) {
      alert();
    } finally {
      submitBtn.disabled = false;
      submitBtn.textContent = "Crear Request";
    }
  });

  form.append(titleGroup, descGroup, critGroup, submitBtn);
  newReqSection.append(form);
  root.append(newReqSection);

  return root;
}

export function renderView({ root, route, state, api, navigate }) {
  root.replaceChildren();
  const view =
    route === "/trabajo"
      ? trabajo({ state, navigate })
      : route === "/trabajo-actual"
      ? current({ state, api, navigate })
      : route === "/proyectos"
      ? projects({ state, navigate })
      : route === "/backlog"
      ? backlog({ state })
      : dashboard({ state, navigate });
  root.append(view);
}
