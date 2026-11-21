## 1. Verify workflow and CLI wording

- [x] 1.1 Update `_run_verify` to distinguish native provider workflow dispatch from strict CLI validation and explicitly rule out `openspec verify` as a CLI command.
- [x] 1.2 Update both installed Verify skill locations while preserving Codex and Antigravity invocation instructions.
- [x] 1.3 Add focused regression coverage asserting the generated Verify prompt includes the correct CLI validation and keeps native dispatch.

## 2. Task metadata comparison

- [x] 2.1 Implement narrow task-description normalization for surrounding/redundant whitespace and the three specified leading status tags; retain canonical task IDs and all substantive checks.
- [x] 2.2 Persist canonical task-description digests in the existing assessment JSON and support legacy records by recovering source text from the recorded candidate revision; fail closed with a specific diagnostic if source recovery is impossible.
- [x] 2.3 Add regression coverage for cosmetic annotations, substantive edits, task inventory changes, and legacy source recovery/failure.

## 3. CLI acknowledgement forwarding

- [x] 3.1 Pass `operator_response=None` explicitly from `request_ack_cmd` through `request_run_cmd`, leaving gate authority and durable action handling on the shared path.
- [x] 3.2 Add a Typer `CliRunner` regression test for `minime request ack` and verify the shared request receives `None`.

## 4. Integrated verification

- [x] 4.1 Run focused tests for Verify prompt construction, feasibility task comparison, and CLI acknowledgement.
- [x] 4.2 Run the OpenSpec strict Change validation and report its actual result separately from the provider-native OpenSpec Verify workflow.
