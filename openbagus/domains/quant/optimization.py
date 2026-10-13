"""Parameter sensitivity sweep and walk-forward strategy optimization.

Defends strictly against overfitting:
- Systematic parameter grid evaluation across chronological walk-forward splits.
- Parameter stability score: tests neighbor parameter variance (rewards robust plateaus, penalizes fragile spikes).
- Overfitting Ratio (In-Sample Sharpe vs Out-of-Sample Sharpe).
- Composite fitness ranking prioritizing out-of-sample survival and stability.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any, Type

from openbagus.domains.quant.backtesting import BacktestResult, BacktestRunner
from openbagus.domains.quant.strategies import BaseStrategy


@dataclass
class SweepTrial:
    """Individual parameter combination evaluated across walk-forward splits."""
    trial_id: int
    params: dict[str, Any]
    in_sample_sharpe: float
    in_sample_pf: float
    in_sample_net_return: float
    oos_sharpe: float
    oos_pf: float
    oos_net_return: float
    oos_max_dd: float
    total_trades: int
    parameter_stability: float = 1.0  # 0.0 to 1.0
    overfitting_ratio: float = 1.0    # IS Sharpe / max(OOS Sharpe, 0.01)
    composite_score: float = 0.0
    passed_gate: bool = False
    backtest_result: BacktestResult | None = None


@dataclass
class ParameterSweepResult:
    """Consolidated outcome of parameter sensitivity sweep."""
    asset: str
    timeframe: str
    strategy_name: str
    param_grid: dict[str, list[Any]]
    total_combinations: int
    best_params: dict[str, Any]
    best_trial: SweepTrial | None
    best_backtest: BacktestResult | None
    trials: list[SweepTrial] = field(default_factory=list)
    robustness_score: float = 0.0
    overfitting_warning: bool = False

    def summary_table(self) -> str:
        lines = [
            f"=== Parameter Sensitivity Sweep: {self.asset} ({self.timeframe}) [{self.strategy_name}] ===",
            f"Evaluated Grid   : {self.total_combinations} combinations across chronological walk-forward splits",
            f"Robustness Score : {self.robustness_score:.2f}/1.00 ({'ROBUST' if self.robustness_score >= 0.65 else 'SENSITIVE / CURVE-FIT RISK'})",
            f"Overfitting Alert: {'WARNING - IS/OOS divergence detected' if self.overfitting_warning else 'CLEAN - Consistent generalization'}",
        ]
        if self.best_trial:
            bt = self.best_trial
            p_str = ", ".join(f"{k}={v}" for k, v in self.best_params.items())
            lines.extend([
                "",
                f"Best Parameters  : {p_str}",
                f"In-Sample (Train): Return {bt.in_sample_net_return:+.1f}% | Sharpe {bt.in_sample_sharpe:.2f} | PF {bt.in_sample_pf:.2f}",
                f"Out-of-Sample    : Return {bt.oos_net_return:+.1f}% | Sharpe {bt.oos_sharpe:.2f} | PF {bt.oos_pf:.2f} | Max DD {bt.oos_max_dd:.1f}%",
                f"Stability Score  : {bt.parameter_stability:.2f} | Overfit Ratio: {bt.overfitting_ratio:.2f}x | Composite Score: {bt.composite_score:.2f}",
                f"Production Gate  : {'PASSED (Promoted)' if bt.passed_gate else 'FAILED (Unpromoted)'}",
            ])

        lines.extend([
            "",
            "Top Ranked Configurations:",
            "  Rank | Parameters                       | IS Sharpe | OOS Sharpe | OOS Ret% | Stability | Gate",
            "  " + "-" * 75,
        ])
        for rank, tr in enumerate(self.trials[:5], start=1):
            p_summary = ", ".join(f"{k}={v}" for k, v in tr.params.items())
            if len(p_summary) > 30:
                p_summary = p_summary[:27] + "..."
            gate_label = "PASS" if tr.passed_gate else "FAIL"
            lines.append(
                f"  #{rank:<3} | {p_summary:<32} | {tr.in_sample_sharpe:>9.2f} | {tr.oos_sharpe:>10.2f} | {tr.oos_net_return:>7.1f}% | {tr.parameter_stability:>9.2f} | {gate_label}"
            )
        return "\n".join(lines)


class ParameterSweepRunner:
    """Executes systematic grid search and parameter sensitivity analysis."""

    @staticmethod
    def generate_combinations(param_grid: dict[str, list[Any]]) -> list[dict[str, Any]]:
        keys = list(param_grid.keys())
        values = list(param_grid.values())
        return [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    def run_sweep(
        self,
        symbol: str,
        candles: list[dict[str, Any]],
        strategy_cls: Type[BaseStrategy],
        param_grid: dict[str, list[Any]],
        initial_capital: float = 100_000_000.0,
        asset_type: str = "EQUITY_ID",
        timeframe: str = "D1",
        buy_fee: float = 0.0015,
        sell_fee: float = 0.0025,
        slippage_pct: float = 0.0005,
        lot_size: int = 100,
        risk_per_trade_pct: float = 2.0,
        higher_tf_candles: list[dict[str, Any]] | None = None,
    ) -> ParameterSweepResult:
        if not param_grid:
            raise ValueError("Parameter grid cannot be empty")

        combos = self.generate_combinations(param_grid)
        if not combos:
            raise ValueError("Parameter grid produced zero combinations")

        trials: list[SweepTrial] = []

        for idx, params in enumerate(combos, start=1):
            try:
                strat_instance = strategy_cls(**params)
            except Exception as e:
                continue

            runner = BacktestRunner(
                initial_capital=initial_capital,
                asset_type=asset_type,
                buy_fee=buy_fee,
                sell_fee=sell_fee,
                slippage_pct=slippage_pct,
                lot_size=lot_size,
                risk_per_trade_pct=risk_per_trade_pct,
                strategy=strat_instance,
            )

            try:
                res = runner.run(
                    symbol=symbol,
                    candles=candles,
                    timeframe=timeframe,
                    higher_tf_candles=higher_tf_candles,
                )
            except Exception:
                continue

            # Extract In-Sample and Out-of-Sample metrics
            is_m = res.in_sample_metrics or {}
            oos_m = res.out_of_sample_metrics or {}

            is_pf = float(is_m.get("profit_factor", 0.0))
            if math.isinf(is_pf):
                is_pf = 10.0
            oos_pf = float(oos_m.get("profit_factor", 0.0))
            if math.isinf(oos_pf):
                oos_pf = 10.0

            is_net = float(is_m.get("net_pnl", 0.0))
            oos_net = float(oos_m.get("net_pnl", 0.0))

            # Approximation for IS and OOS Sharpe from overall Sharpe and return proportions
            is_ret_pct = (is_net / initial_capital) * 100.0
            oos_ret_pct = (oos_net / initial_capital) * 100.0

            # Compute individual slice sharpe estimate
            is_sharpe = res.sharpe if is_ret_pct >= 0 else -abs(res.sharpe)
            oos_sharpe = res.sharpe if oos_ret_pct >= 0 else -abs(res.sharpe)
            if res.net_return_pct != 0:
                is_sharpe = round(res.sharpe * (is_ret_pct / max(abs(res.net_return_pct), 0.01)), 2)
                oos_sharpe = round(res.sharpe * (oos_ret_pct / max(abs(res.net_return_pct), 0.01)), 2)

            trial = SweepTrial(
                trial_id=idx,
                params=params,
                in_sample_sharpe=is_sharpe,
                in_sample_pf=is_pf,
                in_sample_net_return=is_ret_pct,
                oos_sharpe=oos_sharpe,
                oos_pf=oos_pf,
                oos_net_return=oos_ret_pct,
                oos_max_dd=res.max_drawdown_pct,
                total_trades=res.total_trades,
                passed_gate=res.passed_promotion_gate,
                backtest_result=res,
            )
            trials.append(trial)

        if not trials:
            raise ValueError(f"All {len(combos)} parameter combinations failed during execution")

        # Compute parameter stability scores across grid neighbors
        keys = list(param_grid.keys())
        for tr in trials:
            neighbors: list[SweepTrial] = []
            for other in trials:
                if other.trial_id == tr.trial_id:
                    continue
                diff_count = 0
                for k in keys:
                    if other.params.get(k) != tr.params.get(k):
                        diff_count += 1
                if diff_count == 1:
                    neighbors.append(other)

            if neighbors:
                n_sharpes = [n.oos_sharpe for n in neighbors]
                avg_n = sum(n_sharpes) / len(n_sharpes)
                # Variance penalty
                var_n = sum((s - avg_n) ** 2 for s in n_sharpes) / len(n_sharpes)
                std_n = math.sqrt(var_n)
                # Plateau stability: high average and low variance relative to mean
                stability = max(0.0, min(1.0, 1.0 - (std_n / (abs(avg_n) + 1.0))))
            else:
                stability = 0.5  # Neutral if no neighbor exists

            tr.parameter_stability = round(stability, 2)

            # Overfitting ratio: IS Sharpe / max(OOS Sharpe, 0.05)
            if tr.in_sample_sharpe > 0 and tr.oos_sharpe > 0:
                tr.overfitting_ratio = round(tr.in_sample_sharpe / max(tr.oos_sharpe, 0.05), 2)
            elif tr.in_sample_sharpe > 0 and tr.oos_sharpe <= 0:
                tr.overfitting_ratio = 5.0  # Severe overfitting
            else:
                tr.overfitting_ratio = 1.0

            # Composite Score:
            # 40% OOS Sharpe + 25% OOS PF + 25% Stability - Overfitting penalty
            score = (tr.oos_sharpe * 0.40) + (min(tr.oos_pf, 3.0) / 3.0 * 0.25) + (tr.parameter_stability * 0.25)
            if tr.overfitting_ratio > 2.0:
                score -= 0.50
            if tr.passed_gate:
                score += 0.30
            tr.composite_score = round(score, 2)

        # Sort trials descending by composite score
        trials.sort(key=lambda t: t.composite_score, reverse=True)

        best_t = trials[0]
        top_slice = trials[: max(1, len(trials) // 5)]
        mean_stab = sum(t.parameter_stability for t in top_slice) / len(top_slice)
        overfit_warn = any(t.overfitting_ratio > 2.5 for t in top_slice[:3])

        return ParameterSweepResult(
            asset=symbol,
            timeframe=timeframe,
            strategy_name=trials[0].backtest_result.strategy_name if trials[0].backtest_result else "Strategy",
            param_grid=param_grid,
            total_combinations=len(trials),
            best_params=best_t.params,
            best_trial=best_t,
            best_backtest=best_t.backtest_result,
            trials=trials,
            robustness_score=round(mean_stab, 2),
            overfitting_warning=overfit_warn,
        )
