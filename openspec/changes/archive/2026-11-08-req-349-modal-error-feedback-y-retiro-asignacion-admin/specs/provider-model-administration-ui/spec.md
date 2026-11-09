## REMOVED Requirements

### Requirement: Configure provider and model for project roles
**Reason**: Superseded and deprecated under Contrato Rector 2.0. Project role configuration belongs canonically and exclusively to the project management view (`ProyectosComponent`), which handles all 4 required contract roles (`thinking`, `execution`, `independent_review`, `fallback`), independent reasoning effort levels, and unified searchable selection. The legacy 3-role section in the administration view presented unpopulated controls and duplicated configuration authority.
**Migration**: Configure and edit project role profiles and reasoning efforts exclusively through the Proyectos view (`/proyectos`).
