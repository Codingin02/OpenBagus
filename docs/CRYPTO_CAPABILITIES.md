# Crypto Capabilities

Status describes executable code and permanent fixtures, not claimed predictive accuracy.
The canonical implementation is `openbagus.domains.crypto.quant.QuantEngine`.

| Family | Status | Source and calculation | Interpretation and limits |
| --- | --- | --- | --- |
| Market structure | PARTIAL | Public OHLCV; floor pivots and recent swing extremes | Support/resistance and conditional breakout/rejection candidates. No full HH/HL, BOS, CHoCH or failed-breakout state machine. |
| Trend/momentum | PARTIAL | Binance/Gate candles; recursive EMA8/21 and one/four bar returns | Requested-timeframe momentum, not independent higher-timeframe confirmation. MACD, RSI, ADX are NOT_IMPLEMENTED. |
| Volatility | PARTIAL | Closed OHLCV; Wilder ATR14, return variation for cycle diagnostics; 24h range regime | ATR is price units. Short histories use explicitly degraded range context, not invented ATR. Bollinger Bands are NOT_IMPLEMENTED. |
| Volume | PARTIAL | Exchange quote volume and candle volume; tested VWAP/volume-profile helpers in `core.market_structure` | Liquidity tier and candle confirmation proxy. VWAP/profile helpers are not wired into the canonical crypto decision path; no relative-volume strategy validation. |
| Microstructure | IMPLEMENTED | Binance/Gate public books/trades; normalized depth and aggressive notional imbalance, top-book microprice | Snapshot spread/depth/flow; not persistent CVD. Order spoofing, sampling and venue mismatch limit interpretation. |
| Derivatives | PARTIAL | Gate public futures/CoinGecko; funding, basis in bps and OI with explicit units | Funding crowding is evidence, not a standalone reversal. OI change requires comparable timestamped observations; liquidation maps are DATA_UNAVAILABLE. |
| Liquidity | PARTIAL | Public orderbook and cross-venue quotes | Depth/spread and dispersion after estimated costs. No executable routing, guaranteed arbitrage, measured market impact or transfer-cost model. |
| Spot/DEX | PARTIAL | GeckoTerminal pool liquidity/volume/transactions, DefiLlama stablecoins | Pool context, not wallet attribution or verified whale ownership. DEX orderbook/derivatives are DATA_UNAVAILABLE. |
| Patterns | PARTIAL | OHLCV candlestick/structural pattern fixtures | Material patterns only; no exhaustive pattern library or predictive probability. |
| Confluence | IMPLEMENTED | OHLCV Fibonacci proximity plus independent structure and RR; stochastic 14/3 | Auxiliary price-derived evidence never counts as another independent data family. Short/flat histories are guarded. |
| Macro | PARTIAL | BLS CPI, Federal Reserve calendar, public macro/FRED inputs, stablecoins | Dates and available data only. DXY/US10Y/VIX/gold/oil exist in shared ingestion, not all in every coin packet. No automatic forecast of event outcome. |
| Risk | IMPLEMENTED | Canonical structural candidate geometry and RR; equity/risk inputs for sizing | Competing long/short candidates; quality and RR gates. Leverage ceiling is a constraint, not advice without capital context. |
| Strategy validation | NOT_IMPLEMENTED | Deterministic formula and geometry regression tests | No walk-forward/out-of-sample performance dataset; no published win rate, calibrated confidence percentage or profitability claim. Arbitrage costs are estimates. |

## Highest-impact corrections

1. Numerical/data integrity: real recursive EMA and current Wilder ATR; validate finite OHLC and chronological closed candles; reject missing/stale/future market timestamps for active decisions. Normalize derivatives units explicitly.
2. Evidence integrity: group price-derived confluence with price evidence; missing sentiment and volume proxies cannot impersonate independent market evidence; expose supporting/opposing evidence and contradictions without changing structural RR.
3. Conversation selection: route explanatory follow-ups to the cached asset/timeframe and scenarios; acknowledge stale snapshots without refetching for an explanation; use the same guarded language contract for local/cloud prose.

## Technical references

- [EMA definition](https://www.tradingview.com/support/solutions/43000592270-exponential-moving-average/)
- [ATR and Wilder/RMA smoothing](https://www.tradingview.com/support/solutions/43000501823-average-true-range-atr/)
- [Binance public market data](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)
- [Gate public futures units](https://www.gate.com/docs/developers/apiv4/en/)
- [CoinGecko derivatives](https://docs.coingecko.com/reference/derivatives-tickers)

Tests establish implementation correctness only. Live data is read-only and can be unavailable; no order execution is implemented.
