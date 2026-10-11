"""IDX rendering and evidence selection using the existing research runner/packet."""

from datetime import datetime, timezone
import re

from openbagus.domains.equities.catalog import SECTORS
from openbagus.domains.equities.data import EquityData, fundamentals, timestamp
from openbagus.domains.equities.policy import EquityMarketPolicy


def equity_context(asset, query: str) -> str:
    lower = query.lower()
    if any(word in lower for word in ("nikel", "nickel", "emas", "gold")) and asset.symbol == "ANTM":
        return ("ANTM memiliki eksposur nikel dan emas. Kenaikan harga komoditas berpotensi membantu pendapatan, "
                "namun realisasi harga, volume produksi, biaya, royalti dan kurs menentukan transmisi ke margin. "
                "Tanpa angka produksi/biaya dan valuasi terkini, belum ada dasar menyimpulkan harga saham akan naik.")
    if asset.sector_code == "A":
        return (f"Transmisi laba {asset.symbol} (sektor energi) didorong oleh realisasi harga acuan komoditas global, "
                "volume produksi, cash cost per ton, stripping ratio, dan royalti progresif.")
    if asset.sector_code == "B":
        return (f"Sensitivitas laba {asset.symbol} (barang baku/tambang) dipengaruhi siklus harga komoditas acuan, "
                "biaya energi smelter, kurs USD/IDR, serta margin pemrosesan hilirisasi.")
    if asset.sector_code == "C":
        return (f"Driver operasional {asset.symbol} (perindustrian) mencakup volume penjualan unit, "
                "siklus belanja modal sektor konstruksi/tambang, dan efisiensi manufaktur.")
    if asset.sector_code == "D":
        return (f"Ketahanan laba {asset.symbol} (konsumen primer) ditentukan oleh elastisitas harga, "
                "volatilitas biaya input bahan baku, serta kemampuan mempertahankan Operating Margin.")
    if asset.sector_code == "E":
        return (f"Dinamika penjualan {asset.symbol} (konsumen non-primer) didorong oleh Same-Store-Sales-Growth (SSSG), "
                "perputaran persediaan (inventory turnover), dan discretionary spending konsumen.")
    if asset.sector_code == "F":
        return (f"Kinerja operasional {asset.symbol} (kesehatan/farmasi) ditentukan oleh bauran produk etikal vs generik, "
                "ketergantungan impor bahan baku obat (BBO), dan stabilitas margin laba.")
    if asset.sector_code == "G":
        return (f"Transmisi BI-Rate ke {asset.symbol} (perbankan) mempengaruhi biaya dana (CoF) dan repricing kredit terhadap NIM. "
                "Dampaknya bergantung pada rasio CASA, pertumbuhan kredit, dan kualitas aset (NPL). "
                "Bandingkan NIM/NPL/CAR yang benar-benar dilaporkan; harga saham tidak otomatis mengikuti suku bunga.")
    if asset.sector_code == "H":
        return (f"Sensitivitas {asset.symbol} (properti) terhadap suku bunga berkaitan dengan realisasi marketing sales, "
                "permintaan KPR, serta Debt-to-Equity dan interest coverage emiten.")
    if asset.sector_code == "I":
        return (f"Kinerja fundamental {asset.symbol} (teknologi) dievaluasi dari monetisasi (take rate), "
                "perbaikan Contribution Margin, dan runway kas menuju profitabilitas.")
    if asset.sector_code == "J":
        return (f"Driver arus kas {asset.symbol} (infrastruktur/telco) didorong oleh ARPU, trafik data, "
                "rasio Capex-to-Revenue, serta yield arus kas bebas (FCF).")
    if asset.sector_code == "K":
        return (f"Efisiensi {asset.symbol} (transportasi & logistik) ditentukan oleh tingkat utilisasi armada (load factor), "
                "rasio biaya bahan bakar terhadap pendapatan, dan perputaran aset.")
    return f"Evaluasi laba {asset.symbol} membutuhkan realisasi permintaan, biaya input, dan margin sesuai model bisnis emiten."


def render_equity(packet, quant, asset, query: str, *, language: str = "ID", show_sources: bool = False, narrative: str = "") -> str:
    english = language == "EN"
    price = f"Rp{quant.price:,.0f}" if quant.price else "DATA GAP"
    status = quant.decision_status if quant.decision_status == "INSUFFICIENT_DATA_FOR_DECISION" else quant.decision
    text = [f"{asset.symbol} | IDX | {quant.timeframe} | {status} | {price}"]
    if quant.decision_status == "INSUFFICIENT_DATA_FOR_DECISION" and quant.price is None:
        ratios = packet.fundamentals.get("ratios", {})
        text.append(f"SOURCE GAP: {asset.name} dikenali sebagai {asset.id}, tetapi harga dan OHLCV berizin belum tersedia. Ini kegagalan ketersediaan data, bukan keputusan WAIT setelah evaluasi pasar.")
        if ratios:
            text.append(f"Laporan {packet.fundamentals['period']} ({packet.fundamentals['basis']}): " + "; ".join(f"{k} {v:,.3f}" for k, v in ratios.items()))
        else:
            text.append("Laporan keuangan bertanggal juga belum tersedia; rasio bank/valuasi tidak diestimasi.")
        if re.search(r"bi.?rate|suku bunga|nikel|nickel|emas|gold|prospek|sektor", query, re.I):
            text.append(equity_context(asset, query))
        text.append(EquityData.import_guidance(asset.symbol))
        text.append(f"Sumber identitas: {asset.source}; bukan sumber quote. Harga as-of: UNAVAILABLE.")
        return "\n\n".join(text)
    follow = bool(re.search(r"kenapa|why|rate|nikel|nickel|dampak|pengaruh|sederhana|simple", query.lower()))
    if narrative:
        text.append(narrative)
    elif not follow or re.search(r"kenapa|why", query.lower()):
        text.append(quant.decision_reason)
    if not narrative and re.search(r"bi.?rate|suku bunga|nikel|nickel|emas|gold|prospek|sektor", query, re.I):
        text.append(equity_context(asset, query))
    f = packet.fundamentals
    val_query = bool(re.search(r"valuasi|fundamental|layak\s+beli|layak\s+investasi|prospek", query.lower()))
    if val_query and f.get("ratios") and not narrative:
        r = f["ratios"]
        roe_val = r.get("ROE_pct")
        pbv_val = r.get("PBV")
        per_val = r.get("PER")
        car_val = r.get("CAR_pct")
        nim_val = r.get("NIM_pct")
        npl_val = r.get("NPL_gross_pct")
        opm_val = r.get("Operating_Margin_pct")
        npm_val = r.get("Net_Margin_pct")
        der_val = r.get("Debt_to_Equity")
        eval_lines = [
            f"Analisis Valuasi & Fundamental {asset.symbol}:",
            f"Berdasarkan laporan {f.get('period_type', '')} {f.get('period', '')} ({f.get('basis', 'konsolidasi')}), rasio yang dilaporkan:",
        ]
        if pbv_val is not None:
            eval_lines.append(f"  - Price to Book (PBV): {pbv_val:.2f}x")
        if per_val is not None:
            eval_lines.append(f"  - Price to Earnings (PER): {per_val:.2f}x")
        if roe_val is not None:
            eval_lines.append(f"  - ROE: {roe_val:.2f}%")
        if opm_val is not None:
            eval_lines.append(f"  - Operating Margin: {opm_val:.2f}%")
        if npm_val is not None:
            eval_lines.append(f"  - Net Margin: {npm_val:.2f}%")
        if der_val is not None:
            eval_lines.append(f"  - Debt to Equity (DER): {der_val:.2f}x")
        if car_val is not None:
            eval_lines.append(f"  - CAR: {car_val:.2f}%")
        if nim_val is not None:
            eval_lines.append(f"  - NIM: {nim_val:.2f}%")
        if npl_val is not None:
            eval_lines.append(f"  - NPL Gross: {npl_val:.2f}%")
        eval_lines.append(f"Hasil Quant: {quant.decision_reason}; tidak menyimpulkan premi valuasi tanpa pembanding terverifikasi.")
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


def _render_equity_followup(runner, session, asset, packet, quant, query: str) -> str:
    lower = query.lower()
    english = session.language == "EN" if session else False

    # Rate / macro impact follow-up
    if re.search(r"\b(?:suku bunga|bi.?rate|rate|dampak|pengaruh)\b", lower):
        return equity_context(asset, query)

    # Check for unverified/missing data gap
    if quant and quant.decision_status == "INSUFFICIENT_DATA_FOR_DECISION" and quant.price is None:
        return (
            f"SOURCE GAP: {asset.name} dikenali sebagai {asset.id}, tetapi harga dan OHLCV berizin belum tersedia. "
            f"Ini kegagalan ketersediaan data, bukan keputusan WAIT setelah evaluasi pasar."
        )

    # 1. Ratios and margins follow-up
    if re.search(r"\b(?:margin|operating margin|net margin|npm|opm|laba|profit|der|roe|pbv|per|eps|car|nim|npl|rasio|fundamental)\b", lower):
        r = packet.fundamentals.get("ratios", {}) if packet and packet.fundamentals else {}
        if r:
            lines = [f"Rasio Keuangan {asset.symbol} ({packet.fundamentals.get('period', '')} {packet.fundamentals.get('basis', 'konsolidasi')}):"]
            if "Operating_Margin_pct" in r:
                lines.append(f"  - Operating Margin: {r['Operating_Margin_pct']:.2f}%")
            if "Net_Margin_pct" in r:
                lines.append(f"  - Net Margin: {r['Net_Margin_pct']:.2f}%")
            if "ROE_pct" in r:
                lines.append(f"  - ROE: {r['ROE_pct']:.2f}%")
            if "PBV" in r:
                lines.append(f"  - PBV: {r['PBV']:.2f}x")
            if "PER" in r:
                lines.append(f"  - PER: {r['PER']:.2f}x")
            if "Debt_to_Equity" in r:
                lines.append(f"  - Debt to Equity (DER): {r['Debt_to_Equity']:.2f}x")
            if "NIM_pct" in r:
                lines.append(f"  - NIM: {r['NIM_pct']:.2f}%")
            if "CAR_pct" in r:
                lines.append(f"  - CAR: {r['CAR_pct']:.2f}%")
            if "NPL_gross_pct" in r:
                lines.append(f"  - NPL Gross: {r['NPL_gross_pct']:.2f}%")
            return "\n".join(lines)
        return f"SOURCE GAP: Laporan keuangan bertanggal untuk {asset.symbol} belum tersedia di data lokal; rasio margin belum dapat diverifikasi."

    # 2. Decision reason follow-up (kenapa / why / alasan)
    if re.search(r"\b(?:kenapa|mengapa|why|alasan|reason)\b", lower):
        status = quant.decision_status if quant.decision_status == "INSUFFICIENT_DATA_FOR_DECISION" else quant.decision
        resp = f"Alasan keputusan {status} pada {asset.symbol}: {quant.decision_reason}."
        if quant.bullish_validation:
            b = quant.bullish_validation
            resp += f"\nSkenario validasi yang ditunggu: Trigger {b.trigger_condition}, Entry {b.entry_zone}, Invalidation Rp{b.stop_price:,.0f}, Target Rp{b.tp1:,.0f} (RR {b.reward_risk_str})."
        return resp

    # 3. Sources follow-up
    if re.search(r"\b(?:sumber|source|sources|darimana|origin)\b", lower):
        srcs = packet.sources if packet and packet.sources else [asset.source]
        fresh = packet.data_freshness if packet else quant.data_freshness
        as_of = packet.price_as_of if packet and packet.price_as_of else "UNAVAILABLE"
        return f"Data {asset.symbol} bersumber dari: {', '.join(srcs)}. Freshness: {fresh}; Harga as-of: {as_of}."

    # 4. Local Qwen targeted response
    if runner and runner.local_llm and runner.local_llm.is_available() and packet:
        narrative = runner.local_llm.generate_narrative(packet, user_query=query, language="en" if english else "id")
        if narrative:
            return narrative

    # 5. Direct concise fallback
    return f"{asset.symbol} ({quant.timeframe}): {quant.decision_reason}. Freshness: {quant.data_freshness}."


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
    auto_fetch = bool(re.search(r"\b(?:analisa|analyze|prospek|valuasi|valuation|bandingkan|compare|cek|fetch|gimana|bagaimana|review|outlook)\b", req.raw_query, re.I)) or req.request_type == "COMPARE"
    data = EquityData(runner.root).load(asset.symbol, auto_fetch=auto_fetch)
    if req.request_type == "REPORT_WORD" and not data.get("quote") and not data.get("fundamentals"):
        return f"{asset.id}: belum ada observasi harga/laporan keuangan untuk report Word. " + EquityData.import_guidance(asset.symbol)
    if req.request_type in {"VISUALIZE", "REPORT_HTML"} and not data.get("candles"):
        return f"{asset.id} ({asset.name}): belum ada OHLCV untuk visualisasi native. " + EquityData.import_guidance(asset.symbol)
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
        candles = BacktestRunner.select_history(data.get("candles", []), req.raw_query, listing_date=asset.listing_date)
        if data.get("timeframe") and data["timeframe"] != req.timeframe:
            return f"{asset.id}: data tersedia {data['timeframe']}, bukan {req.timeframe}; impor timeframe yang sesuai."
        if len(candles) < 25:
            return f"{asset.id}: rentang '{req.raw_query}' menghasilkan {len(candles)} closed bar; minimal 25. " + EquityData.import_guidance(asset.symbol)
        if data.get("unresolved_corporate_actions") is not False:
            return f"{asset.id}: backtest diblokir; basis adjustment dan corporate actions belum dikonfirmasi sumber. Tidak menghitung return dari seri yang belum konsisten."
        bt_runner = BacktestRunner(
            initial_capital=100_000_000.0,
            asset_type="EQUITY_ID",
            buy_fee=float(data.get("fees", {}).get("buy", 0.0015)),
            sell_fee=float(data.get("fees", {}).get("sell", 0.0025)),
        )
        bt_res = bt_runner.run(asset.symbol, candles, timeframe=req.timeframe)
        return bt_res.summary_table()
    if req.request_type == "FOLLOW_UP" and session and session.last_research_packet and session.last_research_packet.asset == asset.symbol:
        return _render_equity_followup(runner, session, asset, session.last_research_packet, session.last_quant_result, req.raw_query)
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
            "   - Permintaan manufaktur China memengaruhi logam industri melalui baja nirkarat (stainless steel) dan rantai baterai EV; besaran terkini perlu data bertanggal.",
            "   - Data Purchasing Managers' Index (PMI) manufaktur China yang ekspansif meningkatkan proyeksi konsumsi bijih nikel dan feronikel.",
            "   - Ekspektasi ini ditransmisikan langsung ke harga acuan LME Nickel dan Shanghai Futures Exchange (SHFE).",
            "",
            f"2. Eksposur & Sensitivitas Emiten ({asset.symbol}):",
            f"   - {asset.symbol} memiliki portofolio komoditas tambang terintegrasi (bijih nikel, feronikel, bauksit, dan emas).",
            "   - Kenaikan harga nikel global berpotensi mengangkat Average Selling Price (ASP), namun transmisi ke laba bersih tetap dibatasi oleh royalti progresif, biaya energi smelter, dan nilai tukar USD/IDR.",
            "",
            f"3. Struktur Teknikal & Level Kuantitatif {asset.symbol} ({q.timeframe}):",
            f"   - Harga Terakhir: {'Rp' + format(q.price, ',.0f') if q.price is not None else 'DATA GAP'} | Status: {q.decision_status if q.price is None else q.decision} ({q.regime})",
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
    if req.request_type in ("VISUALIZE", "CHART"):
        from openbagus.reporting.terminal_chart import render_terminal_chart
        candles = data.get("candles", [])
        if candles:
            output = render_terminal_chart(asset.symbol, candles, timeframe=req.timeframe, currency="IDR", quant_result=q)
        else:
            output = f"{asset.id} ({asset.name}): belum ada OHLCV untuk visualisasi native. " + EquityData.import_guidance(asset.symbol)
        packet.narrative = output
    elif req.request_type == "REPORT_HTML":
        from openbagus.domains.equities.ownership import load_ownership
        from openbagus.reporting.visualizer import generate_html_report
        own = load_ownership(asset.symbol, runner.root)
        html_path = generate_html_report(asset.symbol, data.get("candles", []), q, packet, own, root=runner.root, timeframe=req.timeframe)
        output = f"Laporan visualisasi interaktif {asset.symbol} ({req.timeframe}) berhasil diekspor ke:\n{html_path}\n\n(Telah mencakup Interactive Candlestick, Radar Multi-Factor, Hierarchical Sunburst, Correlation Heatmap, dan Kepemilikan)"
        packet.narrative = output
    elif req.request_type == "REPORT_WORD":
        from openbagus.domains.equities.ownership import load_ownership
        from openbagus.reporting.word_report import generate_word_report
        own = load_ownership(asset.symbol, runner.root)
        docx_path = generate_word_report(asset.symbol, q, packet, own, root=runner.root, timeframe=req.timeframe)
        output = f"Laporan Microsoft Word (.docx) {asset.symbol} ({req.timeframe}) berhasil diekspor ke:\n{docx_path}\n\n(Memuat chart DrawingML native dengan embedded workbook Excel yang dapat diedit langsung di Word)"
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
        if q.price is not None:
            session.last_successful_asset = asset.symbol
        if session.is_persistence_enabled():
            session.save_persistent()
    return output
