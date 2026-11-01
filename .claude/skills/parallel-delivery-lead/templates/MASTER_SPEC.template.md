# MASTER SPEC — [Challenge]
> State: DRAFT until explicitly reviewed and committed. Commit SHA is recorded in the handoff *after* commit.
> Authoritative: this document controls the three task briefs; frozen by team policy after baseline.

## Global client contract
- Stated client problem / end user / desired measurable outcome:
- Evidence, source data and allowed permissions:
- One demoable vertical slice (input → action → output):
- Three MVP must-haves (maximum):
- Non-goals / deferrals:
- Confirmed facts vs assumptions (label each):
- Security / privacy / cost limits:
- Architecture rationale + one rejected simpler/complex alternative:
- Local Gradio demo plan and public-sharing authorization:
- Render deployment path (optional; one service/port where possible):

## Canonical interface contract (frozen)
- Contract type: HTTP API **OR** Python function interface (choose deliberately):
- Entrypoints (method/path or module.function signature):
- Input fields (name/type/required/validation/example):
- Output fields (name/type/required/example):
- Error/status/fallback behavior:
- State/session/memory semantics:
- Mock test fixture (exact response shape):
- Timeout/retry expectations:

## Acceptance criteria and failure handling
1. Given / When / Then:
2. Given / When / Then:
3. Given / When / Then:
- Failure 1 and expected safe behavior:
- Failure 2 and expected safe behavior:
- First runnable UI→backend→result smoke test:
- Evidence (actual test output, screenshots, trace, git SHA, URLs):

## CLAUDE OWNERSHIP
- Branch/worktree: main / main checkout
- Owns `backend/`, `workflows/`, central integration, final README/demo
- First 15–25-minute artifact:
- Commit/test handoff:

## CURSOR OWNERSHIP
- Branch/worktree: feat/cursor-ui / sibling -cursor
- Owns `ui/` only; create contract-accurate mocks
- States to implement (idle/loading/error/success):
- First visible 15–25-minute artifact:
- Commit/test handoff:

## CODEX OWNERSHIP (OPTIONAL TO ACTIVATE)
- Branch/worktree: feat/codex-qa / sibling -codex
- Owns `tests/`, `evals/`, `deploy/` only
- Contract tests, task-specific LLM evals, Render config and release checks:
- First 15–25-minute artifact:
- Activation decision (yes/no and why):
- Commit/test handoff:

## Integration / release protocol
- Frozen baseline SHA (record in external handoff after commit):
- Worktree locations confirmed by Git, not assumed:
- 15–25 minute checkpoints, integration owner and reviewer:
- Spec-change procedure (decision request + rebaseline):
- Priority: working local, optional public Gradio tunnel, optional Render cloud:
- Feature freeze and presentation evidence:
