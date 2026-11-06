## 1. Proposal-review escalation payload

- [x] 1.1 Include available structured reviewer findings and the original reviewer summary in the active proposal-review escalation payload, retaining the existing gate identity and secret sanitization.
- [x] 1.2 Build a concise Spanish gate question that identifies the exhausted review stop and explicitly asks for the operator's decision without claiming unverified impact.
- [x] 1.3 Add focused coordinator tests for structured finding preservation, missing optional fields, original wording, current payload replacement, and safe native/generated/free-text response choices.
- [x] 1.4 Verify through the existing persisted-payload/API integration path that the escalated active payload reaches the operator response projection and the accepted response remains a response only, not review approval.

## 2. Trabajo actual presentation

- [x] 2.1 Render available severity, location, affected requirement, expected correction, and original reviewer wording as clearly labeled evidence beside the current gate question; distinguish native options from generated options and retain free-text response.
- [x] 2.2 Add focused frontend coverage for findings, labels, absent fields, options/source distinction, and free-text response without stale payload fallback.
- [x] 2.3 Run the frontend test suite and `npm --prefix frontend run build` (or `npx tsc --noEmit -p frontend/tsconfig.app.json`) successfully.

## 3. End-to-end acceptance

- [x] 3.1 Exercise an exhausted proposal-review gate through durable payload persistence and the real API projection/response acceptance path, verifying finding details reach the operator and the response does not approve or bypass independent review.
