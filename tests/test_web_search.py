import os
import unittest
from unittest.mock import Mock, patch

from services import web_search


class SearchRoutingTests(unittest.TestCase):
    def test_verifiable_facts_trigger_search(self):
        for question in (
            "이완용은 누구야?",
            "세종대왕은 몇 년에 태어났어?",
            "이완용의 작위와 출생지 알려줘",
            "오늘 환율 알려줘",
            "메모리의 원리가 뭐야?",
            "안녕, 이완용 검색해줘",
        ):
            with self.subTest(question=question):
                self.assertTrue(web_search.needs_search(question))

    def test_personal_chat_stays_local(self):
        for question in (
            "안녕 ㅋㅋ",
            "플레타야 뭐해?",
            "나는 오늘 기분이 좋아",
            "내가 아까 뭐라고 했어?",
            "사랑해",
        ):
            with self.subTest(question=question):
                self.assertFalse(web_search.needs_search(question))

    def test_search_query_cleanup(self):
        self.assertEqual(
            web_search.prepare_search_query("플레타야, 이완용은 누구야? <@12345>"),
            "이완용은 누구야?",
        )


class WebSearchTests(unittest.TestCase):
    def setUp(self):
        web_search._CACHE.clear()

    def tearDown(self):
        web_search._CACHE.clear()

    def test_relevance_and_domains_and_cache(self):
        response = Mock()
        response.json.return_value = {
            "results": [
                {"url": "http://127.0.0.1/private", "title": "secret", "content": "private"},
                {"url": "https://someblog.example/post", "title": "blog", "content": "unverified", "score": 0.9},
                {"url": "https://encyclopedia.go.kr/article", "title": "official", "content": "source text", "score": 0.8},
                {"url": "https://encyclopedia.go.kr/article", "title": "duplicate", "content": "duplicate"},
            ],
        }
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test"}):
            with patch.object(web_search.httpx, "post", return_value=response) as request:
                first = web_search.search_web("이완용은 누구야?")
                second = web_search.search_web("이완용은 누구야?")
        self.assertEqual(first, second)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(len(first[1]), 2)
        self.assertEqual(first[1][0][0], "official")
        self.assertNotIn("127.0.0.1", first[0])

    def test_search_failure_does_not_invent_sources(self):
        with patch.dict(os.environ, {"TAVILY_API_KEY": "test"}):
            with patch.object(web_search.httpx, "post", side_effect=web_search.httpx.TimeoutException("timeout")):
                self.assertIsNone(web_search.search_web("이완용은 누구야?"))

    def test_missing_api_key_is_safe(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(web_search.search_web("이완용은 누구야?"))


if __name__ == "__main__":
    unittest.main()
