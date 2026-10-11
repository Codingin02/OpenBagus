"""Tests for OpenBagus Unlimited Local Harness Storage & SQLite Persistence."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openbagus.intelligence.intent import SessionState
from openbagus.storage.harness_db import HarnessStorage


class TestUnlimitedHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.appdata = self.root / "AppData/Local/OpenBagus"
        self.appdata.mkdir(parents=True, exist_ok=True)
        self.harness_dir = self.appdata / "harness"
        self.harness_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.harness_dir / "harness_history.db"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_harness_db_schema_and_save_turn(self) -> None:
        storage = HarnessStorage(self.db_path)
        self.assertTrue(self.db_path.exists())

        turn_id = storage.save_turn(
            session_id="test_sess_1",
            user_text="analisa BBCA",
            assistant_text="BBCA dalam konsolidasi sehat di Rp10,200.",
            asset="BBCA",
            market="IDX",
            intent="ANALYZE",
        )
        self.assertGreater(turn_id, 0)

        recent = storage.get_recent_turns(limit=10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0]["asset"], "BBCA")
        self.assertEqual(recent[0]["user"], "analisa BBCA")

    def test_unbounded_retention_over_500_turns(self) -> None:
        storage = HarnessStorage(self.db_path)
        # Store 600 turns (exceeds previous 200 turn arbitrary cap)
        for i in range(600):
            storage.save_turn(
                session_id=f"sess_{i % 5}",
                user_text=f"query {i} for BTC",
                assistant_text=f"response {i} level {60000 + i}",
                asset="BTC",
                market="PERPETUAL",
            )

        stats = storage.get_stats()
        self.assertEqual(stats["total_turns"], 600)
        self.assertGreater(stats["db_size_bytes"], 0)

        # Retrieve history
        history = storage.get_history(limit=50)
        self.assertEqual(len(history), 50)
        self.assertEqual(history[0]["user"], "query 599 for BTC")

    def test_keyword_search(self) -> None:
        storage = HarnessStorage(self.db_path)
        storage.save_turn("s1", "bagaimana valuasi ICBP?", "ICBP PER 14x, ROE 18%.", asset="ICBP")
        storage.save_turn("s1", "analisa BMRI?", "BMRI NIM 5.2%, CAR 21%.", asset="BMRI")
        storage.save_turn("s1", "apakah SOL bullish?", "SOL breakout di 190 USD.", asset="SOL")

        res_icbp = storage.search("valuasi")
        self.assertEqual(len(res_icbp), 1)
        self.assertEqual(res_icbp[0]["asset"], "ICBP")

        res_nim = storage.search("NIM")
        self.assertEqual(len(res_nim), 1)
        self.assertEqual(res_nim[0]["asset"], "BMRI")

        res_none = storage.search("nonexistent_word_12345")
        self.assertEqual(len(res_none), 0)

    def test_idempotent_migration_from_json(self) -> None:
        storage = HarnessStorage(self.db_path)
        json_file = self.harness_dir / "session_context.json"
        json_file.write_text(
            """{
                "last_asset": "KLBF",
                "market_type": "IDX",
                "last_intent": "ANALYZE",
                "conversational_turns": [
                    {"user": "cek KLBF", "assistant": "KLBF stabil di Rp1,500.", "at": "2026-01-01T10:00:00Z"},
                    {"user": "bagaimana prospeknya?", "assistant": "Operating margin 16.5%.", "at": "2026-01-01T10:05:00Z"}
                ]
            }""",
            encoding="utf-8",
        )

        migrated = storage.migrate_from_json(json_file)
        self.assertEqual(migrated, 2)
        stats = storage.get_stats()
        self.assertEqual(stats["total_turns"], 2)

        # Second migration must be idempotent (0 newly inserted)
        migrated_again = storage.migrate_from_json(json_file)
        self.assertEqual(migrated_again, 0)
        stats2 = storage.get_stats()
        self.assertEqual(stats2["total_turns"], 2)

    def test_session_state_bounded_memory_vs_unbounded_disk(self) -> None:
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "AppData/Local")}), \
             patch("openbagus.intelligence.intent.SessionState.get_harness_dir", return_value=self.harness_dir):

            session = SessionState()
            session.set_persistence_enabled(True)
            session.last_asset = "BBCA"
            session.recent_preferences["history_turn_limit"] = 10

            # Add 25 turns
            for i in range(25):
                session.add_turn(f"pertanyaan {i}", f"jawaban {i}")

            # In-memory working window is bounded to recent turns for LLM prompt safety
            self.assertLessEqual(len(session.conversational_turns), 10)

            # SQLite storage holds all 25 turns without truncation
            stats = session.get_storage_stats()
            self.assertEqual(stats["total_turns"], 25)

            # Search finds older turn that slid out of in-memory working window
            found = session.search_history("pertanyaan 2")
            self.assertTrue(any("pertanyaan 2" in t["user"] for t in found))


if __name__ == "__main__":
    unittest.main()
