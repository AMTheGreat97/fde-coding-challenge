"""Frozen fixture, real-store, grounding and prohibited-input contract checks.

Run: python -m unittest discover -s tests -v
Only pipeline-produced index/store.pkl is loaded; never accept arbitrary paths.
"""
import ast
import json
from pathlib import Path
import pickle
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "specs" / "fixtures"
BANNED = {"chromadb", "onnxruntime", "fastembed", "sentence_transformers", "torch"}
DOC_ID = re.compile(r"ch(?:0[1-9]|1[0-4])_.+")
CONTENT_TYPES = {"procedure", "concept", "regulation", "table", "safety", "calculation", "definition", "other"}
ENTITY_TYPES = {"component", "material", "tool", "process", "regulation", "part_number", "specification", "condition", "safety_hazard", "other"}


def fixture(name):
    return json.loads((FIXTURES / (name + ".json")).read_text(encoding="utf-8"))


def normalize(text):
    text = re.sub(r"<!--.*?-->|<[^>]+>", " ", text, flags=re.S)
    return " ".join(re.sub(r"[*_`]+", "", text).casefold().split())


def production_files():
    # git-tracked files + new files in production ownership, never other worktrees.
    for folder in ("ingest", "rag", "ui", "scripts", "evals"):
        for path in (ROOT / folder).rglob("*.py"):
            if "__pycache__" not in path.parts:
                yield path


class FixtureContractTests(unittest.TestCase):
    def check_id(self, record):
        self.assertRegex(record["doc_id"], DOC_ID)
        self.assertTrue(1 <= record["chapter"] <= 14)
        self.assertEqual(int(record["doc_id"][2:4]), record["chapter"])

    def test_section_fixture(self):
        s = fixture("section_record")
        self.check_id(s)
        self.assertRegex(s["section_id"], r"^ch\d{2}\.s\d{3}$")
        self.assertEqual(s["heading_source"], "markdown")
        self.assertIn(s["content_type"], CONTENT_TYPES)
        self.assertIn(s["enrichment"]["source"], {"llm", "failed"})
        for field in ("path", "topics", "entities", "keywords", "questions", "chunk_ids"):
            self.assertIsInstance(s[field], list)
        for t in s["topics"]:
            self.assertTrue(all(isinstance(t[k], str) for k in ("topic_id", "label", "evidence_quote")))
        for entity in s["entities"]:
            self.assertIn(entity["type"], ENTITY_TYPES)

    def test_chunk_fixture(self):
        c, s = fixture("chunk_record"), fixture("section_record")
        self.check_id(c)
        self.assertEqual(c["section_id"], s["section_id"])
        self.assertIn(c["chunk_id"], s["chunk_ids"])
        self.assertTrue(c["chunk_id"].startswith(c["section_id"] + ".c"))
        self.assertEqual(c["embed_text"], c["section_path"] + "\n" + c["context_line"] + "\n\n" + c["text"])
        self.assertNotIn("<!-- page", c["embed_text"])

    def test_answer_fixtures(self):
        for mode in ("fast", "verify"):
            with self.subTest(mode=mode):
                a = fixture("answer_" + mode)
                self.assertEqual(a["mode"], mode)
                self.assertIsInstance(a["latency_ms"], int)
                self.assertIsInstance(a["insufficient_evidence"], bool)
                self.assertIsNone(a["error"])
                ns = [c["n"] for c in a["citations"]]
                self.assertEqual(len(ns), len(set(ns)))
                for c in a["citations"]:
                    self.check_id(c)
                    self.assertIn(c["relevance"], range(4))
                    for field in ("section_id", "section_path", "page_label", "snippet"):
                        self.assertIsInstance(c[field], str)
                for n in re.findall(r"\[(\d+)\]", a["answer_markdown"]):
                    self.assertIn(int(n), ns)
                for sub in a["sub_questions"]:
                    self.assertTrue(set(sub["citation_ns"]) <= set(ns))
                if mode == "fast":
                    self.assertIsNone(a["coverage"])
                else:
                    coverage = a["coverage"]
                    self.assertEqual(coverage["complete"], not coverage["missed_sections"])
                    self.assertTrue(set(coverage["chapters_cited"]) <= set(coverage["chapters_relevant"]))
                    for missed in coverage["missed_sections"]:
                        self.assertTrue(all(isinstance(missed[k], str) for k in ("section_id", "section_path", "page_label", "reason")))


class PolicyTests(unittest.TestCase):
    def test_no_banned_imports(self):
        violations = []
        for path in production_files():
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                elif (isinstance(node, ast.Call) and node.args
                      and isinstance(node.args[0], ast.Constant)
                      and isinstance(node.args[0].value, str)
                      and ((isinstance(node.func, ast.Name) and node.func.id == "__import__")
                           or (isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"))):
                    names = [node.args[0].value]
                if any(n.split(".")[0] in BANNED for n in names):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(violations, [], "Prohibited local inference imports: " + ", ".join(violations))

    def test_corpus_filename_contract(self):
        files = sorted(p for p in (ROOT / "corpus").glob("ch??_*.md") if DOC_ID.fullmatch(p.stem))
        self.assertEqual([int(p.stem[2:4]) for p in files], list(range(1, 15)))

    def test_no_literal_prohibited_ingestion_reads(self):
        violations = []
        prohibited = {"00_front-matter.md", "index.md", "glossary.md", "manifest.json"}
        for path in (ROOT / "ingest").rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"read_text", "read_bytes", "open"}:
                    constants = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                    if any(Path(v).name in prohibited or "DATA/" in v.replace("\\", "/") for v in constants):
                        violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertFalse(violations, violations)


@unittest.skipUnless((ROOT / "index/store.pkl").exists(), "Waiting for Claude's pipeline-produced store commit")
class RealStoreContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with (ROOT / "index/store.pkl").open("rb") as stream:
            cls.store = pickle.load(stream)

    def test_schema_and_alignment(self):
        import numpy as np
        s = self.store
        self.assertEqual(s["schema_version"], 1)
        self.assertIsInstance(s["built_at"], str)
        self.assertEqual(s["models"]["embedding_dims"], 1536)
        docs = {d["doc_id"]: d for d in s["documents"]}
        sections = {r["section_id"]: r for r in s["sections"]}
        chunks = {r["chunk_id"]: r for r in s["chunks"]}
        self.assertEqual(len(sections), len(s["sections"]))
        self.assertEqual(len(chunks), len(s["chunks"]))
        for kind, rows, key in (("document", s["documents"], "doc_id"), ("section", s["sections"], "section_id"), ("chunk", s["chunks"], "chunk_id")):
            ids = s["vector_ids"][kind]
            self.assertEqual(set(ids), {r[key] for r in rows})
            self.assertEqual(len(ids), len(rows))
            vectors = s["vectors"][kind]
            self.assertIsInstance(vectors, np.ndarray)
            self.assertEqual(vectors.shape, (len(rows), 1536))
            self.assertEqual(vectors.dtype, np.float32)
            self.assertTrue(np.isfinite(vectors).all())
        self.assertEqual(len(s["bm25_tokens"]["chunk"]), len(chunks))
        memberships = []
        for section in sections.values():
            self.assertIn(section["doc_id"], docs)
            self.assertIn(section["content_type"], CONTENT_TYPES)
            self.assertEqual(section["heading_source"], "markdown")
            self.assertIn(section["enrichment"]["source"], {"llm", "failed"})
            for cid in section["chunk_ids"]:
                self.assertEqual(chunks[cid]["section_id"], section["section_id"])
                memberships.append(cid)
        self.assertEqual(sorted(memberships), sorted(chunks))
        for doc in docs.values():
            self.assertTrue(DOC_ID.fullmatch(doc["doc_id"]), doc["doc_id"])
            self.assertEqual(set(doc["section_ids"]), {sid for sid, sec in sections.items() if sec["doc_id"] == doc["doc_id"]})
        for chunk in chunks.values():
            self.assertTrue(DOC_ID.fullmatch(chunk["doc_id"]))
            self.assertIn(chunk["section_id"], sections)
            self.assertNotRegex(chunk["embed_text"], r"<!--\s*page")

    def test_grounded_quotes_and_topics(self):
        s = self.store
        sources = {}
        for doc in s["documents"]:
            self.assertTrue(DOC_ID.fullmatch(doc["doc_id"]))
            sources[doc["doc_id"]] = normalize((ROOT / "corpus" / (doc["doc_id"] + ".md")).read_text(encoding="utf-8"))
        grounded_topics = set()
        chunk_texts = {c["chunk_id"]: c["text"] for c in s["chunks"]}
        for row in s["documents"] + s["sections"]:
            source = sources[row["doc_id"]] if "section_id" not in row else normalize("\n".join(chunk_texts[c] for c in row["chunk_ids"]))
            for topic in row["topics"]:
                self.assertTrue(normalize(topic["evidence_quote"]))
                self.assertIn(normalize(topic["evidence_quote"]), source)
                grounded_topics.add(topic["topic_id"])
            for entity in row["entities"]:
                self.assertIn(entity["type"], ENTITY_TYPES)
                self.assertTrue(normalize(entity["evidence_quote"]))
                self.assertIn(normalize(entity["evidence_quote"]), source)
                self.assertIn(normalize(entity["text"]), source)
        self.assertTrue({t["topic_id"] for t in s["taxonomy"]["topics"]} <= grounded_topics)


if __name__ == "__main__":
    unittest.main()
