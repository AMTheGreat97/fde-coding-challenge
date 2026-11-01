---
name: actual-interview-challenge
description: Apply the supplied Perficient AI Prototype Challenge constraints before any build or demo; prefer Portkey, a 120-minute working prototype, and exactly one presentation slide.
---
# Actual Interview Challenge — overriding runbook

Before invoking any architecture/backend/demo skill, read `fde-kit/ACTUAL_CHALLENGE_BRIEF.md`. Treat that file and any live interviewer instructions as overriding older practice-runbook assumptions. If there's a conflict, explain the tradeoff and follow actual challenge.

- Use supplied Portkey gateway, not OpenRouter, as default inference provider. Key/model/base URL must come from environment variables. Test a real request with the supplied credentials before building features dependent on it.
- Presentation: ONE slide, not four. Live interview 20 minutes after recommended 120-minute build and 10-minute slide period.
- Choose one provided scenario, agree MVP proof with interviewer, source documents responsibly, implement measured tests and one stable live path.
- Keep the UI/backend/QA assignments and frozen spec/worktree discipline from previous skills, but do not use them to delay the first running vertical slice.
- Scope note: recommended manufacturing scenario is a starting choice, not a user-confirmed decision. If user/interviewer selects another, adjust without friction.
