"""Stable, versioned taxonomy for F2 context organization.

The taxonomy defines *where* sourced facts can be documented, not business
truth, task admission, OpenSpec specifications, or a mandatory set of files.
Only populated documents are materialized/indexed. The original ZIP lives at
context/incoming/<zip-sha>/ and is never rewritten by this organizer.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath

CONTEXT_CATALOG_VERSION = "f2-standard-v1"

# A deliberately complete but optional reference taxonomy for medium/large projects.
# Never interpret a catalog filename as authorization to invent its contents.
CONTEXT_DOCUMENT_CATALOG: dict[str, tuple[str, ...]] = {
    "00-general": (
        "descripcion-del-proyecto.md",
        "resumen-ejecutivo.md",
        "vision-general.md",
        "glosario.md",
        "acronimos.md",
        "mapa-del-contexto.md",
    ),
    "01-negocio": (
        "intencion-de-negocio.md",
        "problema-y-oportunidad.md",
        "objetivos-de-negocio.md",
        "propuesta-de-valor.md",
        "modelo-de-negocio.md",
        "mercado-y-segmentos.md",
        "competencia.md",
        "monetizacion.md",
        "indicadores-de-negocio.md",
        "politicas-de-negocio.md",
        "estrategia-comercial.md",
    ),
    "02-producto": (
        "vision-del-producto.md",
        "alcance.md",
        "modulos-y-capacidades.md",
        "funcionalidades.md",
        "requerimientos-funcionales.md",
        "requerimientos-no-funcionales.md",
        "casos-de-uso.md",
        "escenarios-de-uso.md",
        "configuracion-y-personalizacion.md",
        "limitaciones-del-producto.md",
        "dependencias-del-producto.md",
        "compatibilidad.md",
        "variantes-y-ediciones.md",
    ),
    "03-usuarios-y-ux": (
        "tipos-de-usuario.md",
        "perfiles-y-personas.md",
        "necesidades-de-usuario.md",
        "recorridos-de-usuario.md",
        "flujos-de-interaccion.md",
        "arquitectura-de-informacion.md",
        "navegacion.md",
        "interfaces-y-pantallas.md",
        "diseno-responsive.md",
        "accesibilidad.md",
        "usabilidad.md",
        "experiencia-movil.md",
        "internacionalizacion.md",
        "contenido-y-microcopy.md",
    ),
    "04-dominio-y-procesos": (
        "conceptos-del-dominio.md",
        "entidades-de-negocio.md",
        "reglas-de-negocio.md",
        "procesos-de-negocio.md",
        "flujos-operativos.md",
        "estados-y-transiciones.md",
        "roles-y-responsabilidades.md",
        "autorizaciones-y-aprobaciones.md",
        "eventos-de-negocio.md",
        "excepciones-del-proceso.md",
    ),
    "05-arquitectura": (
        "vision-de-arquitectura.md",
        "principios-arquitectonicos.md",
        "estilo-y-patrones.md",
        "componentes.md",
        "servicios.md",
        "comunicacion-entre-componentes.md",
        "estructura-de-repositorios.md",
        "stack-tecnologico.md",
        "dependencias-tecnicas.md",
        "arquitectura-frontend.md",
        "arquitectura-backend.md",
        "arquitectura-movil.md",
        "arquitectura-multitenant.md",
        "concurrencia-y-asincronia.md",
        "escalabilidad.md",
        "disponibilidad-y-resiliencia.md",
        "restricciones-tecnicas.md",
    ),
    "06-datos": (
        "arquitectura-de-datos.md",
        "modelo-conceptual.md",
        "modelo-logico.md",
        "modelo-fisico.md",
        "diccionario-de-datos.md",
        "bases-de-datos.md",
        "almacenamiento-de-archivos.md",
        "flujos-y-transformaciones.md",
        "migraciones-de-datos.md",
        "retencion-y-eliminacion.md",
        "respaldo-y-restauracion.md",
        "gobierno-de-datos.md",
        "calidad-de-datos.md",
    ),
    "07-integraciones": (
        "catalogo-de-integraciones.md",
        "sistemas-externos.md",
        "contratos-api.md",
        "webhooks.md",
        "eventos-y-mensajeria.md",
        "autenticacion-entre-sistemas.md",
        "formatos-de-intercambio.md",
        "importacion-y-exportacion.md",
        "limites-y-cuotas.md",
        "errores-y-reintentos.md",
        "dependencias-externas.md",
    ),
    "08-seguridad": (
        "arquitectura-de-seguridad.md",
        "autenticacion.md",
        "autorizacion-y-permisos.md",
        "identidad-y-sesiones.md",
        "gestion-de-secretos.md",
        "proteccion-de-datos.md",
        "cifrado.md",
        "auditoria-y-trazabilidad.md",
        "amenazas-y-riesgos.md",
        "aislamiento-y-sandboxing.md",
        "seguridad-de-aplicaciones.md",
        "gestion-de-vulnerabilidades.md",
    ),
    "09-infraestructura": (
        "vision-de-infraestructura.md",
        "infraestructura-local.md",
        "infraestructura-cloud.md",
        "entornos.md",
        "contenedores.md",
        "redes-y-conectividad.md",
        "configuracion-y-secretos.md",
        "infraestructura-como-codigo.md",
        "ci-cd.md",
        "estrategia-de-despliegue.md",
        "observabilidad.md",
        "capacidad-y-dimensionamiento.md",
        "alta-disponibilidad.md",
        "costos-de-infraestructura.md",
    ),
    "10-calidad": (
        "estrategia-de-calidad.md",
        "estrategia-de-pruebas.md",
        "pruebas-unitarias.md",
        "pruebas-de-integracion.md",
        "pruebas-end-to-end.md",
        "pruebas-de-rendimiento.md",
        "pruebas-de-seguridad.md",
        "pruebas-de-aceptacion.md",
        "estandares-de-codigo.md",
        "compatibilidad-y-regresion.md",
        "defectos-conocidos.md",
    ),
    "11-operacion": (
        "modelo-operativo.md",
        "procedimientos-operativos.md",
        "monitoreo-y-alertas.md",
        "gestion-de-incidentes.md",
        "gestion-de-problemas.md",
        "soporte.md",
        "mantenimiento.md",
        "continuidad-del-servicio.md",
        "recuperacion-ante-desastres.md",
        "sla-y-slo.md",
        "manuales-operativos.md",
        "runbooks.md",
    ),
    "12-planificacion": (
        "roadmap-documentado.md",
        "fases-documentadas.md",
        "hitos-documentados.md",
        "entregas-previstas.md",
        "dependencias-de-planificacion.md",
        "compromisos-documentados.md",
        "antecedentes-de-planificacion.md",
    ),
    "13-decisiones": (
        "decisiones-de-negocio.md",
        "decisiones-de-producto.md",
        "decisiones-tecnicas.md",
        "decisiones-arquitectonicas.md",
        "alternativas-consideradas.md",
        "restricciones-documentadas.md",
        "supuestos-documentados.md",
        "asuntos-sin-definir.md",
        "contradicciones-documentadas.md",
        "historial-de-decisiones.md",
    ),
    "14-investigacion": (
        "descubrimiento-del-producto.md",
        "estudios-de-mercado.md",
        "analisis-competitivo.md",
        "entrevistas.md",
        "encuestas.md",
        "benchmarking.md",
        "experimentos-documentados.md",
        "resultados-de-investigacion.md",
        "hallazgos-documentados.md",
    ),
    "15-diseno-y-recursos": (
        "lineamientos-visuales.md",
        "sistema-de-diseno.md",
        "identidad-de-marca.md",
        "componentes-visuales.md",
    ),
    "16-ia-y-automatizacion": (
        "casos-de-uso-ia.md",
        "modelos-y-proveedores.md",
        "agentes.md",
        "orquestacion-de-agentes.md",
        "automatizaciones.md",
        "herramientas-y-skills.md",
        "prompts-documentados.md",
        "memoria-y-contexto.md",
        "rag-y-busqueda.md",
        "evaluacion-de-modelos.md",
        "limites-y-costos.md",
        "restricciones-de-ia.md",
    ),
    "17-legal-y-cumplimiento": (
        "requisitos-legales.md",
        "regulaciones-aplicables.md",
        "privacidad-y-datos-personales.md",
        "terminos-y-condiciones.md",
        "licencias.md",
        "propiedad-intelectual.md",
        "acuerdos-y-contratos.md",
        "cumplimiento-normativo.md",
        "restricciones-legales.md",
    ),
    "18-organizacion": (
        "interesados.md",
        "equipos.md",
        "estructura-organizativa.md",
        "responsabilidades.md",
        "mecanismos-de-coordinacion.md",
        "proveedores-y-socios.md",
        "comunicacion.md",
        "dependencias-organizacionales.md",
    ),
    "fuentes": (
        "INDEX.md",
    ),
}

CONTEXT_DOCUMENT_PATHS = frozenset(
    f"context/{section}/{name}"
    for section, names in CONTEXT_DOCUMENT_CATALOG.items()
    for name in names
)
# Supporting binary originals remain in context/incoming/<sha>/.
CONTEXT_ROOT_INDEX = "context/INDEX.md"


def catalog_instruction() -> str:
    """List canonical targets to the thinking agent; no inferred headings."""
    sections = [
        f"{section}/: {', '.join(files)}"
        for section, files in CONTEXT_DOCUMENT_CATALOG.items()
    ]
    return (
        f"Canonical document catalog ({CONTEXT_CATALOG_VERSION}), rooted at context/:\n"
        + "\n".join(sections)
    )


def has_substantive_content(text: str) -> bool:
    """Ignore heading-only placeholders without attempting semantic validation."""
    return any(
        line.strip()
        and not line.lstrip().startswith("#")
        and line.strip() not in {"---", "***", "___"}
        for line in text.splitlines()
    )


def populated_catalog_documents(worktree: Path) -> tuple[str, ...]:
    """Only substantive canonical Markdown documents belong in the main index."""
    docs: list[str] = []
    for relative in sorted(CONTEXT_DOCUMENT_PATHS):
        path = worktree / relative
        if path.is_file() and has_substantive_content(path.read_text(encoding="utf-8")):
            docs.append(relative)
    return tuple(docs)


def generated_context_path_allowed(relative: str) -> bool:
    """Bound generated context files without restricting original ZIP paths."""
    path = PurePosixPath(relative)
    if relative == CONTEXT_ROOT_INDEX or relative in CONTEXT_DOCUMENT_PATHS:
        return True
    return (
        len(path.parts) >= 4
        and path.parts[0] == "context"
        and path.parts[1] == "incoming"
        and bool(path.parts[2])
    )
