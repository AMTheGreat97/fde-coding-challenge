"""LLM enrichment: document profiles (E1), section + chunk cards (E2), and topic
normalization (E3). Every topic and entity must carry a quote that is found
verbatim in the source Markdown; anything else is dropped.
"""
import json
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

from rag.llm import ProviderError, chat_json, embed
from rag.text import is_supported, normalize_for_match

CONTENT_TYPES = ["procedure", "concept", "regulation", "table", "safety", "calculation", "definition", "other"]
ENTITY_TYPES = ["component", "material", "tool", "process", "regulation", "part_number",
                "specification", "condition", "safety_hazard", "other"]

QUOTE_RULE = ("Every evidence_quote must be copied character-for-character from the text: one contiguous span "
              "of 5 to 25 words, same words in the same order, no paraphrasing, no ellipses, no added words.")


def _obj(props):
    return {"type": "object", "additionalProperties": False, "required": list(props), "properties": props}


STR = {"type": "string"}
STRS = {"type": "array", "items": STR}
TOPICS = {"type": "array", "items": _obj({"label": STR, "evidence_quote": STR})}
ENTITIES = {"type": "array", "items": _obj({"text": STR, "type": {"type": "string", "enum": ENTITY_TYPES},
                                            "evidence_quote": STR})}

E1_SCHEMA = _obj({"summary": STR, "scope": STR, "topics": TOPICS, "entities": ENTITIES})
E2_SCHEMA = _obj({
    "summary": STR,
    "content_type": {"type": "string", "enum": CONTENT_TYPES},
    "topics": TOPICS, "entities": ENTITIES, "keywords": STRS, "questions": STRS,
    "chunks": {"type": "array", "items": _obj({"chunk_id": STR, "context_line": STR, "topic_labels": STRS})},
})
TAXONOMY_SCHEMA = _obj({
    "categories": {"type": "array", "items": _obj({"topic_id": STR, "label": STR})},
    "topics": {"type": "array", "items": _obj({"topic_id": STR, "label": STR, "parent_id": STR})},
})
MAPPING_SCHEMA = _obj({"mappings": {"type": "array", "items": _obj({"raw_label": STR, "topic_id": STR})}})

SYSTEM = ("You build a retrieval index for the FAA Aviation Maintenance Technician General Handbook. "
          "Use only the text you are given; never add outside knowledge. " + QUOTE_RULE)


class Stats:
    def __init__(self):
        self.lock = threading.Lock()
        self.c = Counter()
        self.cost = 0.0
        self.failures = []

    def add(self, **counts):
        with self.lock:
            self.c.update(counts)

    def record(self, rec):
        with self.lock:
            self.c["llm_calls"] += 1
            self.c["llm_cached"] += rec["cached"]
            self.cost += float(rec.get("usage", {}).get("cost") or 0)

    def fail(self, msg):
        with self.lock:
            self.failures.append(msg)


def _ground(items, source_norm, text_key=None):
    kept, bad = [], []
    for it in items:
        ok = is_supported(it["evidence_quote"], source_norm)
        if ok and text_key:
            ok = is_supported(it[text_key], source_norm, min_chars=2)
        (kept if ok else bad).append(it)
    return kept, bad


def grounded_call(messages, schema_name, schema, source_norm, *, prompt_version, kind, cache, stats,
                  max_tokens, timeout):
    """One structured call plus at most one retry for quotes that are not verbatim."""
    out, rec = chat_json(messages, schema_name, schema, prompt_version=prompt_version, kind=kind,
                         cache=cache, max_tokens=max_tokens, timeout=timeout)
    stats.record(rec)
    topics, bad_t = _ground(out["topics"], source_norm)
    ents, bad_e = _ground(out["entities"], source_norm, text_key="text")
    if bad_t or bad_e:
        bad = [i["evidence_quote"] for i in bad_t + bad_e] + [i["text"] for i in bad_e]
        retry = messages + [
            {"role": "assistant", "content": json.dumps(out)},
            {"role": "user", "content": "These values were not found verbatim in the text: "
             + json.dumps(bad[:30]) + ". Return the complete JSON again. Copy every evidence_quote and "
             "entity text exactly as it appears in the text, or leave that item out."},
        ]
        try:
            out2, rec2 = chat_json(retry, schema_name, schema, prompt_version=prompt_version + "-retry",
                                   kind=kind + "-retry", cache=cache, max_tokens=max_tokens, timeout=timeout)
            stats.record(rec2)
            out, rec = out2, rec2
            topics, bad_t = _ground(out["topics"], source_norm)
            ents, bad_e = _ground(out["entities"], source_norm, text_key="text")
        except ProviderError as e:
            stats.fail(f"{kind} retry failed: {e}")
    stats.add(topics_raw=len(topics) + len(bad_t), topics_dropped_unsupported=len(bad_t),
              entities_raw=len(ents) + len(bad_e), entities_dropped_unsupported=len(bad_e))
    return {**out, "topics": topics, "entities": ents}, rec


def chapter_text(sections):
    return "\n\n".join(f"### {' > '.join(s['path'][1:])}\n\n{s['_text']}" for s in sections)


def profile_document(doc, sections, cache, stats):
    text = chapter_text(sections)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"Chapter {doc['chapter']}: {doc['title']}\n\n<chapter_text>\n{text}\n</chapter_text>\n\n"
            "Profile this chapter. summary: 4-6 sentences on what it covers. scope: one sentence on the kinds "
            "of maintenance questions it answers. topics: 8-15 subject areas it covers, each with an "
            "evidence_quote. entities: up to 20 key components, materials, tools, processes, regulations, "
            "part numbers, specifications, conditions or hazards, each with an evidence_quote.")},
    ]
    out, rec = grounded_call(messages, "document_profile", E1_SCHEMA, normalize_for_match(text),
                             prompt_version="e1.v1", kind="e1", cache=cache, stats=stats,
                             max_tokens=6000, timeout=300)
    return out, rec


def enrich_section(section, doc, profile_summary, cache, stats):
    chunk_ids = [c["chunk_id"] for c in section["_chunks"]]
    marked = "\n\n".join(f"[[CHUNK {c['chunk_id']}]]\n{c['text']}" for c in section["_chunks"])
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            f"Chapter {doc['chapter']}: {doc['title']}\nChapter summary: {profile_summary}\n"
            f"Section path: {' > '.join(section['path'])}\n\n<section_text>\n{marked}\n</section_text>\n\n"
            "Describe this section. summary: 2-3 sentences. content_type: the best fit. topics: 2-6 subject "
            "areas this section covers. entities: up to 12. keywords: 3-10 exact phrases from the text that "
            "someone might search for. questions: 3-5 questions this section answers. chunks: one entry per "
            f"chunk, in order, for chunk_ids {chunk_ids}; context_line is 1-2 sentences placing the chunk "
            "within the section and chapter; topic_labels are labels from your topics list that the chunk "
            "covers.")},
    ]
    return grounded_call(messages, "section_card", E2_SCHEMA, normalize_for_match(section["_text"]),
                         prompt_version="e2.v1", kind="e2", cache=cache, stats=stats,
                         max_tokens=8000, timeout=180)


def run_parallel(fn, items, workers, label, every=50):
    results = [None] * len(items)
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fn, item): i for i, item in enumerate(items)}
        for future in as_completed(futures):
            results[futures[future]] = future.result()
            done += 1
            if done % every == 0 or done == len(items):
                print(f"  {label}: {done}/{len(items)}", flush=True)
    return results


def build_taxonomy(label_counts, cache, stats, embed_cache, workers=8):
    """E3: normalize grounded raw topic labels into a two-level topic list and map every label."""
    lines = "\n".join(f"{label}\t{n}" for label, n in label_counts.most_common())
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            "Below are topic labels extracted from the handbook, with how often each occurs (label<TAB>count)."
            "\n\n" + lines + "\n\nNormalize them into one two-level topic list. categories: 10-25 broad areas, "
            "topic_id like 'corrosion'. topics: 80-250 specific topics, topic_id like 'corrosion.aluminum_alloys' "
            "(category id, a dot, lowercase snake_case), parent_id is its category's topic_id. Only create "
            "topics that the labels above actually represent; merge synonyms and near-duplicates.")},
    ]
    tax, rec = chat_json(messages, "taxonomy", TAXONOMY_SCHEMA, prompt_version="e3.taxonomy.v1",
                         kind="e3-taxonomy", cache=cache, max_tokens=16000, timeout=300)
    stats.record(rec)
    categories = {c["topic_id"]: c["label"] for c in tax["categories"]}
    leaves = {t["topic_id"]: t for t in tax["topics"] if t["parent_id"] in categories}
    catalog = "\n".join(f"{tid}\t{t['label']}" for tid, t in sorted(leaves.items()))

    labels = [label for label, _ in label_counts.most_common()]
    batches = [labels[i:i + 250] for i in range(0, len(labels), 250)]

    def map_batch(batch):
        msgs = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": (
                "Topic list (topic_id<TAB>label):\n" + catalog + "\n\nFor each raw label below, choose the single "
                "best topic_id from the list. Use only topic_ids from the list.\n\n" + "\n".join(batch))},
        ]
        try:
            out, r = chat_json(msgs, "topic_mapping", MAPPING_SCHEMA, prompt_version="e3.map.v1",
                               kind="e3-map", cache=cache, max_tokens=12000, timeout=180)
            stats.record(r)
            return {m["raw_label"]: m["topic_id"] for m in out["mappings"]}
        except ProviderError as e:
            stats.fail(f"e3-map batch failed: {e}")
            return {}

    mapping = {}
    for part in run_parallel(map_batch, batches, workers, "topic mapping", every=5):
        mapping.update(part)

    # Labels the model skipped or mapped to an unknown id go to the nearest topic by embedding.
    unmapped = [l for l in labels if mapping.get(l) not in leaves]
    if unmapped:
        leaf_ids = list(leaves)
        leaf_vecs = embed([leaves[t]["label"] for t in leaf_ids], cache=embed_cache)
        label_vecs = embed(unmapped, cache=embed_cache)
        for label, row in zip(unmapped, label_vecs @ leaf_vecs.T):
            mapping[label] = leaf_ids[int(np.argmax(row))]
    stats.add(taxonomy_fallback_mapped=len(unmapped))

    used = {mapping[l] for l in labels}
    topics = [{"topic_id": tid, "label": leaves[tid]["label"], "parent_id": leaves[tid]["parent_id"]}
              for tid in sorted(used)]
    used_cats = {t["parent_id"] for t in topics}
    topics = [{"topic_id": cid, "label": categories[cid], "parent_id": None} for cid in sorted(used_cats)] + topics
    return {"topics": topics, "raw_to_canonical": {l: mapping[l] for l in labels}}
