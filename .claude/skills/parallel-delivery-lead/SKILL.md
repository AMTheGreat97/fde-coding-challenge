---
name: parallel-delivery-lead
description: Create and freeze one canonical FDE prototype spec, produce Claude/Cursor/Codex task briefs, verify Git worktree handoff, and coordinate 2 or 3 parallel desktop coding workers.
---
# Parallel delivery lead — spec-first (150-minute FDE assessment)

Use **after** `client-intent-interview` writes `docs/INTENT_BRIEF.md`. Read and apply `client-solution-architect` first. You are the **Claude Desktop** coordinator in the main checkout, not a communications bridge to other desktop apps. Do not pretend to send messages to Cursor or Codex.

## Stage 1 — Complete architecture and the only master contract

Create these files *on main, before worktree branching*:
- `specs/MASTER_SPEC.md`: single canonical source of truth. Fill `templates/MASTER_SPEC.template.md` under this skill. Include business outcome, target user, three MVP must-haves, assumptions, data, privacy, architecture/one rejected alternative, **exact HTTP or Python-function interface contract**, input/output/error schema, mock fixture, 3+ acceptance criteria, 2+ failure modes, demo workflow, success test, and sections labeled Claude, Cursor, Codex.
- `specs/CLAUDE_TASK.md`, `specs/CURSOR_TASK.md`, `specs/CODEX_TASK.md`: derivative workstream briefs, each referencing `MASTER_SPEC.md` rather than redefining it; use `templates/WORKSTREAM_TASK.template.md`.
- Ensure `docs/INTENT_BRIEF.md` already exists. Never imply interviewer answers are approved client statements unless confirmed.

**One interface:** For a single-process Gradio app, a Python callable with typed input/output can be the contract. For a separate API, specify HTTP endpoints and JSON exactly. Avoid inventing an API solely to impress the evaluator.

## Stage 2 — Human freeze gate

Show the candidate the three must-haves, contract shapes, five biggest assumptions/risks, owner paths and acceptance tests. They must review and approve. Commit and push the initial spec on `main` *only when permitted*. Capture the actual baseline SHA **after** the commit; do not attempt to embed its own SHA in the committed file. If not committed, label DRAFT, not FROZEN. After freeze, `specs/*` and `docs/INTENT_BRIEF.md` become read-only by **policy**, not filesystem/Git immutability.

## Stage 3 — Provision deterministic worktrees after baseline

Inspect actual repository root/name and existing worktrees, using `git worktree list` or equivalent. With repo basename `<repo>`:
- Claude: `<repo>/`, branch `main`.
- Cursor: sibling `<repo>-cursor/`, branch `feat/cursor-ui`.
- Codex: sibling `<repo>-codex/`, branch `feat/codex-qa`.

If absent, create with Git worktrees at the **frozen main baseline** after permission, or give exact instructions. If present, **never** reset/delete/recreate; inspect uncommitted changes, then safely sync baseline and verify identical master spec. Print verified absolute path, branch, and baseline SHA in the handoff. Never assume that a push updates other checkout files. See `fde-kit/WORKTREE_AND_SPEC_PROTOCOL.md`.

## Stage 4 — Skills and adaptive staffing

The candidate copies Cursor ZIP contents into `<repo>-cursor/` and Codex ZIP contents into `<repo>-codex/` after those folders exist. Those files may remain branch-local until later merge; no need to merge simply to run skills. Cursor is the UI owner. **Codex is optional**: activate for >=15 minutes of independent, bounded QA, evaluations or Render preparation; if not useful, Claude owns basic smoke tests/deployment instead. Maintain `specs/CODEX_TASK.md` as a documented *conditional* assignment; if skipped label it INACTIVE in the handoff. Do not add a third worker to impress the observer.

## Stage 5 — Three paste-ready prompts and ownership

Present up to three copy-paste messages:
- Claude: read master and Claude task; own `backend/`,`workflows/`, and *integration only after review*; prove first runnable result.
- Cursor: read master and Cursor task; own `ui/`; create mock UI conforming to the exact contract before backend is complete; cover idle/loading/error/success.
- Codex when active: read master and Codex task; own `tests/`,`evals/`,`deploy/`; start contract/eval tests and **Render deployment preparation concurrently**; never deploy unmerged branch as final product.

Every prompt must include verified checkout path/branch, baseline SHA, off-limits paths, first 15–25 minute deliverable, real test evidence, and instruction to never edit frozen specs. Assign `README.md` final edits to Claude during integration; do not have multiple agents editing root README. Report actual commit SHAs for handoff.

## Stage 6 — Delivery schedule

Use the current `fde-kit/INTERVIEW_DAY_RUNBOOK.md` as the primary target:
- 0–7 intent; 7–17 architecture/spec/freeze; 17–25 worktrees/dispatch.
- 25–65 independent building; 65–95 merge and get local/live Gradio demo; 95–120 tests + Render attempt; 120–140 stabilize/docs; 140–150 presentation and rehearsal.

Release order: **locally working end-to-end app → optional temporary Gradio URL → tested integrated commit on main → Render Web Service**, never wait for Render to prove the local product works. A `share=True` link is a public tunnel to the running local process, not cloud hosting; authorize sharing and verify browser access. For Render, use `0.0.0.0` and `$PORT` for the web server, Render-managed secrets, `/health` if provided, GitHub `main`, and a real inference smoke test. Avoid two independently exposed servers unless justified.

## Change control, reviews and finish

If an interface must change after freeze, record `docs/decisions/CHANGE_REQUEST.md`, get human approval, and explicitly rebaseline v2 or implement a backward-compatible change. Never silently edit v1. Before merge check `git diff <baseline> -- docs/INTENT_BRIEF.md specs/` on each worker's commit; reject unauthorized edits. Review diffs and secrets before merge. Test the integrated main checkout. Final delivery: actual GitHub URL, commit SHA, demo URL/limitations, evaluated examples, Render deploy state, and business presentation with **no fabricated metrics**.

**Stop rule:** If the spec has not been approved and committed, do not claim a frozen spec or start parallel worker implementation.
