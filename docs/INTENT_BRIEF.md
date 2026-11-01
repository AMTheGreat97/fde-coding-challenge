# Intent Brief — Aviation Maintenance Handbook Assistant

**Client / sponsor:** An aircraft maintenance operations organization (assumed; simulated case).
**Primary end user:** The person running maintenance operations for aircraft (stated).
**Current job-to-be-done:** Answering maintenance questions by searching the FAA Aviation Maintenance Technician General Handbook.
**Core pain:** Questions are nested and their answers span several chapters, so a single search misses parts (stated).
**Desired outcome:** A chat assistant whose answers capture everything the handbook says, with citations (stated).
**One demonstrable user journey:** Ask a multi-part question → get a cited answer from every relevant chapter → run a corpus-wide check that confirms nothing relevant was missed.
**Candidate must-haves (max 3):**
1. Metadata-rich ingestion of the Markdown chapters — the main focus (stated).
2. Fast, cited answers to nested, multi-chapter questions (stated).
3. A corpus-wide completeness check (stated).
**Explicit non-goals:** Figures/images, aircraft-specific manuals, access control, exam mode, deployment, local models (inferred / stated).
**Data and access reality:** Only the 14 Markdown chapter bodies may be used. The table of contents, book index, glossary and PDF navigation data are prohibited (stated). The OpenRouter key works (observed).
**Critical constraints:** 60-minute build; hosted inference through OpenRouter only; pickle storage, no database; every topic supported by Markdown text (all stated). Safety-critical domain; keys only through environment variables.
**Success signal:** Multi-chapter answers cite every relevant section. Measured as recall against ground truth from an LLM reading the full chapters, spot-checked by the user (inferred).
**Unacceptable failure:** Stating something the handbook does not support, or silently leaving out a relevant chapter (assumed).
**Decision record:**
- Confirmed by stakeholder: user, pain, recall priority, fast-plus-verify approach, 60 minutes, ingestion focus, OpenRouter with OpenAI models, Markdown-only corpus, pickle storage.
- Observed / supplied: 14 chapter files with page markers; working key.
- Assumed by FDE: unacceptable failure, non-goals, glossary excluded, LLM-judged recall.
- Unresolved / defer to real client: acceptable answer latency.
**Handoff to architect:** Scope the smallest working MVP against the desired outcome; establish API contract, ≥3 acceptance criteria, ≥2 failure modes, and assign independent workstreams.
