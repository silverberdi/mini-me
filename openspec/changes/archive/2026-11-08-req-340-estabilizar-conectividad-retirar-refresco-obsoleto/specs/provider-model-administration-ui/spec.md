## REMOVED Requirements

### Requirement: Defer credential testing to its owning issue
**Reason**: Artificial active probe connections to AI providers consume API quota, violate Contrato Rector 2.0 regarding unneeded paid/test actions, and duplicate verified configuration.
**Migration**: Model and provider availability is derived strictly from verified credentials and installed harness capabilities without per-model active test probes in the administration view.
