## 1. Parser Implementation

- [x] 1.1 Refactor `src/minime/services/review_verdict_parser.py` to use `json.JSONDecoder().raw_decode` when extracting JSON candidates from raw output and fenced blocks.
- [x] 1.2 Ensure candidate search scans root-level JSON objects containing `"verdict"` and tolerates arbitary nesting, quoted braces, and escaped strings.
- [x] 1.3 Maintain strict validation and ambiguity checks (`ReviewVerdictPayload.model_validate`, single unambiguous valid payload requirement, fail-closed on malformed or conflicting payloads).

## 2. Unit Testing & Verification

- [x] 2.1 Add unit tests covering payloads with CSS rules `{ display: flex; }` inside finding fields.
- [x] 2.2 Add unit tests covering responses with multiple findings and nested object/array structures.
- [x] 2.3 Add unit tests verifying responses with markdown narrative text placed after the raw JSON block.
- [x] 2.4 Run existing review parser test suite and full project tests to ensure zero regressions.
