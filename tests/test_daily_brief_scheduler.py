"""Unit and integration test suite for OpenBagus Automated Daily Research Brief Engine.

Tests:
1. DailyBriefGenerator morning and evening brief data generation.
2. Renderers: Markdown, Publication-grade PDF, and Visual PNG.
3. DailyBriefScheduler state tracking, trigger_now, draft listing, and due check.
4. IntentRouter parsing for /brief, /schedule, and natural Indonesian queries.
5. CryptoResearchRunner execution dispatch for DAILY_BRIEF.
"""

from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest

from openbagus.domains.crypto.research import CryptoResearchRunner
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.monitoring.daily_brief import (
    WIB_TZ,
    DailyBriefData,
    DailyBriefGenerator,
    DailyBriefItem,
    DailyBriefScheduler,
    render_brief_markdown,
    render_brief_pdf,
    render_brief_png,
)


class TestDailyBriefScheduler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.generator = DailyBriefGenerator(self.root)
        self.scheduler = DailyBriefScheduler(self.root)
        self.router = IntentRouter(repo_root=self.root)
        self.runner = CryptoResearchRunner(repo_root=self.root)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_generator_morning_and_evening(self):
        morning = self.generator.generate(session_type="MORNING")
        self.assertEqual(morning.session_type, "MORNING")
        self.assertGreater(len(morning.macro_events), 0)
        self.assertIn("Pra-Pembukaan", morning.ihsg_context)
        self.assertIn("Bitcoin", morning.crypto_context)
        self.assertGreater(len(morning.items), 0)
        self.assertGreater(len(morning.top_setups), 0)
        self.assertGreater(len(morning.risk_checklist), 0)

        evening = self.generator.generate(session_type="EVENING")
        self.assertEqual(evening.session_type, "EVENING")
        self.assertIn("Penutupan Perdagangan", evening.ihsg_context)
        self.assertIn("Tinjauan Sesi Sore", evening.crypto_context)

        # Test to_dict conversion
        d_dict = morning.to_dict()
        self.assertEqual(d_dict["session_type"], "MORNING")
        self.assertIsInstance(d_dict["items"], list)

    def test_render_brief_markdown(self):
        brief = self.generator.generate(session_type="MORNING")
        md = render_brief_markdown(brief)
        self.assertIn("# OPENBAGUS — RISALAH RISET PAGI (PRE-MARKET)", md)
        self.assertIn("## 1. Konteks Makroekonomi & Pasar", md)
        self.assertIn("## 3. Matriks Pengamatan Aset Unggulan (Watchlist)", md)
        self.assertIn("| Aset | Tipe | Harga Referensi |", md)
        self.assertIn("## 5. Protokol Manajemen Risiko", md)

    def test_render_brief_pdf(self):
        brief = self.generator.generate(session_type="MORNING")
        pdf_target = self.root / "test_morning_brief.pdf"
        out_path = render_brief_pdf(brief, output_path=pdf_target)
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 1000)
        with out_path.open("rb") as f:
            header = f.read(5)
        self.assertEqual(header, b"%PDF-")

    def test_render_brief_png(self):
        brief = self.generator.generate(session_type="EVENING")
        png_target = self.root / "test_evening_brief.png"
        out_path = render_brief_png(brief, output_path=png_target)
        self.assertTrue(out_path.exists())
        self.assertGreater(out_path.stat().st_size, 1000)
        with out_path.open("rb") as f:
            header = f.read(8)
        self.assertEqual(header, b"\x89PNG\r\n\x1a\n")

    def test_scheduler_status_and_listing(self):
        st = self.scheduler.get_status()
        self.assertTrue(st["enabled"])
        self.assertIn("07:30 WIB", st["morning_schedule"])
        self.assertIn("17:00 WIB", st["evening_schedule"])
        self.assertIn("drafts_directory", st)

        # Initially no drafts in temp dir
        drafts = self.scheduler.list_drafts()
        self.assertIsInstance(drafts, list)

    def test_scheduler_trigger_now(self):
        res = self.scheduler.trigger_now(session_type="MORNING")
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["session_type"], "MORNING")
        self.assertTrue(Path(res["markdown_path"]).exists())
        self.assertTrue(Path(res["pdf_path"]).exists())
        self.assertTrue(Path(res["png_path"]).exists())

        # Verify state updated
        st = self.scheduler.get_status()
        self.assertIsNotNone(st["last_morning_run"])

        # Verify listed drafts
        drafts = self.scheduler.list_drafts()
        self.assertGreaterEqual(len(drafts), 3)  # md, pdf, png

    def test_scheduler_check_due(self):
        # Morning due check at 08:00 WIB
        dt_morning = datetime(2026, 10, 14, 8, 0, tzinfo=WIB_TZ)
        res = self.scheduler.check_and_run_due_brief(now_dt=dt_morning)
        self.assertIsNotNone(res)
        self.assertEqual(res["session_type"], "MORNING")

        # Running again same morning should not duplicate
        res_dup = self.scheduler.check_and_run_due_brief(now_dt=dt_morning)
        self.assertIsNone(res_dup)

        # Evening due check at 17:30 WIB
        dt_evening = datetime(2026, 10, 14, 17, 30, tzinfo=WIB_TZ)
        res_eve = self.scheduler.check_and_run_due_brief(now_dt=dt_evening)
        self.assertIsNotNone(res_eve)
        self.assertEqual(res_eve["session_type"], "EVENING")

    def test_intent_routing_brief(self):
        # 1. Status queries
        r1 = self.router.parse("/brief")
        self.assertEqual(r1.request_type, "DAILY_BRIEF")
        self.assertEqual(r1.focus, "status")

        r2 = self.router.parse("/schedule brief")
        self.assertEqual(r2.request_type, "DAILY_BRIEF")
        self.assertEqual(r2.focus, "status")

        r3 = self.router.parse("jadwal riset harian")
        self.assertEqual(r3.request_type, "DAILY_BRIEF")
        self.assertEqual(r3.focus, "status")

        # 2. Generation queries
        r4 = self.router.parse("/brief morning")
        self.assertEqual(r4.request_type, "DAILY_BRIEF")
        self.assertEqual(r4.focus, "generate")
        self.assertEqual(r4.topic, "morning")

        r5 = self.router.parse("buat riset pagi hari ini")
        self.assertEqual(r5.request_type, "DAILY_BRIEF")
        self.assertEqual(r5.focus, "generate")
        self.assertEqual(r5.topic, "morning")

        r6 = self.router.parse("/brief evening")
        self.assertEqual(r6.request_type, "DAILY_BRIEF")
        self.assertEqual(r6.focus, "generate")
        self.assertEqual(r6.topic, "evening")

        r7 = self.router.parse("risalah riset sore")
        self.assertEqual(r7.request_type, "DAILY_BRIEF")
        self.assertEqual(r7.focus, "generate")
        self.assertEqual(r7.topic, "evening")

        # 3. Draft listing
        r8 = self.router.parse("/brief list")
        self.assertEqual(r8.request_type, "DAILY_BRIEF")
        self.assertEqual(r8.focus, "list")

        r9 = self.router.parse("daftar draf riset")
        self.assertEqual(r9.request_type, "DAILY_BRIEF")
        self.assertEqual(r9.focus, "list")

    def test_runner_execution_dispatch(self):
        session = SessionState()

        # Status inspection
        req_status = self.router.parse("/brief status", session=session)
        out_status = self.runner.execute(req_status, session=session)
        self.assertIn("Status Penjadwalan Riset Harian OpenBagus", out_status)
        self.assertIn("07:30 WIB", out_status)

        # List inspection
        req_list = self.router.parse("/brief list", session=session)
        out_list = self.runner.execute(req_list, session=session)
        self.assertTrue("Daftar Draf Riset Harian" in out_list or "Belum ada draf riset" in out_list)

        # Generation trigger
        req_gen = self.router.parse("/brief morning", session=session)
        out_gen = self.runner.execute(req_gen, session=session)
        self.assertIn("OPENBAGUS — RISALAH RISET PAGI", out_gen)
        self.assertIn("[Draf Riset Berhasil Dibuat Secara Lokal]", out_gen)
        self.assertIn("PDF Dokumen", out_gen)


if __name__ == "__main__":
    unittest.main()
