"""Build the index store from the Markdown chapter bodies.

Usage: python -m ingest.build [--only ch13] [--concurrency 16]

Writes index/store.pkl, index/llm_cache.pkl, index/embed_cache.pkl and index/report.json.
Re-running replays both caches and only calls the API for what is missing.
"""
import argparse
import json
import os
import pickle
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from ingest.enrich import Stats, build_taxonomy, enrich_section, profile_document, run_parallel
from ingest.parse import chapter_files, parse_chapter
from rag.llm import EMBEDDING_DIMS, PickleCache, ProviderError, embed, load_env, model_name
from rag.text import is_supported, normalize_for_match, tokenize

SCHEMA_VERSION = 1
MAX_EMBED_CHARS = 24000


def _label_key(label):
    return " ".join(label.lower().split())


def _topic_refs(items, mapping, labels_by_id):
    refs, seen = [], set()
    for it in items:
        tid = mapping.get(_label_key(it["label"]))
        if tid and tid not in seen:
            seen.add(tid)
            refs.append({"topic_id": tid, "label": labels_by_id[tid], "evidence_quote": it["evidence_quote"]})
    return refs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="corpus")
    ap.add_argument("--out", default="index")
    ap.add_argument("--only", help="build only documents whose doc_id starts with this, e.g. ch13")
    ap.add_argument("--concurrency", type=int, default=16)
    args = ap.parse_args()
    load_env()
    started = time.time()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    llm_cache = PickleCache(out_dir / "llm_cache.pkl")
    embed_cache = PickleCache(out_dir / "embed_cache.pkl", autosave_every=500)
    stats = Stats()
    llm, emb = model_name("LLM_MODEL"), model_name("EMBEDDING_MODEL")

    # 1-2. Parse and chunk.
    docs, sections = [], []
    for path in chapter_files(args.corpus):
        if args.only and not path.stem.startswith(args.only):
            continue
        doc, secs = parse_chapter(path)
        docs.append(doc)
        sections.extend(secs)
    for s in sections:
        for i, c in enumerate(s["_chunks"]):
            c["chunk_id"] = f"{s['section_id']}.c{i:02d}"
    print(f"Parsed {len(docs)} documents, {len(sections)} sections, "
          f"{sum(len(s['_chunks']) for s in sections)} chunks", flush=True)

    # 3. E1 document profiles.
    by_doc = {d["doc_id"]: [s for s in sections if s["doc_id"] == d["doc_id"]] for d in docs}

    def do_profile(doc):
        try:
            return profile_document(doc, by_doc[doc["doc_id"]], llm_cache, stats)
        except ProviderError as e:
            stats.fail(f"e1 {doc['doc_id']}: {e}")
            return None
    profiles = dict(zip([d["doc_id"] for d in docs], run_parallel(do_profile, docs, 6, "E1 profiles", every=2)))

    # 4-5. E2 section and chunk enrichment with grounding.
    doc_by_id = {d["doc_id"]: d for d in docs}

    def do_section(s):
        prof = profiles.get(s["doc_id"])
        summary = prof[0]["summary"] if prof else ""
        try:
            return enrich_section(s, doc_by_id[s["doc_id"]], summary, llm_cache, stats)
        except ProviderError as e:
            stats.fail(f"e2 {s['section_id']}: {e}")
            return None
    cards = run_parallel(do_section, sections, args.concurrency, "E2 sections")
    llm_cache.save()

    # 6-7. E3 topic normalization over grounded labels only, then apply in code.
    label_counts = Counter()
    for prof in profiles.values():
        if prof:
            label_counts.update(_label_key(t["label"]) for t in prof[0]["topics"])
    for card in cards:
        if card:
            label_counts.update(_label_key(t["label"]) for t in card[0]["topics"])
    taxonomy = build_taxonomy(label_counts, llm_cache, stats, embed_cache)
    llm_cache.save()
    mapping = taxonomy["raw_to_canonical"]
    labels_by_id = {t["topic_id"]: t["label"] for t in taxonomy["topics"]}

    # Assemble records (shapes match specs/fixtures/*.json).
    section_records, chunk_records = [], []
    for s, card in zip(sections, cards):
        src = normalize_for_match(s["_text"])
        out, rec = card if card else ({}, None)
        topics = _topic_refs(out.get("topics", []), mapping, labels_by_id)
        label_to_tid = {t["label"].lower(): mapping.get(_label_key(t["label"])) for t in out.get("topics", [])}
        chunk_cards = {c["chunk_id"]: c for c in out.get("chunks", [])}
        section_path = " > ".join([f"Ch {s['chapter']}"] + s["path"][1:])
        for c in s["_chunks"]:
            cc = chunk_cards.get(c["chunk_id"], {})
            context = cc.get("context_line", "")
            ctopics = sorted({label_to_tid[l.lower()] for l in cc.get("topic_labels", [])
                              if label_to_tid.get(l.lower())})
            embed_text = f"{section_path}\n{context}\n\n{c['text']}" if context else f"{section_path}\n\n{c['text']}"
            chunk_records.append({
                "chunk_id": c["chunk_id"], "section_id": s["section_id"], "doc_id": s["doc_id"],
                "chapter": s["chapter"], "section_path": section_path, "page_label": c["page_label"],
                "pdf_page": c["pdf_page"], "token_count": len(c["text"]) // 4, "text": c["text"],
                "context_line": context, "topics": ctopics, "embed_text": embed_text,
                "_pages": c["pages"],
            })
        section_records.append({
            "section_id": s["section_id"], "doc_id": s["doc_id"], "chapter": s["chapter"],
            "title": s["title"], "path": s["path"], "parent_id": s["parent_id"], "level": s["level"],
            "heading_source": "markdown", "page_start_label": s["page_start_label"],
            "page_end_label": s["page_end_label"], "pdf_pages": s["pdf_pages"],
            "text_chars": s["text_chars"], "chunk_ids": [c["chunk_id"] for c in s["_chunks"]],
            "content_type": out.get("content_type", "other"), "summary": out.get("summary", ""),
            "topics": topics, "entities": out.get("entities", []),
            "keywords": [k for k in out.get("keywords", []) if is_supported(k, src, min_chars=2)],
            "questions": out.get("questions", []), "cross_refs": s["cross_refs"],
            "enrichment": ({"source": "llm", "model": rec["model"], "prompt_version": rec["prompt_version"],
                            "request_sha256": rec["request_sha256"]} if rec else
                           {"source": "failed", "model": llm, "prompt_version": "e2.v1", "request_sha256": None}),
        })

    documents = []
    for d in docs:
        prof = profiles.get(d["doc_id"])
        p = prof[0] if prof else {}
        documents.append({
            "doc_id": d["doc_id"], "chapter": d["chapter"], "title": d["title"],
            "profile_summary": p.get("summary", ""), "scope": p.get("scope", ""),
            "topics": _topic_refs(p.get("topics", []), mapping, labels_by_id),
            "entities": p.get("entities", []),
            "section_ids": [s["section_id"] for s in section_records if s["doc_id"] == d["doc_id"]],
        })

    # 8. Embeddings (same model as queries).
    print("Embedding chunks, sections and documents...", flush=True)
    chunk_vecs = embed([c["embed_text"][:MAX_EMBED_CHARS] for c in chunk_records], cache=embed_cache)
    section_texts = [
        (s["summary"] + "\n" + "\n".join(s["questions"])) if s["summary"]
        else " > ".join(s["path"]) + "\n" + next(c["text"] for c in chunk_records if c["section_id"] == s["section_id"])
        for s in section_records
    ]
    section_vecs = embed([t[:MAX_EMBED_CHARS] for t in section_texts], cache=embed_cache)
    doc_vecs = embed([d["profile_summary"] or d["title"] for d in documents], cache=embed_cache)
    embed_cache.save()

    # 9. BM25 tokens: chunk text plus its section's keywords and entity texts.
    sec_by_id = {s["section_id"]: s for s in section_records}
    bm25_tokens = []
    for c in chunk_records:
        s = sec_by_id[c["section_id"]]
        extra = " ".join(s["keywords"] + [e["text"] for e in s["entities"]])
        bm25_tokens.append(tokenize(c["text"] + " " + extra))

    pages_expected = set().union(*(d["_pages_with_text"] for d in docs))
    pages_covered = {p for c in chunk_records for p in c.pop("_pages")}

    store = {
        "schema_version": SCHEMA_VERSION, "built_at": datetime.now(timezone.utc).isoformat(),
        "models": {"embedding": emb, "embedding_dims": EMBEDDING_DIMS, "llm": llm},
        "documents": documents, "sections": section_records, "chunks": chunk_records,
        "taxonomy": taxonomy,
        "vectors": {"chunk": chunk_vecs, "section": section_vecs, "document": doc_vecs},
        "vector_ids": {"chunk": [c["chunk_id"] for c in chunk_records],
                       "section": [s["section_id"] for s in section_records],
                       "document": [d["doc_id"] for d in documents]},
        "bm25_tokens": {"chunk": bm25_tokens},
    }
    tmp = out_dir / "store.tmp"
    with open(tmp, "wb") as f:
        pickle.dump(store, f, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, out_dir / "store.pkl")

    failed = sum(1 for s in section_records if s["enrichment"]["source"] == "failed")
    report = {
        "documents": len(documents), "sections": len(section_records), "chunks": len(chunk_records),
        "pages_covered": len(pages_covered & pages_expected), "pages_expected": len(pages_expected),
        "sections_enriched": len(section_records) - failed, "sections_failed": failed,
        "topics_raw": stats.c["topics_raw"], "topics_dropped_unsupported": stats.c["topics_dropped_unsupported"],
        "taxonomy_size": len(taxonomy["topics"]), "llm_calls": stats.c["llm_calls"],
        "llm_cost_usd": round(stats.cost, 4), "embedding_inputs": len(chunk_records) + len(section_records) + len(documents),
        "embedding_model": emb, "llm_model": llm, "built_at": store["built_at"], "failures": stats.failures,
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "failures"}, indent=2))
    print(f"entities dropped as unsupported: {stats.c['entities_dropped_unsupported']}/{stats.c['entities_raw']}; "
          f"cached LLM responses reused: {stats.c['llm_cached']}; topic labels mapped by embedding fallback: "
          f"{stats.c['taxonomy_fallback_mapped']}; failures: {len(stats.failures)}; {time.time() - started:.0f}s")
    for f in stats.failures[:10]:
        print("  FAIL", f)


if __name__ == "__main__":
    main()
