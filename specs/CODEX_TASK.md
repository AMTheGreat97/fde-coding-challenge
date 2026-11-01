# CODEX_TASK
> Derived from FROZEN v1 `specs/MASTER_SPEC.md`; the baseline SHA is recorded in dispatch. The master contract wins.

- **Active?** YES. The user chose three workers, and the evaluation and verify work is independent and bounded.
- **Owner / worktree / branch:** Codex Desktop, `C:/Users/amber/.codex/worktrees/fde-challenge-work/fde-coding-challenge`, `codex/fde-challenge-work`
- **Baseline SHA:** _(merge `main` at the dispatch SHA before starting)_
- **Goal:** Must-have 3 (verify mode), the contract and policy tests, and the recall evaluation.
- **Owned paths:** `rag/verify.py`, `evals/`, `tests/`
- **Forbidden paths:** `specs/`, `docs/INTENT_BRIEF.md`, `ingest/`, other files in `rag/`, `ui/`, `index/`, `requirements.txt`, `README.md`
- **Contract:** MASTER_SPEC § Canonical interface contract, part C (`verify_coverage(question, intent, citations, store)` → Coverage). The `store` dict follows part A and the fixtures.
- **Build:**
  1. **`tests/`:**
     - validate the four fixtures, and once committed, `index/store.pkl` against the part A schema;
     - criterion 2: every `doc_id` matches `ch\d\d_*`, and no repo code imports `chromadb`, `onnxruntime`, `fastembed`, `sentence_transformers` or `torch`;
     - criterion 1's grounding: every kept quote is found in its source Markdown.
  2. **`rag/verify.py`:** sweep every section using its topics, entities, keywords, questions, summary and section vector. Send the top 20 uncited candidates to `openai/gpt-4.1-mini` via OpenRouter as a judge. Return the relevant-but-uncited sections. Hosted inference only.
  3. **`evals/golden.jsonl`:** `{id, question, expected_section_ids[], expected_chapters[], ground_truth_source, verified_by_human}`. Include 15 or more nested, multi-chapter questions, written by hand or generated from **chapter Markdown only**. Ground truth comes from `gpt-4.1-mini` reading each full chapter body with section markers and returning relevant `section_id`s with verified quotes. Leave `verified_by_human` false until the user spot-checks.
  4. **`python -m evals.recall`:** section-level and chapter-level Recall@k for fast and verify modes. Print the actual numbers.
- **Never use:** `corpus/index.md`, `corpus/00_front-matter.md`, `corpus/glossary.md`, `corpus/manifest.json`, `DATA/`, or PDF bookmarks.
- **First checkpoint (~15 min):** contract tests pass, and `verify_coverage` runs on a small `store`-shaped dict built from the fixtures. Commit it.
- **Allowed mocks:** fixtures, until Claude commits the real `index/`. Merge `main` when announced.
- **Blocker format:** `BLOCKER: <what> | impact | needs <who/what>`
- **Handoff:** SHA, changed paths, test and eval output, limitations.
