# CURSOR_TASK
> Derived from FROZEN v1 `specs/MASTER_SPEC.md`; the baseline SHA is recorded in dispatch. The master contract wins.

- **Active?** YES
- **Owner / worktree / branch:** Cursor Desktop, `C:/Users/amber/code/fde-coding-challenge/.worktrees/cursor-isolated-work`, `cursor/isolated-work`
- **Baseline SHA:** _(merge `main` at the dispatch SHA before starting)_
- **Goal:** A Gradio chat UI for the demo journey. Ask a question, read the cited answer and its sub-questions, switch to Verify, and read the coverage report.
- **Owned paths:** `ui/` only. Entry point: `python -m ui.app` on 127.0.0.1:7860.
- **Forbidden paths:** `specs/`, `docs/INTENT_BRIEF.md`, `ingest/`, `rag/`, `index/`, `evals/`, `tests/`, `requirements.txt`, `README.md`
- **Contract:** MASTER_SPEC § Canonical interface contract, part B (the `ask` signature and Answer shape). Call `rag.ask` when it imports; when `MOCK=1`, load `specs/fixtures/answer_fast.json` or `answer_verify.json` depending on the mode.
- **Must show:**
  - a Fast/Verify toggle;
  - the answer with `[n]` markers;
  - a citations list with section path, page label and relevance (0–3);
  - the sub-questions;
  - the coverage panel: chapters cited vs relevant, missed sections, complete or incomplete;
  - the states idle, loading, error (shows `error.message`), success and insufficient evidence.
- **Never in the UI:** API keys, raw prompts, or loading of pickle files. The UI calls only `rag.ask`.
- **First checkpoint (~15 min):** the mock UI renders both fixtures. Commit it.
- **Evidence:** a screenshot of each mode, and the command used to launch.
- **Dependencies:** you may need `gradio`. Report it to Claude rather than editing `requirements.txt`.
- **Blocker format:** `BLOCKER: <what> | impact | needs <who/what>`
- **Handoff:** SHA, changed paths, commands run with their output, limitations.
