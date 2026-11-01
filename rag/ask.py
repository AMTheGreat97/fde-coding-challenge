"""rag.ask: intent -> per-sub-question hybrid search (dense + BM25 + RRF) -> LLM relevance
assessment -> context expansion -> grounded answer with citations (MASTER_SPEC contract B).
Never raises; errors are returned in the `error` field.
"""
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from rag.llm import ProviderError, chat_json, embed, load_env, model_name
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

_store, _store_lock = None, threading.Lock()


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


def get_store():
    global _store
    with _store_lock:
        if _store is None:
            load_env()
            _store = load_store()
        return _store


def _result(mode, started, **fields):
    base = {"answer_markdown": "", "citations": [], "intent": None, "sub_questions": [], "coverage": None,
            "insufficient_evidence": False, "mode": mode, "latency_ms": 0, "error": None}
    base.update(fields)
    base["latency_ms"] = int((time.time() - started) * 1000)
    return base


def _error(code, message):
    return {"code": code, "message": message}


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
    out, _ = chat_json(messages, "intent", INTENT_SCHEMA, prompt_version="intent.v1", kind="intent",
                       max_tokens=1500, timeout=CALL_TIMEOUT_S)
    valid = {t["topic_id"] for t in store["taxonomy"]["topics"]}
    out["topics"] = [t for t in out["topics"] if t in valid]
    out["sub_questions"] = [q for q in out["sub_questions"] if q.strip()][:4] or [out["standalone_question"] or question]
    return out


def _rrf(rankings):
    scores = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking):
            scores[idx] = scores.get(idx, 0.0) + 1.0 / (RRF_K + rank + 1)
    return scores


def search(sub_question, query_vec, keyword_query, intent_topics, store):
    """Hybrid search for one sub-question; returns [(chunk_idx, rrf_score)] best first."""
    rankings = []
    if query_vec is not None:
        rankings.append(list(np.argsort(-(store["vectors"]["chunk"] @ query_vec))[:DENSE_CHUNKS]))
        top_sections = np.argsort(-(store["vectors"]["section"] @ query_vec))[:DENSE_SECTIONS]
        via_sections = []
        for si in top_sections:
            for cid in store["sections"][si]["chunk_ids"]:
                via_sections.append(store["chunk_index"][cid])
        rankings.append(via_sections)
    tokens = tokenize(sub_question + " " + keyword_query)
    if tokens:
        bm25 = store["bm25"].get_scores(tokens)
        rankings.append([i for i in np.argsort(-bm25)[:BM25_TOP] if bm25[i] > 0])
    scores = _rrf(rankings)
    wanted = set(intent_topics)
    if wanted:
        for idx in scores:  # soft boost only; topics never filter
            scores[idx] += TOPIC_BOOST * len(wanted & set(store["chunks"][idx]["topics"]))
    return sorted(scores.items(), key=lambda kv: -kv[1])[:CANDIDATES]


def assess_relevance(sub_question, candidates, store):
    """LLM relevance assessment (replaces a local cross-encoder). Returns {chunk_idx: (score, reason)}."""
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
    out, _ = chat_json(messages, "relevance", RELEVANCE_SCHEMA, prompt_version="relevance.v1", kind="relevance",
                       max_tokens=4000, timeout=CALL_TIMEOUT_S)
    by_id = {store["chunks"][i]["chunk_id"]: i for i, _ in candidates}
    return {by_id[s["chunk_id"]]: (s["score"], s["reason"]) for s in out["scores"] if s["chunk_id"] in by_id}


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
    return contexts


def _citation(n, idx, store, relevance):
    c = store["chunks"][idx]
    snippet = " ".join(c["text"].split())[:240]
    return {"n": n, "section_id": c["section_id"], "doc_id": c["doc_id"], "chapter": c["chapter"],
            "section_path": c["section_path"], "page_label": c["page_label"], "snippet": snippet,
            "relevance": relevance}


def ask(question, history=None, mode="fast"):
    started = time.time()
    mode = mode if mode in ("fast", "verify") else "fast"
    if not question or not question.strip():
        return _result(mode, started, error=_error("empty_question", "Please enter a question."))
    if len(question) > MAX_QUESTION_CHARS:
        return _result(mode, started, error=_error("question_too_long", f"Questions are limited to {MAX_QUESTION_CHARS} characters."))
    try:
        store = get_store()
    except (StoreError, OSError) as e:
        return _result(mode, started, error=_error("index_missing", str(e)))

    error = None
    try:
        intent = classify_intent(question, history, store)
    except ProviderError as e:
        error = _error("provider_unavailable", f"Intent step unavailable: {e}")
        intent = {"standalone_question": question, "primary": "multi_hop", "intents": [], "topics": [],
                  "entities": [], "sub_questions": [question], "keyword_query": "", "needs_clarification": None}
    sub_questions = intent["sub_questions"]

    try:
        query_vecs = embed(sub_questions, model=model_name("EMBEDDING_MODEL"), timeout=CALL_TIMEOUT_S)
    except ProviderError as e:
        error = error or _error("provider_unavailable", f"Embeddings unavailable, keyword search only: {e}")
        query_vecs = [None] * len(sub_questions)

    results = [search(q, v, intent["keyword_query"], intent["topics"], store) for q, v in zip(sub_questions, query_vecs)]

    def assess(args):
        q, candidates = args
        try:
            return assess_relevance(q, candidates, store)
        except ProviderError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        assessments = list(pool.map(assess, zip(sub_questions, results)))

    # Keep relevant chunks per sub-question, best first; remember which sub-question used each.
    selected, relevance, chunk_subq = [], {}, {}
    for qi, (candidates, scored) in enumerate(zip(results, assessments)):
        if scored is None:
            error = error or _error("provider_unavailable", "Relevance assessment unavailable; using fused ranking.")
            keep = [(i, 2) for i, _ in candidates[:KEEP_PER_SUBQ]]
        else:
            ranked = sorted(((i, scored[i][0], s) for i, s in candidates if i in scored and scored[i][0] >= 2),
                            key=lambda t: (-t[1], -t[2]))
            keep = [(i, sc) for i, sc, _ in ranked[:KEEP_PER_SUBQ]]
        for i, sc in keep:
            relevance[i] = max(relevance.get(i, 0), sc)
            chunk_subq.setdefault(i, set()).add(qi)
            if i not in selected:
                selected.append(i)

    if time.time() - started > FAST_TIMEOUT_S:
        return _result(mode, started, intent=_public_intent(intent),
                       error=_error("timeout", "Search took too long; please try a narrower question."))

    contexts = expand_context(selected, store)
    numbered = list(contexts)
    citations = [_citation(n + 1, idx, store, relevance[idx]) for n, idx in enumerate(numbered)]
    insufficient = not numbered
    answer_md = ""
    sub_out = [{"question": q, "citation_ns": [n + 1 for n, idx in enumerate(numbered) if qi in chunk_subq.get(idx, ())]}
               for qi, q in enumerate(sub_questions)]

    if numbered:
        passages = "\n\n".join(f"[{n + 1}] {store['chunks'][idx]['section_path']} (page {store['chunks'][idx]['page_label']})\n{contexts[idx]}"
                               for n, idx in enumerate(numbered))
        messages = [
            {"role": "system", "content": (
                "You answer questions for aircraft maintenance staff using only the numbered passages from the FAA "
                "Aviation Maintenance Technician General Handbook. Cover every part of the question. Put a [n] "
                "citation after every claim. Include any warnings or cautions the passages give. If the passages do "
                "not cover a part of the question, say so plainly for that part. If they support no answer at all, "
                "set insufficient_evidence to true. Never invent values, limits, torque figures or procedures.")},
            {"role": "user", "content": f"Question: {intent['standalone_question'] or question}\n\nSub-questions: {sub_questions}\n\nPassages:\n{passages}"},
        ]
        try:
            out, _ = chat_json(messages, "answer", ANSWER_SCHEMA, model=model_name("ANSWER_MODEL"),
                               prompt_version="answer.v1", kind="answer", max_tokens=3000, timeout=CALL_TIMEOUT_S)
            answer_md, insufficient = out["answer_markdown"], out["insufficient_evidence"]
            valid_ns = {c["n"] for c in citations}
            sub_out = [{"question": s["question"], "citation_ns": [n for n in s["citation_ns"] if n in valid_ns]}
                       for s in out["sub_answers"]] or sub_out
            used = {int(n) for n in re.findall(r"\[(\d+)\]", answer_md)}
            if used:
                citations = [c for c in citations if c["n"] in used]
        except ProviderError as e:
            error = _error("provider_unavailable", f"Answer model unavailable; showing the best passages: {e}")
            answer_md = "\n\n".join(f"[{c['n']}] {c['section_path']} (p. {c['page_label']}): {c['snippet']}" for c in citations)
    else:
        answer_md = "The handbook passages found do not support an answer to this question."

    coverage = None
    if mode == "verify":
        try:
            from rag.verify import verify_coverage
            coverage = verify_coverage(question, _public_intent(intent), citations, store)
        except ImportError:
            coverage = None
            error = error or _error("provider_unavailable", "Verify sweep is not installed.")
        except TimeoutError as e:
            error = error or _error("timeout", f"Verify sweep timed out: {e}")
        except Exception as e:  # never raise to the UI
            error = error or _error("provider_unavailable", f"Verify sweep unavailable: {e}")

    return _result(mode, started, answer_markdown=answer_md, citations=citations, intent=_public_intent(intent),
                   sub_questions=sub_out, coverage=coverage, insufficient_evidence=insufficient, error=error)


def _public_intent(intent):
    return {"primary": intent["primary"], "intents": intent["intents"], "topics": intent["topics"],
            "entities": intent["entities"], "needs_clarification": intent["needs_clarification"]}
