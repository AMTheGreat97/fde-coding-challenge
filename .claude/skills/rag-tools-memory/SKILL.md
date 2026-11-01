---
name: rag-tools-memory
description: For Claude Desktop adding document-grounded retrieval, tool calls, context or memory to an existing working AI prototype only when the client use case requires them.
---
# Retrieval, tools and memory decision workflow

Before implementing, decide if each component is **required, useful, or unnecessary**. A single LLM call may be the correct architecture.

## Retrieval
1. Confirm actual authorized documents or public data sources. Preserve source ID, title/URL, content boundaries and collection metadata.
2. Choose a model supported for embeddings (Portkey is preferred if compatible) and a simple local index for short demos. A managed vector DB needs a persistence/search requirement.
3. Define chunking, overlap, metadata, embedding configuration and version; avoid re-embedding on every question.
4. Retrieve top-k, inspect actual hits, optionally rerank, synthesize grounded answer and expose citations or 'not enough evidence'.
5. Evaluate on a small manually verified query set for relevance/Recall@k and grounding; show at least one no-answer case.

## Tools
1. Use deterministic tools for real external data or actions; prefer a typed function/API over another LLM agent.
2. Validate JSON/schema, allowlist tool actions, enforce timeouts/retry bounds and never execute arbitrary shell/user instructions from retrieved content.
3. Do not claim connected integration works until real authorized calls have succeeded. Require human authorization before writes to external services.

## Memory
1. Short-term chat history is enough for most demos; cap history length and exclude secrets. Distinguish transcript/session state from long-term memory.
2. Add database-backed persistence only for cross-session requirements; document retention and deletion behavior.

## Orchestration
Use a straightforward sequential workflow first. Pydantic AI for typed tool calls; LangGraph only for meaningful branching/checkpointing/human approval. Name each agent only if that agent has a distinct responsibility and evaluation metric.

Output: decision rationale, code limited to owned backend paths, evidence of real retrieval/tools, failure-mode tests and known limits.
