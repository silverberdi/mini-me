---
name: minime-deployment-safety-guardian
description: Protect container preview/production deployment, candidate identity and production-data separation.
---
# Deployment Safety Guardian
UI preview is containerized and tied to exact head/base/image identity. Never point preview at production DB/data by accident. Prefer promotion of the validated immutable image to production. Production only after human merge and explicit project policy. Rollback requires human authorization in MVP.
