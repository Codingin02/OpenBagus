//! OpenBagus Native Quantitative Kernel
//!
//! PyO3-accelerated vector indicators, rolling statistics, Monte Carlo VaR/CVaR,
//! parallel universe screening, and exact market lot arithmetic.

use pyo3::prelude::*;
use rayon::prelude::*;

/// Computes Simple Moving Average (SMA).
#[pyfunction]
pub fn calculate_sma(prices: Vec<f64>, period: usize) -> Vec<Option<f64>> {
    let n = prices.len();
    let mut result = vec![None; n];
    if period == 0 || n < period {
        return result;
    }

    let mut sum: f64 = prices.iter().take(period).sum();
    result[period - 1] = Some(sum / period as f64);

    for i in period..n {
        sum += prices[i] - prices[i - period];
        result[i] = Some(sum / period as f64);
    }
    result
}

/// Computes Exponential Moving Average (EMA).
#[pyfunction]
pub fn calculate_ema(prices: Vec<f64>, period: usize) -> Vec<Option<f64>> {
    let n = prices.len();
    let mut result = vec![None; n];
    if period == 0 || n < period {
        return result;
    }

    let multiplier = 2.0 / (period as f64 + 1.0);
    let initial_sum: f64 = prices.iter().take(period).sum();
    let mut prev_ema = initial_sum / period as f64;
    result[period - 1] = Some(prev_ema);

    for i in period..n {
        let ema = (prices[i] - prev_ema) * multiplier + prev_ema;
        result[i] = Some(ema);
        prev_ema = ema;
    }
    result
}

/// Computes Wilder's Relative Strength Index (RSI).
#[pyfunction]
pub fn calculate_rsi(prices: Vec<f64>, period: usize) -> Vec<Option<f64>> {
    let n = prices.len();
    let mut result = vec![None; n];
    if period == 0 || n <= period {
        return result;
    }

    let mut gains = Vec::with_capacity(n - 1);
    let mut losses = Vec::with_capacity(n - 1);

    for i in 1..n {
        let change = prices[i] - prices[i - 1];
        if change > 0.0 {
            gains.push(change);
            losses.push(0.0);
        } else {
            gains.push(0.0);
            losses.push(-change);
        }
    }

    let mut avg_gain: f64 = gains.iter().take(period).sum::<f64>() / period as f64;
    let mut avg_loss: f64 = losses.iter().take(period).sum::<f64>() / period as f64;

    if avg_loss == 0.0 {
        result[period] = Some(100.0);
    } else {
        let rs = avg_gain / avg_loss;
        result[period] = Some(100.0 - (100.0 / (1.0 + rs)));
    }

    let p_f = period as f64;
    for i in period..(n - 1) {
        avg_gain = (avg_gain * (p_f - 1.0) + gains[i]) / p_f;
        avg_loss = (avg_loss * (p_f - 1.0) + losses[i]) / p_f;

        if avg_loss == 0.0 {
            result[i + 1] = Some(100.0);
        } else if avg_gain == 0.0 {
            result[i + 1] = Some(0.0);
        } else {
            let rs = avg_gain / avg_loss;
            result[i + 1] = Some(100.0 - (100.0 / (1.0 + rs)));
        }
    }

    result
}

/// Computes Average True Range (ATR).
#[pyfunction]
pub fn calculate_atr(highs: Vec<f64>, lows: Vec<f64>, closes: Vec<f64>, period: usize) -> Vec<Option<f64>> {
    let n = closes.len();
    let mut result = vec![None; n];
    if period == 0 || n < period || highs.len() != n || lows.len() != n {
        return result;
    }

    let mut trs = Vec::with_capacity(n);
    trs.push(highs[0] - lows[0]);

    for i in 1..n {
        let h_l = highs[i] - lows[i];
        let h_cp = (highs[i] - closes[i - 1]).abs();
        let l_cp = (lows[i] - closes[i - 1]).abs();
        let tr = h_l.max(h_cp).max(l_cp);
        trs.push(tr);
    }

    let mut prev_atr: f64 = trs.iter().take(period).sum::<f64>() / period as f64;
    result[period - 1] = Some(prev_atr);

    let p_f = period as f64;
    for i in period..n {
        let atr = (prev_atr * (p_f - 1.0) + trs[i]) / p_f;
        result[i] = Some(atr);
        prev_atr = atr;
    }

    result
}

/// Computes MACD Line, Signal Line, and MACD Histogram.
#[pyfunction]
pub fn calculate_macd(
    prices: Vec<f64>,
    fast: usize,
    slow: usize,
    signal: usize,
) -> (Vec<Option<f64>>, Vec<Option<f64>>, Vec<Option<f64>>) {
    let n = prices.len();
    let mut macd_line = vec![None; n];
    let mut signal_line = vec![None; n];
    let mut histogram = vec![None; n];

    if fast >= slow || n < slow {
        return (macd_line, signal_line, histogram);
    }

    let ema_fast = calculate_ema(prices.clone(), fast);
    let ema_slow = calculate_ema(prices, slow);

    let mut valid_macd_vals = Vec::new();
    let mut valid_indices = Vec::new();

    for i in 0..n {
        if let (Some(f), Some(s)) = (ema_fast[i], ema_slow[i]) {
            let m = f - s;
            macd_line[i] = Some(m);
            valid_macd_vals.push(m);
            valid_indices.push(i);
        }
    }

    if valid_macd_vals.len() >= signal {
        let sig_emas = calculate_ema(valid_macd_vals, signal);
        for (j, &orig_idx) in valid_indices.iter().enumerate() {
            if let Some(sig) = sig_emas[j] {
                signal_line[orig_idx] = Some(sig);
                if let Some(m) = macd_line[orig_idx] {
                    histogram[orig_idx] = Some(m - sig);
                }
            }
        }
    }

    (macd_line, signal_line, histogram)
}

/// Computes Bollinger Bands (Upper, Middle SMA, Lower).
#[pyfunction]
pub fn calculate_bollinger_bands(
    prices: Vec<f64>,
    period: usize,
    num_std: f64,
) -> (Vec<Option<f64>>, Vec<Option<f64>>, Vec<Option<f64>>) {
    let n = prices.len();
    let mut upper = vec![None; n];
    let mut middle = vec![None; n];
    let mut lower = vec![None; n];

    if period == 0 || n < period {
        return (upper, middle, lower);
    }

    let sma = calculate_sma(prices.clone(), period);

    for i in (period - 1)..n {
        if let Some(m) = sma[i] {
            middle[i] = Some(m);
            let slice = &prices[(i + 1 - period)..=i];
            let variance: f64 = slice.iter().map(|&x| (x - m).powi(2)).sum::<f64>() / period as f64;
            let std_dev = variance.sqrt();
            upper[i] = Some(m + num_std * std_dev);
            lower[i] = Some(m - num_std * std_dev);
        }
    }

    (upper, middle, lower)
}

/// Computes Volume Weighted Average Price (VWAP).
#[pyfunction]
pub fn calculate_vwap(prices: Vec<f64>, volumes: Vec<f64>) -> Vec<Option<f64>> {
    let n = prices.len();
    let mut vwap = vec![None; n];
    if n == 0 || volumes.len() != n {
        return vwap;
    }

    let mut cum_pv = 0.0;
    let mut cum_vol = 0.0;

    for i in 0..n {
        cum_pv += prices[i] * volumes[i];
        cum_vol += volumes[i];
        if cum_vol > 0.0 {
            vwap[i] = Some(cum_pv / cum_vol);
        }
    }
    vwap
}

/// Computes rolling mean and standard deviation.
#[pyfunction]
pub fn calculate_rolling_stats(prices: Vec<f64>, period: usize) -> (Vec<Option<f64>>, Vec<Option<f64>>) {
    let n = prices.len();
    let mut means = vec![None; n];
    let mut stds = vec![None; n];

    if period == 0 || n < period {
        return (means, stds);
    }

    let sma = calculate_sma(prices.clone(), period);
    for i in (period - 1)..n {
        if let Some(m) = sma[i] {
            means[i] = Some(m);
            let slice = &prices[(i + 1 - period)..=i];
            let variance: f64 = slice.iter().map(|&x| (x - m).powi(2)).sum::<f64>() / period as f64;
            stds[i] = Some(variance.sqrt());
        }
    }

    (means, stds)
}

/// Simulates parametric Monte Carlo Value at Risk (VaR) and Conditional VaR (CVaR).
#[pyfunction]
pub fn calculate_var_cvar_mc(
    returns: Vec<f64>,
    confidence: f64,
    num_simulations: usize,
    seed: Option<u64>,
) -> (f64, f64) {
    if returns.is_empty() || num_simulations == 0 {
        return (0.0, 0.0);
    }

    let n = returns.len() as f64;
    let mean = returns.iter().sum::<f64>() / n;
    let variance = returns.iter().map(|r| (r - mean).powi(2)).sum::<f64>() / n;
    let std_dev = variance.sqrt();

    // Deterministic pseudo-random normal generation (Box-Muller)
    let mut rng_state = seed.unwrap_or(42);
    let mut sim_losses = Vec::with_capacity(num_simulations);

    for _ in 0..(num_simulations / 2 + 1) {
        // Xorshift64star RNG
        rng_state ^= rng_state >> 12;
        rng_state ^= rng_state << 25;
        rng_state ^= rng_state >> 27;
        let u1 = ((rng_state.wrapping_mul(0x2545F4914F6CDD1D) >> 11) as f64) / 9007199254740992.0 + 1e-10;

        rng_state ^= rng_state >> 12;
        rng_state ^= rng_state << 25;
        rng_state ^= rng_state >> 27;
        let u2 = ((rng_state.wrapping_mul(0x2545F4914F6CDD1D) >> 11) as f64) / 9007199254740992.0 + 1e-10;

        let z0 = (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos();
        let z1 = (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).sin();

        let r0 = mean + std_dev * z0;
        let r1 = mean + std_dev * z1;

        sim_losses.push(-r0);
        if sim_losses.len() < num_simulations {
            sim_losses.push(-r1);
        }
    }

    sim_losses.truncate(num_simulations);
    sim_losses.sort_by(|a, b| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal));

    let cutoff_idx = ((confidence * num_simulations as f64).floor() as usize).min(num_simulations - 1);
    let var = sim_losses[cutoff_idx];

    let tail = &sim_losses[cutoff_idx..];
    let cvar = tail.iter().sum::<f64>() / tail.len() as f64;

    (var, cvar)
}

/// Sizing share lots with board lot constraint (100 shares) and risk budget.
#[pyfunction]
pub fn calculate_lot_shares(
    cash: f64,
    price: f64,
    max_risk_cash: f64,
    stop_loss_price: f64,
) -> (i64, f64) {
    if price <= 0.0 || cash <= 0.0 {
        return (0, 0.0);
    }

    let risk_per_share = (price - stop_loss_price).abs();
    let max_shares_by_risk = if risk_per_share > 0.0 {
        (max_risk_cash / risk_per_share).floor()
    } else {
        f64::INFINITY
    };

    let max_shares_by_cash = (cash / price).floor();
    let target_shares = max_shares_by_risk.min(max_shares_by_cash).max(0.0);

    // Board lot constraint: multiples of 100 shares
    let lots = (target_shares / 100.0).floor() as i64;
    let final_shares = lots * 100;
    let notional = (final_shares as f64) * price;

    (final_shares, notional)
}

/// Fast parallel universe screener for volume breakout using Rayon.
#[pyfunction]
pub fn parallel_universe_screen(
    tickers: Vec<String>,
    closes_list: Vec<Vec<f64>>,
    volumes_list: Vec<Vec<f64>>,
    min_volume_multiplier: f64,
) -> Vec<String> {
    tickers
        .par_iter()
        .zip(closes_list.par_iter())
        .zip(volumes_list.par_iter())
        .filter_map(|((ticker, closes), volumes)| {
            let n = volumes.len();
            if n < 20 || closes.len() != n {
                return None;
            }

            let last_vol = volumes[n - 1];
            let avg_20d_vol = volumes[(n - 20)..(n - 1)].iter().sum::<f64>() / 19.0;

            if avg_20d_vol > 0.0 && last_vol >= min_volume_multiplier * avg_20d_vol {
                let last_close = closes[n - 1];
                let highest_20d_close = closes[(n - 20)..(n - 1)]
                    .iter()
                    .cloned()
                    .fold(f64::NEG_INFINITY, f64::max);

                if last_close > highest_20d_close {
                    return Some(ticker.clone());
                }
            }
            None
        })
        .collect()
}

/// Returns native engine version and metadata.
#[pyfunction]
pub fn engine_info() -> String {
    format!(
        "OpenBagus Native Quant Engine v0.1.0 (Rust {}-bit, Rayon Parallel, PyO3)",
        std::mem::size_of::<usize>() * 8
    )
}

/// PyO3 Python module definition.
#[pymodule]
fn openbagus_quant_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(calculate_sma, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_ema, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_rsi, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_atr, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_macd, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_bollinger_bands, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_vwap, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_rolling_stats, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_var_cvar_mc, m)?)?;
    m.add_function(wrap_pyfunction!(calculate_lot_shares, m)?)?;
    m.add_function(wrap_pyfunction!(parallel_universe_screen, m)?)?;
    m.add_function(wrap_pyfunction!(engine_info, m)?)?;
    Ok(())
}
