"""Test domain neutrality of OpenBagus core."""

import inspect
import unittest

import openbagus.core
import openbagus.core.contracts
import openbagus.core.env
import openbagus.core.guards
import openbagus.core.market_structure


class TestDomainNeutrality(unittest.TestCase):
    def test_core_does_not_depend_on_domains(self):
        core_modules = [
            openbagus.core.env,
            openbagus.core.guards,
            openbagus.core.contracts,
            openbagus.core.market_structure,
        ]
        for mod in core_modules:
            src = inspect.getsource(mod)
            self.assertNotIn("openbagus.domains", src, f"{mod.__name__} violates domain neutrality!")

    def test_crypto_domain_imports(self):
        import openbagus.domains.crypto.microstructure as cm
        self.assertTrue(hasattr(cm, "analyze_crypto_microstructure"))
        self.assertTrue(hasattr(cm, "funding_rate_pressure"))


if __name__ == "__main__":
    unittest.main()
