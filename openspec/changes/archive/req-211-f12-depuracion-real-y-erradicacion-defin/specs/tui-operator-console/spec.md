# Spec Delta

## REMOVED Requirements

### Requirement: Interactive Terminal Operator Console
**Reason**: The Textual TUI and its console entrypoints are obsolete; the official operator interface is the Angular PWA.
**Migration**: Use the active Angular PWA and preserved FastAPI operator contracts.

### Requirement: Responsive Multi-Viewport Terminal Adaptation
**Reason**: No active product capability requires a terminal UI after F12.
**Migration**: Validate responsive operator behavior through the Angular PWA contract.

### Requirement: Interactive Change and Run Navigation
**Reason**: The TUI navigation is retired with the TUI package.
**Migration**: Use active PWA navigation and API resources.

### Requirement: Visual Pipeline Stage and Candidate Lineage Projection
**Reason**: The TUI projection is retired; candidate authority remains in backend/API contracts.
**Migration**: Use retained API/PWA observability where implemented.

### Requirement: Deterministic Check Diagnostics and Review/Audit Authority
**Reason**: TUI-only diagnostics and tests are removed; underlying evidence contracts are not removed by this delta.
**Migration**: Use retained candidate evidence and review APIs.

### Requirement: 013 Container Preview and Guided Validation Projection
**Reason**: The TUI preview projection is obsolete and outside the active Angular build contract.
**Migration**: Do not invoke the retired TUI; use the active supported validation surface.

### Requirement: Keyboard-First Navigation and Accessibility
**Reason**: Terminal keyboard navigation is removed with the TUI.
**Migration**: Follow the Angular PWA accessibility contract.

