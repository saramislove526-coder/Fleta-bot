import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import asyncio

from database import database as database_module
from services import ai_service, prompt_builder
from services.grounding import extract_claims, find_unsupported_claims
from services import web_search


class DatabaseReliabilityTests(unittest.TestCase):
    def test_concurrent_writes_use_separate_cursors(self):
        # 윈도우는 열린 DB 파일을 못 지워서 정리 단계 오류만 무시합니다. (리눅스 CI는 원래 문제없습니다.)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            with patch.object(database_module, "DATABASE_PATH", Path(directory) / "test.db"):
                database = database_module.Database()
                with ThreadPoolExecutor(max_workers=4) as executor:
                    list(executor.map(
                        lambda value: database.add_conversation(17, 2, "user", str(value)),
                        range(16),
                    ))
                self.assertEqual(database.count_conversations(17, 2), 16)

    def test_summary_only_deletes_the_summarized_batch(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            with patch.object(database_module, "DATABASE_PATH", Path(directory) / "test.db"):
                database = database_module.Database()
                for index in range(30):
                    database.add_conversation(17, 2, "user", f"message {index}")
                rows = database.get_conversations_for_summary(17, 2, 10, limit=12)
                self.assertEqual(len(rows), 12)
                database.commit_summary_batch(17, 2, "confirmed facts", rows[-1]["id"])
                self.assertEqual(database.count_conversations(17, 2), 18)
                self.assertEqual(database.get_summary(17, 2), "confirmed facts")
                remaining = database.get_conversation(17, 2, 30)
                self.assertEqual(remaining[0]["content"], "message 12")


class PromptReliabilityTests(unittest.TestCase):
    def test_search_evidence_survives_user_input_limit(self):
        character = {
            "id": 2,
            "name": "플레타",
            "description": "",
            "personality": "",
            "speech": "",
            "world": "",
        }
        with patch.object(prompt_builder.db, "get_conversation", return_value=[]), \
             patch.object(prompt_builder.db, "get_summary", return_value=""), \
             patch.object(prompt_builder, "get_memories", return_value=[]), \
             patch.object(prompt_builder.AffectionService, "get", return_value=0), \
             patch.object(prompt_builder.AffectionService, "get_level", return_value="보통"):
            messages = prompt_builder.build_prompt(
                17, character, "가" * 1500, search_context="검증된검색결과",
            )
        self.assertIn("검증된검색결과", messages[-1]["content"])
        self.assertEqual(messages[-1]["role"], "user")


CHARACTER = {"id": 2, "name": "플레타", "description": "", "personality": "", "speech": "", "world": "", "avatar": None}


def _build(message, **kwargs):
    with patch.object(prompt_builder.db, "get_conversation", return_value=[]), \
         patch.object(prompt_builder.db, "get_summary", return_value=""), \
         patch.object(prompt_builder, "get_memories", return_value=[]), \
         patch.object(prompt_builder.AffectionService, "get", return_value=0), \
         patch.object(prompt_builder.AffectionService, "get_level", return_value="보통"):
        return prompt_builder.build_prompt(17, CHARACTER, message, **kwargs)


class FactualQuestionTests(unittest.TestCase):
    """검색 판단은 web_search.needs_search가 합니다. 여기선 정확도 관점에서 꼭 지켜야 할 경우만 확인합니다."""

    def test_detects_fact_questions(self):
        for text in (
            "엔비디아 CEO 누구야?",
            "세종대왕 언제 태어났어?",
            "우리나라 인구 몇 명이야?",
            "2002 월드컵 어디서 했어?",
            "광합성 원리 알려줘",
            "내일 개봉하는 영화 뭐야?",
        ):
            with self.subTest(text=text):
                self.assertTrue(web_search.needs_search(text))

    def test_skips_small_talk_and_personal_questions(self):
        for text in (
            "너 몇 살이야?", "내 생일 언제였지?", "뭐해?", "오늘 기분 어때?", "밥 먹었어?", "사랑해",
            "오늘 사장한테 혼났어", "어제 올림픽 봤는데 재밌더라", "그 감독 영화 진짜 좋아",
        ):
            with self.subTest(text=text):
                self.assertFalse(web_search.needs_search(text))

    def test_ignores_discord_context_lines(self):
        text = "[답장한 메시지 - 철수]: 너 몇 살이야?\n엔비디아 CEO 누구야?\nAttached files: a.png."
        self.assertEqual(web_search.prepare_search_query(text), "엔비디아 CEO 누구야?")
        self.assertTrue(web_search.needs_search(text))


class GroundingTests(unittest.TestCase):
    def test_supported_numbers_pass(self):
        evidence = "[1] 출시일 2024-03-05, 가격 1299달러"
        self.assertEqual(find_unsupported_claims("2024년 3월 5일에 나왔고 1,299달러야 [1]", evidence), [])

    def test_unsupported_numbers_are_reported(self):
        evidence = "[1] 출시일 2024-03-05"
        self.assertEqual(find_unsupported_claims("2023년에 출시됐어", evidence), ["2023년"])

    def test_small_counts_are_not_claims(self):
        self.assertEqual(extract_claims("두 가지야. 1개는 빨강, 2명이 왔어"), [])


class AccuracyPromptTests(unittest.TestCase):
    def test_evidence_rules_and_numbered_sources(self):
        messages = _build("엔비디아 CEO 누구야?", search_context="[1] 젠슨 황\n출처: https://a", search_attempted=True)
        self.assertIn(prompt_builder.EVIDENCE_RULES, messages[-1]["content"])
        self.assertIn("[1] 젠슨 황", messages[-1]["content"])

    def test_failed_search_has_no_citation_rules(self):
        messages = _build("엔비디아 CEO 누구야?", search_attempted=True)
        self.assertNotIn(prompt_builder.EVIDENCE_RULES, messages[-1]["content"])
        self.assertIn("[Search unavailable]", messages[0]["content"])

    def test_small_talk_gets_no_extra_rules(self):
        content = _build("뭐해?")[-1]["content"]
        self.assertNotIn("[정확성 규칙]", content)


class VerifyAnswerTests(unittest.TestCase):
    def test_grounded_answer_skips_revision(self):
        with patch.object(ai_service, "_request_generation") as generate:
            answer, note = ai_service._verify_answer("2024년이야 [1]", "[1] 2024년 발표", "언제야?", True)
        generate.assert_not_called()
        self.assertEqual((answer, note), ("2024년이야 [1]", ""))

    def test_unsupported_answer_is_revised_once(self):
        with patch.object(ai_service, "_request_generation", return_value="2024년이야 [1]") as generate:
            answer, note = ai_service._verify_answer("2023년이야", "[1] 2024년 발표", "언제야?", True)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual((answer, note), ("2024년이야 [1]", ""))

    def test_failed_revision_keeps_draft_with_note(self):
        with patch.object(ai_service, "_request_generation", side_effect=ai_service.AIServiceError("down")):
            answer, note = ai_service._verify_answer("2023년이야", "[1] 2024년 발표", "언제야?", True)
        self.assertEqual(answer, "2023년이야")
        self.assertIn("2023년", note)

    def test_unverified_fact_answer_gets_warning(self):
        answer, note = ai_service._verify_answer("1397년에 태어났어", None, "세종대왕 언제 태어났어?", True)
        self.assertEqual(note, ai_service._NO_EVIDENCE_NOTE)
        self.assertEqual(ai_service._verify_answer("응 좋아", None, "뭐해?", False), ("응 좋아", ""))


class ModelFailureTests(unittest.TestCase):
    def test_timeout_cools_down_only_that_model(self):
        with patch.dict(os.environ, {"GROQ_API_KEY": "k"}), \
             patch.object(ai_service.httpx, "post", side_effect=ai_service.httpx.ReadTimeout("slow")):
            with self.assertRaises(ai_service.AIConfigError) as caught:
                ai_service._single_api_call("groq", [{"role": "user", "content": "hi"}], model="slow-model")
        self.assertFalse(caught.exception.provider_wide)

    def test_retired_model_message_is_model_error(self):
        response = ai_service.httpx.Response(404, text='{"error": {"message": "This model is no longer available."}}')
        with patch.dict(os.environ, {"GROQ_API_KEY": "k"}), \
             patch.object(ai_service.httpx, "post", return_value=response):
            with self.assertRaises(ai_service.AIConfigError) as caught:
                ai_service._single_api_call("groq", [{"role": "user", "content": "hi"}], model="old-model")
        self.assertFalse(caught.exception.provider_wide)


class GenerateResponseWiringTests(unittest.TestCase):
    def _run(self, message, search_result):
        calls = {}

        def fake_generation(messages, image_urls=None, max_tokens=0, temperature=0.0):
            calls["temperature"] = temperature
            calls["last"] = messages[-1]["content"]
            return "젠슨 황이야 [1]"

        stored = []
        with patch.object(ai_service.db, "get_selected_character", return_value=CHARACTER), \
             patch.object(ai_service.db, "add_conversation", side_effect=lambda *a: stored.append(a)), \
             patch.object(ai_service, "remember_message"), \
             patch.object(ai_service, "_summarize_conversation"), \
             patch.object(ai_service, "search_web", return_value=search_result) as search, \
             patch.object(ai_service, "build_prompt", side_effect=lambda *a, **k: [{"role": "user", "content": str(k)}]), \
             patch.object(ai_service, "_request_generation", side_effect=fake_generation), \
             patch.object(ai_service.AffectionService, "check_cooldown", return_value=False), \
             patch.object(ai_service.AffectionService, "apply_delta", return_value={"level_changed": False}):
            text, _ = asyncio.run(ai_service.generate_response(17, None, message))
        return text, calls, search, stored

    def test_fact_question_searches_and_uses_low_temperature(self):
        text, calls, search, stored = self._run(
            "엔비디아 CEO 누구야?", ("[1] 젠슨 황\n출처: https://a", [("엔비디아", "https://a")]),
        )
        search.assert_called_once_with("엔비디아 CEO 누구야?")
        self.assertEqual(calls["temperature"], ai_service._FACT_TEMPERATURE)
        self.assertIn("'search_attempted': True", calls["last"])
        self.assertIn("[1] [엔비디아](https://a)", text)
        self.assertEqual(stored[-1][3], "젠슨 황이야 [1]")

    def test_small_talk_does_not_search(self):
        _, calls, search, _ = self._run("뭐해?", None)
        search.assert_not_called()
        self.assertLessEqual(calls["temperature"], ai_service._CHAT_TEMPERATURE_CAP)


if __name__ == "__main__":
    unittest.main()
