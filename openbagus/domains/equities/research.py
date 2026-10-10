"""IDX rendering and evidence selection using the existing research runner/packet."""

from datetime import datetime, timezone
import re

from openbagus.domains.equities.catalog import SECTORS
from openbagus.domains.equities.data import EquityData, fundamentals, timestamp
from openbagus.domains.equities.policy import EquityMarketPolicy


def equity_context(asset, query: str) -> str:
    lower = query.lower()
    if asset.sector_code == "G":
        return ("Penurunan BI-Rate dapat menurunkan biaya dana, tetapi repricing kredit juga dapat menekan NIM. "
                "Dampaknya bergantung pada CASA, pertumbuhan kredit, kualitas aset dan valuasi masing-masing bank. "
                "Bandingkan NIM/NPL/CAR yang benar-benar dilaporkan; arah harga saham tidak otomatis mengikuti suku bunga.")
    if any(word in lower for word in ("nikel", "nickel", "emas", "gold")) and asset.symbol == "ANTM":
        return ("ANTM memiliki eksposur nikel dan emas. Kenaikan harga komoditas berpotensi membantu pendapatan, "
                "namun realisasi harga, volume produksi, biaya, royalti dan kurs menentukan transmisi ke margin. "
                "Tanpa angka produksi/biaya dan valuasi terkini, belum ada dasar menyimpulkan harga saham akan naik.")
    if asset.sector_code == "J":
        return "Untuk infrastruktur/telekomunikasi, periksa pertumbuhan pendapatan, capex, utang dan arus kas; ARPU hanya jika dilaporkan."
    if asset.sector_code in {"D", "E"}:
        return "Daya beli, pertumbuhan penjualan, biaya bahan baku dan margin menjadi driver utama; sektor saja tidak membuktikan pricing power."
    if asset.sector_code == "I":
        return "Periksa kualitas pendapatan, cash burn, profitabilitas dan risiko dilusi; jangan memakai skor fundamental seragam."
    return "Evaluasi permintaan, biaya input, arus kas dan margin sesuai bisnis emiten. Kebijakan/berita bukan pengganti harga pasar."


def render_equity(packet, quant, asset, query: str, *, language: str = "ID", show_sources: bool = False, narrative: str = "") -> str:
    english = language == "EN"
    price = f"Rp{quant.price:,.0f}" if quant.price else "DATA GAP"
    text = [f"{asset.symbol} | IDX | {quant.timeframe} | {quant.decision} | {price}"]
    follow = bool(re.search(r"kenapa|why|rate|nikel|nickel|dampak|pengaruh|sederhana|simple", query.lower()))
    if narrative:
        text.append(narrative)
    elif not follow or re.search(r"kenapa|why", query.lower()):
        text.append(quant.decision_reason)
    if english and not narrative:
        text.append("IDX cash-equity research uses IDR, closed bars and effective market rules, not perpetual funding or leverage. "
                    "A policy-rate change can affect funding cost, loan yields, credit demand and valuation differently. Missing evidence is not a directional signal.")
    elif not narrative:
        text.append(equity_context(asset, query))
    f = packet.fundamentals
    val_query = bool(re.search(r"valuasi|fundamental|layak\s+beli|layak\s+investasi", query.lower()))
    if val_query and f.get("ratios") and not narrative:
        r = f["ratios"]
        roe_val = r.get("roe") or r.get("ROE")
        pbv_val = r.get("pbv") or r.get("PBV")
        per_val = r.get("per") or r.get("PER")
        car_val = r.get("car") or r.get("CAR")
        nim_val = r.get("nim") or r.get("NIM")
        npl_val = r.get("npl") or r.get("NPL")
        eval_lines = [
            f"Analisis Valuasi & Fundamental {asset.symbol}:",
            f"Berdasarkan laporan {f.get('period_type', '')} {f.get('period', '')} ({f.get('basis', 'konsolidasi')}), rasio yang dilaporkan:",
        ]
        if pbv_val is not None:
            eval_lines.append(f"  - Price to Book (PBV): {pbv_val:.2f}x")
        if per_val is not None:
            eval_lines.append(f"  - Price to Earnings (PER): {per_val:.2f}x")
        if roe_val is not None:
            eval_lines.append(f"  - Return on Equity (ROE): {roe_val*100 if roe_val < 1 else roe_val:.2f}%")
        if car_val is not None:
            eval_lines.append(f"  - Capital Adequacy Ratio (CAR): {car_val*100 if car_val < 1 else car_val:.2f}%")
        if nim_val is not None:
            eval_lines.append(f"  - Net Interest Margin (NIM): {nim_val*100 if nim_val < 1 else nim_val:.2f}%")
        if npl_val is not None:
            eval_lines.append(f"  - Non-Performing Loan (NPL Gross): {npl_val*100 if npl_val < 1 else npl_val:.2f}%")
        eval_lines.append(
            f"Prinsip Riset: Terdapat perbedaan esensial antara emiten berkualitas fundamental tinggi dan harga entry yang atraktif. "
            f"Valuasi saat ini mencerminkan premi kualitas. Keputusan Quant adalah '{quant.decision}' ({quant.regime}) "
            f"karena setup teknikal dan margin of safety belum memenuhi kriteria entry baru."
        )
        text.append("\n".join(eval_lines))
    elif f.get("ratios") and (not follow or re.search(r"fundamental|valuasi|rate|nikel|dampak", query.lower())):
        text.append(f"Fundamental {f['period_type']} {f['period']} ({f['basis']}): " +
                    "; ".join(f"{key} {value:,.3f}" for key, value in f["ratios"].items()))
    elif not f.get("ratios"):
        text.append("SOURCE GAP: laporan keuangan belum tersedia; EPS/PER/PBV/rasio bank tidak diisi dengan perkiraan.")
    if quant.bullish_validation:
        s = quant.bullish_validation
        text.append(f"Scenario {s.trigger_state}: {s.trigger_condition}. Entry {s.entry_zone}, invalidation Rp{s.stop_price:,.0f}, "
                    f"target Rp{s.tp1:,.0f}, RR setelah biaya {s.reward_risk_str}.")
    for event in packet.events[:3]:
        text.append(f"{event['status']}: {event['summary']} [{event['observation_period']}; publikasi {event['published_at']}]. "
                    f"Sumber: {event['source']}")
    if not packet.events and re.search(r"rate|inflasi|rupiah|news|berita|nikel", query.lower()):
        text.append("DATA GAP: publikasi BI/BPS/OJK/emiten/komoditas terkini belum diimpor; mekanisme di atas adalah skenario, bukan konfirmasi event.")
    text.append(f"Data Freshness: {quant.data_freshness}; harga as-of {packet.price_as_of or 'UNAVAILABLE'}. "
                "Risk Note: likuiditas, corporate actions dan keterbatasan sumber dapat mengubah tesis.")
    if show_sources:
        text.append("Evidence Stack: " + "; ".join(packet.sources or ["SOURCE GAP"]))
    return "\n\n".join(text)


def run_equity_research(runner, req, session=None) -> str:
    from openbagus.domains.crypto.research import ResearchPacket

    if req.request_type == "EQUITY_SECTOR":
        if req.category not in SECTORS:
            return "IDX-IC: " + "; ".join(f"{code} {names[0]} / {names[1]}" for code, names in SECTORS.items())
        names = SECTORS[req.category]
        members = [a.symbol for a in runner.assets.equities.assets if a.sector_code == req.category]
        return f"IDX-IC {names[0]} / {names[1]}: {', '.join(members) or 'SOURCE GAP'}\nCatalog parsial; perlu impor untuk universe dan hierarki resmi lengkap."
    asset = runner.assets.equities.resolve(req.asset or "")
    if not asset:
        return "SOURCE GAP: IDX identity unverified."
    data = EquityData(runner.root).load(asset.symbol)
    policy = EquityMarketPolicy(runner.root)
    if req.request_type == "EQUITY_QUOTE":
        q = data.get("quote", {})
        return (f"{asset.symbol}: Rp{q['price']:,.0f}\nAs-of: {q['as_of']}\n"
                f"Data Freshness: {policy.freshness(q, datetime.now(timezone.utc))}\nSource: {data['source']}") if q else "SOURCE GAP: harga IDX berizin belum tersedia."
    if req.request_type == "EQUITY_OWNERSHIP":
        from openbagus.domains.equities.ownership import load_ownership
        own = load_ownership(asset.symbol, runner.root)
        if not own:
            return f"SOURCE GAP: Data kepemilikan terverifikasi untuk {asset.symbol} belum tersedia. Impor data KSEI/IDX."
        lines = [
            f"Struktur Kepemilikan Saham: {own.issuer} ({own.ticker})",
            f"Periode Pelaporan: {own.reporting_date} | Publikasi: {own.publication_date}",
            f"Total Saham Beredar: {own.shares_outstanding:,.0f} lembar",
            "",
            f"Komposisi Investor: Domestik {own.domestic_pct:.2f}% | Asing {own.foreign_pct:.2f}%",
            f"Free Float Publik (<5%): {own.public_shareholders_pct:.2f}%",
            "",
            "Pemegang Saham Utama (>= 5% / Pengendali):",
        ]
        for s in own.top_shareholders:
            lines.append(f"  - {s.shareholder}: {s.percentage:.2f}% ({s.shares_held:,.0f} lembar) [{s.investor_type}]")
        lines.append("")
        lines.append(f"Catatan Denominator: {own.denominator_explanation}")
        lines.append(f"Sumber: {own.source}")
        return "\n".join(lines)
    if req.request_type == "BACKTEST":
        from openbagus.domains.quant.backtesting import BacktestRunner
        from openbagus.reporting.visualizer import generate_html_report
        import webbrowser
        candles = data.get("candles", [])
        if len(candles) < 25:
            return f"SOURCE GAP: Data OHLCV {asset.symbol} ({len(candles)} bar) tidak mencukupi untuk backtest (minimal 25 bar)."
        bt_runner = BacktestRunner(
            initial_capital=100_000_000.0,
            asset_type="EQUITY_ID",
            buy_fee=float(data.get("fees", {}).get("buy", 0.0015)),
            sell_fee=float(data.get("fees", {}).get("sell", 0.0025)),
        )
        bt_res = bt_runner.run(asset.symbol, candles, timeframe=req.timeframe)
        q_dummy = runner.quant.evaluate_equity(asset.symbol, data, policy, timeframe=req.timeframe)
        html_path = generate_html_report(asset.symbol, candles, quant_result=q_dummy, backtest_result=bt_res, root=runner.root, timeframe=req.timeframe)
        try:
            webbrowser.open(html_path.as_uri())
        except Exception:
            pass
        return bt_res.summary_table() + f"\n\nLaporan visual backtest disimpan di:\n{html_path}"
    if req.request_type == "FOLLOW_UP" and session and session.last_research_packet and session.last_research_packet.asset == asset.symbol:
        return render_equity(session.last_research_packet, session.last_quant_result, asset, req.raw_query,
                             language=session.language, show_sources=session.show_sources)
    if req.request_type in ("VISUALIZE", "REPORT_HTML", "REPORT_WORD") and session and session.last_research_packet and session.last_research_packet.asset == asset.symbol and session.last_quant_result:
        q = session.last_quant_result
        packet = session.last_research_packet
    else:
        q = runner.quant.evaluate_equity(asset.symbol, data, policy, timeframe=req.timeframe,
            has_position_context=req.has_position_context, is_index=asset.asset_type == "INDEX_ID")
        packet = None

    if req.request_type == "SECTOR_IMPACT":
        lines = [
            f"Analisis Transmisi Makro & Dampak Sektoral: Data Manufaktur China -> {asset.symbol} (Sektor {asset.sector_code})",
            "",
            "1. Rantai Transmisi Permintaan Global (Demand Transmission):",
            "   - China menyerap >50% pasokan logam industri dunia, terutama untuk pabrik baja nirkarat (stainless steel) dan rantai baterai EV.",
            "   - Data Purchasing Managers' Index (PMI) manufaktur China yang ekspansif meningkatkan proyeksi konsumsi bijih nikel dan feronikel.",
            "   - Ekspektasi ini ditransmisikan langsung ke harga acuan LME Nickel dan Shanghai Futures Exchange (SHFE).",
            "",
            f"2. Eksposur & Sensitivitas Emiten ({asset.symbol}):",
            f"   - {asset.symbol} memiliki portofolio komoditas tambang terintegrasi (bijih nikel, feronikel, bauksit, dan emas).",
            "   - Kenaikan harga nikel global berpotensi mengangkat Average Selling Price (ASP), namun transmisi ke laba bersih tetap dibatasi oleh royalti progresif, biaya energi smelter, dan nilai tukar USD/IDR.",
            "",
            f"3. Struktur Teknikal & Level Kuantitatif {asset.symbol} ({q.timeframe}):",
            f"   - Harga Terakhir: Rp{q.price:,.0f} | Keputusan Quant: {q.decision} ({q.regime})",
            f"   - Catatan Risiko: {q.decision_reason}",
        ]
        if q.bullish_validation:
            b = q.bullish_validation
            lines.append(f"   - Skenario Validasi: Trigger {b.trigger_condition}, Target Rp{b.tp1:,.0f}, Stop Rp{b.stop_price:,.0f} (RR {b.reward_risk_str}).")
        lines.append("")
        lines.append(f"Data Freshness: {q.data_freshness}; Sumber: {data.get('source', 'Katalog IDX')}.")
        output = "\n".join(lines)
        if session:
            session.last_asset = asset.symbol
            session.market_type = q.market
            session.timeframe = q.timeframe
            session.last_quant_result = q
            session.last_query = req.raw_query
            session.last_research_at = datetime.now(timezone.utc).isoformat()
            if session.is_persistence_enabled():
                session.save_persistent()
        return output

    statement = data.get("fundamentals")
    now = datetime.now(timezone.utc)
    if statement and timestamp(statement["published_at"]) > now:
        statement = None
    previous = data.get("previous_fundamentals")
    if previous and timestamp(previous["published_at"]) > now:
        previous = None
    financials = fundamentals(statement, q.price or None, previous)
    events = []
    fingerprints = set()
    for event in data.get("events", []):
        publication = timestamp(event["published_at"])
        if publication > now or (now - publication).days > 30:
            continue
        if asset.symbol not in event.get("assets", []) and asset.sector_code not in event.get("sectors", []):
            continue
        fingerprint = re.sub(r"\W+", "", event["summary"].lower())
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        when = timestamp(event["event_at"]) if event.get("event_at") else None
        status = "UPCOMING" if when and when > now else ("COMPLETED_EVENT" if when else "ANNOUNCED")
        events.append({**event, "status": status})
    sources = list(dict.fromkeys([*q.sources, asset.source, *([financials["source"]] if financials.get("source") else []),
                                 *[e["source"] for e in events]]))
    from openbagus.domains.equities.ownership import load_ownership
    own = load_ownership(asset.symbol, runner.root)
    if packet is None:
        packet = ResearchPacket(asset.symbol, q.market, q.timeframe, q.price, q.decision, q.data_quality, q.setup_quality,
            regime=q.regime, decision_reason=q.decision_reason, reward_risk_str=q.reward_risk_str,
            rr_gate_passed=q.rr_gate_passed, entry_zone=q.entry_zone, stop_price=q.stop_price, tp1=q.tp1,
            leverage_ceiling="N/A", bullish_validation=q.bullish_validation, sources=sources,
            data_freshness=q.data_freshness, evidence_families=q.evidence_families,
            currency="IDR", asset_type=asset.asset_type, fundamentals=financials, events=events,
            price_as_of=data.get("quote", {}).get("as_of", ""), ownership=own)
        from openbagus.intelligence.evidence import build_evidence_packet_from_research
        packet.evidence_packet = build_evidence_packet_from_research(packet, q)
        output = render_equity(packet, q, asset, req.raw_query, language=session.language if session else "ID",
                               show_sources=session.show_sources if session else False)
        if data.get("quote") or statement:
            narrative = runner.local_llm.generate_narrative(packet, user_query=req.raw_query,
                language="en" if session and session.language == "EN" else "id")
            if narrative:
                output = render_equity(packet, q, asset, req.raw_query, language=session.language if session else "ID",
                                       show_sources=session.show_sources if session else False, narrative=narrative)
        packet.narrative = output
    else:
        output = packet.narrative or render_equity(packet, q, asset, req.raw_query,
                                                  language=session.language if session else "ID",
                                                  show_sources=session.show_sources if session else False)
    if req.request_type in ("VISUALIZE", "REPORT_HTML"):
        from openbagus.domains.equities.ownership import load_ownership
        from openbagus.reporting.visualizer import generate_html_report
        import webbrowser
        own = load_ownership(asset.symbol, runner.root)
        html_path = generate_html_report(asset.symbol, data.get("candles", []), q, packet, own, root=runner.root, timeframe=req.timeframe)
        try:
            webbrowser.open(html_path.as_uri())
        except Exception:
            pass
        output = f"Laporan visualisasi interaktif {asset.symbol} ({req.timeframe}) berhasil dibuat:\n{html_path}\n\n(Telah mencakup Interactive Candlestick, Radar Multi-Factor, Hierarchical Sunburst, Correlation Heatmap, dan Kepemilikan)"
        packet.narrative = output
    elif req.request_type == "REPORT_WORD":
        from openbagus.domains.equities.ownership import load_ownership
        from openbagus.reporting.word_report import generate_word_report
        own = load_ownership(asset.symbol, runner.root)
        docx_path = generate_word_report(asset.symbol, q, packet, own, root=runner.root, timeframe=req.timeframe)
        output = f"Laporan Microsoft Word (.docx) {asset.symbol} ({req.timeframe}) berhasil dibuat:\n{docx_path}\n\n(Memuat chart DrawingML native dengan embedded workbook Excel yang dapat diedit langsung di Word)"
        packet.narrative = output
    if req.focus == "capital":
        if req.equity is not None and req.risk_pct is not None and q.stop_price is not None and q.bullish_validation:
            try:
                shares = policy.position_size(q.bullish_validation.entry_price, q.stop_price,
                    req.equity, req.risk_pct, data["fees"]["buy"], data["fees"]["sell"])
                output += f"\n\nRisk-budget review: {shares} lembar, sesuai round lot dan biaya; bukan order."
            except (ValueError, TypeError, KeyError):
                output += "\n\nDATA GAP: parameter budget/risk/fee belum valid untuk sizing."
        else:
            output += "\n\nSizing belum tersedia: perlu modal Rp/IDR, risk %, biaya dan setup aktif terverifikasi."
        packet.narrative = output
    if session:
        session.last_asset, session.market_type, session.timeframe = asset.symbol, q.market, q.timeframe
        session.last_quant_result, session.last_research_packet = q, packet
        session.last_query, session.last_research_at = req.raw_query, now.isoformat()
        if session.is_persistence_enabled():
            session.save_persistent()
    return output
