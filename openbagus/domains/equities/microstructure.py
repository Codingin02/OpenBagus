"""IDX Market Microstructure Engine.

Implements realistic exchange trading rules, tick size bands, board lots (100 shares),
auto-rejection limits (ARA/ARB), continuous vs Periodic Call Auction (FCA) models,
liquidity metrics (ADTV, turnover, zero-volume streaks), and slippage calculation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
import math
from typing import Any, Sequence


@dataclass(frozen=True)
class TickSizeRule:
    min_price: float
    max_price: float
    tick_size: float
    max_step: float


@dataclass(frozen=True)
class AutoRejectionRule:
    min_price: float
    max_price: float
    limit_pct: float  # e.g. 0.35 for 35%


# Regular Board Tick Size Bands according to official IDX rules
REGULAR_TICK_BANDS: tuple[TickSizeRule, ...] = (
    TickSizeRule(min_price=1.0, max_price=200.0, tick_size=1.0, max_step=10.0),
    TickSizeRule(min_price=200.0, max_price=500.0, tick_size=2.0, max_step=20.0),
    TickSizeRule(min_price=500.0, max_price=2000.0, tick_size=5.0, max_step=50.0),
    TickSizeRule(min_price=2000.0, max_price=5000.0, tick_size=10.0, max_step=100.0),
    TickSizeRule(min_price=5000.0, max_price=float("inf"), tick_size=25.0, max_step=250.0),
)

# Acceleration Board: Rp 1 flat tick size
ACCELERATION_TICK_BANDS: tuple[TickSizeRule, ...] = (
    TickSizeRule(min_price=1.0, max_price=float("inf"), tick_size=1.0, max_step=10.0),
)

# Regular Board Symmetric Auto-Rejection (ARA / ARB) limits
REGULAR_ARA_ARB_RULES: tuple[AutoRejectionRule, ...] = (
    AutoRejectionRule(min_price=50.0, max_price=200.0, limit_pct=0.35),
    AutoRejectionRule(min_price=200.0, max_price=5000.0, limit_pct=0.25),
    AutoRejectionRule(min_price=5000.0, max_price=float("inf"), limit_pct=0.20),
)


@dataclass
class MicrostructureProfile:
    symbol: str
    board: str
    trading_mechanism: str  # "CONTINUOUS", "PERIODIC_CALL_AUCTION", "SUSPENDED"
    reference_price: float
    tick_size: float
    ara_price: float
    arb_price: float
    is_fca: bool
    is_suspended: bool
    lot_size: int = 100
    adtv_20d: float = 0.0
    adtv_60d: float = 0.0
    zero_volume_streak: int = 0
    estimated_spread_pct: float = 0.0
    execution_eligible: bool = True
    rejection_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "board": self.board,
            "trading_mechanism": self.trading_mechanism,
            "reference_price": self.reference_price,
            "tick_size": self.tick_size,
            "ara_price": self.ara_price,
            "arb_price": self.arb_price,
            "is_fca": self.is_fca,
            "is_suspended": self.is_suspended,
            "lot_size": self.lot_size,
            "adtv_20d": self.adtv_20d,
            "adtv_60d": self.adtv_60d,
            "zero_volume_streak": self.zero_volume_streak,
            "estimated_spread_pct": round(self.estimated_spread_pct, 4),
            "execution_eligible": self.execution_eligible,
            "rejection_reason": self.rejection_reason,
        }


class IDXMicrostructureEngine:
    """Calculates official exchange constraints, tick sizes, rejection bounds, and execution realism."""

    LOT_SIZE: int = 100
    DEFAULT_BUY_FEE: float = 0.0015   # 0.15% broker + exchange fee
    DEFAULT_SELL_FEE: float = 0.0025  # 0.25% broker + exchange + final income tax (0.1%)

    @staticmethod
    def get_tick_size(price: float, board: str = "MAIN") -> float:
        """Returns official IDX tick size for price and listing board."""
        if price <= 0:
            return 1.0

        b_clean = board.strip().upper()
        if b_clean == "ACCELERATION":
            return 1.0

        for rule in REGULAR_TICK_BANDS:
            if rule.min_price <= price < rule.max_price:
                return rule.tick_size
        return 25.0

    @classmethod
    def snap_to_tick(cls, price: float, board: str = "MAIN", round_up: bool = False) -> float:
        """Snaps nominal price to legitimate exchange tick size."""
        if price <= 0:
            return 1.0
        tick = cls.get_tick_size(price, board)
        if round_up:
            return float(math.ceil(price / tick) * tick)
        return float(math.floor(price / tick) * tick)

    @classmethod
    def round_to_lot(cls, shares: int | float) -> int:
        """Rounds share count to board lot (100 shares). Fraction lots are rounded down."""
        if shares <= 0:
            return 0
        return int(math.floor(float(shares) / cls.LOT_SIZE) * cls.LOT_SIZE)

    @classmethod
    def calculate_auto_rejection(cls, reference_price: float, board: str = "MAIN") -> tuple[float, float]:
        """Calculates Auto-Rejection Atas (ARA) and Auto-Rejection Bawah (ARB) prices."""
        if reference_price <= 0:
            return (1.0, 1.0)

        b_clean = board.strip().upper()

        # Special Monitoring Board (FCA): max 10% ARA/ARB, min price Rp 1
        if b_clean in ("SPECIAL_MONITORING", "PAPAN PEMANTAUAN KHUSUS"):
            limit_pct = 0.10
            min_floor = 1.0
        # Acceleration Board: max 10% ARA/ARB, min price Rp 1
        elif b_clean in ("ACCELERATION", "PAPAN AKSELERASI"):
            limit_pct = 0.10
            min_floor = 1.0
        else:
            # Regular (Main & Development boards)
            min_floor = 50.0
            limit_pct = 0.25
            for rule in REGULAR_ARA_ARB_RULES:
                if rule.min_price <= reference_price < rule.max_price:
                    limit_pct = rule.limit_pct
                    break

        raw_ara = reference_price * (1.0 + limit_pct)
        raw_arb = reference_price * (1.0 - limit_pct)

        ara_snapped = cls.snap_to_tick(raw_ara, board, round_up=False)
        arb_snapped = cls.snap_to_tick(max(min_floor, raw_arb), board, round_up=True)

        return (ara_snapped, arb_snapped)

    @classmethod
    def analyze_liquidity(
        cls,
        candles: Sequence[dict[str, Any]],
        window_short: int = 20,
        window_long: int = 60,
    ) -> dict[str, Any]:
        """Evaluates historical trading liquidity, ADTV, zero-volume streaks, and spread proxy."""
        if not candles:
            return {
                "adtv_20d": 0.0,
                "adtv_60d": 0.0,
                "zero_volume_streak": 0,
                "spread_proxy_pct": 0.05,
                "liquidity_regime": "NO_DATA",
            }

        # Daily trading value = close * volume
        values = []
        zero_streak = 0
        current_streak = 0

        for c in reversed(candles):
            v = float(c.get("volume", 0.0))
            px = float(c.get("close", 0.0))
            val = float(c.get("value", px * v))
            values.append(val)
            if v == 0:
                current_streak += 1
            else:
                if zero_streak == 0:
                    zero_streak = current_streak

        values.reverse()  # chronological order

        v20 = values[-window_short:] if len(values) >= window_short else values
        v60 = values[-window_long:] if len(values) >= window_long else values

        adtv_20 = sum(v20) / len(v20) if v20 else 0.0
        adtv_60 = sum(v60) / len(v60) if v60 else 0.0

        # Spread proxy based on tick size / price + volatility
        last_candle = candles[-1]
        last_px = float(last_candle.get("close", 100.0))
        tick = cls.get_tick_size(last_px)
        base_spread = tick / last_px if last_px > 0 else 0.02

        # Illiquidity regime classification
        if adtv_20 >= 50_000_000_000.0:  # >= Rp 50M per day: Ultra Liquid
            regime = "ULTRA_LIQUID"
        elif adtv_20 >= 10_000_000_000.0: # >= Rp 10M per day: High Liquid
            regime = "LIQUID"
        elif adtv_20 >= 1_000_000_000.0:  # >= Rp 1M per day: Moderate Liquid
            regime = "MODERATE_LIQUID"
        elif adtv_20 >= 100_000_000.0:    # >= Rp 100 Juta per day: Thinly Traded
            regime = "THINLY_TRADED"
        else:
            regime = "ILLIQUID"

        return {
            "adtv_20d": adtv_20,
            "adtv_60d": adtv_60,
            "zero_volume_streak": current_streak,
            "spread_proxy_pct": round(base_spread, 4),
            "liquidity_regime": regime,
        }

    @classmethod
    def estimate_slippage(
        cls,
        order_value_idr: float,
        adtv_20d: float,
        price: float,
        board: str = "MAIN",
        is_fca: bool = False,
    ) -> float:
        """Estimates market impact slippage percentage for a given order size.

        Uses square-root market impact model:
        Slippage = Spread/2 + gamma * sqrt(Order_Value / ADTV_20d)
        """
        if price <= 0:
            return 0.02

        tick = cls.get_tick_size(price, board)
        half_spread = (tick / price) / 2.0

        if is_fca:
            # Call Auction has higher friction and wider execution uncertainty
            return max(0.02, half_spread + 0.03)

        if adtv_20d <= 0:
            return 0.05  # Conservative 5% slippage on unknown/zero liquidity

        participation_ratio = min(1.0, order_value_idr / adtv_20d)
        # Gamma impact parameter: 0.10 for standard mid/small cap
        market_impact = 0.10 * math.sqrt(participation_ratio)

        return min(0.10, half_spread + market_impact)

    @classmethod
    def profile_asset(
        cls,
        symbol: str,
        board: str,
        reference_price: float,
        candles: Sequence[dict[str, Any]] | None = None,
        is_suspended: bool = False,
        status: str = "ACTIVE",
    ) -> MicrostructureProfile:
        """Builds complete microstructure and execution eligibility profile."""
        b_clean = board.strip().upper()
        is_fca = b_clean in ("SPECIAL_MONITORING", "PAPAN PEMANTAUAN KHUSUS")
        suspended = is_suspended or status.strip().upper() == "SUSPENDED"

        if suspended:
            mechanism = "SUSPENDED"
        elif is_fca:
            mechanism = "PERIODIC_CALL_AUCTION"
        else:
            mechanism = "CONTINUOUS"

        tick = cls.get_tick_size(reference_price, board)
        ara, arb = cls.calculate_auto_rejection(reference_price, board)

        liq = cls.analyze_liquidity(candles or [])
        adtv20 = liq["adtv_20d"]
        adtv60 = liq["adtv_60d"]
        zero_streak = liq["zero_volume_streak"]
        spread_pct = liq["spread_proxy_pct"]

        eligible = True
        rejection = ""

        if suspended:
            eligible = False
            rejection = "Saham dalam status suspensi sementara oleh Bursa Efek Indonesia."
        elif is_fca:
            eligible = False  # By default, periodic call auction requires dedicated auction strategy
            rejection = "Saham berada di Papan Pemantauan Khusus (FCA); tidak memenuhi syarat continuous execution."
        elif zero_streak >= 5:
            eligible = False
            rejection = f"Likuiditas beku: volume nol selama {zero_streak} hari bursa berturut-turut."
        elif adtv20 < 50_000_000.0 and candles and len(candles) >= 20:
            eligible = False
            rejection = f"ADTV 20-hari terlalu rendah (Rp{adtv20:,.0f} < Rp50,000,000); risiko likuiditas tinggi."

        return MicrostructureProfile(
            symbol=symbol.strip().upper(),
            board=board,
            trading_mechanism=mechanism,
            reference_price=reference_price,
            tick_size=tick,
            ara_price=ara,
            arb_price=arb,
            is_fca=is_fca,
            is_suspended=suspended,
            lot_size=cls.LOT_SIZE,
            adtv_20d=adtv20,
            adtv_60d=adtv60,
            zero_volume_streak=zero_streak,
            estimated_spread_pct=spread_pct,
            execution_eligible=eligible,
            rejection_reason=rejection,
        )
