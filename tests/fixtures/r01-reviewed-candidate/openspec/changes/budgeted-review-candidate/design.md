## Context

The fixture verifies that a separately authorized post-review continuation resumes from the existing review checkpoint.

## Decisions

- Use the existing Control Plane, recovery claim, and downstream lifecycle gates.
- Preserve the candidate and review evidence.
