# CLAUDE_TASK
> Derived from FROZEN v1 `specs/MASTER_SPEC.md`; the baseline SHA is recorded in dispatch. The master contract wins.

- **Active?** YES
- **Owner / worktree / branch:** Claude Desktop, `C:/Users/amber/code/fde-coding-challenge`, `main`
- **Baseline SHA:** _(recorded in dispatch after the freeze commit)_
- **Goal:** Must-haves 1 and 2. First the index store (contract A), then `rag.ask` in fast mode (contract B), then integration.
- **Owned paths:** `ingest/`, `rag/` (except `rag/verify.py`), `index/`, `scripts/`, `requirements.txt`, `README.md`
- **Forbidden paths:** `specs/`, `docs/INTENT_BRIEF.md`, `ui/`, `rag/verify.py`, `evals/`, `tests/`
- **Contract:** MASTER_SPEC § Canonical interface contract, parts A and B, and § Ingestion pipeline. Do not change the schema.
- **Build order:**
  1. Clean up dependencies: remove `chromadb` and the Chroma-based test scripts; add `numpy`, `rank-bm25`, `pydantic`.
  2. Parse the chapter Markdown into sections using heading lines and their style. Strip page markers from model inputs and keep them only for citations.
  3. Chunk within sections.
  4. E1 document profiles.
  5. E2 section and chunk enrichment: `openai/gpt-4.1-mini`, structured JSON, 16 calls at once, all responses cached in `llm_cache.pkl`.
  6. The grounding check in code.
  7. E3 topic-list normalization.
  8. Embeddings, with `embed_cache.pkl`.
  9. BM25 tokens.
  10. Write `store.pkl` and `report.json`.
  11. `rag.store.load_store`.
  12. `rag.ask`: intent → search each sub-question (dense + BM25 + RRF) → relevance assessment → context expansion → answer with `openai/gpt-4.1`.
- **Never read:** `corpus/00_front-matter.md`, `corpus/index.md`, `corpus/glossary.md`, `corpus/manifest.json`, `DATA/`, PDF bookmarks.
- **First checkpoint (~15 min):** `python -m ingest.build --only ch13` produces a valid store with grounded enrichment. Commit it.
- **Smoke test:** the first smoke test in MASTER_SPEC.
- **Allowed mocks:** none in the live path. Unit tests may mock the provider.
- **Blocker format:** `BLOCKER: <what> | impact | needs <who/what>`
- **Handoff:** SHA, changed paths, commands run with their output, the `report.json` summary, limitations.
