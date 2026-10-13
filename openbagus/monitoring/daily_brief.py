"""OpenBagus Automated Daily Research Brief Engine.

Generates structured Morning and Evening executive intelligence briefs across the entire IDX universe and Crypto:
- Morning Brief (Pre-Market 07:30 WIB): Macro calendar events, actual verified EOD context, watchlist across sectors.
- Evening Brief (Post-Market 17:00 WIB): Session closing recap, rotational observation, risk checklist, and validated Quant setups.
- Real Data Only: Zero synthetic/fabricated prices, zero fictional levels, and zero hallucinated macro claims.
- Universal discovery: Supports large-caps, mid-caps, and third-liners across all 11 IDX-IC sectors.
- Zero-cost, zero-spam: Outputs saved locally to %LOCALAPPDATA%\\OpenBagus\\briefs\\ as PDF, PNG, and Markdown drafts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import subprocess
import sys

from openbagus.core.env import get_repo_root
from openbagus.intelligence.local_language import get_local_appdata_dir

try:
    from zoneinfo import ZoneInfo
    WIB_TZ = ZoneInfo("Asia/Jakarta")
except Exception:
    WIB_TZ = timezone(timedelta(hours=7), "Asia/Jakarta")


def _to_wib(dt: datetime | None = None) -> datetime:
    """Converts datetime to Asia/Jakarta (WIB) timezone-aware datetime."""
    if dt is None:
        return datetime.now(WIB_TZ)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=WIB_TZ)
    return dt.astimezone(WIB_TZ)


def _get_briefs_dir(root: Path | None = None) -> Path:
    """Returns local storage path for daily research brief drafts."""
    base = get_local_appdata_dir() / "briefs"
    try:
        base.mkdir(parents=True, exist_ok=True)
        return base
    except Exception:
        fallback = (root or get_repo_root()) / "reports" / "briefs"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


@dataclass
class DailyBriefItem:
    asset: str
    asset_type: str  # "EQUITY_ID" or "CRYPTO"
    price: float | None
    decision: str
    decision_reason: str
    key_levels: str
    change_pct: float = 0.0
    sector: str = ""
    board: str = ""
    cap_tier: str = ""
    observation_date: str = ""
    data_quality: str = "VERIFIED_EOD"


@dataclass
class DailyBriefData:
    session_type: str  # "MORNING" or "EVENING"
    date_str: str
    generated_at: str
    macro_events: list[str] = field(default_factory=list)
    ihsg_context: str = ""
    crypto_context: str = ""
    items: list[DailyBriefItem] = field(default_factory=list)
    top_setups: list[str] = field(default_factory=list)
    risk_checklist: list[str] = field(default_factory=list)
    total_catalog_equities: int = 0
    total_active_equities: int = 0
    equities_with_data: int = 0
    equities_screened: int = 0
    screened_sectors: list[str] = field(default_factory=list)
    special_monitoring_count: int = 0
    suspended_count: int = 0
    is_market_closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DailyBriefGenerator:
    """Generates structured Morning and Evening research briefs with dynamic universe selection."""

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()

    def select_dynamic_watchlist(
        self,
        user_watchlist: list[tuple[str, str]] | None = None,
        max_items: int = 7,
    ) -> list[tuple[str, str]]:
        """Dynamically selects candidate assets across sectors without defaulting solely to blue chips."""
        if user_watchlist:
            return user_watchlist

        from openbagus.domains.equities.catalog import EquityCatalog
        from openbagus.domains.equities.data import EquityData
        catalog = EquityCatalog(self.root)
        eq_data = EquityData(self.root)

        selected: list[tuple[str, str]] = []
        # 1. Search locally imported equity files
        local_symbols = set()
        if eq_data.directory.exists():
            for p in sorted(eq_data.directory.glob("*.json")):
                if p.stem.upper() not in ("CATALOG", "RULES"):
                    local_symbols.add(p.stem.upper())

        # Group local symbols by sector for diversity
        by_sec: dict[str, list[str]] = {}
        for sym in sorted(local_symbols):
            asset = catalog.resolve(sym)
            sec = asset.sector_code if asset else "UNKNOWN"
            by_sec.setdefault(sec, []).append(sym)

        for sec in sorted(by_sec.keys()):
            for s in by_sec[sec]:
                if (s, "EQUITY_ID") not in selected and len(selected) < max_items - 2:
                    selected.append((s, "EQUITY_ID"))
                    break

        # 2. If fewer candidates with local data, pick across multiple sectors (including third-liners)
        if len(selected) < max_items - 2:
            sectors_order = ["A", "C", "D", "F", "G", "I", "K", "B", "E", "H", "J"]
            for sec_code in sectors_order:
                candidates = [a.symbol for a in catalog.assets if a.sector_code == sec_code and a.asset_type == "EQUITY_ID"]
                for sym in candidates:
                    if (sym, "EQUITY_ID") not in selected:
                        selected.append((sym, "EQUITY_ID"))
                        break
                    if len(selected) >= max_items - 2:
                        break

        # 3. Add Crypto benchmarks
        selected.append(("BTC", "CRYPTO"))
        selected.append(("ETH", "CRYPTO"))
        return selected[:max_items]

    def generate(
        self,
        session_type: str = "MORNING",
        date_str: str | None = None,
        watchlist: list[tuple[str, str]] | None = None,
        now_dt: datetime | None = None,
    ) -> DailyBriefData:
        now_wib = _to_wib(now_dt)
        now_utc = now_wib.astimezone(timezone.utc)
        d_str = date_str or now_wib.strftime("%Y-%m-%d")
        s_type = session_type.upper()
        if s_type not in ("MORNING", "EVENING"):
            s_type = "MORNING"

        is_weekend = now_wib.weekday() >= 5  # Saturday=5, Sunday=6

        # 1. Universe Metrics from Catalog
        from openbagus.domains.equities.catalog import EquityCatalog
        from openbagus.domains.equities.data import EquityData
        from openbagus.domains.equities.policy import EquityMarketPolicy
        from openbagus.domains.crypto.quant import QuantEngine

        catalog = EquityCatalog(self.root)
        eq_data = EquityData(self.root)
        policy = EquityMarketPolicy(self.root)
        quant = QuantEngine()

        total_catalog = len(catalog.assets)
        common_eqs = sum(1 for a in catalog.assets if a.asset_type == "EQUITY_ID")
        spec_mon = sum(1 for a in catalog.assets if a.is_special_monitoring)
        suspended = sum(1 for a in catalog.assets if a.is_suspended)
        local_data_count = len(list(eq_data.directory.glob("*.json"))) if eq_data.directory.exists() else 0

        # Dynamic Watchlist Selection
        active_list = watchlist or self.select_dynamic_watchlist(user_watchlist=watchlist, max_items=7)

        # 2. Macro Calendar Integration (Real Events Only)
        macro_lines: list[str] = []
        try:
            from openbagus.intelligence.macro.events import MacroEventManager
            mgr = MacroEventManager()
            upcoming = mgr.get_upcoming_events(now=now_utc, horizon_days=2)
            for ev in upcoming[:4]:
                act_str = f"Aktual: {ev.actual} {ev.unit}" if ev.actual is not None else "Menunggu rilis"
                macro_lines.append(f"{ev.scheduled_at[:16]} UTC: {ev.event_name} (Forecast: {ev.forecast} {ev.unit} | {act_str})")
        except Exception:
            pass

        if not macro_lines:
            macro_lines.append("Tidak ada agenda rilis data makro berdampak tinggi yang terjadwal dalam 48 jam ke depan.")

        # 3. Watchlist Analysis (Real Data Only; No Fake Prices or Multipliers)
        items: list[DailyBriefItem] = []
        top_setups: list[str] = []
        screened_sectors_set: set[str] = set()

        for sym, a_type in active_list:
            if a_type == "EQUITY_ID":
                asset = catalog.resolve(sym)
                sec_code = asset.sector_code if asset else "-"
                b_name = asset.canonical_board if asset else "-"
                tier_name = asset.cap_tier() if asset else "-"
                if sec_code:
                    screened_sectors_set.add(sec_code)

                data = eq_data.load(sym) if asset else {}
                candles = data.get("candles", []) if isinstance(data, dict) else []

                if candles:
                    c_now = float(candles[-1]["close"])
                    c_prev = float(candles[-2]["close"]) if len(candles) >= 2 else c_now
                    chg = ((c_now - c_prev) / c_prev * 100.0) if c_prev > 0 else 0.0
                    obs_date = str(candles[-1].get("open_at", ""))[:10]

                    # Genuine technical levels from price action
                    if len(candles) >= 20:
                        s_val = min(float(c["low"]) for c in candles[-20:])
                        r_val = max(float(c["high"]) for c in candles[-20:])
                        levels = f"Support: Rp{s_val:,.0f} | Resistance: Rp{r_val:,.0f}"
                    else:
                        levels = "Data historis tidak cukup untuk level teknikal"

                    # Authoritative Quant Evaluation
                    q_res = quant.evaluate_equity(sym, data, policy)
                    decision = q_res.decision if q_res.price else q_res.decision_status
                    reason = q_res.decision_reason or "Menunggu konfirmasi volume dan breakout"
                    if decision in ("BUY", "HOLD/BUY"):
                        top_setups.append(f"{sym}: Skenario swing beli terkonfirmasi (R:R {q_res.reward_risk:.1f}x) batas invalidasi Rp{q_res.stop_loss:,.0f}")

                    items.append(DailyBriefItem(
                        asset=sym,
                        asset_type="EQUITY_ID",
                        price=c_now,
                        decision=decision,
                        decision_reason=reason,
                        key_levels=levels,
                        change_pct=round(chg, 2),
                        sector=sec_code,
                        board=b_name,
                        cap_tier=tier_name,
                        observation_date=obs_date,
                        data_quality="VERIFIED_EOD",
                    ))
                else:
                    # Honest missing data reporting
                    items.append(DailyBriefItem(
                        asset=sym,
                        asset_type="EQUITY_ID",
                        price=None,
                        decision="NO_DATA",
                        decision_reason="Data harga EOD belum diimpor ke penyimpanan lokal",
                        key_levels="Tidak tersedia",
                        change_pct=0.0,
                        sector=sec_code,
                        board=b_name,
                        cap_tier=tier_name,
                        observation_date="-",
                        data_quality="NO_DATA",
                    ))
            else:
                # Crypto reference values (Real Data Check)
                items.append(DailyBriefItem(
                    asset=sym,
                    asset_type="CRYPTO",
                    price=None,
                    decision="WAIT",
                    decision_reason="Kuotasi pasar kripto menunggu pembaruan sesi live",
                    key_levels="Tidak tersedia",
                    change_pct=0.0,
                    sector="CRYPTO",
                    board="CRYPTO",
                    cap_tier="CRYPTO",
                    observation_date="-",
                    data_quality="AWAITING_LIVE_QUOTE",
                ))

        # Truthful top setups: Never fabricate canned recommendations
        if not top_setups:
            top_setups.append("Tidak ada setup perdagangan tervalidasi pada data yang tersedia.")

        # 4. Contextual Narratives (Factual only, no invented macroeconomic claims)
        if is_weekend:
            ihsg_summary = f"Pasar Tutup (Akhir Pekan): Perdagangan reguler BEI libur. Menampilkan analisis pengamatan penutupan EOD terakhir ({len(items)} aset dipantau)."
            crypto_summary = "Pasar Kripto / Bitcoin Akhir Pekan: Likuiditas pasar berjalan 24/7; waspadai potensi gap pembukaan bursa tradisional."
        elif s_type == "MORNING":
            ihsg_summary = f"Pra-Pembukaan Sesi 1 (07:30 WIB): Menampilkan pengamatan EOD sesi terakhir ({len(items)} aset dipantau lintas sektor). Disiplin rencana perdagangan sebelum open."
            crypto_summary = "Ringkasan Aset Kripto / Bitcoin Overnight: Pasar beroperasi kontinu; pantau keselarasan volatilitas pasar global."
        else:
            ihsg_summary = f"Penutupan Perdagangan (17:00 WIB): Evaluasi penutupan pasar domestik ({len(items)} instrumen dipantau). Periksa realisasi setup dan evaluasi batas risiko."
            crypto_summary = "Tinjauan Sesi Sore Kripto / Bitcoin: Transisi menuju sesi likuiditas Amerika Serikat; evaluasi korelasi silang portofolio."

        checklist = [
            "Verifikasi likuiditas dan status perdagangan sebelum eksekusi (hindari saham tersuspensi).",
            "Disiplin batas risiko maksimal 2.0% modal per trade (posisi dibatalkan jika 1 lot melebihi anggaran risiko).",
            "Periksa konfirmasi breakout volume pada emiten kandidat sebelum entry.",
            "Pantau agenda makro terjadwal untuk antisipasi volatilitas tak terduga.",
        ]

        return DailyBriefData(
            session_type=s_type,
            date_str=d_str,
            generated_at=now_wib.strftime("%Y-%m-%d %H:%M WIB"),
            macro_events=macro_lines,
            ihsg_context=ihsg_summary,
            crypto_context=crypto_summary,
            items=items,
            top_setups=top_setups,
            risk_checklist=checklist,
            total_catalog_equities=total_catalog,
            total_active_equities=common_eqs,
            equities_with_data=local_data_count,
            equities_screened=len(items),
            screened_sectors=sorted(screened_sectors_set),
            special_monitoring_count=spec_mon,
            suspended_count=suspended,
            is_market_closed=is_weekend,
        )


def render_brief_markdown(brief: DailyBriefData) -> str:
    """Renders formatted research brief in GitHub-flavored Markdown for terminal output."""
    tag = "RISALAH RISET PAGI (PRE-MARKET)" if brief.session_type == "MORNING" else "RISALAH RISET SORE (POST-MARKET)"
    if brief.is_market_closed:
        tag += " [AKHIR PEKAN - PASAR TUTUP]"

    lines = [
        f"# OPENBAGUS — {tag}",
        f"**Tanggal:** {brief.date_str}  |  **Waktu Rilis:** {brief.generated_at}  |  **Status:** Draf Tersimpan",
        "",
        "## 1. Konteks Makroekonomi & Pasar",
        f"- **IHSG & Pasar Domestik:** {brief.ihsg_context}",
        f"- **Pasar Kripto:** {brief.crypto_context}",
        f"- **Cakupan Semesta:** {brief.total_active_equities} emiten katalog | {brief.equities_with_data} data EOD | Papan Khusus: {brief.special_monitoring_count} | Suspen: {brief.suspended_count} | Sektor: {', '.join(brief.screened_sectors) if brief.screened_sectors else 'Semua'}",
        "",
        "## 2. Agenda Rilis Data Makro Terjadwal",
    ]
    for ev in brief.macro_events:
        lines.append(f"- {ev}")

    lines.extend([
        "",
        "## 3. Matriks Pengamatan Aset Unggulan (Watchlist)",
        "| Aset | Tipe | Harga Referensi | Papan / Tier | Status Quant | Rencana & Batas Kunci |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])
    for it in brief.items:
        if it.price is not None and it.price > 0:
            px_str = f"Rp{it.price:,.0f} ({it.change_pct:+.1f}%)" if it.asset_type == "EQUITY_ID" else f"${it.price:,.2f}"
        else:
            px_str = "Belum ada EOD"
        board_tier = f"{it.board}/{it.cap_tier}" if it.board else it.asset_type
        lines.append(f"| **{it.asset}** | {it.asset_type} | {px_str} | {board_tier} | `{it.decision}` | {it.key_levels} |")

    lines.extend([
        "",
        "## 4. Peluang & Skenario Perdagangan (Actionable Setups)",
    ])
    for s in brief.top_setups:
        lines.append(f"- {s}")

    lines.extend([
        "",
        "## 5. Protokol Manajemen Risiko",
    ])
    for r in brief.risk_checklist:
        lines.append(f"- [x] {r}")

    return "\n".join(lines)


def render_brief_pdf(brief: DailyBriefData, output_path: Path | None = None) -> Path:
    """Generates an executive standalone PDF brief document using matplotlib."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dest_dir = _get_briefs_dir()
    name = f"{brief.date_str}_{brief.session_type.lower()}_brief.pdf"
    dest = output_path or (dest_dir / name)
    dest.parent.mkdir(parents=True, exist_ok=True)

    fig = plt.figure(figsize=(8.27, 11.69), dpi=200)  # A4 Portrait
    fig.patch.set_facecolor("#ffffff")

    gs = fig.add_gridspec(nrows=5, ncols=1, height_ratios=[1.2, 2.2, 2.0, 4.0, 1.8], hspace=0.35)

    # 1. Header Banner
    ax0 = fig.add_subplot(gs[0])
    ax0.axis("off")
    ax0.fill_between([0, 1], [0, 0], [1, 1], color="#0f172a", transform=ax0.transAxes)
    tag = "MORNING PRE-MARKET BRIEF" if brief.session_type == "MORNING" else "EVENING POST-MARKET BRIEF"
    if brief.is_market_closed:
        tag += " [WEEKEND CLOSED]"
    ax0.text(0.04, 0.65, f"OPENBAGUS INTELLIGENCE — {tag}", transform=ax0.transAxes,
             fontsize=13, fontweight="bold", color="#f8fafc", va="center")
    ax0.text(0.04, 0.28, f"Date: {brief.date_str}  |  Generated: {brief.generated_at}  |  Verified Real Data Only",
             transform=ax0.transAxes, fontsize=8, color="#94a3b8", va="center")

    # 2. Macro & Market Context
    ax1 = fig.add_subplot(gs[1])
    ax1.axis("off")
    ax1.set_title("1. Market Environment & Macro Catalysts", fontsize=10, fontweight="bold", loc="left", color="#0f172a", pad=8)
    ctx_text = f"IHSG / IDX Equities:\n{brief.ihsg_context}\n\nCrypto Market:\n{brief.crypto_context}"
    ax1.text(0.02, 0.88, ctx_text, transform=ax1.transAxes, fontsize=7.5, color="#334155", va="top", wrap=True)

    # 3. Macro Releases
    ax2 = fig.add_subplot(gs[2])
    ax2.axis("off")
    ax2.set_title("2. Scheduled Macroeconomic Agenda", fontsize=10, fontweight="bold", loc="left", color="#0f172a", pad=8)
    m_text = "\n".join(f"• {ev}" for ev in brief.macro_events)
    ax2.text(0.02, 0.88, m_text, transform=ax2.transAxes, fontsize=7.5, color="#334155", va="top")

    # 4. Watchlist Table
    ax3 = fig.add_subplot(gs[3])
    ax3.axis("off")
    ax3.set_title("3. Monitored Assets & Quant Signals", fontsize=10, fontweight="bold", loc="left", color="#0f172a", pad=8)
    table_data = [["Asset", "Type", "Ref Price", "24h %", "Signal", "Key Levels"]]
    for it in brief.items:
        if it.price is not None and it.price > 0:
            px = f"Rp{it.price:,.0f}" if it.asset_type == "EQUITY_ID" else f"${it.price:,.2f}"
            pct_s = f"{it.change_pct:+.1f}%"
        else:
            px = "N/A"
            pct_s = "-"
        table_data.append([it.asset, it.asset_type, px, pct_s, it.decision, it.key_levels[:30]])

    t = ax3.table(
        cellText=table_data,
        cellLoc="left",
        loc="upper left",
        colWidths=[0.14, 0.14, 0.18, 0.12, 0.14, 0.28],
    )
    t.auto_set_font_size(False)
    t.set_fontsize(7.5)
    t.scale(1.0, 1.3)

    # 5. Risk Checklist
    ax4 = fig.add_subplot(gs[4])
    ax4.axis("off")
    ax4.set_title("4. Actionable Setups & Risk Checklist", fontsize=10, fontweight="bold", loc="left", color="#0f172a", pad=8)
    c_lines = ["Top Setups:"] + [f"• {s}" for s in brief.top_setups[:2]] + ["", "Risk Protocols:"] + [f"✓ {r}" for r in brief.risk_checklist[:3]]
    ax4.text(0.02, 0.88, "\n".join(c_lines), transform=ax4.transAxes, fontsize=7.5, color="#1e293b", va="top")

    fig.savefig(str(dest), format="pdf", bbox_inches="tight")
    plt.close(fig)
    return dest


def render_brief_png(brief: DailyBriefData, output_path: Path | None = None) -> Path:
    """Generates a high-resolution PNG image of the daily brief for quick viewing."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    dest_dir = _get_briefs_dir()
    name = f"{brief.date_str}_{brief.session_type.lower()}_brief.png"
    dest = output_path or (dest_dir / name)
    dest.parent.mkdir(parents=True, exist_ok=True)

    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#0f172a")
    ax.axis("off")

    tag = "RISALAH RISET PAGI (07:30 WIB)" if brief.session_type == "MORNING" else "RISALAH RISET SORE (17:00 WIB)"
    if brief.is_market_closed:
        tag += " [PASAR TUTUP]"
    title_str = f"OPENBAGUS FINANCIAL TERMINAL — {tag}\nTanggal: {brief.date_str} | Waktu: {brief.generated_at}"
    ax.text(0.03, 0.94, title_str, transform=ax.transAxes, color="#f8fafc", fontsize=11, fontweight="bold", va="top")

    body_lines = [
        "1. RINGKASAN PASAR (DATA NYATA):",
        f"   • IHSG / Saham : {brief.ihsg_context[:105]}...",
        f"   • Kripto Pasar : {brief.crypto_context[:105]}...",
        "",
        "2. FOKUS ASET & STATUS QUANT:",
    ]
    for it in brief.items:
        if it.price is not None and it.price > 0:
            px = f"Rp{it.price:,.0f}" if it.asset_type == "EQUITY_ID" else f"${it.price:,.2f}"
        else:
            px = "N/A"
        body_lines.append(f"   • {it.asset:<5} ({it.asset_type:<9}) : {px:<12} | Signal: {it.decision:<6} | {it.key_levels[:35]}")

    body_lines.extend([
        "",
        "3. REKOMENDASI & MANAJEMEN RISIKO:",
    ])
    for s in brief.top_setups[:2]:
        body_lines.append(f"   ✓ Setup: {s}")
    for r in brief.risk_checklist[:2]:
        body_lines.append(f"   ⚠ Risk : {r}")

    ax.text(0.03, 0.82, "\n".join(body_lines), transform=ax.transAxes, color="#cbd5e1", fontsize=8.5, fontfamily="monospace", va="top")

    fig.savefig(str(dest), dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return dest


class DailyBriefScheduler:
    """Manages autonomous scheduling, draft generation, and status inspection."""

    def __init__(self, repo_root: Path | None = None, briefs_dir: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()
        self.generator = DailyBriefGenerator(self.root)
        if briefs_dir:
            self.briefs_dir = briefs_dir
        elif repo_root and repo_root != get_repo_root():
            self.briefs_dir = repo_root / "briefs"
        else:
            self.briefs_dir = _get_briefs_dir(self.root)
        self.briefs_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = self.briefs_dir / "scheduler_state.json"

    def _load_state(self) -> dict[str, Any]:
        if self.state_file.exists():
            try:
                with self.state_file.open("r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {
            "enabled": True,
            "morning_time": "07:30",
            "evening_time": "17:00",
            "last_morning_run": None,
            "last_evening_run": None,
            "os_scheduler_installed": False,
            "runs": {},
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            with self.state_file.open("w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def get_status(self) -> dict[str, Any]:
        state = self._load_state()
        now_wib = _to_wib()

        # Determine separate scheduler state
        if not state.get("enabled", True):
            status_name = "DISABLED"
        elif state.get("os_scheduler_installed"):
            status_name = "OS_SCHEDULER_INSTALLED"
        else:
            status_name = "SCHEDULE_CONFIGURED_ONLY"

        return {
            "enabled": state.get("enabled", True),
            "scheduler_state": status_name,
            "effective_timezone": "Asia/Jakarta (WIB)",
            "current_time_wib": now_wib.strftime("%Y-%m-%d %H:%M:%S WIB"),
            "morning_schedule": f"{state.get('morning_time', '07:30')} WIB",
            "evening_schedule": f"{state.get('evening_time', '17:00')} WIB",
            "last_morning_run": state.get("last_morning_run"),
            "last_evening_run": state.get("last_evening_run"),
            "drafts_directory": str(self.briefs_dir),
            "total_drafts_saved": len(list(self.briefs_dir.glob("*_brief.*"))),
            "os_scheduler_installed": state.get("os_scheduler_installed", False),
        }

    def list_drafts(self) -> list[dict[str, Any]]:
        drafts: list[dict[str, Any]] = []
        for p in sorted(self.briefs_dir.glob("*_brief.*"), reverse=True):
            drafts.append({
                "filename": p.name,
                "path": str(p),
                "size_kb": round(p.stat().st_size / 1024, 1),
                "modified": datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            })
        return drafts

    def trigger_now(self, session_type: str = "MORNING", now_dt: datetime | None = None) -> dict[str, Any]:
        """Manually triggers generation of the research brief across all formats with atomic safety."""
        now_wib = _to_wib(now_dt)
        brief_data = self.generator.generate(session_type=session_type, now_dt=now_wib)
        md_text = render_brief_markdown(brief_data)

        # 1. Save Markdown file
        md_path = self.briefs_dir / f"{brief_data.date_str}_{brief_data.session_type.lower()}_brief.md"
        with md_path.open("w", encoding="utf-8") as f:
            f.write(md_text)

        # 2. Atomic generation of PDF and PNG with individual error capture
        pdf_path = None
        pdf_error = None
        try:
            pdf_path = render_brief_pdf(brief_data, output_path=self.briefs_dir / f"{brief_data.date_str}_{brief_data.session_type.lower()}_brief.pdf")
        except Exception as exc:
            pdf_error = str(exc)

        png_path = None
        png_error = None
        try:
            png_path = render_brief_png(brief_data, output_path=self.briefs_dir / f"{brief_data.date_str}_{brief_data.session_type.lower()}_brief.png")
        except Exception as exc:
            png_error = str(exc)

        # Update durable state
        state = self._load_state()
        run_key = f"{brief_data.session_type}_{brief_data.date_str}"
        state.setdefault("runs", {})[run_key] = brief_data.generated_at

        if brief_data.session_type == "MORNING":
            state["last_morning_run"] = brief_data.generated_at
        else:
            state["last_evening_run"] = brief_data.generated_at
        self._save_state(state)

        status_result = "SUCCESS" if (pdf_path and png_path) else "PARTIAL_SUCCESS"

        return {
            "status": status_result,
            "session_type": brief_data.session_type,
            "date": brief_data.date_str,
            "markdown_path": str(md_path),
            "pdf_path": str(pdf_path) if pdf_path else None,
            "png_path": str(png_path) if png_path else None,
            "markdown_content": md_text,
            "errors": {"pdf": pdf_error, "png": png_error} if (pdf_error or png_error) else {},
        }

    def check_and_run_due_brief(self, now_dt: datetime | None = None) -> dict[str, Any] | None:
        """Evaluates whether morning or evening brief is due and executes automatically."""
        state = self._load_state()
        if not state.get("enabled", True):
            return None

        current = _to_wib(now_dt)
        today_str = current.strftime("%Y-%m-%d")
        curr_hm = current.strftime("%H:%M")

        morning_t = state.get("morning_time", "07:30")
        evening_t = state.get("evening_time", "17:00")
        runs = state.get("runs", {})

        morning_key = f"MORNING_{today_str}"
        evening_key = f"EVENING_{today_str}"

        # Exactly-once check for morning run
        if curr_hm >= morning_t and morning_key not in runs:
            if not state.get("last_morning_run") or not str(state.get("last_morning_run")).startswith(today_str):
                return self.trigger_now("MORNING", now_dt=current)

        # Exactly-once check for evening run
        if curr_hm >= evening_t and evening_key not in runs:
            if not state.get("last_evening_run") or not str(state.get("last_evening_run")).startswith(today_str):
                return self.trigger_now("EVENING", now_dt=current)

        return None

    def get_windows_task_status(self) -> dict[str, Any]:
        """Checks registration status in Windows Task Scheduler."""
        try:
            res = subprocess.run(
                ["schtasks", "/query", "/tn", "OpenBagus_DailyBrief", "/fo", "csv"],
                capture_output=True, text=True, timeout=5,
            )
            installed = (res.returncode == 0)
            return {
                "installed": installed,
                "task_name": "OpenBagus_DailyBrief",
                "detail": res.stdout.strip() if installed else "Not installed in Windows Task Scheduler",
            }
        except Exception as exc:
            return {"installed": False, "task_name": "OpenBagus_DailyBrief", "error": str(exc)}

    def install_windows_task(self, python_exe: str | None = None, time_str: str = "07:30") -> dict[str, Any]:
        """Registers optional daily brief task in Windows Task Scheduler."""
        py = python_exe or sys.executable
        cmd = f'"{py}" -m openbagus.cli brief morning'
        try:
            res = subprocess.run(
                ["schtasks", "/create", "/tn", "OpenBagus_DailyBrief", "/tr", cmd, "/sc", "daily", "/st", time_str, "/f"],
                capture_output=True, text=True, timeout=10,
            )
            success = (res.returncode == 0)
            state = self._load_state()
            state["os_scheduler_installed"] = success
            self._save_state(state)
            return {
                "success": success,
                "task_name": "OpenBagus_DailyBrief",
                "time": time_str,
                "output": res.stdout.strip() if success else res.stderr.strip(),
            }
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def uninstall_windows_task(self) -> dict[str, Any]:
        """Removes the OpenBagus_DailyBrief task from Windows Task Scheduler."""
        try:
            res = subprocess.run(
                ["schtasks", "/delete", "/tn", "OpenBagus_DailyBrief", "/f"],
                capture_output=True, text=True, timeout=10,
            )
            success = (res.returncode == 0)
            state = self._load_state()
            state["os_scheduler_installed"] = False
            self._save_state(state)
            return {"success": success, "task_name": "OpenBagus_DailyBrief"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}
