---
name: integration-gate
description: Review and integrate parallel Cursor/Codex commits into Claude main only after frozen-spec checks, then prove an end-to-end local Gradio demo before releasing to Render.
---
# Integration gate — Claude Desktop main checkout

Run at first worker handoff; do not leave all integration to the last 20 minutes.

1. Read `specs/MASTER_SPEC.md`, frozen baseline SHA and the three task briefs. Query actual worktree paths/branches and check user changes before touching Git. Uncommitted worker code is not present in main.
2. Require each participating worker to report commit SHA, changed paths, tests actually executed, and blockers. Require codex deployment config to remain on its branch until reviewed; don't deploy the worker branch as final.
3. Compare each candidate to frozen spec (`git diff <BASELINE_SHA> <WORKER_SHA> -- specs/ docs/INTENT_BRIEF.md`) and stop on unauthorized edits. Inspect for API signature mismatches, hardcoded keys, UI secrets, and editing outside file ownership. Do not force-reset/delete.
4. Merge small reviewed commits into main. Resolve conflicts with human input. Run deterministic tests, one real user journey from UI through backend, failure-handling case, and a genuine model call if authorized.
5. **Immediately after a working local vertical slice**, offer Gradio share link via `share=True` only with human approval; verify URL in a separate/incognito browser. Note this is a public temporary tunnel to a process running on the user's machine, not independent cloud hosting. If using FastAPI-mounted Gradio, test whether share works with the chosen startup topology rather than assuming it; an independent Gradio launch may be the fallback.
6. For Render: integrate Codex deployment files, push tested `main` when authorized, confirm correct service start host `0.0.0.0` and env `$PORT`, Render secret variables, `/health` where present; ask `cloud-release-verifier` to validate the actual public URL and real inference response. A successful build alone isn't verification.
7. Stabilize: record GitHub URL, commit SHA, successful demo input/output, honest eval results, failed cases, current Render status and chosen fallback. Keep a tested local checkpoint before additional changes; defer optional features after feature freeze.

Output GO/NO-GO with evidence. Do not claim deployed or tested unless observed.
