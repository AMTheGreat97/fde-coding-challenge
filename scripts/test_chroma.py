"""Smoke-test local ChromaDB: write, persist, reopen and query. No API key needed."""
import shutil
import tempfile

import chromadb


def main():
    path = tempfile.mkdtemp(prefix="chroma_smoke_")
    try:
        client = chromadb.PersistentClient(path=path)
        collection = client.create_collection("smoke", metadata={"hnsw:space": "cosine"})
        collection.add(
            ids=["a", "b", "c"],
            embeddings=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.9, 0.1, 0.0]],
            documents=["torque wrench", "corrosion control", "hand tools"],
            metadatas=[{"chapter": "ch11"}, {"chapter": "ch08"}, {"chapter": "ch11"}],
        )
        del client

        # Reopen from disk to prove persistence.
        reopened = chromadb.PersistentClient(path=path).get_collection("smoke")
        result = reopened.query(query_embeddings=[[1.0, 0.05, 0.0]], n_results=2, where={"chapter": "ch11"})
        assert reopened.count() == 3, reopened.count()
        assert result["ids"][0] == ["a", "c"], result["ids"]
        print(f"ChromaDB {chromadb.__version__} OK: persisted 3 vectors, reopened, filtered query -> {result['ids'][0]}")
    finally:
        shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    main()
