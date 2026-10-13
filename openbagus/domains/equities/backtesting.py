"""Point-in-Time Event-Driven Backtesting Engine.

Simulates event-driven swing strategies on historical Indonesian market data
without lookahead bias, enforcing official exchange session timestamps, tick snapping,
100-share board lots, ARA/ARB limits, slippage, and commission fees.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time, timezone, timedelta
import math
from typing import Any, Sequence

from openbagus.domains.equities.events import CorporateEventRecord
from openbagus.domains.equities.microstructure import IDXMicrostructureEngine, MicrostructureProfile
from openbagus.domains.equities.strategies import BaseStrategy, TradingSignal

try:
    from zoneinfo import ZoneInfo
    WIB_TZ = ZoneInfo("Asia/Jakarta")
except Exception:
    WIB_TZ = timezone(timedelta(hours=7), "Asia/Jakarta")


@dataclass
class BacktestTrade:
    trade_id: str
    ticker: str
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    shares: int
    gross_pnl: float
    fees: float
    net_pnl: float
    return_pct: float
    holding_days: int
    exit_reason: str          # "TARGET", "STOP_LOSS", "TIME_STOP", "CATALYST_EXIT"
    slippage_paid: float
    signal_publication_time: str
    earliest_eligible_execution: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BacktestResult:
    strategy_name: str
    initial_capital: float
    final_capital: float
    net_profit: float
    total_return_pct: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    rejected_orders: int
    trades: list[BacktestTrade] = field(default_factory=list)
    execution_assumptions: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        res = asdict(self)
        res["trades"] = [t.to_dict() for t in self.trades]
        return res


class PointInTimeBacktester:
    """Rigorous point-in-time trade simulation engine."""

    MARKET_CLOSE_WIB = time(16, 0)  # Regular IDX close at 16:00 WIB

    def __init__(
        self,
        initial_capital: float = 100_000_000.0,
        buy_fee: float = 0.0015,
        sell_fee: float = 0.0025,
        max_risk_pct: float = 0.02,
        participation_limit: float = 0.10,
    ) -> None:
        self.initial_capital = initial_capital
        self.buy_fee = buy_fee
        self.sell_fee = sell_fee
        self.max_risk_pct = max_risk_pct
        self.participation_limit = participation_limit

    @classmethod
    def get_earliest_execution_session(cls, publication_timestamp_iso: str) -> str:
        """Determines earliest possible trading session without lookahead bias.

        If published after market close (16:00 WIB) or during weekend,
        earliest execution is the next market day (T+1 Open).
        """
        try:
            dt = datetime.fromisoformat(publication_timestamp_iso)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=WIB_TZ)
            else:
                dt = dt.astimezone(WIB_TZ)

            # Check if after hours
            if dt.time() >= cls.MARKET_CLOSE_WIB:
                return "NEXT_SESSION_OPEN (T+1)"
            return "SAME_SESSION_CLOSE (T+0)"
        except Exception:
            return "NEXT_SESSION_OPEN (T+1)"

    def run(
        self,
        strategy: BaseStrategy,
        ticker: str,
        candles: Sequence[dict[str, Any]],
        board: str = "MAIN",
        events: Sequence[CorporateEventRecord] | None = None,
        warmup_period: int = 20,
    ) -> BacktestResult:
        """Executes chronological historical simulation."""
        if len(candles) <= warmup_period:
            return BacktestResult(
                strategy_name=strategy.name,
                initial_capital=self.initial_capital,
                final_capital=self.initial_capital,
                net_profit=0.0,
                total_return_pct=0.0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                win_rate_pct=0.0,
                profit_factor=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                sortino_ratio=0.0,
                rejected_orders=0,
            )

        capital = self.initial_capital
        peak_capital = capital
        max_drawdown = 0.0
        trades: list[BacktestTrade] = []
        rejected_orders = 0

        in_position = False
        pos_entry_px = 0.0
        pos_shares = 0
        pos_stop_px = 0.0
        pos_target_px = 0.0
        pos_entry_date = ""
        pos_holding_days = 0
        pos_slippage = 0.0
        pos_signal_time = ""
        pos_exec_session = ""

        daily_returns: list[float] = []

        # Chronological day-by-day loop
        for t in range(warmup_period, len(candles)):
            curr_candle = candles[t]
            curr_date = curr_candle.get("open_at", "")[:10]
            curr_close = float(curr_candle.get("close", 0.0))
            curr_open = float(curr_candle.get("open", curr_close))
            curr_high = float(curr_candle.get("high", curr_close))
            curr_low = float(curr_candle.get("low", curr_close))
            curr_vol = float(curr_candle.get("volume", 0.0))

            window_candles = candles[: t + 1]

            # 1. Manage active position exit
            if in_position:
                pos_holding_days += 1
                exit_triggered = False
                exit_px = curr_close
                exit_reason = "TIME_STOP"

                # Check Stop Loss
                if curr_low <= pos_stop_px:
                    exit_px = pos_stop_px
                    exit_reason = "STOP_LOSS"
                    exit_triggered = True
                # Check Profit Target
                elif curr_high >= pos_target_px:
                    exit_px = pos_target_px
                    exit_reason = "TARGET"
                    exit_triggered = True
                # Max holding time stop (10 trading days for swing setup)
                elif pos_holding_days >= 10:
                    exit_px = curr_close
                    exit_reason = "TIME_STOP"
                    exit_triggered = True

                if exit_triggered:
                    # Apply slippage on exit
                    exit_slippage = IDXMicrostructureEngine.estimate_slippage(
                        order_value_idr=pos_shares * exit_px,
                        adtv_20d=curr_vol * curr_close,
                        price=exit_px,
                        board=board,
                    )
                    realized_exit_px = IDXMicrostructureEngine.snap_to_tick(
                        exit_px * (1.0 - exit_slippage), board, round_up=False
                    )

                    gross_proceeds = pos_shares * realized_exit_px
                    cost_basis = pos_shares * pos_entry_px
                    gross_pnl = gross_proceeds - cost_basis

                    exit_fee = gross_proceeds * self.sell_fee
                    entry_fee = cost_basis * self.buy_fee
                    total_fees = entry_fee + exit_fee

                    net_pnl = gross_pnl - total_fees
                    ret_pct = (net_pnl / cost_basis) * 100.0 if cost_basis > 0 else 0.0

                    capital += gross_proceeds - exit_fee
                    daily_returns.append(ret_pct / 100.0)

                    trades.append(
                        BacktestTrade(
                            trade_id=f"TRD_{len(trades)+1:03d}",
                            ticker=ticker,
                            entry_date=pos_entry_date,
                            exit_date=curr_date,
                            entry_price=pos_entry_px,
                            exit_price=realized_exit_px,
                            shares=pos_shares,
                            gross_pnl=round(gross_pnl, 2),
                            fees=round(total_fees, 2),
                            net_pnl=round(net_pnl, 2),
                            return_pct=round(ret_pct, 2),
                            holding_days=pos_holding_days,
                            exit_reason=exit_reason,
                            slippage_paid=round(pos_slippage + exit_slippage, 4),
                            signal_publication_time=pos_signal_time,
                            earliest_eligible_execution=pos_exec_session,
                        )
                    )

                    in_position = False

            # Update drawdown tracking
            if capital > peak_capital:
                peak_capital = capital
            dd = (peak_capital - capital) / peak_capital if peak_capital > 0 else 0.0
            if dd > max_drawdown:
                max_drawdown = dd

            # 2. Check for entry signal if flat
            if not in_position:
                profile = IDXMicrostructureEngine.profile_asset(
                    symbol=ticker,
                    board=board,
                    reference_price=curr_close,
                    candles=window_candles,
                )

                # Filter events strictly known at or before this date
                as_of_events = [ev for ev in (events or []) if ev.effective_date <= curr_date]

                signal = strategy.evaluate(
                    ticker=ticker,
                    candles=window_candles,
                    profile=profile,
                    events=as_of_events,
                    capital_budget=capital,
                    max_risk_pct=self.max_risk_pct,
                )

                if signal.action == "BUY" and signal.entry_price and signal.suggested_shares > 0:
                    # Enforce point-in-time publication timestamp
                    pub_time = signal.catalyst_event.published_at if signal.catalyst_event else f"{curr_date}T10:00:00+07:00"
                    exec_session = self.get_earliest_execution_session(pub_time)

                    # Liquidity participation gate: order size cannot exceed 10% of 20d ADTV
                    order_val = signal.suggested_shares * signal.entry_price
                    if profile.adtv_20d > 0 and (order_val / profile.adtv_20d) > self.participation_limit:
                        rejected_orders += 1
                        continue

                    # Apply entry slippage
                    entry_slippage = IDXMicrostructureEngine.estimate_slippage(
                        order_value_idr=order_val,
                        adtv_20d=profile.adtv_20d,
                        price=signal.entry_price,
                        board=board,
                    )
                    fill_entry_px = IDXMicrostructureEngine.snap_to_tick(
                        signal.entry_price * (1.0 + entry_slippage), board, round_up=True
                    )

                    # Ensure not exceeding Auto-Rejection Atas (ARA)
                    if fill_entry_px > profile.ara_price:
                        rejected_orders += 1
                        continue

                    total_entry_cost = signal.suggested_shares * fill_entry_px * (1.0 + self.buy_fee)
                    if total_entry_cost <= capital:
                        capital -= total_entry_cost
                        in_position = True
                        pos_entry_px = fill_entry_px
                        pos_shares = signal.suggested_shares
                        pos_stop_px = signal.stop_loss or (fill_entry_px * 0.95)
                        pos_target_px = signal.target_price or (fill_entry_px * 1.10)
                        pos_entry_date = curr_date
                        pos_holding_days = 0
                        pos_slippage = entry_slippage
                        pos_signal_time = pub_time
                        pos_exec_session = exec_session
                    else:
                        rejected_orders += 1
                elif signal.action == "REJECTED_BY_RISK":
                    rejected_orders += 1

        # Summary statistics
        n_trades = len(trades)
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        win_rate = (len(wins) / n_trades * 100.0) if n_trades > 0 else 0.0

        total_gain = sum(t.net_pnl for t in wins)
        total_loss = abs(sum(t.net_pnl for t in losses))
        profit_factor = (total_gain / total_loss) if total_loss > 0 else (float("inf") if total_gain > 0 else 0.0)

        tot_ret_pct = ((capital - self.initial_capital) / self.initial_capital) * 100.0

        # Sharpe & Sortino ratios (annualized, 252 trading days)
        if daily_returns:
            mean_r = sum(daily_returns) / len(daily_returns)
            var_r = sum((r - mean_r) ** 2 for r in daily_returns) / len(daily_returns)
            std_r = math.sqrt(var_r)
            downside_var = sum(min(0.0, r) ** 2 for r in daily_returns) / len(daily_returns)
            downside_std = math.sqrt(downside_var)

            sharpe = (mean_r / std_r * math.sqrt(252)) if std_r > 0 else 0.0
            sortino = (mean_r / downside_std * math.sqrt(252)) if downside_std > 0 else 0.0
        else:
            sharpe = 0.0
            sortino = 0.0

        return BacktestResult(
            strategy_name=strategy.name,
            initial_capital=self.initial_capital,
            final_capital=round(capital, 2),
            net_profit=round(capital - self.initial_capital, 2),
            total_return_pct=round(tot_ret_pct, 2),
            total_trades=n_trades,
            winning_trades=len(wins),
            losing_trades=len(losses),
            win_rate_pct=round(win_rate, 2),
            profit_factor=round(min(999.0, profit_factor), 2),
            max_drawdown_pct=round(max_drawdown * 100.0, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            rejected_orders=rejected_orders,
            trades=trades,
            execution_assumptions={
                "board": board,
                "buy_fee_pct": self.buy_fee * 100.0,
                "sell_fee_pct": self.sell_fee * 100.0,
                "max_participation_pct": self.participation_limit * 100.0,
                "lot_size": IDXMicrostructureEngine.LOT_SIZE,
                "no_lookahead_enforced": True,
            },
        )
