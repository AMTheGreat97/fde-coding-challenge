"""Load the pickled index store and build the in-memory BM25 index."""
import pickle
from pathlib import Path

from rank_bm25 import BM25Okapi

from rag.llm import ROOT, model_name

SCHEMA_VERSION = 1


class StoreError(Exception):
    pass


def load_store(path=ROOT / "index" / "store.pkl"):
    """Load store.pkl (only files written by ingest.build; unpickling can run code)."""
    path = Path(path)
    if not path.exists():
        raise StoreError(f"{path} not found; run python -m ingest.build")
    with open(path, "rb") as f:
        store = pickle.load(f)
    if store.get("schema_version") != SCHEMA_VERSION:
        raise StoreError(f"store schema_version {store.get('schema_version')} != {SCHEMA_VERSION}")
    expected = model_name("EMBEDDING_MODEL")
    if store["models"]["embedding"] != expected:
        raise StoreError(f"store was embedded with {store['models']['embedding']}, but EMBEDDING_MODEL is {expected}")
    store["bm25"] = BM25Okapi(store["bm25_tokens"]["chunk"])  # in memory only, never pickled
    store["chunk_index"] = {cid: i for i, cid in enumerate(store["vector_ids"]["chunk"])}
    store["section_index"] = {sid: i for i, sid in enumerate(store["vector_ids"]["section"])}
    return store
