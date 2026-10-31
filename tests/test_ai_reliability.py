import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from database import database as database_module
from services import prompt_builder


class DatabaseReliabilityTests(unittest.TestCase):
    def test_concurrent_writes_use_separate_cursors(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(database_module, "DATABASE_PATH", Path(directory) / "test.db"):
                database = database_module.Database()
                with ThreadPoolExecutor(max_workers=4) as executor:
                    list(executor.map(
                        lambda value: database.add_conversation(17, 2, "user", str(value)),
                        range(16),
                    ))
                self.assertEqual(database.count_conversations(17, 2), 16)

    def test_summary_only_deletes_the_summarized_batch(self):
        with tempfile.TemporaryDirectory() as directory:
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


if __name__ == "__main__":
    unittest.main()
