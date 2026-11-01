import copy
import unittest
from unittest.mock import patch

from rag import verify
from test_contract import fixture


def small_store(count=2):
    sections = []
    for i in range(count):
        section = copy.deepcopy(fixture("section_record"))
        section["section_id"] = f"ch01.s{i:03d}"
        sections.append(section)
    return {"schema_version": 1, "sections": sections, "chunks": [fixture("chunk_record")]}


def judge(messages, schema, *, deadline):
    import json
    rows = json.loads(messages[1]["content"])["sections"]
    return {"sections": [{"section_id": s["section_id"], "score": 3, "reason": "Describes hot start response."} for s in rows]}


class VerifyTests(unittest.TestCase):
    def test_flags_missing_section_with_page(self):
        store = small_store()
        citation = {"section_id": "ch01.s000", "chapter": 1}
        with patch.object(verify, "_structured", side_effect=judge):
            coverage = verify.verify_coverage("How do I handle a hot start?", {}, [citation], store)
        self.assertFalse(coverage["complete"])
        self.assertEqual(coverage["missed_sections"][0]["section_id"], "ch01.s001")
        self.assertEqual(coverage["missed_sections"][0]["page_label"], "1-17")
        self.assertEqual(coverage["chapters_relevant"], [1])

    def test_all_cited_needs_no_provider(self):
        with patch.object(verify, "_structured") as api:
            result = verify.verify_coverage("hot start", {}, [{"section_id": "ch01.s000", "chapter": 1}], small_store(1))
        self.assertTrue(result["complete"])
        api.assert_not_called()

    def test_irrelevant_candidates_do_not_become_misses(self):
        def irrelevant(*args, **kwargs):
            result = judge(*args, **kwargs)
            for row in result["sections"]:
                row["score"] = 1
            return result
        with patch.object(verify, "_structured", side_effect=irrelevant):
            self.assertTrue(verify.verify_coverage("weight and balance", {}, [], small_store())["complete"])

    def test_sweeps_beyond_first_twenty_and_excludes_cited(self):
        store = small_store(30)
        store["sections"][-1]["summary"] = "uniquequestionword " * 20
        with patch.object(verify, "_structured", side_effect=judge) as api:
            result = verify.verify_coverage("uniquequestionword", {}, [{"section_id": "ch01.s000", "chapter": 1}], store)
        ids = [m["section_id"] for m in result["missed_sections"]]
        self.assertEqual(len(ids), 20)
        self.assertIn("ch01.s029", ids)
        self.assertNotIn("ch01.s000", ids)

    def test_failed_judgment_never_reports_complete(self):
        with patch.object(verify, "_structured", side_effect=RuntimeError("provider_unavailable")):
            with self.assertRaisesRegex(RuntimeError, "provider_unavailable"):
                verify.verify_coverage("hot start", {}, [], small_store())

    def test_hallucinated_or_partial_judge_ids_rejected(self):
        with patch.object(verify, "_structured", return_value={"sections": [{"section_id": "bogus", "score": 3, "reason": "x"}]}):
            with self.assertRaisesRegex(RuntimeError, "invalid coverage judgment"):
                verify.verify_coverage("hot start", {}, [], small_store())

    def test_vectors_participate_in_ranking(self):
        store = small_store(30)
        store.update(models={"embedding": "openai/text-embedding-3-small"},
                     vector_ids={"section": [s["section_id"] for s in store["sections"]]},
                     vectors={"section": [[0, 1]] * 29 + [[1, 0]]})
        with patch.object(verify, "_post", return_value={"data": [{"embedding": [1, 0]}]}) as embed, patch.object(verify, "_structured", side_effect=judge):
            result = verify.verify_coverage("unmatchedword", {}, [], store)
        embed.assert_called_once()
        self.assertIn("ch01.s029", [m["section_id"] for m in result["missed_sections"]])

    def test_markers_removed_from_hosted_payload(self):
        import json
        response = {"choices": [{"message": {"content": "{}"}}]}
        with patch.object(verify, "_post", return_value=response) as api:
            verify._structured([{"role": "user", "content": "hi <!-- page 1-2 (pdf p.3) --> there"}], {}, deadline=999999)
        self.assertNotIn("<!-- page", json.dumps(api.call_args.args[1]))


if __name__ == "__main__":
    unittest.main()
