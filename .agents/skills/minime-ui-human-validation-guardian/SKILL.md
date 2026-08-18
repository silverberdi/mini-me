---
name: minime-ui-human-validation-guardian
description: Ensure UI changes have explicit human validation scenarios and stale validation is never reused.
---
# UI Human Validation Guardian
Human validation is for UI behavior. Required scenarios specify prerequisites, user actions and expected visible outcomes. Do not approve with unresolved required scenarios. Bind results to head SHA + base SHA + image digest when present. Candidate/base drift invalidates stale validation according to policy.
