import unittest
from unittest.mock import patch

from services.ai_service import _format_response_with_sources
from services import prompt_builder


class SearchIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.character = {
            "id": 2,
            "name": "플레타",
            "description": "",
            "personality": "",
            "speech": "",
            "world": "",
        }

    def build(self, context, attempted):
        with patch.object(prompt_builder.db, "get_conversation", return_value=[]), \
             patch.object(prompt_builder.db, "get_summary", return_value=""), \
             patch.object(prompt_builder, "get_memories", return_value=[]), \
             patch.object(prompt_builder.AffectionService, "get", return_value=0), \
             patch.object(prompt_builder.AffectionService, "get_level", return_value="보통"):
            return prompt_builder.build_prompt(
                17, self.character, "이완용은 누구야?",
                search_context=context, search_attempted=attempted,
            )

    def test_search_failure_signals_uncertainty(self):
        messages = self.build(None, True)
        self.assertIn("[Search unavailable]", messages[0]["content"])
        self.assertNotIn("검증된", messages[-1]["content"])

    def test_search_result_keeps_evidence_and_guidance(self):
        messages = self.build("이완용 관련 외부 검색 결과", True)
        self.assertIn("[Search grounding]", messages[0]["content"])
        self.assertIn("이완용 관련 외부 검색 결과", messages[-1]["content"])

    def test_citation_links_survive_long_answers(self):
        response = "답변" * 1000
        answer = _format_response_with_sources(
            response, [("역사자료", "https://example.org/article")],
        )
        self.assertLessEqual(len(answer), 1900)
        self.assertIn("https://example.org/article", answer)
        self.assertIn("🔎 참고 자료:", answer)

    def test_unsourced_response_is_limited(self):
        self.assertEqual(
            len(_format_response_with_sources("가" * 3000, [])),
            1900,
        )


if __name__ == "__main__":
    unittest.main()
