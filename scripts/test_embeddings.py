"""End-to-end test: check the OpenRouter key, embed one corpus document, store it in
local ChromaDB, and run a sample query.

Usage: python scripts/test_embeddings.py [corpus_file.md] ["question"]
"""
import sys
from pathlib import Path

import chromadb

from common import CHROMA_DIR, ROOT, chunk_markdown, embed, load_env, openrouter

DEFAULT_DOC = ROOT / "corpus" / "ch13_mechanic-privileges-limitations.md"
DEFAULT_QUESTION = "What can a mechanic with an airframe rating do?"
COLLECTION = "handbook_test"


def main():
    load_env()
    doc = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOC
    question = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_QUESTION

    key_info = openrouter("/key")["data"]
    print(f"Key OK: label={key_info.get('label')!r} usage=${key_info.get('usage')} limit={key_info.get('limit')}")

    chunks = chunk_markdown(doc.read_text(encoding="utf-8"))
    vectors, result = embed([c["text"] for c in chunks])
    print(f"Embedded {len(chunks)} chunks from {doc.name} with {result.get('model')}: "
          f"{len(vectors[0])} dims, usage={result.get('usage')}")

    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    collection = client.get_or_create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    collection.upsert(
        ids=[f"{doc.stem}:{i}" for i in range(len(chunks))],
        embeddings=vectors,
        documents=[c["text"] for c in chunks],
        metadatas=[{"doc": doc.stem, "page_label": c["page_label"], "pdf_page": c["pdf_page"]} for c in chunks],
    )
    print(f"Stored in ChromaDB at {CHROMA_DIR.relative_to(ROOT)}/ collection {COLLECTION!r}: {collection.count()} vectors")

    query_vector, _ = embed([question])
    hits = collection.query(query_embeddings=query_vector, n_results=3)
    print(f"\nQuery: {question}")
    for text, meta, dist in zip(hits["documents"][0], hits["metadatas"][0], hits["distances"][0]):
        snippet = " ".join(text.split())[:160]
        print(f"  [{meta['page_label']}] distance={dist:.3f}  {snippet}...")


if __name__ == "__main__":
    main()
