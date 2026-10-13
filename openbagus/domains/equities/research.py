"""IDX rendering and evidence selection using the existing research runner/packet."""

from datetime import datetime, timezone
import re

from openbagus.domains.equities.catalog import SECTORS
from openbagus.domains.equities.data import EquityData, fundamentals, timestamp
from openbagus.domains.equities.policy import EquityMarketPolicy


def equity_context(asset, query: str, packet: Any = None) -> str:
    lower = query.lower()
    r = packet.fundamentals.get("ratios", {}) if packet and getattr(packet, "fundamentals", None) else {}
    period_str = f" ({packet.fundamentals.get('period', '')})" if packet and getattr(packet, "fundamentals", None) and packet.fundamentals.get("period") else ""

    if any(word in lower for word in ("nikel", "nickel", "emas", "gold")) and asset.symbol == "ANTM":
        res = ("ANTM memiliki eksposur nikel dan emas. Kenaikan harga komoditas berpotensi membantu pendapatan, "
               "namun realisasi harga, volume produksi, biaya, royalti dan kurs menentukan transmisi ke margin. ")
        if r and "Operating_Margin_pct" in r:
            res += f"Data laporan keuangan{period_str} mencatat OPM {r['Operating_Margin_pct']:.2f}% dan Net Margin {r.get('Net_Margin_pct', 0):.2f}%."
        else:
            res += "Tanpa angka produksi/biaya dan valuasi terkini, belum ada dasar menyimpulkan harga saham akan naik."
        return res
    if asset.sector_code == "A":
        res = (f"Transmisi laba {asset.symbol} (sektor energi) didorong oleh realisasi harga acuan komoditas global, "
               "volume produksi, cash cost per ton, stripping ratio, dan royalti progresif.")
        if r and "Operating_Margin_pct" in r:
            res += f" Dilaporkan{period_str} Operating Margin {r['Operating_Margin_pct']:.2f}%."
        return res
    if asset.sector_code == "B":
        res = (f"Sensitivitas laba {asset.symbol} (barang baku/tambang) dipengaruhi siklus harga komoditas acuan, "
               "biaya energi smelter, kurs USD/IDR, serta margin pemrosesan hilirisasi.")
        if r and "Operating_Margin_pct" in r:
            res += f" Dilaporkan{period_str} Operating Margin {r['Operating_Margin_pct']:.2f}%."
        return res
    if asset.sector_code == "C":
        res = (f"Driver operasional {asset.symbol} (perindustrian) mencakup volume penjualan unit, "
               "siklus belanja modal sektor konstruksi/tambang, dan efisiensi manufaktur.")
        if r and "Operating_Margin_pct" in r:
            res += f" Tercatat{period_str} OPM {r['Operating_Margin_pct']:.2f}%."
        return res
    if asset.sector_code == "D":
        res = (f"Ketahanan laba {asset.symbol} (konsumen primer) ditentukan oleh elastisitas harga, "
               "volatilitas biaya input bahan baku, serta kemampuan mempertahankan Operating Margin.")
        if r and "Operating_Margin_pct" in r:
            res += f" Tercatat{period_str} Operating Margin {r['Operating_Margin_pct']:.2f}%."
        return res
    if asset.sector_code == "E":
        res = (f"Dinamika penjualan {asset.symbol} (konsumen non-primer) didorong oleh Same-Store-Sales-Growth (SSSG), "
               "perputaran persediaan (inventory turnover), dan discretionary spending konsumen.")
        if r and "Operating_Margin_pct" in r:
            res += f" Tercatat{period_str} OPM {r['Operating_Margin_pct']:.2f}%."
        return res
    if asset.sector_code == "F":
        res = (f"Kinerja operasional {asset.symbol} (kesehatan/farmasi) ditentukan oleh bauran produk etikal vs generik, "
               "ketergantungan impor bahan baku obat (BBO), dan stabilitas margin laba.")
        if r and "Operating_Margin_pct" in r:
            res += f" Tercatat{period_str} OPM {r['Operating_Margin_pct']:.2f}% dan NPM {r.get('Net_Margin_pct', 0):.2f}%."
        return res
    if asset.sector_code == "G":
        res = (f"Transmisi BI-Rate ke {asset.symbol} (perbankan) mempengaruhi biaya dana (CoF) dan repricing kredit terhadap NIM. ")
        if r and any(k in r for k in ("NIM_pct", "NPL_gross_pct", "CAR_pct")):
            details = []
            if "NIM_pct" in r:
                details.append(f"NIM {r['NIM_pct']:.2f}%")
            if "NPL_gross_pct" in r:
                details.append(f"NPL Gross {r['NPL_gross_pct']:.2f}%")
            if "CAR_pct" in r:
                details.append(f"CAR {r['CAR_pct']:.2f}%")
            res += f"Berdasarkan laporan{period_str}, tercatat {', '.join(details)}. "
        res += ("Dampaknya bergantung pada rasio CASA, pertumbuhan kredit, dan kualitas aset (NPL). "
                "Bandingkan NIM/NPL/CAR yang benar-benar dilaporkan; harga saham tidak otomatis mengikuti suku bunga.")
        return res
    if asset.sector_code == "H":
        res = (f"Sensitivitas {asset.symbol} (properti) terhadap suku bunga berkaitan dengan realisasi marketing sales, "
               "permintaan KPR, serta Debt-to-Equity dan interest coverage emiten.")
        if r and "Debt_to_Equity" in r:
            res += f" Tercatat{period_str} DER {r['Debt_to_Equity']:.2f}x."
        return res
    if asset.sector_code == "I":
        res = (f"Kinerja fundamental {asset.symbol} (teknologi) dievaluasi dari monetisasi (take rate), "
               "perbaikan Contribution Margin, dan runway kas menuju profitabilitas.")
        if r and "Debt_to_Equity" in r:
            res += f" Tercatat{period_str} DER {r['Debt_to_Equity']:.2f}x."
        return res
    if asset.sector_code == "J":
        res = (f"Driver arus kas {asset.symbol} (infrastruktur/telco) didorong oleh ARPU, trafik data, "
               "rasio Capex-to-Revenue, serta yield arus kas bebas (FCF).")
        if r and "Debt_to_Equity" in r:
            res += f" Tercatat{period_str} DER {r['Debt_to_Equity']:.2f}x."
        return res
    if asset.sector_code == "K":
        res = (f"Efisiensi {asset.symbol} (transportasi & logistik) ditentukan oleh tingkat utilisasi armada (load factor), "
               "rasio biaya bahan bakar terhadap pendapatan, dan perputaran aset.")
        if r and "Operating_Margin_pct" in r:
            res += f" Tercatat{period_str} OPM {r['Operating_Margin_pct']:.2f}%."
        return res
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
            text.append(equity_context(asset, query, packet=packet))
        text.append(EquityData.import_guidance(asset.symbol))
        text.append(f"Sumber identitas: {asset.source}; bukan sumber quote. Harga as-of: UNAVAILABLE.")
        return "\n\n".join(text)
    follow = bool(re.search(r"kenapa|why|rate|nikel|nickel|dampak|pengaruh|sederhana|simple", query.lower()))
    if narrative:
        text.append(narrative)
    elif not follow or re.search(r"kenapa|why", query.lower()):
        text.append(quant.decision_reason)
    if not narrative and re.search(r"bi.?rate|suku bunga|nikel|nickel|emas|gold|prospek|sektor", query, re.I):
        text.append(equity_context(asset, query, packet=packet))
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
        coverage_status = [
            ("Identitas", "TERVERIFIKASI" if packet.identity_verified else "GAP"),
            ("OHLCV", "TERSEDIA" if packet.market_ohlcv_available else "GAP"),
            ("EOD Quote", "TERSEDIA" if packet.recent_eod_available else "GAP"),
            ("Lapkeu/Rasio", "TERSEDIA" if packet.fundamentals_available else "GAP"),
            ("Aksi Korporasi", "KONSISTEN" if packet.corporate_actions_available else "GAP"),
            ("Statistik Sektor", "TERSEDIA" if packet.sector_statistics_available else "GAP"),
            ("Makro IDN", "TERSEDIA" if packet.macro_context_available else "GAP"),
        ]
        cov_str = " | ".join(f"{k}: [{v}]" for k, v in coverage_status)
        text.append(f"Data Coverage Matrix: {cov_str}")
        text.append("Evidence Stack: " + "; ".join(packet.sources or ["SOURCE GAP"]))
    return "\n\n".join(text)


def _render_equity_followup(runner, session, asset, packet, quant, query: str) -> str:
    lower = query.lower()
    english = session.language == "EN" if session else False

    # 1. Rate / macro transmission impact follow-up (answerable conceptually even if quote has source gap)
    if re.search(r"\b(?:suku bunga|bi.?rate|rate|dampak|pengaruh|makro|inflasi|jisdor)\b", lower):
        return equity_context(asset, query, packet=packet)

    # 2. Check for unverified/missing data gap
    if quant and quant.decision_status == "INSUFFICIENT_DATA_FOR_DECISION" and quant.price is None:
        return (
            f"SOURCE GAP: {asset.name} dikenali sebagai {asset.id}, tetapi harga dan OHLCV berizin belum tersedia. "
            f"Ini kegagalan ketersediaan data, bukan keputusan WAIT setelah evaluasi pasar."
        )

    # 3. Discrepancy & Numeric Challenge (tapi aku lihat labanya kok beda ya / bukannya tadi salah)
    if re.search(r"\b(?:beda|kok\s+beda|berbeda|selisih)\b", lower) and re.search(r"\b(?:laba(?:nya)?|profit(?:nya)?|angka(?:nya)?|margin(?:nya)?|omzet(?:nya)?|pendapatan(?:nya)?)\b", lower):
        r = packet.fundamentals.get("ratios", {}) if packet and packet.fundamentals else {}
        period = packet.fundamentals.get("period", "terakhir") if packet and packet.fundamentals else "terakhir"
        basis = packet.fundamentals.get("basis", "konsolidasian") if packet and packet.fundamentals else "konsolidasian"
        srcs = packet.sources if packet and packet.sources else [asset.source]
        lines = [
            f"Tinjauan perbedaan angka laba {asset.symbol}:",
            f"1. Basis Pelaporan: Data OpenBagus menggunakan laporan keuangan {period} ({basis}) bersumber dari {', '.join(srcs)}.",
            f"2. Kemungkinan Perbedaan: Periksa apakah angka pembanding yang Anda lihat adalah (a) laba bersih tahun berjalan vs laba yang dapat diatribusikan ke pemilik entitas induk, (b) angka interim belum diaudit (misal Q1/Q2/Q3) vs angka tahunan (FY), atau (c) laba operasional (EBIT) vs laba bersih (Net Profit).",
        ]
        if r and "Net_Margin_pct" in r:
            lines.append(f"3. Rasio Tercatat: Net Margin {r['Net_Margin_pct']:.2f}% dan Operating Margin {r.get('Operating_Margin_pct', 0):.2f}%.")
        return "\n".join(lines)

    # 4. Valuation focus follow-up (yang valuasinya aja dulu)
    if re.search(r"\b(?:valuasi(?:nya)?\s+aja|valuasi(?:nya)?\s+dulu|fokus\s+valuasi)\b", lower):
        r = packet.fundamentals.get("ratios", {}) if packet and packet.fundamentals else {}
        if r and any(k in r for k in ("PER", "PBV")):
            lines = [f"Valuasi {asset.symbol} ({packet.fundamentals.get('period', '')}):"]
            if "PER" in r:
                lines.append(f"  - Price to Earnings (PER): {r['PER']:.2f}x")
            if "PBV" in r:
                lines.append(f"  - Price to Book Value (PBV): {r['PBV']:.2f}x")
            if "ROE_pct" in r:
                lines.append(f"  - Return on Equity (ROE): {r['ROE_pct']:.2f}%")
            if "FCF_Yield_pct" in r:
                lines.append(f"  - FCF Yield: {r['FCF_Yield_pct']:.2f}%")
            return "\n".join(lines)

    # 4b. Free cash flow follow-up (fcf / arus kas bebas)
    if re.search(r"\b(?:fcf|free\s*cash\s*flow|arus\s+kas\s+bebas)\b", lower):
        f = packet.fundamentals if packet and packet.fundamentals else {}
        is_bank = (
            asset.sector_code == "G"
            or f.get("sector", "").upper() in {"FINANCIALS", "KEUANGAN", "BANK"}
            or any(k in f.get("reported_ratios_pct", {}) for k in ("NIM", "CAR", "NPL_gross", "CASA", "LDR"))
        )
        if is_bank:
            return (
                f"Analisis Free Cash Flow {asset.symbol}: NOT_MEANINGFUL (Sektor Perbankan/Keuangan).\n"
                "Arus kas operasional bank didominasi oleh penghimpunan dana pihak ketiga (DPK) dan penyaluran kredit, "
                "sehingga konsep FCF industri (OCF - Capex) tidak relevan untuk mengukur kesehatan bank.\n"
                f"Metrik kesehatan alternatif: NIM {f.get('reported_ratios_pct', {}).get('NIM', '-')}% | CAR {f.get('reported_ratios_pct', {}).get('CAR', '-')}% | NPL Gross {f.get('reported_ratios_pct', {}).get('NPL_gross', '-')}%."
            )
        v = f.get("values", {})
        unit = f.get("unit", "million_IDR")
        ocf = v.get("operating_cash_flow")
        capex = v.get("capital_expenditure")
        if ocf is not None and capex is not None:
            fcf_val = ocf - abs(capex)
            lines = [
                f"Arus Kas Bebas (FCF) {asset.symbol} ({f.get('period', '')}, satuan {unit}):",
                f"  - Arus Kas Operasi (OCF): {ocf:,.0f}",
                f"  - Belanja Modal (Capex): {abs(capex):,.0f}",
                f"  - Free Cash Flow (FCF = OCF - Capex): {fcf_val:,.0f}",
            ]
            if ocf > 0:
                lines.append(f"  - Intensitas Capex (Capex / OCF): {(abs(capex) / ocf * 100):.1f}%")
            return "\n".join(lines)
        return f"Data arus kas atau belanja modal untuk {asset.symbol} belum lengkap pada laporan yang tersimpan."

    # 5. Long-term horizon follow-up (terus kalau buat jangka panjang?)
    if re.search(r"\b(?:jangka\s+panjang|long\s*term|simpan\s+lama|investasi\s+panjang)\b", lower):
        r = packet.fundamentals.get("ratios", {}) if packet and packet.fundamentals else {}
        lines = [f"Perspektif Jangka Panjang {asset.symbol}:"]
        if r:
            if "ROE_pct" in r:
                lines.append(f"  - Profitabilitas Modal (ROE): {r['ROE_pct']:.2f}% (kemampuan menghasilkan return)")
            if "Debt_to_Equity" in r:
                lines.append(f"  - Rasio Utang (DER): {r['Debt_to_Equity']:.2f}x (ketahanan solvabilitas neraca)")
            if "Operating_Margin_pct" in r:
                lines.append(f"  - Operating Margin: {r['Operating_Margin_pct']:.2f}% (daya saing operasional)")
        lines.append(f"Keputusan quant jangka pendek/H1 ({quant.decision}) tidak otomatis mencerminkan prospek fundamental tahunan; periksa konsistensi arus kas dan pembagian dividen historis.")
        return "\n".join(lines)

    # 6. Decision reason / causal reasoning follow-up (kenapa / why / alasan)
    if re.search(r"\b(?:kenapa|mengapa|why|alasan|reason)\b", lower):
        status = quant.decision_status if quant.decision_status == "INSUFFICIENT_DATA_FOR_DECISION" else quant.decision
        resp = f"Alasan keputusan {status} pada {asset.symbol}: {quant.decision_reason}."
        if quant.bullish_validation:
            b = quant.bullish_validation
            resp += f"\nSkenario validasi yang ditunggu: Trigger {b.trigger_condition}, Entry {b.entry_zone}, Invalidation Rp{b.stop_price:,.0f}, Target Rp{b.tp1:,.0f} (RR {b.reward_risk_str})."
        return resp

    # 7. Financial ratios and margins follow-up
    if re.search(r"\b(?:margin(?:nya)?|operating margin|net margin|npm|opm|laba(?:nya)?|profit(?:nya)?|der|roe|pbv|per|eps|car|nim|npl|rasio(?:nya)?|fundamental|valuasi(?:nya)?)\b", lower):
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

    # 8. Sources follow-up
    if re.search(r"\b(?:sumber|source|sources|darimana|origin)\b", lower):
        srcs = packet.sources if packet and packet.sources else [asset.source]
        fresh = packet.data_freshness if packet else quant.data_freshness
        as_of = packet.price_as_of if packet and packet.price_as_of else "UNAVAILABLE"
        return f"Data {asset.symbol} bersumber dari: {', '.join(srcs)}. Freshness: {fresh}; Harga as-of: {as_of}."

    # 9. Local Qwen targeted response for conversational/complex queries
    if runner and runner.local_llm and runner.local_llm.is_available() and packet:
        fact_lines = [
            f"Asset: {asset.symbol} ({asset.name})",
            f"Quant Decision: {quant.decision} ({quant.decision_reason})",
            f"Timeframe: {getattr(quant, 'timeframe', 'D1')}, Freshness: {getattr(quant, 'data_freshness', 'RECENT')}",
            f"Price: {getattr(quant, 'price', 'N/A')}",
            f"Fundamentals: {packet.fundamentals.get('ratios', {}) if packet.fundamentals else {}}",
            f"Sources: {', '.join(packet.sources or [asset.source])}",
        ]
        conv_resp = runner.local_llm.answer_conversation(query, "\n".join(fact_lines), language="en" if english else "id", session=session)
        if conv_resp:
            return conv_resp
        narrative = runner.local_llm.generate_narrative(packet, user_query=query, language="en" if english else "id")
        if narrative:
            return narrative

    # 10. Direct concise fallback
    return f"{asset.symbol} ({quant.timeframe}): {quant.decision_reason}. Freshness: {quant.data_freshness}."


def run_equity_research(runner, req, session=None) -> str:
    from openbagus.domains.crypto.research import ResearchPacket

    if req.request_type == "EQUITY_DISCOVERY":
        from openbagus.domains.equities.catalog import EquityCatalog
        catalog = getattr(getattr(runner, "assets", None), "equities", None) or EquityCatalog(runner.root)
        from openbagus.reporting.terminal_table import render_stocks_table
        focus = getattr(req, "focus", "")
        if focus == "coverage":
            stats = catalog.get_universe_stats()
            lines = [
                "=== Cakupan Semesta Pasar IDX (Universe Coverage & Reconciliation) ===",
                f"Total Seluruh Instrumen : {stats['total_instruments']}",
                f"  - Saham Ekuitas Biasa : {stats['common_equities']}",
                f"  - Indeks & ETF Resmi  : {stats['indices']}",
                "",
                "Distribusi Papan Pencatatan Resmi:",
            ]
            for b_name, b_count in sorted(stats['boards'].items(), key=lambda x: -x[1]):
                lines.append(f"  - {b_name:<20}: {b_count:>3} emiten")
            lines.append("")
            lines.append("Distribusi 11 Sektor IDX-IC:")
            for s_name, s_count in sorted(stats['sectors'].items()):
                lines.append(f"  - {s_name:<30}: {s_count:>3} emiten")
            lines.append("")
            lines.append(f"Status Pencatatan: {stats['statuses']}")
            lines.append("Integritas Data  : 100% instrumen terpetakan tanpa tebakan papan semu.")
            return "\n".join(lines)
        elif focus == "third_liner":
            items = catalog.search_third_liners(limit=25)
            table = render_stocks_table(items, title="Eksplorasi Saham Lapis Tiga (Third-Liner / Small-Micro Cap)", limit=25, total_count=len(catalog.search_third_liners(limit=1000)))
            note = "\nCatatan Integritas: Kategori lapis tiga didasarkan pada kapitalisasi pasar (Small/Micro Cap) dan papan pencatatan (Pengembangan/Akselerasi) tanpa label manipulatif buatan."
            return f"{table}{note}\n\nGunakan '/stocks info <ticker>' untuk rincian emiten atau '/stocks third-liner [page]' untuk navigasi."
        elif focus == "small_cap":
            items = catalog.by_tier("SMALL_CAP", limit=25)
            table = render_stocks_table(items, title="Saham Small-Cap IDX (Rp 500M - Rp 5T)", limit=25, total_count=len(catalog.by_tier("SMALL_CAP", limit=1000)))
            return f"{table}\n\nGunakan '/stocks smallcap [page]' untuk melihat halaman lainnya."
        elif focus == "micro_cap":
            items = catalog.by_tier("MICRO_CAP", limit=25)
            table = render_stocks_table(items, title="Saham Micro-Cap IDX (< Rp 500M)", limit=25, total_count=len(catalog.by_tier("MICRO_CAP", limit=1000)))
            return f"{table}\n\nGunakan '/stocks microcap [page]' untuk melihat halaman lainnya."
        elif focus == "special_monitoring":
            items = catalog.search_special_monitoring(limit=25)
            table = render_stocks_table(items, title="Daftar Saham Papan Pemantauan Khusus (Special Monitoring)", limit=25, total_count=len(catalog.search_special_monitoring(limit=1000)))
            return f"{table}\n\nCatatan: Saham di papan pemantauan khusus memiliki kriteria likuiditas/kondisi keuangan khusus oleh BEI."
        elif focus == "acceleration":
            items = catalog.by_board("ACCELERATION", limit=25)
            table = render_stocks_table(items, title="Daftar Saham Papan Akselerasi (Acceleration Board)", limit=25, total_count=len(catalog.by_board("ACCELERATION", limit=1000)))
            return f"{table}\n\nGunakan '/stocks board akselerasi [page]' untuk navigasi penuh."
        elif focus == "development":
            items = catalog.by_board("DEVELOPMENT", limit=25)
            table = render_stocks_table(items, title="Daftar Saham Papan Pengembangan (Development Board)", limit=25, total_count=len(catalog.by_board("DEVELOPMENT", limit=1000)))
            return f"{table}\n\nGunakan '/stocks board pengembangan [page]' untuk navigasi penuh."
        elif focus == "main_board":
            items = catalog.by_board("MAIN", limit=25)
            table = render_stocks_table(items, title="Daftar Saham Papan Utama (Main Board)", limit=25, total_count=len(catalog.by_board("MAIN", limit=1000)))
            return f"{table}\n\nGunakan '/stocks board utama [page]' untuk navigasi penuh."
        elif focus == "suspended":
            items = catalog.search_suspended(limit=25)
            table = render_stocks_table(items, title="Daftar Saham Dalam Status Suspensi", limit=25, total_count=len(catalog.search_suspended(limit=1000)))
            return f"{table}\n\nCatatan: Status suspensi aktif tercatat resmi di bursa."
        else:
            items = [a for a in catalog.assets if a.asset_type == "EQUITY_ID"][:25]
            table = render_stocks_table(items, title="Semesta Seluruh Saham IDX", limit=25, total_count=len(catalog.assets))
            return f"{table}\n\nGunakan '/stocks all [page]' untuk navigasi."

    if req.request_type == "EQUITY_SECTOR":
        from openbagus.domains.equities.catalog import EquityCatalog
        catalog = getattr(getattr(runner, "assets", None), "equities", None) or EquityCatalog(runner.root)
        cat = req.category or ""
        if cat in SECTORS:
            names = SECTORS[cat]
            members = catalog.by_sector(cat, limit=25)
            total_sec = len(catalog.by_sector(cat, limit=1000))
            from openbagus.reporting.terminal_table import render_stocks_table
            table = render_stocks_table(members, title=f"Emiten Sektor {cat} - {names[0]} ({names[1]})", limit=25, total_count=total_sec)
            return f"{table}\n\nGunakan '/stocks sector {cat} [page]' untuk navigasi atau '/stocks info <ticker>' untuk detail emiten."
        else:
            matched = catalog.by_sector(cat, limit=25) if cat else []
            if matched:
                from openbagus.reporting.terminal_table import render_stocks_table
                table = render_stocks_table(matched, title=f"Emiten Sektor '{cat}'", limit=25, total_count=len(catalog.by_sector(cat, limit=1000)))
                return f"{table}\n\nGunakan '/stocks sector {cat} [page]' untuk navigasi."
            lines = ["IDX-IC 11 Sektor Resmi:"]
            for code, names in sorted(SECTORS.items()):
                lines.append(f"  {code}. {names[0]} / {names[1]}")
            return "\n".join(lines)
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
        if getattr(req, "focus", "") == "chart" or "grafik" in req.raw_query.lower() or "chart" in req.raw_query.lower():
            if not own.top_shareholders or own.public_shareholders_pct <= 0:
                return f"{asset.symbol}: Rincian pemegang saham tidak memiliki klasifikasi atau pembagi yang valid; tidak membuat grafik kepemilikan buatan."
            try:
                from openbagus.reporting.static_charts import render_ownership_pie_png
                png_path = render_ownership_pie_png(own, asset.symbol)
                return f"Visualisasi komposisi kepemilikan saham {own.issuer} ({asset.symbol}) berhasil diekspor ke PNG:\n{png_path}\n(Memuat porsi pemegang saham utama dan free float publik terverifikasi)"
            except Exception as err:
                return f"{asset.symbol}: Gagal membuat grafik kepemilikan: {err}"
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
        from openbagus.domains.quant.strategies import (
            EMATrendPullbackStrategy,
            DonchianBreakoutStrategy,
            RSIReversionStrategy,
            MultiTimeframeStrategy,
        )
        from openbagus.domains.quant.visualization import (
            render_ascii_equity_curve,
            render_ascii_drawdown_chart,
        )
        from openbagus.domains.quant.optimization import ParameterSweepRunner

        candles = BacktestRunner.select_history(data.get("candles", []), req.raw_query, listing_date=asset.listing_date)
        if data.get("timeframe") and data["timeframe"] != req.timeframe:
            return f"{asset.id}: data tersedia {data['timeframe']}, bukan {req.timeframe}; impor timeframe yang sesuai."
        if len(candles) < 25:
            return f"{asset.id}: rentang '{req.raw_query}' menghasilkan {len(candles)} closed bar; minimal 25. " + EquityData.import_guidance(asset.symbol)
        if data.get("unresolved_corporate_actions") is not False:
            return f"{asset.id}: backtest diblokir; basis adjustment dan corporate actions belum dikonfirmasi sumber. Tidak menghitung return dari seri yang belum konsisten."

        strategy_map = {
            "donchian": DonchianBreakoutStrategy,
            "breakout": DonchianBreakoutStrategy,
            "rsi": RSIReversionStrategy,
            "reversion": RSIReversionStrategy,
            "mtf": MultiTimeframeStrategy,
            "multitimeframe": MultiTimeframeStrategy,
            "ema": EMATrendPullbackStrategy,
        }
        chosen_strat_cls = strategy_map.get(getattr(req, "topic", "ema") or "ema", EMATrendPullbackStrategy)
        if getattr(req, "focus", "") == "mtf":
            chosen_strat_cls = MultiTimeframeStrategy

        buy_fee = float(data.get("fees", {}).get("buy", 0.0015))
        sell_fee = float(data.get("fees", {}).get("sell", 0.0025))

        # Parameter Sensitivity Sweep / Optimization
        if getattr(req, "focus", "") == "sweep" or "sweep" in req.raw_query.lower() or "optimasi" in req.raw_query.lower():
            param_grids = {
                EMATrendPullbackStrategy: {
                    "fast_ema": [5, 8, 13],
                    "slow_ema": [21, 34],
                    "stop_atr_mult": [1.5, 2.0],
                    "tp_atr_mult": [2.5, 3.0],
                },
                DonchianBreakoutStrategy: {
                    "lookback": [15, 20, 30],
                    "stop_atr_mult": [1.5, 2.0],
                    "tp_atr_mult": [2.5, 3.5],
                },
                RSIReversionStrategy: {
                    "rsi_period": [10, 14],
                    "oversold": [25.0, 30.0],
                    "stop_atr_mult": [1.5, 2.0],
                    "tp_atr_mult": [2.0, 2.5],
                },
                MultiTimeframeStrategy: {
                    "htf_ratio": [4, 6],
                    "htf_ema_fast": [10, 20],
                    "htf_ema_slow": [30, 50],
                    "ltf_ema_fast": [8],
                    "ltf_ema_slow": [21],
                },
            }
            grid = param_grids.get(chosen_strat_cls, param_grids[EMATrendPullbackStrategy])
            sweep_runner = ParameterSweepRunner()
            sweep_res = sweep_runner.run_sweep(
                symbol=asset.symbol,
                candles=candles,
                strategy_cls=chosen_strat_cls,
                param_grid=grid,
                initial_capital=100_000_000.0,
                asset_type="EQUITY_ID",
                timeframe=req.timeframe,
                buy_fee=buy_fee,
                sell_fee=sell_fee,
                lot_size=100,
            )
            if session and sweep_res.best_backtest:
                session.last_backtest_result = sweep_res.best_backtest
                session.last_backtest_asset = asset.symbol
            out_lines = [sweep_res.summary_table(), ""]
            if sweep_res.best_backtest and sweep_res.best_backtest.equity_curve:
                out_lines.append(render_ascii_equity_curve(sweep_res.best_backtest.equity_curve, title=f"Best Strategy Equity: {asset.symbol}", currency="IDR"))
            return "\n".join(out_lines)

        # Standard or MTF execution
        strategy_obj = chosen_strat_cls()
        bt_runner = BacktestRunner(
            initial_capital=100_000_000.0,
            asset_type="EQUITY_ID",
            buy_fee=buy_fee,
            sell_fee=sell_fee,
            lot_size=100,
            strategy=strategy_obj,
        )
        bt_res = bt_runner.run(asset.symbol, candles, timeframe=req.timeframe)
        if session:
            session.last_backtest_result = bt_res
            session.last_backtest_asset = asset.symbol

        if getattr(req, "focus", "") == "equity_curve" or "equity curve" in req.raw_query.lower() or "kurva ekuitas" in req.raw_query.lower():
            from openbagus.reporting.static_charts import render_equity_curve_png
            png_path = render_equity_curve_png(bt_res, asset.symbol)
            ascii_curve = render_ascii_equity_curve(bt_res.equity_curve, title=f"Equity Curve: {asset.symbol}", currency="IDR")
            ascii_dd = render_ascii_drawdown_chart(bt_res.drawdown_curve)
            return (
                f"{bt_res.summary_table()}\n\n"
                f"{ascii_curve}\n\n"
                f"{ascii_dd}\n\n"
                f"Grafik Equity Curve PNG diekspor ke:\n{png_path}"
            )

        ascii_curve = render_ascii_equity_curve(bt_res.equity_curve, title=f"Equity Curve: {asset.symbol}", currency="IDR")
        return f"{bt_res.summary_table()}\n\n{ascii_curve}"
    if req.request_type == "FOLLOW_UP" and session and session.last_research_packet and session.last_research_packet.asset == asset.symbol:
        return _render_equity_followup(runner, session, asset, session.last_research_packet, session.last_quant_result, req.raw_query)
    if req.request_type in ("VISUALIZE", "CHART", "REPORT_HTML", "REPORT_WORD", "REPORT_PDF", "EXPORT_PNG") and session and session.last_research_packet and session.last_research_packet.asset == asset.symbol and session.last_quant_result:
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
            price_as_of=data.get("quote", {}).get("as_of", ""), ownership=own,
            identity_verified=bool(asset.symbol and asset.source and not data.get("gaps")),
            market_ohlcv_available=bool(data.get("candles")),
            recent_eod_available=bool(data.get("candles") or data.get("quote", {}).get("price")),
            fundamentals_available=bool(financials.get("ratios")),
            corporate_actions_available=bool(data.get("unresolved_corporate_actions") is False),
            sector_statistics_available=bool(data.get("sector_stats")),
            macro_context_available=bool(data.get("macro") or events))
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
        candles = data.get("candles", [])
        if not candles:
            output = f"{asset.id} ({asset.name}): belum ada OHLCV untuk visualisasi native. " + EquityData.import_guidance(asset.symbol)
        elif getattr(req, "focus", "") == "terminal":
            from openbagus.reporting.terminal_chart import render_terminal_chart
            output = render_terminal_chart(asset.symbol, candles, timeframe=req.timeframe, currency="IDR", quant_result=q)
        else:
            from openbagus.reporting.interactive_chart import launch_interactive_chart
            res = launch_interactive_chart(
                symbol=asset.symbol,
                candles=candles,
                timeframe=req.timeframe,
                quant_result=q,
                root=runner.root,
                blocking=False,
            )
            output = res["message"]
        packet.narrative = output
    elif req.request_type == "EXPORT_PNG":
        candles = data.get("candles", [])
        if not candles:
            output = f"{asset.id}: Tidak ada data candle OHLCV untuk ekspor PNG."
        else:
            from openbagus.reporting.static_charts import render_candlestick_png
            png_path = render_candlestick_png(
                symbol=asset.symbol,
                candles=candles,
                timeframe=req.timeframe,
                quant_result=q,
            )
            output = f"Grafik Candlestick publikasi {asset.symbol} ({req.timeframe}) berhasil diekspor ke PNG:\n{png_path}"
        packet.narrative = output
    elif req.request_type == "REPORT_PDF":
        from openbagus.domains.equities.ownership import load_ownership
        from openbagus.reporting.pdf import generate_pdf_report
        own = load_ownership(asset.symbol, runner.root)
        pdf_path = generate_pdf_report(asset.symbol, q, packet, own, root=runner.root, timeframe=req.timeframe)
        output = f"Laporan PDF profesional {asset.symbol} ({req.timeframe}) berhasil diekspor ke:\n{pdf_path}\n\n(Telah dilengkapi chart statis beresolusi tinggi, tabel metrik, dan disclaimer kepatuhan)"
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
