"""OpenBagus Interactive PWA Dashboard Renderer.

Renders a standalone, responsive, client-side PWA dashboard to reports/runtime/app.
Presents active crypto domain data, shared macro context, news intelligence, and system telemetry.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from openbagus.core.env import get_repo_root

ENGINE_VERSION = "openbagus.pwa_dashboard_renderer.v2"
APP_DIR = Path("reports/runtime/app")


class PwaDashboardRenderer:
    """Renders the static PWA dashboard files."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()

    def write(
        self,
        runtime: Mapping[str, Any] | None = None,
        reports: Mapping[str, Any] | None = None,
        delivery_status: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        app_dir = self.root / APP_DIR
        app_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = app_dir / "assets"
        assets_dir.mkdir(exist_ok=True)

        payload = self._build_payload(runtime or {}, reports or {}, delivery_status or {})

        (app_dir / "openbagus_latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        (app_dir / "index.html").write_text(self._index_html(payload), encoding="utf-8")
        (app_dir / "app.css").write_text(self._css(), encoding="utf-8")
        (app_dir / "app.js").write_text(self._js(payload), encoding="utf-8")
        (app_dir / "manifest.webmanifest").write_text(self._manifest(), encoding="utf-8")
        (app_dir / "service-worker.js").write_text(self._service_worker(), encoding="utf-8")
        (assets_dir / "README.md").write_text("Static assets for OpenBagus PWA dashboard.\n", encoding="utf-8")

        return {
            "status": "WEB_PWA_READY",
            "engine_version": ENGINE_VERSION,
            "index_html": str(app_dir / "index.html"),
            "data_json": str(app_dir / "openbagus_latest.json"),
        }

    def _build_payload(
        self,
        runtime: Mapping[str, Any],
        reports: Mapping[str, Any],
        delivery_status: Mapping[str, Any],
    ) -> dict[str, Any]:
        analysis_path = self.root / "reports/runtime/openbagus_real_analysis_latest.json"
        ingestion_path = self.root / "reports/runtime/openbagus_real_data_snapshot_latest.json"

        analysis: dict[str, Any] = {}
        if analysis_path.exists():
            try:
                analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        ingestion: dict[str, Any] = {}
        if ingestion_path.exists():
            try:
                ingestion = json.loads(ingestion_path.read_text(encoding="utf-8"))
            except Exception:
                pass

        asset_views = analysis.get("asset_views", {})
        macro_views = analysis.get("macro_views", {})
        source_health = ingestion.get("source_health", [])

        return {
            "platform": "OpenBagus",
            "active_domain": "crypto",
            "available_domains": ["crypto", "equities_indonesia"],
            "disabled_domains": ["foreign_equities"],
            "generated_at_utc": analysis.get("generated_at_utc", "N/A"),
            "status": analysis.get("data_freshness_summary", {}).get("overall_analysis_status", "OK"),
            "asset_views": asset_views,
            "macro_views": macro_views,
            "source_health": source_health,
            "delivery_status": dict(delivery_status),
        }

    def _index_html(self, payload: dict[str, Any]) -> str:
        gen_time = payload.get("generated_at_utc", "N/A")
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>OpenBagus &bull; Market Intelligence Platform</title>
    <link rel="stylesheet" href="app.css">
    <link rel="manifest" href="manifest.webmanifest">
    <meta name="theme-color" content="#06090e">
</head>
<body>
    <header class="app-header">
        <div class="brand">
            <span class="brand-logo">◆</span>
            <div class="brand-text">
                <h1>OpenBagus</h1>
                <span class="tagline">Modular Quantitative Intelligence Platform</span>
            </div>
        </div>
        <div class="header-status">
            <span class="badge badge-active">Active Domain: Crypto</span>
            <span class="badge badge-disabled">Equities: Disabled</span>
            <span class="timestamp" id="sync-time">Sync: {gen_time}</span>
        </div>
    </header>

    <nav class="nav-tabs">
        <button class="tab-btn active" data-tab="tab-crypto">Crypto Assets</button>
        <button class="tab-btn" data-tab="tab-market-structure">Market Structure</button>
        <button class="tab-btn" data-tab="tab-macro">Shared Macro</button>
        <button class="tab-btn" data-tab="tab-news">Intelligence & News</button>
        <button class="tab-btn" data-tab="tab-telemetry">Telemetry & Health</button>
    </nav>

    <main class="content-container">
        <!-- TAB 1: CRYPTO -->
        <section id="tab-crypto" class="tab-pane active">
            <div class="section-title">
                <h2>Digital Asset Universe (Active Domain)</h2>
                <span class="subtitle">Python Quant Engine Decision Core &bull; Real-time Public Ingestion</span>
            </div>
            <div class="cards-grid" id="crypto-cards">
                <!-- Dynamically populated by app.js -->
            </div>
        </section>

        <!-- TAB 2: MARKET STRUCTURE -->
        <section id="tab-market-structure" class="tab-pane">
            <div class="section-title">
                <h2>Market Structure & Key Levels</h2>
                <span class="subtitle">Support, Resistance, Regime Classification & Liquidity Sweeps</span>
            </div>
            <div class="table-responsive">
                <table class="data-table" id="structure-table">
                    <thead>
                        <tr>
                            <th>Asset</th>
                            <th>Regime</th>
                            <th>Current Price</th>
                            <th>Support</th>
                            <th>Resistance</th>
                            <th>Range Pos</th>
                            <th>Microstructure</th>
                        </tr>
                    </thead>
                    <tbody id="structure-body"></tbody>
                </table>
            </div>
        </section>

        <!-- TAB 3: SHARED MACRO -->
        <section id="tab-macro" class="tab-pane">
            <div class="section-title">
                <h2>Cross-Asset Macro Overlay</h2>
                <span class="subtitle">Explanatory Context for Digital Assets (DXY, VIX, Rates, Commodities)</span>
            </div>
            <div class="macro-grid" id="macro-cards">
                <!-- Dynamically populated by app.js -->
            </div>
        </section>

        <!-- TAB 4: NEWS INTELLIGENCE -->
        <section id="tab-news" class="tab-pane">
            <div class="section-title">
                <h2>Market Intelligence & Narrative Pulse</h2>
                <span class="subtitle">Deduplicated & Scored Headlines with Narrative Clusters</span>
            </div>
            <div class="news-list" id="news-container">
                <p class="placeholder-text">Loading intelligence memory feed...</p>
            </div>
        </section>

        <!-- TAB 5: TELEMETRY -->
        <section id="tab-telemetry" class="tab-pane">
            <div class="section-title">
                <h2>Platform Health & Data Ingestion Telemetry</h2>
                <span class="subtitle">Source Reliability, Freshness Guards & Offline Storage Status</span>
            </div>
            <div class="telemetry-grid">
                <div class="telemetry-card">
                    <h3>Engine Safety Mode</h3>
                    <p class="stat-highlight">NO_SEND_FILE_ONLY</p>
                    <small>Real sending deactivated. All runs persist locally.</small>
                </div>
                <div class="telemetry-card">
                    <h3>Data Quality Status</h3>
                    <p class="stat-highlight" id="overall-freshness">{payload.get('status', 'OK')}</p>
                    <small>Freshness policy active</small>
                </div>
            </div>
            <div class="table-responsive" style="margin-top: 20px;">
                <table class="data-table">
                    <thead>
                        <tr>
                            <th>Source</th>
                            <th>Provider</th>
                            <th>Status</th>
                            <th>Detail</th>
                        </tr>
                    </thead>
                    <tbody id="telemetry-body"></tbody>
                </table>
            </div>
        </section>
    </main>

    <footer class="app-footer">
        <p>OpenBagus Platform &bull; Modular Umbrella Architecture &bull; Research-only local deployment.</p>
    </footer>

    <script id="bootstrap-data" type="application/json">
        {json.dumps(payload)}
    </script>
    <script src="app.js"></script>
</body>
</html>"""

    def _css(self) -> str:
        return """
:root {
    --bg-main: #06090e;
    --bg-card: #0d121c;
    --bg-card-hover: #121824;
    --border-color: #1e293b;
    --text-primary: #f8fafc;
    --text-secondary: #94a3b8;
    --text-muted: #64748b;
    --accent: #38bdf8;
    --accent-glow: rgba(56, 189, 248, 0.15);
    --green: #10b981;
    --yellow: #f59e0b;
    --red: #ef4444;
}

* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    background-color: var(--bg-main);
    color: var(--text-primary);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
}

.app-header {
    background: #090e17;
    border-bottom: 1px solid var(--border-color);
    padding: 16px 32px;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.brand { display: flex; align-items: center; gap: 12px; }
.brand-logo { color: var(--accent); font-size: 24px; }
.brand-text h1 { font-size: 18px; font-weight: 700; letter-spacing: 0.5px; }
.brand-text .tagline { font-size: 12px; color: var(--text-secondary); }

.header-status { display: flex; align-items: center; gap: 12px; }
.badge {
    padding: 4px 10px;
    border-radius: 9999px;
    font-size: 11px;
    font-weight: 600;
}
.badge-active { background: rgba(16, 185, 129, 0.15); color: var(--green); border: 1px solid rgba(16, 185, 129, 0.3); }
.badge-disabled { background: rgba(148, 163, 184, 0.1); color: var(--text-muted); border: 1px solid var(--border-color); }
.timestamp { font-size: 11px; color: var(--text-muted); font-family: monospace; }

.nav-tabs {
    background: #090e17;
    border-bottom: 1px solid var(--border-color);
    padding: 0 32px;
    display: flex;
    gap: 8px;
}

.tab-btn {
    background: none;
    border: none;
    color: var(--text-secondary);
    padding: 12px 18px;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    border-bottom: 2px solid transparent;
    transition: all 0.2s;
}
.tab-btn:hover { color: var(--text-primary); }
.tab-btn.active {
    color: var(--accent);
    border-bottom: 2px solid var(--accent);
}

.content-container { flex: 1; padding: 32px; max-width: 1400px; margin: 0 auto; width: 100%; }
.tab-pane { display: none; }
.tab-pane.active { display: block; }

.section-title { margin-bottom: 24px; }
.section-title h2 { font-size: 20px; font-weight: 700; color: var(--text-primary); }
.section-title .subtitle { font-size: 13px; color: var(--text-secondary); margin-top: 4px; display: block; }

.cards-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
    gap: 20px;
}

.asset-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 12px;
    padding: 24px;
    transition: transform 0.2s, border-color 0.2s;
}
.asset-card:hover {
    border-color: var(--accent);
    transform: translateY(-2px);
}

.card-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; }
.asset-symbol { font-size: 20px; font-weight: 700; }
.asset-price { font-size: 22px; font-weight: 800; font-family: monospace; color: var(--accent); }
.stance-pill {
    padding: 4px 10px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
    display: inline-block;
    margin-bottom: 16px;
}
.stance-accumulate { background: rgba(16, 185, 129, 0.2); color: var(--green); }
.stance-hold { background: rgba(56, 189, 248, 0.2); color: var(--accent); }
.stance-watchlist { background: rgba(245, 158, 11, 0.2); color: var(--yellow); }
.stance-avoid { background: rgba(239, 68, 68, 0.2); color: var(--red); }

.metrics-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    padding-top: 16px;
    border-top: 1px solid var(--border-color);
}
.metric-item small { color: var(--text-muted); font-size: 11px; display: block; }
.metric-item span { font-size: 14px; font-weight: 600; font-family: monospace; }

.table-responsive { overflow-x: auto; background: var(--bg-card); border-radius: 12px; border: 1px solid var(--border-color); }
.data-table { width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }
.data-table th { background: #090e17; padding: 14px 18px; color: var(--text-secondary); font-weight: 600; border-bottom: 1px solid var(--border-color); }
.data-table td { padding: 14px 18px; border-bottom: 1px solid var(--border-color); }

.macro-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
    gap: 16px;
}
.macro-card {
    background: var(--bg-card);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 20px;
}
.macro-card h4 { font-size: 13px; color: var(--text-secondary); margin-bottom: 8px; }
.macro-val { font-size: 24px; font-weight: 700; color: var(--text-primary); font-family: monospace; }

.telemetry-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.telemetry-card { background: var(--bg-card); border: 1px solid var(--border-color); border-radius: 8px; padding: 20px; }
.stat-highlight { font-size: 20px; font-weight: 700; color: var(--green); margin: 6px 0; }

.app-footer {
    background: #090e17;
    border-top: 1px solid var(--border-color);
    padding: 16px 32px;
    text-align: center;
    font-size: 12px;
    color: var(--text-muted);
}
"""

    def _js(self, payload: dict[str, Any]) -> str:
        return """
document.addEventListener('DOMContentLoaded', () => {
    // 1. Tab Navigation
    const tabs = document.querySelectorAll('.tab-btn');
    const panes = document.querySelectorAll('.tab-pane');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            panes.forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            const target = document.getElementById(tab.dataset.tab);
            if (target) target.classList.add('active');
        });
    });

    // 2. Load data from bootstrap element
    let data = {};
    const bootstrapEl = document.getElementById('bootstrap-data');
    if (bootstrapEl) {
        try {
            data = JSON.parse(bootstrapEl.textContent);
        } catch(e) {
            console.error('Failed to parse bootstrap data', e);
        }
    }

    renderApp(data);
});

function renderApp(data) {
    if (!data) return;

    // Render Crypto Cards
    const cryptoContainer = document.getElementById('crypto-cards');
    if (cryptoContainer && data.asset_views) {
        cryptoContainer.innerHTML = '';
        Object.entries(data.asset_views).forEach(([symbol, view]) => {
            const ms = view.market_structure || {};
            const sr = ms.support_resistance || {};
            const rawPrice = view.current_price || ms.current_price || sr.latest_close;
            const price = rawPrice ? `$${Number(rawPrice).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}` : 'N/A';
            const stance = view.portfolio_stance || 'Watchlist';
            let stanceClass = 'stance-watchlist';
            if (stance.includes('Accumulate')) stanceClass = 'stance-accumulate';
            else if (stance === 'Hold') stanceClass = 'stance-hold';
            else if (stance === 'Avoid') stanceClass = 'stance-avoid';

            const card = document.createElement('div');
            card.className = 'asset-card';
            card.innerHTML = `
                <div class="card-top">
                    <div>
                        <div class="asset-symbol">${symbol}</div>
                        <small style="color: #64748b;">Crypto Core</small>
                    </div>
                    <div class="asset-price">${price}</div>
                </div>
                <div class="stance-pill ${stanceClass}">Stance: ${stance}</div>
                <div class="metrics-row">
                    <div class="metric-item">
                        <small>Conviction</small>
                        <span>${view.conviction_score || 0} / 100</span>
                    </div>
                    <div class="metric-item">
                        <small>Actionability</small>
                        <span>${view.actionability_score || 0} / 100</span>
                    </div>
                    <div class="metric-item">
                        <small>Invalidation</small>
                        <span>${view.invalidation_level ? `$${Number(view.invalidation_level).toLocaleString()}` : 'N/A'}</span>
                    </div>
                    <div class="metric-item">
                        <small>Regime</small>
                        <span>${ms.regime || 'RANGE'}</span>
                    </div>
                </div>
                <div style="margin-top: 14px; font-size: 12px; color: #94a3b8; border-top: 1px solid #1e293b; padding-top: 10px;">
                    ${view.risk_note || ''}
                </div>
            `;
            cryptoContainer.appendChild(card);
        });
    }

    // Render Market Structure Table
    const structBody = document.getElementById('structure-body');
    if (structBody && data.asset_views) {
        structBody.innerHTML = '';
        Object.entries(data.asset_views).forEach(([symbol, view]) => {
            const ms = view.market_structure || {};
            const sr = ms.support_resistance || {};
            const cm = view.crypto_microstructure || {};
            const rawPrice = view.current_price || ms.current_price || sr.latest_close;
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><strong>${symbol}</strong></td>
                <td><span style="color: #38bdf8;">${ms.regime || 'RANGE'}</span></td>
                <td>$${Number(rawPrice || 0).toLocaleString()}</td>
                <td>$${Number(sr.support || 0).toLocaleString()}</td>
                <td>$${Number(sr.resistance || 0).toLocaleString()}</td>
                <td>${sr.range_position !== undefined ? (sr.range_position * 100).toFixed(1) + '%' : 'N/A'}</td>
                <td>${cm.microstructure_quality || 'OK'}</td>
            `;
            structBody.appendChild(row);
        });
    }

    // Render Macro Cards
    const macroContainer = document.getElementById('macro-cards');
    if (macroContainer && data.macro_views) {
        macroContainer.innerHTML = '';
        Object.values(data.macro_views).forEach(group => {
            if (group && group.indicators) {
                group.indicators.forEach(ind => {
                    const card = document.createElement('div');
                    card.className = 'macro-card';
                    card.innerHTML = `
                        <h4>${ind.indicator_name || ind.indicator_code}</h4>
                        <div class="macro-val">${Number(ind.value).toLocaleString()} <span style="font-size: 13px; color: #64748b;">${ind.unit || ''}</span></div>
                        <small style="color: #64748b; margin-top: 6px; display: block;">Observed: ${ind.freshness_status || 'FRESH'}</small>
                    `;
                    macroContainer.appendChild(card);
                });
            }
        });
    }

    // Render Telemetry
    const telemBody = document.getElementById('telemetry-body');
    if (telemBody && data.source_health) {
        telemBody.innerHTML = '';
        data.source_health.forEach(h => {
            const tr = document.createElement('tr');
            const statusColor = h.status === 'OK' ? '#10b981' : (h.status === 'WARNING' ? '#f59e0b' : '#ef4444');
            tr.innerHTML = `
                <td>${h.source_name}</td>
                <td>${h.provider}</td>
                <td><strong style="color: ${statusColor};">${h.status}</strong></td>
                <td>${h.reason || 'Rows: ' + (h.rows_returned || 0)}</td>
            `;
            telemBody.appendChild(tr);
        });
    }
}
"""

    def _manifest(self) -> str:
        return json.dumps({
            "name": "OpenBagus Platform",
            "short_name": "OpenBagus",
            "description": "Modular Financial & Alternative Data Intelligence Platform",
            "start_url": "index.html",
            "display": "standalone",
            "background_color": "#06090e",
            "theme_color": "#06090e",
            "icons": [
                {"src": "assets/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "assets/icon-512.png", "sizes": "512x512", "type": "image/png"}
            ]
        }, indent=2)

    def _service_worker(self) -> str:
        return """
const CACHE_NAME = 'openbagus-v2';
const STATIC_ASSETS = [
    './',
    './index.html',
    './app.css',
    './app.js',
    './manifest.webmanifest',
    './openbagus_latest.json'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => Promise.all(
            keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
        ))
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    event.respondWith(
        fetch(event.request).catch(() => caches.match(event.request))
    );
});
"""
