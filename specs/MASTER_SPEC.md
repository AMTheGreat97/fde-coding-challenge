# MASTER SPEC — Aviation Maintenance Handbook Assistant (v1)
> State: **FROZEN v1** — approved by the user on 2026-11-01 and committed on `main`. The baseline SHA is recorded in the dispatch handoff (it is not embedded here).
> Authoritative: this document controls the three task briefs. After freeze, `specs/*` and `docs/INTENT_BRIEF.md` are read-only by team policy.
> Revision 2 (user decisions): all AI inference is hosted through OpenRouter; OpenAI models; the corpus is the Markdown chapter bodies only; storage is pickle files plus in-memory search.

## Global client contract
- **Client problem / end user / outcome:** The person running aircraft maintenance operations asks nested questions whose answers span several chapters of the FAA Aviation Maintenance Technician General Handbook. They need a chat assistant whose answers capture everything the handbook says, with citations (see `docs/INTENT_BRIEF.md`).
- **Corpus (strict):** only the 14 Markdown chapter bodies, `corpus/ch01_*.md` … `corpus/ch14_*.md`. Documents are discovered by filename pattern; the chapter number and title come from the Markdown H1.
- **Prohibited inputs** for routing, embeddings, metadata or evaluation:
  - `corpus/00_front-matter.md` (table of contents)
  - `corpus/index.md` (book index)
  - `corpus/glossary.md`
  - `corpus/manifest.json`
  - PDF bookmarks or outlines, and anything under `DATA/`
- **Page markers:** the `<!-- page 13-1 (pdf p.616) -->` markers inside the Markdown are used **only** to label citations. They are stripped from all text that gets embedded, BM25-indexed or sent to an LLM.
- **Demo slice:** user asks a multi-part question → fast cited answer from every relevant chapter → user switches on **Verify** → coverage report lists any relevant section the fast answer missed.
- **Three MVP must-haves:**
  1. **Metadata-rich index** (main focus): document → section → chunk hierarchy built from Markdown headings; LLM document profiles, section cards and chunk enrichment; topics backed by verified quotes and normalized into one topic list; stored in pickle files.
  2. **Fast mode** `ask()`: intent, sub-questions, hybrid dense + BM25 search with Reciprocal Rank Fusion (RRF), API-based relevance assessment, context expansion, an answer citing every contributing section.
  3. **Verify mode:** a sweep over all section metadata that reports relevant sections missing from the fast answer.
- **Non-goals:**
  - any local model inference (BGE, FastEmbed, ONNX, sentence-transformers, local cross-encoders, ChromaDB's built-in embedder);
  - a vector database or other database;
  - figures/images, aircraft-specific manuals, access control, exam mode, long-term memory, Render deployment.
- **Facts vs assumptions:**
  - Stated by user: end user, multi-chapter pain, recall as the priority, fast-plus-verify approach, 60-minute budget, OpenRouter, the models, Markdown-only corpus, pickle storage, every section enriched, verify as a metadata sweep, three workers.
  - Assumed: unacceptable failure, non-goals, excluding the glossary (strict reading of "chapter bodies"), and the LLM-judged evaluation ground truth.
- **Security / privacy / cost:**
  - `OPENROUTER_API_KEY` lives only in `.env`, which is gitignored. It never appears in the UI, logs, fixtures or pickle files.
  - **Pickle rule:** load only pickle files produced by this repo's pipeline. Never load user-supplied pickles, because unpickling can execute code.
  - The content is public.
  - Estimated ingestion cost is about $4–5, using `gpt-4.1-mini` with about 1,460 calls. The Markdown has 1,441 styled headings.

### Models (all through OpenRouter, `https://openrouter.ai/api/v1`, `Authorization: Bearer $OPENROUTER_API_KEY`)

| Role | Env var | Default | Verified |
|---|---|---|---|
| Embeddings, both ingestion and query | `EMBEDDING_MODEL` | `openai/text-embedding-3-small` (1536-d) via `POST /embeddings` | live call OK, 1536-d |
| Profiling, topic extraction, topic-list normalization, chunk enrichment, intent, relevance assessment, verify judge | `LLM_MODEL` | `openai/gpt-4.1-mini` via `POST /chat/completions` with `response_format: json_schema` (strict) | live call OK |
| Grounded final answer | `ANSWER_MODEL` | `openai/gpt-4.1` | live call OK |

The same embedding model must be used for ingestion and queries. The query path refuses to run (`index_missing`) if `store.pkl` was built with a different `EMBEDDING_MODEL`.

### Architecture
- One Python process: Gradio UI → `rag.ask()` → OpenRouter.
- Search is fully in memory: NumPy cosine similarity over L2-normalized float32 vectors, plus `rank-bm25` rebuilt from stored tokens at load.
- **Rejected alternatives:**
  - ChromaDB or another vector database: no time to set it up, and Chroma's default embedder is local inference.
  - Sending the whole book to the model on every question: slow and costly per query.

### Ingestion pipeline (Claude): every LLM step is structured JSON, cached, and resumable
1. **Parse.** Read the 14 chapter files and record page markers for citations.
   - Build sections from **Markdown heading lines only**. The H1 is the chapter. Heading style decides the level: bold headings are sections, bold-italic headings are subsections.
   - Section IDs follow document order.
2. **Chunk.** Split within sections at paragraph boundaries, aiming for 300–500 tokens. A chunk never crosses a section boundary. Tables, numbered steps and warnings stay whole.
3. **E1 Document profile** (14 calls). Input: the full chapter body. Output: summary, scope, raw topics with evidence quotes, key entities.
4. **E2 Section and chunk enrichment** (about 1,440 calls, one per section, 16 at a time; a section under about 150 tokens is merged into the one before it). Input: the document profile summary plus the section text with chunk boundaries marked. Output:
   - section summary, `content_type`, raw topics `{label, evidence_quote}`, entities `{text, type, evidence_quote}`, keywords, questions answered;
   - for each chunk: `{chunk_id, context_line, topics[]}`. The context line is one or two sentences placing the chunk within its section.
5. **Grounding check** (in code, not an LLM). Every `evidence_quote` and entity `text` must appear in its source Markdown after normalization (case, whitespace and Markdown emphasis ignored).
   - On failure: retry once, asking for exact quotes. If it still fails, drop the item.
   - Dropped counts go into the report.
   - Reason: in testing, `gpt-4.1-mini` returned non-verbatim "quotes".
6. **E3 Topic-list normalization** (one or a few calls). Input: the grounded raw topic labels with counts. Output: a two-level topic list (`topic_id`, `label`, `parent_id`) and a mapping from each raw label to a canonical topic. Every canonical topic must come from at least one grounded raw topic.
7. **Apply topics** in code: map canonical `topic_id`s onto documents, sections and chunks.
8. **Embed** in batches of up to 128 inputs:
   - chunk text = `section_path + "\n" + context_line + "\n\n" + chunk_text`, with page markers stripped;
   - section text = `summary + questions`;
   - document text = profile summary.
9. **BM25 tokens** cover the chunk text plus the section's keywords and entity texts.
10. **Write** the pickle files and `report.json`.

## Canonical interface contract (frozen)
Contract type: **Python functions** (single-process Gradio app; no HTTP service).

### A. Index store — produced by Claude, read by everyone
| File | Content |
|---|---|
| `index/store.pkl` | The canonical index: **plain dicts, lists, str/int/float and NumPy arrays only, no custom classes**. Schema below. |
| `index/llm_cache.pkl` | Every LLM response, stored once: `{request_sha256: {model, prompt_version, request_kind, response_json, usage, created_at}}`. A rebuild replays from here instead of paying again. |
| `index/embed_cache.pkl` | `{sha256(model + "\n" + text): np.ndarray[float32, 1536]}` |
| `index/report.json` | `IndexReport`, readable by people. |

All four files are committed after the full build, so the worktrees use real data. Their combined size is estimated at about 30 MB.

```python
store = {
  "schema_version": 1, "built_at": str,
  "models": {"embedding": str, "embedding_dims": 1536, "llm": str},
  "documents": [ {doc_id, chapter, title, profile_summary, scope, topics: [topic_ref], entities: [entity], section_ids: [str]} ],
  "sections":  [ section_record ],   # specs/fixtures/section_record.json
  "chunks":    [ chunk_record ],     # specs/fixtures/chunk_record.json
  "taxonomy":  {"topics": [{topic_id, label, parent_id}], "raw_to_canonical": {raw_label: topic_id}},
  "vectors":   {"chunk": ndarray(Nc,1536,f32), "section": ndarray(Ns,1536,f32), "document": ndarray(14,1536,f32)},
  "vector_ids": {"chunk": [chunk_id], "section": [section_id], "document": [doc_id]},
  "bm25_tokens": {"chunk": [[str]]},   # aligned with vector_ids["chunk"]
}
# topic_ref = {"topic_id": str, "label": str, "evidence_quote": str}
# entity    = {"text": str, "type": <entity enum>, "evidence_quote": str}
```
- **IDs:** section `ch07.s012`, chunk `ch07.s012.c02`. A `doc_id` is the corpus file stem.
- **`content_type` enum:** procedure | concept | regulation | table | safety | calculation | definition | other
- **Entity `type` enum:** component | material | tool | process | regulation | part_number | specification | condition | safety_hazard | other
- **`enrichment.source`:** `"llm"` or `"failed"`. A section whose LLM step failed keeps its text, chunks and vectors, but has an empty summary and empty topics.

```python
class IndexReport(BaseModel):
    documents: int; sections: int; chunks: int; pages_covered: int; pages_expected: int
    sections_enriched: int; sections_failed: int
    topics_raw: int; topics_dropped_unsupported: int; taxonomy_size: int
    llm_calls: int; llm_cost_usd: float; embedding_inputs: int
    embedding_model: str; llm_model: str; built_at: str; failures: list[str]
```

Loader for everyone: `rag.store.load_store(path="index/store.pkl") -> dict`. It checks `schema_version` and the embedding model, and builds the in-memory BM25 index once.

### B. `rag.ask` — owned by Claude, called by the UI
```python
def ask(question: str, history: list[dict] | None = None,
        mode: Literal["fast", "verify"] = "fast") -> dict  # Answer, JSON-serialisable
```
**Pipeline:**
1. Validate the input.
2. **Intent call** (`LLM_MODEL`). This also rewrites a follow-up so it stands alone, using the last 6 turns. Output: `{primary, intents[], topics[topic_id], entities[], sub_questions[], keyword_query, needs_clarification}`.
3. **Search, for each sub-question:**
   - dense top 40 chunks, plus dense top 10 sections expanded to their chunks;
   - BM25 top 40;
   - merge with RRF (k=60);
   - apply a soft topic boost. Topics never filter results out.
   - Keep the top 30 candidates.
4. **Relevance assessment** (`LLM_MODEL`, one call per sub-question, sub-questions in parallel). Each candidate gets a score from 0 to 3 with a reason. Keep scores of 2 or more, at most 8 per sub-question.
5. **Context expansion.** Add the chunks on either side within the same section, or the whole section if it is under about 1,500 tokens. Total budget is about 12k tokens.
6. **Answer** (`ANSWER_MODEL`, structured JSON). It uses only the supplied passages, puts a `[n]` marker on every claim, and sets `insufficient_evidence` when the passages don't support an answer.
7. **Verify mode only:** `rag.verify.verify_coverage`.

**Answer shape** (see `specs/fixtures/answer_fast.json` and `answer_verify.json`):

| Field | Type | Notes |
|---|---|---|
| `answer_markdown` | str | Inline `[n]` markers |
| `citations` | list | `{n, section_id, doc_id, chapter, section_path, page_label, snippet, relevance}`; `relevance` is 0–3 from step 4 |
| `intent` | obj | `{primary, intents[], topics[], entities[{text,type}], needs_clarification: str\|null}` |
| `sub_questions` | list | `{question, citation_ns[]}` |
| `coverage` | obj\|null | `null` in fast mode; `Coverage` in verify mode |
| `insufficient_evidence` | bool | |
| `mode` | str | `"fast"` or `"verify"` |
| `latency_ms` | int | |
| `error` | obj\|null | `{code, message}` |

- **`intent.primary` enum:** fact_lookup | definition | how_to | troubleshooting | comparison | calculation | regulatory | navigation | multi_hop | out_of_scope
- **`error.code` enum:** `empty_question`, `question_too_long` (over 2,000 characters), `index_missing`, `provider_unavailable`, `timeout`
- **Never raises.** Errors come back in `error`.
- **Timeouts:** fast mode 60 s overall. Verify mode adds at most 45 s. Each provider call gets 30 s and 2 retries.
- **Degraded mode:**
  - If the LLM is unavailable but embeddings work, return the top passages from dense + BM25 + RRF as the answer, with `error.code = provider_unavailable`.
  - If embeddings are unavailable, use BM25 only.

### C. `rag.verify.verify_coverage` — owned by Codex, called by `ask` in verify mode
```python
def verify_coverage(question: str, intent: dict, citations: list[dict],
                    store: dict) -> dict  # Coverage
```
**Coverage:**
```json
{"chapters_cited": [8, 9], "chapters_relevant": [2, 8, 9],
 "missed_sections": [{"section_id": "...", "section_path": "...", "page_label": "...", "reason": "..."}],
 "complete": false}
```
- Sweeps **every** section in `store["sections"]` using its topics, entities, keywords, questions, summary and section vector.
- Takes the uncited candidates (top 20) and asks `LLM_MODEL` to judge relevance.
- Must finish within the verify timeout.
- Hosted inference only.

### Mock fixtures
- `specs/fixtures/answer_fast.json`
- `specs/fixtures/answer_verify.json`
- `specs/fixtures/section_record.json`
- `specs/fixtures/chunk_record.json`

These are labeled MOCK; their content is illustrative, not verified handbook output.

## Acceptance criteria and failure handling
1. **Index coverage and grounding.** Given the 14 chapter files, when `python -m ingest.build` runs, then `report.json` shows:
   - all 14 documents and every chapter page covered;
   - every chunk inside exactly one section;
   - every kept `evidence_quote` and entity text found verbatim, after normalization, in its source Markdown;
   - every canonical topic traceable to at least one grounded raw topic;
   - a vector shape of (N, 1536) for chunks and sections.
2. **No prohibited inputs, no local inference.** Given the built store, then:
   - every `doc_id` matches `ch\d\d_*`;
   - ingestion never opens `00_front-matter.md`, `index.md`, `glossary.md`, `manifest.json` or `DATA/`;
   - no repo code imports `chromadb`, `onnxruntime`, `fastembed`, `sentence_transformers` or `torch`.
3. **Multi-chapter answer.** Given a nested question whose ground truth spans two or more chapters, when `ask(mode="fast")` runs, then the citations include sections from those chapters, as measured by criterion 5.
4. **Verify flags misses.** Given a question where a relevant section is not cited, when `ask(mode="verify")` runs, then `coverage.missed_sections` lists it with a page label and `complete` is false. When nothing is missed, `complete` is true.
5. **Measured recall.** Given `evals/golden.jsonl`, when `python -m evals.recall` runs, then it prints section-level and chapter-level Recall@k for fast and verify modes.
   - The golden set has 15 or more nested questions, written by hand or generated from chapter text.
   - Ground truth comes from `LLM_MODEL` reading the full chapter bodies (sections marked) and marking the relevant `section_id`s with verified quotes.
   - The user spot-checks at least 5 questions.
   - Actual numbers are reported; no target is invented.
   - No index, table of contents or glossary is used.

**Failure cases:**
- **Not covered by the handbook** (e.g. "torque for a Cessna 172 main wheel axle nut"): `insufficient_evidence` is true and no value is invented.
- **OpenRouter error or rate limit during ingestion:** the build continues; failed sections are marked `"failed"`; re-running replays `llm_cache.pkl` and `embed_cache.pkl` and calls only what is missing.
- **Ungrounded LLM output:** topics or entities whose quotes aren't found in the source are dropped and counted. They never reach the store.
- **Empty or over-long question:** the matching `error.code` is returned; the UI shows it without crashing.

**First smoke test:** run `python -m ingest.build --only ch13`. Expect `report.json` to show 1 document and 8 pages, with grounding counts. Then `ask("What may a mechanic with an airframe rating approve for return to service?")` should return citations with page labels 13-x.

**Evidence to record:** command output, the `report.json` summary, demo Q&A, recall table, commit SHAs.

## CLAUDE OWNERSHIP
- **Worktree:** `C:/Users/amber/code/fde-coding-challenge`, branch `main`.
- **Owns:** `ingest/`, `rag/` (except `rag/verify.py`), `index/` (generated), `scripts/`, `requirements.txt`, `README.md`, and integration.
- **First artifact (~15 min):** `ingest.build --only ch13` writes `store.pkl`, the two cache files and `report.json` with grounded LLM enrichment. Commit and announce the SHA.
- **Handoff:** full store committed, then `rag.ask` working in fast mode.

## CURSOR OWNERSHIP
- **Worktree:** `C:/Users/amber/code/fde-coding-challenge/.worktrees/cursor-isolated-work`, branch `cursor/isolated-work`.
- **Owns:** `ui/` only.
- **Builds:** a Gradio chat app (`python -m ui.app`) with a Fast/Verify toggle, a citations panel with relevance, a coverage panel, and visible sub-questions. Uses `rag.ask` when importable; `MOCK=1` uses the fixtures instead.
- **States:** idle, loading, error, success, insufficient evidence.
- **First artifact (~15 min):** a mock UI rendering both fixtures.
- **Handoff:** commit SHA and a screenshot.

## CODEX OWNERSHIP (ACTIVE)
- **Worktree:** `C:/Users/amber/.codex/worktrees/fde-challenge-work/fde-coding-challenge`, branch `codex/fde-challenge-work`.
- **Owns:** `rag/verify.py`, `evals/`, `tests/`.
- **Builds:**
  - `verify_coverage` per contract C;
  - contract tests for the fixtures and the `store.pkl` schema;
  - the prohibited-input and no-local-inference tests (criterion 2);
  - `evals/golden.jsonl` with LLM-judged ground truth (criterion 5);
  - `python -m evals.recall`.
- **First artifact (~15 min):** contract tests plus `verify_coverage` running against a small `store`-shaped dict built from the fixtures.
- **Activation:** yes. The user chose three workers.

## Integration / release protocol
- **Baseline SHA:** recorded in the dispatch handoff after the freeze commit. The existing worktrees are at `f1c96c4` and must merge `main` at the baseline.
- **Worktree locations:** confirmed with `git worktree list`.
- **Checkpoints:** about 15 minutes after dispatch, and again at about 30 minutes. Claude integrates and reviews.
- **Spec changes:** go through `docs/decisions/CHANGE_REQUEST.md`, need user approval, and are applied as v2.
- **Priority:** a working local app first. The Gradio share link is optional; Render is out of scope.
- **Feature freeze:** about 10 minutes before the end. After that, evaluation and demo only.
