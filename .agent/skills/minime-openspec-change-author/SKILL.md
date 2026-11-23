---
name: minime-openspec-change-author
description: Author the next mini me OpenSpec change from the canonical roadmap without scope creep.
---
# OpenSpec Change Author
Only create the next roadmap stage after the previous stage is fully closed/archived and the human explicitly advances. Use OpenSpec-native workflows. Proposal states value/non-goals; specs are observable with failure/denial scenarios; design resolves implementation-shaping choices; tasks are small/testable. In `tasks.md`, scope test commands strictly to the change's pertinent suites (`test:e2e -- <spec>`, `pytest tests/test_<module>.py`); do not declare entire repository suites for vertical changes. Never pre-create future active changes.
