"""rag.ask: intent -> per-sub-question hybrid search (dense + BM25 + RRF) -> LLM relevance
assessment -> context expansion -> grounded answer with citations (MASTER_SPEC contract B,
plus the v1.1 traceability fields in docs/decisions/CHANGE_REQUEST.md).
Never raises; errors are returned in the `error` field.
"""
import json
import logging
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import numpy as np

from rag.llm import ROOT, ProviderError, chat_json, embed, load_env, model_name
from rag.store import StoreError, load_store
from rag.text import tokenize

INTENTS = ["fact_lookup", "definition", "how_to", "troubleshooting", "comparison", "calculation",
           "regulatory", "navigation", "multi_hop", "out_of_scope"]
ENTITY_TYPES = ["component", "material", "tool", "process", "regulation", "part_number",
                "specification", "condition", "safety_hazard", "other"]
MAX_QUESTION_CHARS = 2000
HISTORY_TURNS = 6
RRF_K = 60
DENSE_CHUNKS, DENSE_SECTIONS, BM25_TOP, CANDIDATES, KEEP_PER_SUBQ = 40, 10, 40, 30, 8
TOPIC_BOOST = 0.004
SMALL_SECTION_TOKENS = 1500
CONTEXT_BUDGET_TOKENS = 12000
FAST_TIMEOUT_S, CALL_TIMEOUT_S = 60, 30
LOG_PATH = ROOT / "logs" / "queries.jsonl"

log = logging.getLogger("rag")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s rag %(message)s", "%H:%M:%S"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)

_store, _store_lock, _log_lock = None, threading.Lock(), threading.Lock()


def _obj(props):
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


STR = {"type": "string"}
INTENT_SCHEMA = _obj({
    "standalone_question": STR,
    "primary": {"type": "string", "enum": INTENTS},
    "intents": {"type": "array", "items": {"type": "string", "enum": INTENTS}},
    "topics": {"type": "array", "items": STR},
    "entities": {"type": "array", "items": _obj({"text": STR, "type": {"type": "string", "enum": ENTITY_TYPES}})},
    "sub_questions": {"type": "array", "items": STR},
    "keyword_query": STR,
    "needs_clarification": {"type": ["string", "null"]},
})
RELEVANCE_SCHEMA = _obj({"scores": {"type": "array", "items": _obj({
    "chunk_id": STR, "score": {"type": "integer", "enum": [0, 1, 2, 3]}, "reason": STR})}})
ANSWER_SCHEMA = _obj({
    "answer_markdown": STR,
    "insufficient_evidence": {"type": "boolean"},
    "sub_answers": {"type": "array", "items": _obj({"question": STR, "citation_ns": {"type": "array", "items": {"type": "integer"}}})},
})


class Tracer:
    """Collects one entry per pipeline step and streams it to an optional callback."""

    def __init__(self, request_id, on_step=None):
        self.request_id, self.on_step = request_id, on_step
        self.steps, self.lock = [], threading.Lock()

    def add(self, step, tool, detail, started, *, model=None, status="ok", cost=0.0):
        entry = {"step": step, "tool": tool, "model": model, "detail": detail,
                 "ms": int((time.time() - started) * 1000), "status": status, "cost_usd": round(cost, 6)}
        with self.lock:
            self.steps.append(entry)
        log.info("%s %-22s %-22s %5dms %s %s", self.request_id, step, tool, entry["ms"], status, detail[:160])
        if self.on_step:
            try:
                self.on_step(entry)
            except Exception:
                pass
        return entry

    @property
    def cost(self):
        return round(sum(s["cost_usd"] for s in self.steps), 6)


def _cost(record):
    return float((record or {}).get("usage", {}).get("cost") or 0)


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            load_env()
            _store = load_store()
        return _store


def source_link(page_label, doc_id):
    """Display-only link target: the chapter PDF and the page within it (label 13-4 -> page 4)."""
    try:
        page = int(str(page_label).rsplit("-", 1)[1])
    except (IndexError, ValueError):
        page = 1
    return {"pdf_file": f"DATA/chapters/{doc_id}.pdf", "pdf_file_page": page}


def _content_text(content):
    """Chat UIs may send content as a string or a list of parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return "" if content is None else str(content)


def classify_intent(question, history, store):
    turns = (history or [])[-HISTORY_TURNS:]
    convo = "\n".join(f"{t.get('role', 'user')}: {_content_text(t.get('content'))[:1000]}"
                      for t in turns if isinstance(t, dict))
    topics = "\n".join(f"{t['topic_id']}\t{t['label']}" for t in store["taxonomy"]["topics"] if t["parent_id"])
    messages = [
        {"role": "system", "content": (
            "You analyse questions for a search system over the FAA Aviation Maintenance Technician General "
            "Handbook. Rewrite follow-ups into a standalone question using the conversation. Split nested or "
            "multi-part questions into 1-4 self-contained sub_questions (one if the question is simple). "
            "topics: topic_ids from the list that the question is about (may be empty). keyword_query: exact "
            "terms, part numbers and regulation references for keyword search. needs_clarification: a short "
            "question to ask the user only if the question cannot be answered without it, else null.")},
        {"role": "user", "content": f"Topic list:\n{topics}\n\nConversation so far:\n{convo or '(none)'}\n\nQuestion: {question}"},
    ]
    out, rec = chat_json(messages, "intent", INTENT_SCHEMA, prompt_version="intent.v1", kind="intent",
                         max_tokens=1500, timeout=CALL_TIMEOUT_S)
    valid = {t["topic_id"] for t in store["taxonomy"]["topics"]}
    out["topics"] = [t for t in out["topics"] if t in valid]
    out["sub_questions"] = [q for q in out["sub_questions"] if q.strip()][:4] or [out["standalone_question"] or question]
    return out, rec


def search(sub_question, query_vec, keyword_query, intent_topics, store):
    """Hybrid search for one sub-question. Returns (candidates, provenance, stats):
    candidates = [(chunk_idx, rrf_score)] best first; provenance[idx] = ranks per retriever."""
    prov, rankings = {}, []
    stats = {"dense": 0, "section": 0, "bm25": 0}
    if query_vec is not None:
        dense = list(np.argsort(-(store["vectors"]["chunk"] @ query_vec))[:DENSE_CHUNKS])
        rankings.append(dense)
        for r, i in enumerate(dense):
            prov.setdefault(int(i), {})["dense_rank"] = r + 1
        top_sections = np.argsort(-(store["vectors"]["section"] @ query_vec))[:DENSE_SECTIONS]
        via_sections = []
        for sr, si in enumerate(top_sections):
            for cid in store["sections"][si]["chunk_ids"]:
                i = store["chunk_index"][cid]
                via_sections.append(i)
                prov.setdefault(i, {}).setdefault("section_rank", sr + 1)
        rankings.append(via_sections)
        stats["dense"], stats["section"] = len(dense), len(top_sections)
    tokens = tokenize(sub_question + " " + keyword_query)
    if tokens:
        bm25 = store["bm25"].get_scores(tokens)
        top = [int(i) for i in np.argsort(-bm25)[:BM25_TOP] if bm25[i] > 0]
        rankings.append(top)
        for r, i in enumerate(top):
            prov.setdefault(i, {})["bm25_rank"] = r + 1
        stats["bm25"] = len(top)
    scores = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[int(idx)] = scores.get(int(idx), 0.0) + 1.0 / (RRF_K + rank + 1)
    wanted = set(intent_topics)
    if wanted:
        for idx in scores:  # soft boost only; topics never filter
            scores[idx] += TOPIC_BOOST * len(wanted & set(store["chunks"][idx]["topics"]))
    candidates = sorted(scores.items(), key=lambda kv: -kv[1])[:CANDIDATES]
    for idx, s in candidates:
        prov[idx]["rrf_score"] = round(s, 5)
    return candidates, prov, stats


def assess_relevance(sub_question, candidates, store):
    """LLM relevance assessment (replaces a local cross-encoder). Returns ({chunk_idx: (score, reason)}, record)."""
    passages = "\n\n".join(
        f"[{store['chunks'][i]['chunk_id']}] {store['chunks'][i]['section_path']}\n{store['chunks'][i]['text'][:1200]}"
        for i, _ in candidates)
    messages = [
        {"role": "system", "content": (
            "Score how well each passage helps answer the question, using only the passage text. "
            "3 = directly answers part of it, 2 = relevant supporting detail, 1 = same topic but not useful, "
            "0 = unrelated. Return one score per chunk_id.")},
        {"role": "user", "content": f"Question: {sub_question}\n\nPassages:\n{passages}"},
    ]
    out, rec = chat_json(messages, "relevance", RELEVANCE_SCHEMA, prompt_version="relevance.v1", kind="relevance",
                         max_tokens=4000, timeout=CALL_TIMEOUT_S)
    by_id = {store["chunks"][i]["chunk_id"]: i for i, _ in candidates}
    return {by_id[s["chunk_id"]]: (s["score"], s["reason"]) for s in out["scores"] if s["chunk_id"] in by_id}, rec


def expand_context(selected, store):
    """For each selected chunk, add its section neighbours (or the whole section if small), within budget."""
    budget = CONTEXT_BUDGET_TOKENS
    contexts = {}
    for idx in selected:
        chunk = store["chunks"][idx]
        section = store["sections"][store["section_index"][chunk["section_id"]]]
        sec_idxs = [store["chunk_index"][c] for c in section["chunk_ids"]]
        if sum(store["chunks"][i]["token_count"] for i in sec_idxs) <= SMALL_SECTION_TOKENS:
            window = sec_idxs
        else:
            pos = sec_idxs.index(idx)
            window = sec_idxs[max(0, pos - 1):pos + 2]
        cost = sum(store["chunks"][i]["token_count"] for i in window)
        if cost > budget:
            window, cost = [idx], chunk["token_count"]
        if cost > budget:
            break
        budget -= cost
        contexts[idx] = "\n\n".join(store["chunks"][i]["text"] for i in window)
    return contexts, CONTEXT_BUDGET_TOKENS - budget


def _citation(n, idx, store, relevance, retrieval, passage):
    c = store["chunks"][idx]
    return {"n": n, "section_id": c["section_id"], "doc_id": c["doc_id"], "chapter": c["chapter"],
            "section_path": c["section_path"], "page_label": c["page_label"],
            "snippet": " ".join(c["text"].split())[:240], "relevance": relevance,
            "chunk_id": c["chunk_id"], "pdf_page": c["pdf_page"],
            "source": source_link(c["page_label"], c["doc_id"]),
            "retrieval": retrieval, "passage": passage}


def _public_intent(intent):
    return {"primary": intent["primary"], "intents": intent["intents"], "topics": intent["topics"],
            "entities": intent["entities"], "needs_clarification": intent["needs_clarification"]}


def _write_log(result, question):
    record = {"ts": datetime.now(timezone.utc).isoformat(), "request_id": result["request_id"],
              "question": question, "mode": result["mode"], "latency_ms": result["latency_ms"],
              "cost_usd": result["cost_usd"], "error": result["error"],
              "insufficient_evidence": result["insufficient_evidence"],
              "intent": result["intent"], "citations": [c["chunk_id"] for c in result["citations"]],
              "trace": result["trace"]}
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _log_lock, open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("could not write %s: %s", LOG_PATH, e)


def ask(question, history=None, mode="fast", *, on_step=None):
    started = time.time()
    mode = mode if mode in ("fast", "verify") else "fast"
    tracer = Tracer(uuid.uuid4().hex[:8], on_step)

    def finish(**fields):
        result = {"answer_markdown": "", "citations": [], "intent": None, "sub_questions": [], "coverage": None,
                  "insufficient_evidence": False, "mode": mode, "latency_ms": 0, "error": None,
                  "request_id": tracer.request_id, "trace": tracer.steps, "cost_usd": 0.0}
        result.update(fields)
        result["latency_ms"] = int((time.time() - started) * 1000)
        result["cost_usd"] = tracer.cost
        tracer.add("done", "rag.ask", f"{result['latency_ms']} ms total, ${result['cost_usd']:.4f}, "
                   f"{len(result['citations'])} citations", started,
                   status="error" if result["error"] else "ok")
        _write_log(result, question)
        return result

    t = time.time()
    if not question or not question.strip():
        tracer.add("validate", "rag.ask", "empty question", t, status="error")
        return finish(error={"code": "empty_question", "message": "Please enter a question."})
    if len(question) > MAX_QUESTION_CHARS:
        tracer.add("validate", "rag.ask", f"{len(question)} chars > {MAX_QUESTION_CHARS}", t, status="error")
        return finish(error={"code": "question_too_long", "message": f"Questions are limited to {MAX_QUESTION_CHARS} characters."})
    try:
        store = get_store()
    except (StoreError, OSError) as e:
        tracer.add("load_index", "pickle", str(e), t, status="error")
        return finish(error={"code": "index_missing", "message": str(e)})
    tracer.add("load_index", "pickle (in memory)",
               f"{len(store['chunks'])} chunks, {len(store['sections'])} sections, {len(store['documents'])} chapters", t)

    error = None
    t = time.time()
    try:
        intent, rec = classify_intent(question, history, store)
        tracer.add("intent", "openrouter.chat", f"{intent['primary']}; {len(intent['sub_questions'])} sub-questions; "
                   f"topics {intent['topics'][:4]}", t, model=rec["model"], cost=_cost(rec))
    except ProviderError as e:
        error = {"code": "provider_unavailable", "message": f"Intent step unavailable: {e}"}
        intent = {"standalone_question": question, "primary": "multi_hop", "intents": [], "topics": [],
                  "entities": [], "sub_questions": [question], "keyword_query": "", "needs_clarification": None}
        tracer.add("intent", "openrouter.chat", str(e), t, model=model_name("LLM_MODEL"), status="error")
    sub_questions = intent["sub_questions"]

    t = time.time()
    try:
        query_vecs = embed(sub_questions, model=model_name("EMBEDDING_MODEL"), timeout=CALL_TIMEOUT_S)
        tracer.add("embed_query", "openrouter.embeddings", f"{len(sub_questions)} vectors x 1536", t,
                   model=model_name("EMBEDDING_MODEL"))
    except ProviderError as e:
        error = error or {"code": "provider_unavailable", "message": f"Embeddings unavailable, keyword search only: {e}"}
        query_vecs = [None] * len(sub_questions)
        tracer.add("embed_query", "openrouter.embeddings", f"failed, BM25 only: {e}", t,
                   model=model_name("EMBEDDING_MODEL"), status="error")

    results = []
    for qi, (q, v) in enumerate(zip(sub_questions, query_vecs)):
        t = time.time()
        candidates, prov, stats = search(q, v, intent["keyword_query"], intent["topics"], store)
        results.append((candidates, prov))
        tracer.add(f"search[{qi + 1}]", "numpy.dense + rank_bm25 + rrf",
                   f"dense {stats['dense']} chunks, {stats['section']} sections, BM25 {stats['bm25']} -> "
                   f"RRF top {len(candidates)} for '{q[:60]}'", t)

    def assess(args):
        qi, q, candidates = args
        t0 = time.time()
        try:
            scored, rec = assess_relevance(q, candidates, store)
            kept = sum(1 for s, _ in scored.values() if s >= 2)
            tracer.add(f"relevance[{qi + 1}]", "openrouter.chat", f"scored {len(scored)}, kept {kept} (score>=2)",
                       t0, model=rec["model"], cost=_cost(rec))
            return scored
        except ProviderError as e:
            tracer.add(f"relevance[{qi + 1}]", "openrouter.chat", f"failed, using RRF order: {e}", t0,
                       model=model_name("LLM_MODEL"), status="error")
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        assessments = list(pool.map(assess, [(qi, q, r[0]) for qi, (q, r) in enumerate(zip(sub_questions, results))]))

    # Keep relevant chunks per sub-question, best first; remember provenance for each.
    selected, relevance, retrieval = [], {}, {}
    for qi, ((candidates, prov), scored) in enumerate(zip(results, assessments)):
        if scored is None:
            error = error or {"code": "provider_unavailable", "message": "Relevance assessment unavailable; using fused ranking."}
            keep = [(i, 2, "relevance step unavailable; kept by RRF rank") for i, _ in candidates[:KEEP_PER_SUBQ]]
        else:
            ranked = sorted(((i, scored[i][0], s, scored[i][1]) for i, s in candidates if i in scored and scored[i][0] >= 2),
                            key=lambda r: (-r[1], -r[2]))
            keep = [(i, sc, reason) for i, sc, _, reason in ranked[:KEEP_PER_SUBQ]]
        for i, sc, reason in keep:
            if sc > relevance.get(i, -1):
                relevance[i] = sc
                retrieval[i] = {"sub_question": sub_questions[qi], "dense_rank": prov[i].get("dense_rank"),
                                "section_rank": prov[i].get("section_rank"), "bm25_rank": prov[i].get("bm25_rank"),
                                "rrf_score": prov[i].get("rrf_score"), "relevance_reason": reason}
            if i not in selected:
                selected.append(i)

    if time.time() - started > FAST_TIMEOUT_S:
        return finish(intent=_public_intent(intent),
                      error={"code": "timeout", "message": "Search took too long; please try a narrower question."})

    t = time.time()
    contexts, used_tokens = expand_context(selected, store)
    tracer.add("context", "rag.expand_context", f"{len(contexts)} passages, ~{used_tokens} of {CONTEXT_BUDGET_TOKENS} tokens", t)
    numbered = list(contexts)
    citations = [_citation(n + 1, idx, store, relevance[idx], retrieval[idx], contexts[idx]) for n, idx in enumerate(numbered)]
    insufficient = not numbered
    answer_md = ""
    sub_out = [{"question": q, "citation_ns": [c["n"] for c in citations if c["retrieval"]["sub_question"] == q]}
               for q in sub_questions]

    if numbered:
        passages = "\n\n".join(f"[{c['n']}] {c['section_path']} (page {c['page_label']})\n{c['passage']}" for c in citations)
        messages = [
            {"role": "system", "content": (
                "You answer questions for aircraft maintenance staff using only the numbered passages from the FAA "
                "Aviation Maintenance Technician General Handbook. Cover every part of the question. Put a [n] "
                "citation after every claim. Include any warnings or cautions the passages give. If the passages do "
                "not cover a part of the question, say so plainly for that part. If they support no answer at all, "
                "set insufficient_evidence to true. Never invent values, limits, torque figures or procedures.")},
            {"role": "user", "content": f"Question: {intent['standalone_question'] or question}\n\nSub-questions: {sub_questions}\n\nPassages:\n{passages}"},
        ]
        t = time.time()
        try:
            out, rec = chat_json(messages, "answer", ANSWER_SCHEMA, model=model_name("ANSWER_MODEL"),
                                 prompt_version="answer.v1", kind="answer", max_tokens=3000, timeout=CALL_TIMEOUT_S)
            answer_md, insufficient = out["answer_markdown"], out["insufficient_evidence"]
            valid_ns = {c["n"] for c in citations}
            sub_out = [{"question": s["question"], "citation_ns": [n for n in s["citation_ns"] if n in valid_ns]}
                       for s in out["sub_answers"]] or sub_out
            used = {int(n) for n in re.findall(r"\[(\d+)\]", answer_md)}
            if used:
                citations = [c for c in citations if c["n"] in used]
            tracer.add("answer", "openrouter.chat", f"{len(answer_md)} chars, cites {sorted(used)}; "
                       f"insufficient_evidence={insufficient}", t, model=rec["model"], cost=_cost(rec))
        except ProviderError as e:
            error = {"code": "provider_unavailable", "message": f"Answer model unavailable; showing the best passages: {e}"}
            answer_md = "\n\n".join(f"[{c['n']}] {c['section_path']} (p. {c['page_label']}): {c['snippet']}" for c in citations)
            tracer.add("answer", "openrouter.chat", str(e), t, model=model_name("ANSWER_MODEL"), status="error")
    else:
        answer_md = "The handbook passages found do not support an answer to this question."
        tracer.add("answer", "openrouter.chat", "skipped: no relevant passages", time.time(),
                   model=model_name("ANSWER_MODEL"), status="skipped")

    coverage = None
    if mode == "verify":
        t = time.time()
        try:
            from rag.verify import verify_coverage
            coverage = verify_coverage(question, _public_intent(intent), citations, store)
            for m in coverage.get("missed_sections", []):
                sec = store["sections"][store["section_index"][m["section_id"]]]
                m["source"] = source_link(m["page_label"], sec["doc_id"])
            tracer.add("verify", "rag.verify (metadata sweep + openrouter.chat judge)",
                       f"{len(store['sections'])} sections swept; relevant chapters {coverage['chapters_relevant']}; "
                       f"{len(coverage['missed_sections'])} missed", t, model="openai/gpt-4.1-mini")
        except ImportError:
            error = error or {"code": "provider_unavailable", "message": "Verify sweep is not installed."}
            tracer.add("verify", "rag.verify", "not installed", t, status="error")
        except TimeoutError as e:
            error = error or {"code": "timeout", "message": f"Verify sweep timed out: {e}"}
            tracer.add("verify", "rag.verify", str(e), t, status="error")
        except Exception as e:  # never raise to the UI
            error = error or {"code": "provider_unavailable", "message": f"Verify sweep unavailable: {e}"}
            tracer.add("verify", "rag.verify", str(e), t, status="error")

    return finish(answer_markdown=answer_md, citations=citations, intent=_public_intent(intent),
                  sub_questions=sub_out, coverage=coverage, insufficient_evidence=insufficient, error=error)
