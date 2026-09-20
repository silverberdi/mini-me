# Tasks: Provider Probe Stale Test Fixtures Update

- [x] Create OpenSpec change directory and planning artifacts <!-- id: 0 -->
- [x] Update `_setup_exhausted` in `tests/test_probe_governance.py` with actionable READY work fixture <!-- id: 1 -->
- [x] Add explicit test for idle expensive probe suppression in `tests/test_probe_governance.py` <!-- id: 2 -->
- [x] Update `test_concurrent_expensive_probes_serialized_at_cooldown_boundary` in `tests/test_provider_execution_safety_corrections.py` <!-- id: 3 -->
- [x] Update `_seed_exhausted_provider` in `tests/test_provider_probe_reservation_concurrency.py` with matching Project + actionable READY WorkQueueItem <!-- id: 4 -->
- [x] Verify test suite (80/80 focused/provider/scheduler tests passed), ruff PASS, and OpenSpec strict PASS <!-- id: 5 -->
- [x] Re-verify candidate 39cc2be... against updated tests in isolated diagnostic repo (27/27 probe tests passed) <!-- id: 6 -->
