# Arquitectura objetivo — mini me (gacela)

**Autoridad:** [CONTRATO_RECTOR.md](CONTRATO_RECTOR.md). Describe objetivo, NO declara que el código actual esté migrado.

```text
 Operador — PWA móvil / tablet / web
                 |
           FastAPI única
                 |
      Coordinación de proyecto
                 |
        +--------+----------+---------------+
        |                   |               |
  Fuente de tickets   Agentes/CLI       Git y PR
    GitHub (inicial)  OpenSpec nativo  repositorio/merge
        |                   |               |
   Issues/comentarios  pensamiento       worktrees
                       ejecutor         ramas/commits
                       revisor          PR/merge según política
                       respaldo         PR cierre autorizado
                 |
      PostgreSQL mínimo: proyecto, checkpoint, decisiones
```

## Fronteras
- **Proyecto:** configuración, activo/pausado, modelos/roles, skills/contexto, GitHub inicial.
- **Tickets:** adaptador mínimo consulta/crea/comenta/cierra; Git/PR es contrato distinto. No crear ADO hasta usarlo.
- **Orquestación:** selecciona ticket más antiguo elegible, invoca etapas nativas y reanuda; no interpreta contenido OpenSpec ni programa. Un Change activo por proyecto.
- **Agentes:** pensamiento propone/verifica y cierra documentación; ejecutor aplica/corrige; independiente revisa read-only solo para complejidad alta; respaldo compatible y autorizado. Modelos/effort por proyecto.
- **OpenSpec:** CLI/workflows instalados; versiones y herramientas realmente verificadas. mini me no genera propuestas, mergea specs por regex ni archiva directorios manualmente.
- **Git:** una rama de implementación por ticket; **rama NUEVA desde main actualizado** para sync/archive tras merge.
- **Humano:** preguntas con opciones originales y alternativa contextual cuando procede; merge de código conforme a la política de complejidad ligada al SHA/PR. El PR documental se fusiona bajo las protecciones Git vigentes.
- **Datos:** GitHub fuente tickets, Git fuente código, OpenSpec fuente especificaciones, PostgreSQL solo configuración/continuidad/gasto/decisiones mínimas. Migraciones Alembic seguras.
- **Seguridad:** worktrees aislados, credenciales protegidas, cuota y presupuesto acotados, no repetir efectos externos conocidos.
- **CI/CD:** despliegue productivo ajeno a mini me. La API y UI no administran despliegues.

## Ingeniería
Python POO/SOLID/DRY/KISS/YAGNI. Interfaces pequeñas, composición, sin clases gigantes, copias de validaciones ni sagas/motores nuevos sin evidencia. Cada Change retira consumidores, código y persistencia obsoletos de su alcance cuando el reemplazo funcional esté probado.

## Riesgo de legado
Los nombres de componentes, servicios y rutas heredadas en documentos anteriores describen hallazgos de su fecha de publicación; no deben presentarse como inventario actual sin volver a inspeccionar `main`. La conformidad de la implementación se determina contra el contrato v2.0, el Change autorizado, código y evidencia del candidato exacto. Véase [RECONCILIACION_LEGADO.md](RECONCILIACION_LEGADO.md).
