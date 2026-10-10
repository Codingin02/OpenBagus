"""One asset lookup surface, preserving the existing crypto discovery catalog."""

from pathlib import Path

from openbagus.domains.crypto.catalog import CryptoAssetCatalog
from openbagus.domains.equities.catalog import EquityCatalog


class AssetRegistry:
    def __init__(self, root: Path, crypto: CryptoAssetCatalog | None = None) -> None:
        self.crypto = crypto or CryptoAssetCatalog(root)
        self.equities = EquityCatalog(root)

    @property
    def assets(self) -> list:
        return self.crypto.assets + self.equities.assets

    def resolve_asset(self, term: str, is_explicit: bool = False) -> tuple:
        equity = self.equities.resolve(term)
        if term.upper().startswith("IDX:") or term.upper().endswith(".JK"):
            return equity, []
        known = [a for a in self.crypto.assets if a.matches(term)]
        if equity and known:
            return None, [equity, *known]
        if equity:
            return equity, []
        return self.crypto.resolve_asset(term, is_explicit)

    def __getattr__(self, name: str):
        return getattr(self.crypto, name)
