# Tasks: Context Discovery Deterministic Deduplication

- [ ] 1. Add status precedence helper and unique accumulator to `src/minime/services/context_discovery_service.py` <!-- id: 0 -->
- [ ] 2. Update `discover_context_pure()` to deduplicate discovered `BacklogItem` projections in memory <!-- id: 1 -->
- [ ] 3. Ensure `discover_context()` safely handles unique projections without `IntegrityError` or terminal state resurrection <!-- id: 2 -->
- [ ] 4. Add unit and regression tests for duplicate ROADMAP section headers, cross-source duplicates, and idempotency <!-- id: 3 -->
- [ ] 5. Run OpenSpec validation and focused test suite verification <!-- id: 4 -->
