"""OpenBagus Executable Arbitrage & Cross-Exchange Dislocation Engine.

Implements real executable order-book depth consumption, taker fees,
slippage, transfer/gas costs, triangular route validation, and spot-perp basis.
Never reports raw price dispersion as guaranteed profit.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass
class DepthWalkResult:
    vwap: float
    filled_qty: float
    filled_notional: float
    is_fully_filled: bool
    levels_traversed: int
    slippage_pct: float


@dataclass
class ArbitrageOpportunity:
    symbol: str
    buy_venue: str
    sell_venue: str
    declared_notional: float
    buy_vwap: float
    sell_vwap: float
    gross_spread_pct: float
    net_spread_pct: float
    net_profit_usd: float
    taker_fee_pct_total: float
    slippage_pct_total: float
    transfer_fee_usd: float
    status: str  # OBSERVED_SPREAD | POTENTIAL_AFTER_COSTS | EXECUTION_RISK | NOT_EXECUTABLE | STALE_QUOTES
    rationale: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class TriangularArbitrageResult:
    route: list[str]
    initial_notional: float
    final_notional: float
    gross_return_pct: float
    net_return_pct: float
    total_fee_pct: float
    status: str  # POTENTIAL_AFTER_COSTS | NOT_EXECUTABLE | INSUFFICIENT_DATA
    summary: str
    legs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BasisDislocationResult:
    symbol: str
    spot_price: float
    perp_price: float
    basis_usd: float
    basis_pct: float
    funding_rate_8h: float | None
    funding_annualized_pct: float | None
    net_cash_carry_apr_pct: float | None
    status: str  # NORMAL | ELEVATED | INVERTED_BACKWARDATION
    summary: str


class ArbitrageEngine:
    """Canonical engine for market microstructure dislocation and arbitrage analysis."""

    DEFAULT_TAKER_FEE_PCT = 0.10  # 0.10% per leg
    DEFAULT_SLIPPAGE_BUFFER_PCT = 0.05
    MAX_ACCEPTABLE_STALENESS_SECONDS = 30.0

    @staticmethod
    def walk_orderbook_asks(
        asks: Sequence[Sequence[float]],
        target_notional_usd: float,
    ) -> DepthWalkResult:
        """Walks up the ask book to determine executable buy VWAP for target notional."""
        if not asks or target_notional_usd <= 0:
            return DepthWalkResult(0.0, 0.0, 0.0, False, 0, 0.0)

        # Sort asks ascending by price
        sorted_asks = sorted(asks, key=lambda x: float(x[0]))
        best_price = float(sorted_asks[0][0])
        accum_notional = 0.0
        accum_qty = 0.0
        levels = 0

        for price_val, qty_val in sorted_asks:
            price = float(price_val)
            qty = float(qty_val)
            levels += 1
            level_notional = price * qty

            needed_notional = target_notional_usd - accum_notional
            if level_notional >= needed_notional:
                needed_qty = needed_notional / price
                accum_qty += needed_qty
                accum_notional += needed_notional
                break
            else:
                accum_qty += qty
                accum_notional += level_notional

        is_filled = accum_notional >= target_notional_usd - 1e-6
        vwap = (accum_notional / accum_qty) if accum_qty > 0 else 0.0
        slippage = ((vwap - best_price) / best_price) * 100.0 if best_price > 0 else 0.0

        return DepthWalkResult(
            vwap=round(vwap, 4),
            filled_qty=round(accum_qty, 6),
            filled_notional=round(accum_notional, 2),
            is_fully_filled=is_filled,
            levels_traversed=levels,
            slippage_pct=round(slippage, 4),
        )

    @staticmethod
    def walk_orderbook_bids(
        bids: Sequence[Sequence[float]],
        target_notional_usd: float,
    ) -> DepthWalkResult:
        """Walks down the bid book to determine executable sell VWAP for target notional."""
        if not bids or target_notional_usd <= 0:
            return DepthWalkResult(0.0, 0.0, 0.0, False, 0, 0.0)

        # Sort bids descending by price
        sorted_bids = sorted(bids, key=lambda x: float(x[0]), reverse=True)
        best_price = float(sorted_bids[0][0])
        accum_notional = 0.0
        accum_qty = 0.0
        levels = 0

        for price_val, qty_val in sorted_bids:
            price = float(price_val)
            qty = float(qty_val)
            levels += 1
            level_notional = price * qty

            needed_notional = target_notional_usd - accum_notional
            if level_notional >= needed_notional:
                needed_qty = needed_notional / price
                accum_qty += needed_qty
                accum_notional += needed_notional
                break
            else:
                accum_qty += qty
                accum_notional += level_notional

        is_filled = accum_notional >= target_notional_usd - 1e-6
        vwap = (accum_notional / accum_qty) if accum_qty > 0 else 0.0
        slippage = ((best_price - vwap) / best_price) * 100.0 if best_price > 0 else 0.0

        return DepthWalkResult(
            vwap=round(vwap, 4),
            filled_qty=round(accum_qty, 6),
            filled_notional=round(accum_notional, 2),
            is_fully_filled=is_filled,
            levels_traversed=levels,
            slippage_pct=round(slippage, 4),
        )

    def evaluate_cross_venue_arbitrage(
        self,
        symbol: str,
        venues: dict[str, dict[str, Any]],
        declared_notional: float = 1000.0,
        taker_fee_pct: float = DEFAULT_TAKER_FEE_PCT,
        transfer_fee_usd: float = 1.0,
        now_ts: float | None = None,
    ) -> ArbitrageOpportunity:
        """Compares orderbooks across venues with executable depth, fees, and slippage."""
        now = now_ts or time.time()
        sym = symbol.upper()

        if len(venues) < 2:
            return ArbitrageOpportunity(
                symbol=sym,
                buy_venue="N/A",
                sell_venue="N/A",
                declared_notional=declared_notional,
                buy_vwap=0.0,
                sell_vwap=0.0,
                gross_spread_pct=0.0,
                net_spread_pct=0.0,
                net_profit_usd=0.0,
                taker_fee_pct_total=0.0,
                slippage_pct_total=0.0,
                transfer_fee_usd=transfer_fee_usd,
                status="NOT_EXECUTABLE",
                rationale="Kurang dari 2 venue aktif untuk perbandingan lintas bursa.",
            )

        # Check quote staleness
        is_stale = False
        for v_name, v_data in venues.items():
            obs_ts = v_data.get("timestamp") or v_data.get("observed_at_ts")
            if obs_ts and (now - float(obs_ts)) > self.MAX_ACCEPTABLE_STALENESS_SECONDS:
                is_stale = True
                break

        best_opp: ArbitrageOpportunity | None = None
        venue_names = list(venues.keys())

        for i in range(len(venue_names)):
            for j in range(len(venue_names)):
                if i == j:
                    continue
                v_buy = venue_names[i]
                v_sell = venue_names[j]

                book_buy = venues[v_buy]
                book_sell = venues[v_sell]

                asks = book_buy.get("asks") or []
                bids = book_sell.get("bids") or []

                # Fallback to top of book if full book not provided
                if not asks and book_buy.get("ask"):
                    asks = [[book_buy["ask"], declared_notional / book_buy["ask"]]]
                elif not asks and book_buy.get("price"):
                    asks = [[book_buy["price"], declared_notional / book_buy["price"]]]

                if not bids and book_sell.get("bid"):
                    bids = [[book_sell["bid"], declared_notional / book_sell["bid"]]]
                elif not bids and book_sell.get("price"):
                    bids = [[book_sell["price"], declared_notional / book_sell["price"]]]

                walk_buy = self.walk_orderbook_asks(asks, declared_notional)
                walk_sell = self.walk_orderbook_bids(bids, declared_notional)

                if not walk_buy.is_fully_filled or not walk_sell.is_fully_filled:
                    continue

                if walk_buy.vwap <= 0 or walk_sell.vwap <= 0:
                    continue

                gross_spread_pct = ((walk_sell.vwap - walk_buy.vwap) / walk_buy.vwap) * 100.0
                total_taker_fee_pct = taker_fee_pct * 2.0  # Buy leg + Sell leg
                total_slippage_pct = walk_buy.slippage_pct + walk_sell.slippage_pct
                transfer_cost_pct = (transfer_fee_usd / declared_notional) * 100.0 if declared_notional > 0 else 0.0

                total_costs_pct = total_taker_fee_pct + total_slippage_pct + transfer_cost_pct
                net_spread_pct = gross_spread_pct - total_costs_pct
                net_profit_usd = declared_notional * (net_spread_pct / 100.0)

                # Status determination
                if is_stale:
                    status = "STALE_QUOTES"
                    rationale = f"Kutipan harga dari salah satu bursa kedaluwarsa (> {self.MAX_ACCEPTABLE_STALENESS_SECONDS:.0f}s)."
                elif net_spread_pct > 0.05:
                    status = "POTENTIAL_AFTER_COSTS"
                    rationale = (
                        f"Peluang arbitrase positif terkonfirmasi setelah biaya. "
                        f"Gross {gross_spread_pct:+.2f}%, Biaya total {total_costs_pct:.2f}% (Taker {total_taker_fee_pct:.2f}%, "
                        f"Slippage {total_slippage_pct:.2f}%, Transfer {transfer_cost_pct:.2f}%), "
                        f"Net profit estimasi: ${net_profit_usd:+.2f}."
                    )
                elif gross_spread_pct > 0:
                    status = "OBSERVED_SPREAD"
                    rationale = (
                        f"Spread kotor terlihat ({gross_spread_pct:+.2f}%), namun menjadi negatif ({net_spread_pct:+.2f}%) "
                        f"setelah memperhitungkan biaya taker {total_taker_fee_pct:.2f}% dan slippage depth."
                    )
                else:
                    status = "NOT_EXECUTABLE"
                    rationale = f"Harga beli di {v_buy} (${walk_buy.vwap:,.2f}) lebih tinggi dari harga jual di {v_sell} (${walk_sell.vwap:,.2f})."

                # Check execution risk (wide bid-ask spread on individual book)
                spread_buy_venue = (
                    ((book_buy.get("ask", walk_buy.vwap) - book_buy.get("bid", walk_buy.vwap)) / walk_buy.vwap) * 100.0
                    if book_buy.get("bid")
                    else 0.0
                )
                if spread_buy_venue > 0.40 and status == "POTENTIAL_AFTER_COSTS":
                    status = "EXECUTION_RISK"
                    rationale += " Peringatan: Bid-Ask spread di bursa asal melebar (>0.40%), risiko eksekusi tinggi."

                opp = ArbitrageOpportunity(
                    symbol=sym,
                    buy_venue=v_buy,
                    sell_venue=v_sell,
                    declared_notional=declared_notional,
                    buy_vwap=walk_buy.vwap,
                    sell_vwap=walk_sell.vwap,
                    gross_spread_pct=round(gross_spread_pct, 4),
                    net_spread_pct=round(net_spread_pct, 4),
                    net_profit_usd=round(net_profit_usd, 2),
                    taker_fee_pct_total=round(total_taker_fee_pct, 4),
                    slippage_pct_total=round(total_slippage_pct, 4),
                    transfer_fee_usd=transfer_fee_usd,
                    status=status,
                    rationale=rationale,
                    details={
                        "walk_buy": walk_buy.__dict__,
                        "walk_sell": walk_sell.__dict__,
                        "total_costs_pct": round(total_costs_pct, 4),
                    },
                )

                if best_opp is None or opp.net_spread_pct > best_opp.net_spread_pct:
                    best_opp = opp

        if best_opp is None:
            return ArbitrageOpportunity(
                symbol=sym,
                buy_venue="N/A",
                sell_venue="N/A",
                declared_notional=declared_notional,
                buy_vwap=0.0,
                sell_vwap=0.0,
                gross_spread_pct=0.0,
                net_spread_pct=0.0,
                net_profit_usd=0.0,
                taker_fee_pct_total=0.0,
                slippage_pct_total=0.0,
                transfer_fee_usd=transfer_fee_usd,
                status="NOT_EXECUTABLE",
                rationale="Kedalaman buku pesanan tidak mencukupi untuk notional yang diminta.",
            )

        return best_opp

    def evaluate_triangular_arbitrage(
        self,
        rates: dict[str, float],
        route: list[str] = ("USDT", "BTC", "ETH", "USDT"),
        initial_notional: float = 1000.0,
        fee_per_leg_pct: float = DEFAULT_TAKER_FEE_PCT,
    ) -> TriangularArbitrageResult:
        """Validates a triangular arbitrage route deducting taker fees on each leg.

        rates format: e.g. {'BTC/USDT': 65000.0, 'ETH/BTC': 0.052, 'ETH/USDT': 3380.0}
        """
        if len(route) < 4 or route[0] != route[-1]:
            return TriangularArbitrageResult(
                route=list(route),
                initial_notional=initial_notional,
                final_notional=0.0,
                gross_return_pct=0.0,
                net_return_pct=0.0,
                total_fee_pct=0.0,
                status="INSUFFICIENT_DATA",
                summary="Rute segitiga harus berawal dan berakhir pada aset dasar yang sama.",
            )

        current_amount = initial_notional
        legs: list[dict[str, Any]] = []
        fee_multiplier = 1.0 - (fee_per_leg_pct / 100.0)

        for step in range(len(route) - 1):
            base = route[step]
            target = route[step + 1]
            pair_direct = f"{target}/{base}"
            pair_inverse = f"{base}/{target}"

            if pair_direct in rates:
                rate = rates[pair_direct]
                if rate <= 0:
                    return TriangularArbitrageResult(list(route), initial_notional, 0.0, 0.0, 0.0, 0.0, "INSUFFICIENT_DATA", "Kurs tidak valid.")
                # We are buying target using base: new_amount = current_amount / rate
                next_amount = (current_amount / rate) * fee_multiplier
                legs.append({
                    "action": f"BUY {target} with {base}",
                    "pair": pair_direct,
                    "rate": rate,
                    "in_amount": current_amount,
                    "out_amount": next_amount,
                })
                current_amount = next_amount
            elif pair_inverse in rates:
                rate = rates[pair_inverse]
                if rate <= 0:
                    return TriangularArbitrageResult(list(route), initial_notional, 0.0, 0.0, 0.0, 0.0, "INSUFFICIENT_DATA", "Kurs tidak valid.")
                # We are selling base to get target: new_amount = current_amount * rate
                next_amount = (current_amount * rate) * fee_multiplier
                legs.append({
                    "action": f"SELL {base} for {target}",
                    "pair": pair_inverse,
                    "rate": rate,
                    "in_amount": current_amount,
                    "out_amount": next_amount,
                })
                current_amount = next_amount
            else:
                return TriangularArbitrageResult(
                    route=list(route),
                    initial_notional=initial_notional,
                    final_notional=0.0,
                    gross_return_pct=0.0,
                    net_return_pct=0.0,
                    total_fee_pct=0.0,
                    status="INSUFFICIENT_DATA",
                    summary=f"Pasangan kurs untuk leg {base}->{target} tidak ditemukan dalam data feed.",
                )

        gross_multiplier = 1.0
        for leg in legs:
            pair = leg["pair"]
            rate = leg["rate"]
            if leg["action"].startswith("BUY"):
                gross_multiplier /= rate
            else:
                gross_multiplier *= rate

        gross_return_pct = (gross_multiplier - 1.0) * 100.0
        net_return_pct = ((current_amount - initial_notional) / initial_notional) * 100.0
        total_fee_pct = (len(route) - 1) * fee_per_leg_pct

        if net_return_pct > 0.02:
            status = "POTENTIAL_AFTER_COSTS"
            summary = (
                f"Triangular arbitrage {'>'.join(route)} menghasilkan profit bersih "
                f"{net_return_pct:+.2f}% setelah 3 leg fee total {total_fee_pct:.2f}%."
            )
        else:
            status = "NOT_EXECUTABLE"
            summary = (
                f"Triangular route {'>'.join(route)} tidak menguntungkan: gross return "
                f"{gross_return_pct:+.2f}%, net return {net_return_pct:+.2f}% (biaya 3 leg: {total_fee_pct:.2f}%)."
            )

        return TriangularArbitrageResult(
            route=list(route),
            initial_notional=initial_notional,
            final_notional=round(current_amount, 4),
            gross_return_pct=round(gross_return_pct, 4),
            net_return_pct=round(net_return_pct, 4),
            total_fee_pct=round(total_fee_pct, 4),
            status=status,
            summary=summary,
            legs=legs,
        )

    def evaluate_basis_dislocation(
        self,
        symbol: str,
        spot_price: float,
        perp_price: float,
        funding_rate_8h: float | None = None,
        roundtrip_fee_pct: float = 0.20,
    ) -> BasisDislocationResult:
        """Evaluates spot-perp basis dislocation and cash-and-carry carry yield."""
        sym = symbol.upper()
        if spot_price <= 0 or perp_price <= 0:
            return BasisDislocationResult(
                symbol=sym,
                spot_price=spot_price,
                perp_price=perp_price,
                basis_usd=0.0,
                basis_pct=0.0,
                funding_rate_8h=None,
                funding_annualized_pct=None,
                net_cash_carry_apr_pct=None,
                status="NORMAL",
                summary="Harga spot atau perp tidak valid.",
            )

        basis_usd = perp_price - spot_price
        basis_pct = (basis_usd / spot_price) * 100.0

        funding_apr = None
        net_apr = None
        if funding_rate_8h is not None:
            # 3 intervals of 8h per day * 365 days
            funding_apr = funding_rate_8h * 3.0 * 365.0 * 100.0
            # Net cash-and-carry: earn funding yield minus entry/exit trading fee
            net_apr = funding_apr - (roundtrip_fee_pct * (365.0 / 30.0))  # amortized over 30d hold

        if basis_pct < -0.50:
            status = "INVERTED_BACKWARDATION"
            summary = f"Basis diskon tajam ({basis_pct:.2f}%); pasar perpetual mengalami backwardation/tekanan jual futures."
        elif basis_pct > 0.80:
            status = "ELEVATED"
            summary = f"Basis contango tinggi ({basis_pct:+.2f}%); perpetual premium over spot."
        else:
            status = "NORMAL"
            summary = f"Basis normal ({basis_pct:+.2f}%); harga spot dan perp selaras."

        if funding_apr is not None:
            summary += f" Funding 8h: {funding_rate_8h:+.4%}, Annualized carry: {funding_apr:+.2f}%."

        return BasisDislocationResult(
            symbol=sym,
            spot_price=round(spot_price, 4),
            perp_price=round(perp_price, 4),
            basis_usd=round(basis_usd, 4),
            basis_pct=round(basis_pct, 4),
            funding_rate_8h=funding_rate_8h,
            funding_annualized_pct=round(funding_apr, 2) if funding_apr is not None else None,
            net_cash_carry_apr_pct=round(net_apr, 2) if net_apr is not None else None,
            status=status,
            summary=summary,
        )
