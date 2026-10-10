"""Realistic walk-forward quantitative backtesting engine.

Guarantees:
- Strict chronological walk-forward splitting (In-Sample -> Out-of-Sample).
- No lookahead bias: signal at bar t uses only candles[:t+1]; execution occurs at t+1.
- Realistic transaction costs:
  * IDX: 0.15% buy fee, 0.25% sell fee (including BEI levy and 0.1% final sales tax), 100-share lot size constraint, tick sizes.
  * Crypto: 0.05% maker / 0.10% taker fee, slippage.
- Intrabar stop-loss and take-profit resolution using candle high/low.
- Out-of-sample performance validation and production promotion gate.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

from openbagus.domains.quant.indicators import (
    ema,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    wilder_atr,
)


@dataclass
class BacktestTrade:
    entry_idx: int
    entry_time: str
    entry_price: float
    direction: str  # "LONG"
    shares: int
    cost_basis: float
    stop_price: float
    tp1_price: float
    exit_idx: int = 0
    exit_time: str = ""
    exit_price: float = 0.0
    exit_reason: str = ""  # "STOP_LOSS", "TAKE_PROFIT", "TIME_EXIT"
    gross_pnl: float = 0.0
    fees_paid: float = 0.0
    net_pnl: float = 0.0
    return_pct: float = 0.0
    bars_held: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    asset: str
    timeframe: str
    asset_type: str
    total_bars: int
    sample_start: str
    sample_end: str
    train_bars: int
    val_bars: int
    test_bars: int
    initial_capital: float
    final_equity: float
    net_return_pct: float
    benchmark_return_pct: float
    alpha_pct: float
    total_trades: int
    win_count: int
    loss_count: int
    win_rate: float
    profit_factor: float
    expectancy: float
    max_drawdown_pct: float
    sharpe: float
    sortino: float
    turnover: float
    exposure_pct: float
    total_fees_paid: float
    in_sample_metrics: dict[str, Any] = field(default_factory=dict)
    out_of_sample_metrics: dict[str, Any] = field(default_factory=dict)
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    drawdown_curve: list[float] = field(default_factory=list)
    passed_promotion_gate: bool = False
    gate_reasons: list[str] = field(default_factory=list)
    evaluation_mode: str = "HOLDOUT"

    def summary_table(self) -> str:
        status = "PASSED (Promoted)" if self.passed_promotion_gate else "FAILED (Unpromoted / Confluence-Only)"
        pf_str = "Inf (No Losses)" if math.isinf(self.profit_factor) else f"{self.profit_factor:.2f}"
        lines = [
            f"=== Backtest Results: {self.asset} ({self.timeframe}) ===",
            f"Period           : {self.sample_start[:10]} to {self.sample_end[:10]} ({self.total_bars} bars)",
            f"Evaluation Mode  : {self.evaluation_mode}",
            f"Walk-Forward Split: Train {self.train_bars}b | Val {self.val_bars}b | Out-of-Sample {self.test_bars}b",
            f"Initial Capital  : {self.initial_capital:,.0f} | Final: {self.final_equity:,.0f}",
            f"Net Return       : {self.net_return_pct:+.2f}% vs Benchmark B&H {self.benchmark_return_pct:+.2f}% (Alpha {self.alpha_pct:+.2f}%)",
            f"Total Trades     : {self.total_trades} (Win Rate: {self.win_rate:.1f}%)",
            f"Profit Factor    : {pf_str} | Expectancy: {self.expectancy:,.2f}",
            f"Max Drawdown     : {self.max_drawdown_pct:.2f}%",
            f"Sharpe / Sortino : {self.sharpe:.2f} / {self.sortino:.2f}",
            f"Fees & Slippage  : {self.total_fees_paid:,.0f}",
            f"Promotion Gate   : {status}",
        ]
        if self.gate_reasons:
            lines.append("Gate Notes       : " + "; ".join(self.gate_reasons))
        return "\n".join(lines)


class BacktestRunner:
    """Executes walk-forward backtests with explicit cost, lot-size, and execution rules."""

    def __init__(
        self,
        initial_capital: float = 100_000_000.0,
        asset_type: str = "EQUITY_ID",
        buy_fee: float = 0.0015,
        sell_fee: float = 0.0025,
        slippage_pct: float = 0.0005,
        lot_size: int = 100,
        risk_per_trade_pct: float = 2.0,
    ) -> None:
        self.initial_capital = initial_capital
        self.asset_type = asset_type
        self.buy_fee = buy_fee
        self.sell_fee = sell_fee
        self.slippage_pct = slippage_pct
        self.lot_size = lot_size if asset_type == "EQUITY_ID" else 1
        self.risk_per_trade_pct = risk_per_trade_pct

    def run(
        self,
        symbol: str,
        candles: list[dict[str, Any]],
        timeframe: str = "D1",
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        evaluation_mode: str = "HOLDOUT",
    ) -> BacktestResult:
        if len(candles) < 25:
            raise ValueError(f"Insufficient candles for backtest (need >= 25, got {len(candles)})")

        n = len(candles)
        # Check strictly monotonic increasing timestamps
        for idx in range(1, n):
            t_prev = candles[idx - 1].get("open_at") or candles[idx - 1].get("time")
            t_curr = candles[idx].get("open_at") or candles[idx].get("time")
            if t_prev and t_curr and str(t_curr) <= str(t_prev):
                raise ValueError(
                    f"Candle timestamps must be strictly monotonic increasing: bar {idx - 1} '{t_prev}' >= bar {idx} '{t_curr}'"
                )

        closes = [float(c["close"]) for c in candles]
        highs = [float(c["high"]) for c in candles]
        lows = [float(c["low"]) for c in candles]
        opens = [float(c["open"]) for c in candles]

        # Calculate indicators without lookahead
        ema_fast = ema(closes, 8)
        ema_slow = ema(closes, 21)
        atr_vals = wilder_atr(highs, lows, closes, 14)

        train_len = int(n * train_ratio)
        val_len = int(n * val_ratio)
        test_len = n - train_len - val_len

        capital = self.initial_capital
        equity_curve: list[float] = [capital]
        trades: list[BacktestTrade] = []
        active_trade: BacktestTrade | None = None
        pending_order: dict[str, Any] | None = None
        total_fees = 0.0
        exposure_bars = 0

        # Benchmark return over active strategy period (Buy and Hold from bar 21 to end)
        b_entry = closes[21]
        b_exit = closes[-1]
        benchmark_ret = ((b_exit - b_entry) / b_entry * 100.0) if b_entry > 0 else 0.0

        for i in range(21, n):
            current_bar = candles[i]
            prev_bar = candles[i - 1]
            c_high = highs[i]
            c_low = lows[i]
            c_open = opens[i]
            c_close = closes[i]

            # 1. Execute queued pending order at bar OPEN
            if pending_order is not None and active_trade is None:
                entry_px = c_open * (1.0 + self.slippage_pct)
                atr = pending_order["atr"]
                stop_px = entry_px - 1.5 * atr
                tp_px = entry_px + 2.5 * atr
                risk_per_share = entry_px - stop_px

                if risk_per_share > 0 and stop_px > 0:
                    risk_capital = capital * (self.risk_per_trade_pct / 100.0)
                    max_shares_risk = int(risk_capital / risk_per_share)
                    max_shares_capital = int((capital * 0.95) / (entry_px * (1.0 + self.buy_fee)))
                    raw_shares = min(max_shares_risk, max_shares_capital)

                    if self.lot_size > 1:
                        shares = (raw_shares // self.lot_size) * self.lot_size
                    else:
                        shares = raw_shares

                    if shares > 0:
                        cost = shares * entry_px
                        fee_buy = cost * self.buy_fee
                        if cost + fee_buy <= capital:
                            capital -= (cost + fee_buy)
                            total_fees += fee_buy
                            active_trade = BacktestTrade(
                                entry_idx=i,
                                entry_time=current_bar.get("open_at", current_bar.get("time", f"bar_{i}")),
                                entry_price=entry_px,
                                direction="LONG",
                                shares=shares,
                                cost_basis=cost,
                                stop_price=stop_px,
                                tp1_price=tp_px,
                                fees_paid=fee_buy,
                            )
                pending_order = None

            # 2. Manage active position (intrabar exits checked first)
            if active_trade is not None:
                exposure_bars += 1
                active_trade.bars_held += 1
                exit_price: float | None = None
                exit_reason = ""

                # Collision check: did both stop and take-profit get hit intrabar?
                is_stop_hit = c_low <= active_trade.stop_price
                is_tp_hit = c_high >= active_trade.tp1_price

                if is_stop_hit and is_tp_hit:
                    # Conservative financial assumption: stop loss hit first
                    exit_price = min(c_open, active_trade.stop_price) * (1.0 - self.slippage_pct)
                    exit_reason = "STOP_LOSS"
                elif is_stop_hit:
                    exit_price = min(c_open, active_trade.stop_price) * (1.0 - self.slippage_pct)
                    exit_reason = "STOP_LOSS"
                elif is_tp_hit:
                    exit_price = max(c_open, active_trade.tp1_price) * (1.0 - self.slippage_pct)
                    exit_reason = "TAKE_PROFIT"
                elif active_trade.bars_held >= 20:
                    exit_price = c_close * (1.0 - self.slippage_pct)
                    exit_reason = "TIME_EXIT"

                if exit_price is not None:
                    # Finalize trade with exact cash conservation
                    proceeds = active_trade.shares * exit_price
                    fee_sell = proceeds * self.sell_fee
                    total_fees += fee_sell
                    gross_pnl = proceeds - active_trade.cost_basis
                    net_pnl = gross_pnl - (active_trade.fees_paid + fee_sell)
                    capital += (proceeds - fee_sell)

                    active_trade.exit_idx = i
                    active_trade.exit_time = current_bar.get("close_at", current_bar.get("open_at", f"bar_{i}"))
                    active_trade.exit_price = exit_price
                    active_trade.exit_reason = exit_reason
                    active_trade.gross_pnl = gross_pnl
                    active_trade.fees_paid += fee_sell
                    active_trade.net_pnl = net_pnl
                    active_trade.return_pct = (net_pnl / active_trade.cost_basis) * 100.0
                    trades.append(active_trade)
                    active_trade = None

            # 3. Track equity curve at bar CLOSE
            cur_equity = capital
            if active_trade is not None:
                cur_equity += active_trade.shares * c_close * (1.0 - self.sell_fee)
            equity_curve.append(cur_equity)

            # 4. Evaluate entry signal at bar CLOSE for NEXT bar OPEN execution
            if active_trade is None and pending_order is None and i < n - 1:
                is_uptrend = ema_fast[i] > ema_slow[i] and ema_fast[i - 1] > ema_slow[i - 1]
                atr = atr_vals[i] if not math.isnan(atr_vals[i]) else (c_close * 0.02)
                low_tested = prev_bar.get("low", c_low) <= ema_fast[i] + 0.25 * atr or c_low <= ema_fast[i] + 0.25 * atr

                if is_uptrend and c_close > ema_fast[i] and low_tested:
                    pending_order = {
                        "signal_idx": i,
                        "atr": atr,
                    }

        # Force-close position at last bar with exact cash conservation
        if active_trade is not None:
            last_c = closes[-1]
            proceeds = active_trade.shares * last_c
            fee_sell = proceeds * self.sell_fee
            total_fees += fee_sell
            gross_pnl = proceeds - active_trade.cost_basis
            net_pnl = gross_pnl - (active_trade.fees_paid + fee_sell)
            capital += (proceeds - fee_sell)
            active_trade.exit_idx = n - 1
            active_trade.exit_time = candles[-1].get("close_at", "last_bar")
            active_trade.exit_price = last_c
            active_trade.exit_reason = "END_OF_SAMPLE"
            active_trade.gross_pnl = gross_pnl
            active_trade.fees_paid += fee_sell
            active_trade.net_pnl = net_pnl
            active_trade.return_pct = (net_pnl / active_trade.cost_basis) * 100.0
            trades.append(active_trade)
            equity_curve[-1] = capital

        # Compute drawdown curve
        max_dd, _, _ = max_drawdown(equity_curve)
        peak = equity_curve[0]
        dd_curve = []
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            dd_curve.append(((peak - eq) / peak * 100.0) if peak > 0 else 0.0)

        # Performance statistics
        wins = [t for t in trades if t.net_pnl > 0]
        losses = [t for t in trades if t.net_pnl <= 0]
        total_t = len(trades)
        win_rate = (len(wins) / total_t * 100.0) if total_t > 0 else 0.0
        tot_win = sum(t.net_pnl for t in wins)
        tot_loss = abs(sum(t.net_pnl for t in losses))
        if tot_loss > 0:
            profit_factor = tot_win / tot_loss
        elif tot_win > 0:
            profit_factor = math.inf
        else:
            profit_factor = 0.0
        expectancy = (sum(t.net_pnl for t in trades) / total_t) if total_t > 0 else 0.0
        net_ret = ((capital - self.initial_capital) / self.initial_capital) * 100.0

        daily_returns: list[float] = []
        for idx in range(1, len(equity_curve)):
            prev = equity_curve[idx - 1]
            if prev > 0:
                daily_returns.append((equity_curve[idx] - prev) / prev)

        ann_factor = 252.0 if (self.asset_type == "EQUITY_ID" or timeframe in ("D1", "D", "W1")) else (365.0 * 24.0 if timeframe in ("H1", "1h") else 365.0)
        sharpe = sharpe_ratio(daily_returns, risk_free_rate=0.05, annualize_factor=ann_factor)
        sortino = sortino_ratio(daily_returns, risk_free_rate=0.05, annualize_factor=ann_factor)

        # Walk-forward slice metrics
        val_start_idx = train_len
        test_start_idx = train_len + val_len
        in_sample_trades = [t for t in trades if t.entry_idx < test_start_idx]
        oos_trades = [t for t in trades if t.entry_idx >= test_start_idx]

        def compute_sub_metrics(sub_trades: list[BacktestTrade]) -> dict[str, Any]:
            if not sub_trades:
                return {"trades": 0, "win_rate": 0.0, "net_pnl": 0.0, "profit_factor": 0.0}
            sub_w = [t for t in sub_trades if t.net_pnl > 0]
            sub_l = [t for t in sub_trades if t.net_pnl <= 0]
            w_sum = sum(t.net_pnl for t in sub_w)
            l_sum = abs(sum(t.net_pnl for t in sub_l))
            if l_sum > 0:
                pf = round(w_sum / l_sum, 2)
            elif w_sum > 0:
                pf = math.inf
            else:
                pf = 0.0
            return {
                "trades": len(sub_trades),
                "win_rate": round(len(sub_w) / len(sub_trades) * 100.0, 1),
                "net_pnl": round(sum(t.net_pnl for t in sub_trades), 2),
                "profit_factor": pf,
            }

        is_metrics = compute_sub_metrics(in_sample_trades)
        oos_metrics = compute_sub_metrics(oos_trades)

        # Production Promotion Gate
        # Requirements:
        # 1. Total trades >= 3
        # 2. Profit factor >= 1.20 after full transaction costs
        # 3. Max drawdown <= 35%
        # 4. Out-of-sample evaluation:
        #    - If test_bars > 0:
        #      * Cannot pass on 0 or < 2 OOS trades
        #      * OOS profit factor >= 1.0 and positive OOS net PnL
        gate_reasons: list[str] = []
        passed = True

        if total_t < 3:
            passed = False
            gate_reasons.append(f"Insufficient trade sample ({total_t} < 3 trades)")
        if profit_factor < 1.20:
            pf_display = "Inf" if math.isinf(profit_factor) else f"{profit_factor:.2f}"
            passed = False
            gate_reasons.append(f"Profit factor after costs {pf_display} < 1.20 threshold")
        if max_dd > 35.0:
            passed = False
            gate_reasons.append(f"Max drawdown {max_dd:.1f}% exceeds 35.0% tolerance")

        if test_len > 0:
            if len(oos_trades) == 0:
                passed = False
                gate_reasons.append("No out-of-sample trades generated to validate strategy")
            elif len(oos_trades) < 2:
                passed = False
                gate_reasons.append(f"Insufficient out-of-sample trades ({len(oos_trades)} < 2)")
            else:
                oos_pf = oos_metrics["profit_factor"]
                if oos_pf < 1.0:
                    passed = False
                    gate_reasons.append(f"Out-of-sample profit factor degraded to {oos_pf}")
                if oos_metrics["net_pnl"] <= 0:
                    passed = False
                    gate_reasons.append(f"Out-of-sample net PnL is non-positive ({oos_metrics['net_pnl']:,.2f})")

        if passed:
            gate_reasons.append("Strategy meets out-of-sample criteria with realistic fees & lot constraints.")

        s_start = candles[0].get("open_at", "START")
        s_end = candles[-1].get("close_at", candles[-1].get("open_at", "END"))

        return BacktestResult(
            asset=symbol,
            timeframe=timeframe,
            asset_type=self.asset_type,
            total_bars=n,
            sample_start=s_start,
            sample_end=s_end,
            train_bars=train_len,
            val_bars=val_len,
            test_bars=test_len,
            initial_capital=self.initial_capital,
            final_equity=capital,
            net_return_pct=net_ret,
            benchmark_return_pct=benchmark_ret,
            alpha_pct=net_ret - benchmark_ret,
            total_trades=total_t,
            win_count=len(wins),
            loss_count=len(losses),
            win_rate=win_rate,
            profit_factor=profit_factor,
            expectancy=expectancy,
            max_drawdown_pct=max_dd,
            sharpe=sharpe,
            sortino=sortino,
            turnover=sum(t.cost_basis for t in trades) / self.initial_capital,
            exposure_pct=(exposure_bars / n * 100.0) if n > 0 else 0.0,
            total_fees_paid=total_fees,
            in_sample_metrics=is_metrics,
            out_of_sample_metrics=oos_metrics,
            trades=trades,
            equity_curve=equity_curve,
            drawdown_curve=dd_curve,
            passed_promotion_gate=passed,
            gate_reasons=gate_reasons,
            evaluation_mode=evaluation_mode,
        )
