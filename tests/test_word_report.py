"""Unit tests for Microsoft Word (.docx) native report generator with editable Office charts."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from openbagus.domains.crypto.quant import QuantDecisionResult
from openbagus.domains.equities.ownership import load_ownership
from openbagus.reporting.word_report import generate_word_report


class TestWordReport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.quant = QuantDecisionResult(
            asset="BBCA",
            market="idx",
            decision="BUY",
            regime="Markup",
            confidence="HIGH",
            price=10500.0,
            entry_zone="10400.0 - 10500.0",
            stop_price=10100.0,
            tp1=11200.0,
            tp2=11600.0,
            reward_risk=2.33,
            reward_risk_str="1:2.33",
            leverage_ceiling="1x",
            leverage_num=1,
            why={"Trend": "Bullish", "Breakout": "Confirmed"},
            sources=["IDX Financial Data", "KSEI Ownership"],
            evidence_count=4,
            composite_score=0.82,
            composite_quality=0.90,
            rr_gate_passed=True,
            quality_gate_passed=True,
            decision_reason="Bullish breakout above resistance with volume expansion.",
            timeframe="D1",
        )
        self.ownership = load_ownership("BBCA", Path("."))

    def tearDown(self):
        self.tmp.cleanup()

    def test_docx_openxml_package_and_drawingml_chart(self):
        docx_file = generate_word_report(
            asset="BBCA",
            quant_result=self.quant,
            ownership=self.ownership,
            root=self.root,
            timeframe="D1",
        )
        self.assertTrue(docx_file.exists())
        self.assertEqual(docx_file.suffix, ".docx")

        with zipfile.ZipFile(docx_file, "r") as z:
            names = z.namelist()

            # Required OpenXML parts
            self.assertIn("[Content_Types].xml", names)
            self.assertIn("_rels/.rels", names)
            self.assertIn("word/document.xml", names)
            self.assertIn("word/_rels/document.xml.rels", names)
            self.assertIn("word/charts/chart1.xml", names)
            self.assertIn("word/charts/_rels/chart1.xml.rels", names)
            self.assertIn("word/embeddings/Microsoft_Excel_Worksheet1.xlsx", names)

            # Check [Content_Types].xml
            ct = z.read("[Content_Types].xml").decode("utf-8")
            self.assertIn("/word/charts/chart1.xml", ct)
            self.assertIn("/word/embeddings/Microsoft_Excel_Worksheet1.xlsx", ct)

            # Check word/document.xml
            doc = z.read("word/document.xml").decode("utf-8")
            self.assertIn("OpenBagus Quantitative Research Report", doc)
            self.assertIn("BBCA", doc)
            self.assertIn("BUY", doc)
            self.assertIn("drawingml", doc)
            self.assertIn("<w:drawing>", doc)
            self.assertIn("Shareholder Ownership Disclosure", doc)

            # Check DrawingML chart definition in chart1.xml
            chart = z.read("word/charts/chart1.xml").decode("utf-8")
            self.assertIn("<c:chartSpace", chart)
            self.assertIn("<c:externalData", chart)
            self.assertIn('r:id="rId1"', chart)

            # Check embedded Excel workbook
            xlsx_bytes = z.read("word/embeddings/Microsoft_Excel_Worksheet1.xlsx")
            import io
            with zipfile.ZipFile(io.BytesIO(xlsx_bytes), "r") as xz:
                xnames = xz.namelist()
                self.assertIn("[Content_Types].xml", xnames)
                self.assertIn("xl/workbook.xml", xnames)
                self.assertIn("xl/worksheets/sheet1.xml", xnames)

    def test_crypto_word_report_without_ownership(self):
        crypto_quant = QuantDecisionResult(
            asset="BTC",
            market="perpetual",
            decision="NO_TRADE",
            regime="Compressed",
            confidence="MODERATE",
            price=85000.0,
            entry_zone="Breakout $85,500.00",
            stop_price=84000.0,
            tp1=87000.0,
            tp2=88500.0,
            reward_risk=1.60,
            reward_risk_str="1:1.60",
            leverage_ceiling="3x",
            leverage_num=3,
            why={"Trend": "Neutral"},
            sources=["Binance Vision"],
            evidence_count=2,
            composite_score=0.20,
            composite_quality=0.80,
            rr_gate_passed=False,
            quality_gate_passed=True,
            decision_reason="Consolidation range.",
            timeframe="H1",
        )
        docx_file = generate_word_report(
            asset="BTC",
            quant_result=crypto_quant,
            ownership=None,
            root=self.root,
            timeframe="H1",
        )
        self.assertTrue(docx_file.exists())
        with zipfile.ZipFile(docx_file, "r") as z:
            doc = z.read("word/document.xml").decode("utf-8")
            self.assertIn("BTC", doc)
            self.assertIn("NO_TRADE", doc)
            # Ownership section is omitted for crypto
            self.assertNotIn("Shareholder Ownership Disclosure", doc)


if __name__ == "__main__":
    unittest.main()
