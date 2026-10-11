"""Tests for OpenBagus Clean Provider Views, Domain Segregation, and Free IDX Probes."""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from openbagus.data.providers import (
    ProviderRegistry,
    VALIDATORS,
    validate_eodhd,
    validate_bps,
    validate_twelve_data,
    validate_fmp,
)


class TestProviderCleanup(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = ProviderRegistry(REPO_ROOT)

    def test_domain_categorization(self) -> None:
        idx_providers = self.registry.list_by_domain("IDX")
        idx_ids = {p.id for p in idx_providers}
        self.assertIn("eodhd", idx_ids)
        self.assertIn("bps", idx_ids)
        self.assertIn("alpha_vantage", idx_ids)
        self.assertIn("twelve_data", idx_ids)
        self.assertIn("fmp", idx_ids)

        macro_providers = self.registry.list_by_domain("MACRO")
        macro_ids = {p.id for p in macro_providers}
        self.assertIn("fred", macro_ids)

        reserved_providers = self.registry.list_by_domain("RESERVED")
        res_ids = {p.id for p in reserved_providers}
        self.assertIn("mass_sse", res_ids)
        self.assertIn("pls", res_ids)
        self.assertIn("openvici", res_ids)

    def test_default_view_hides_dormant_unmapped_slots(self) -> None:
        # Default view without show_all
        default_view = self.registry.format_providers_view(show_all=False)
        self.assertNotIn("Mass SSE", default_view)
        self.assertNotIn("PLS", default_view)
        self.assertNotIn("OpenVICI", default_view)
        self.assertIn("Dormant/advanced slots hidden", default_view)

        # Show all reveals them under reserved section
        all_view = self.registry.format_providers_view(show_all=True)
        self.assertIn("RESERVED & ADVANCED SLOTS", all_view)
        self.assertIn("Mass SSE", all_view)
        self.assertIn("PLS", all_view)
        self.assertIn("OpenVICI", all_view)

    def test_domain_filtering_view(self) -> None:
        idx_view = self.registry.format_providers_view(domain="idx")
        self.assertIn("IDX EQUITIES & INDONESIAN MACRO", idx_view)
        self.assertNotIn("ZERO-KEY CORE", idx_view)
        self.assertNotIn("CRYPTOCURRENCY & ONCHAIN", idx_view)

    def test_missing_apis_default_excludes_dormant_slots(self) -> None:
        missing_default = self.registry.list_missing_apis(show_all=False)
        missing_ids = {p.id for p in missing_default}
        self.assertNotIn("mass_sse", missing_ids)
        self.assertNotIn("pls", missing_ids)
        self.assertNotIn("openvici", missing_ids)

        missing_all = self.registry.list_missing_apis(show_all=True)
        all_ids = {p.id for p in missing_all}
        self.assertIn("mass_sse", all_ids)
        self.assertIn("pls", all_ids)
        self.assertIn("openvici", all_ids)

    def test_validators_registered(self) -> None:
        for vid in ("eodhd", "bps", "twelve_data", "fmp", "fred", "alpha_vantage"):
            self.assertIn(vid, VALIDATORS)

    def test_validator_key_format_checks(self) -> None:
        # Empty or invalid formats
        self.assertEqual(validate_eodhd(""), "MISSING")
        self.assertEqual(validate_eodhd("short"), "INVALID")
        self.assertEqual(validate_bps(""), "MISSING")
        self.assertEqual(validate_twelve_data(""), "MISSING")
        self.assertEqual(validate_fmp(""), "MISSING")


if __name__ == "__main__":
    unittest.main()
