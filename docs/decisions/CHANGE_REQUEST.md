# CHANGE REQUEST 001 — Traceability (contract v1.1, backward-compatible)

- **Requested by:** the user, 2026-11-01. They asked for clickable source links, direct source mapping, and logs in the site that show which tools ran.
- **Approved by:** the user's request in the conversation (above).
- **Type:** backward-compatible additions to MASTER_SPEC contract B. Existing fields keep their names, types and meaning. Consumers of v1 keep working.

## Changes
1. **`ask()` takes an optional keyword `on_step: Callable[[dict], None] | None = None`.**
   - It is called once per pipeline step as the step finishes, so the UI can stream a live log.
   - Exceptions raised by the callback are ignored.
2. **The `Answer` gains these fields:**
   - `request_id: str`
   - `trace: list[Step]`, where a Step is `{step, tool, model, detail, ms, status: "ok"|"error"|"skipped", cost_usd}`. The tool is the component that ran: `openrouter.chat`, `openrouter.embeddings`, `numpy.dense`, `rank_bm25`, `rrf`, `rag.verify`, and so on.
   - `cost_usd: float`, the sum of OpenRouter-reported costs for this request.
3. **Each citation gains:**
   - `chunk_id`
   - `pdf_page`: the page in the full handbook PDF
   - `source: {pdf_file, pdf_file_page}`, for display links only
   - `retrieval: {sub_question, dense_rank, section_rank, bm25_rank, rrf_score, relevance_reason}`
   - `passage`: the exact text sent to the answer model
4. **Each `coverage.missed_sections` item gains** `source: {pdf_file, pdf_file_page}`.
5. **Backend log:** every request is appended as one JSON line to `logs/queries.jsonl` (gitignored), and each step is logged to the console.

## Corpus rule check
- The chapter PDFs in `DATA/chapters/` are used **only as display links** for citations, with the page computed from the citation's page label.
- They are never read for routing, embeddings, metadata or evaluation. MASTER_SPEC's prohibited-inputs rule is unchanged.

## Ownership
- Claude makes the UI part of this change in `ui/` on `main`, because the Cursor workstream has merged and is idle.
- Cursor must merge `main` before making any further edits to `ui/`.
