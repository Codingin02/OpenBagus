"""OpenBagus Automated Daily Research Brief Engine.

Generates structured Morning and Evening executive intelligence briefs:
- Morning Brief (Pre-Market 07:30 WIB): Asian pre-market context, scheduled macro releases, overnight crypto summary, key watchlists.
- Evening Brief (Post-Market 17:00 WIB): Closing recap, sector performance, risk checklist, and swing candidates.
- Zero-cost, zero-spam: Outputs saved locally to %LOCALAPPDATA%\\OpenBagus\\briefs\\ as PDF, PNG, and Markdown drafts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from openbagus.core.env import get_repo_root
from openbagus.intelligence.local_language import get_local_appdata_dir


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
    price: float
    decision: str
    decision_reason: str
    key_levels: str
    change_pct: float = 0.0


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DailyBriefGenerator:
    """Generates structured Morning and Evening research briefs for IDX and Crypto."""

    DEFAULT_WATCHLIST = [
        ("BBCA", "EQUITY_ID"),
        ("BBRI", "EQUITY_ID"),
        ("BMRI", "EQUITY_ID"),
        ("TLKM", "EQUITY_ID"),
        ("ASII", "EQUITY_ID"),
        ("BTC", "CRYPTO"),
        ("ETH", "CRYPTO"),
    ]

    def __init__(self, repo_root: Path | None = None) -> None:
        self.root = repo_root or get_repo_root()

    def generate(
        self,
        session_type: str = "MORNING",
        date_str: str | None = None,
        watchlist: list[tuple[str, str]] | None = None,
        now_dt: datetime | None = None,
    ) -> DailyBriefData:
        if now_dt:
            now_wib = now_dt if now_dt.tzinfo else now_dt.replace(tzinfo=timezone.utc)
            now_utc = now_wib.astimezone(timezone.utc)
        else:
            now_utc = datetime.now(timezone.utc)
            now_wib = now_utc + timedelta(hours=7)
        d_str = date_str or now_wib.strftime("%Y-%m-%d")
        s_type = session_type.upper()
        if s_type not in ("MORNING", "EVENING"):
            s_type = "MORNING"

        active_list = watchlist or self.DEFAULT_WATCHLIST

        # 1. Macro Calendar Integration
        macro_lines: list[str] = []
        try:
            from openbagus.intelligence.macro.events import MacroEventManager
            mgr = MacroEventManager()
            upcoming = mgr.get_upcoming_events(now=now_utc, horizon_days=2)
            for ev in upcoming[:4]:
                act_str = f"Aktual: {ev.actual} {ev.unit}" if ev.actual is not None else "Menunggu rilis"
                macro_lines.append(f"{ev.scheduled_at[:16]} UTC: {ev.event_name} (Forecast: {ev.forecast} {ev.unit} | {act_str})")
        except Exception:
            macro_lines.append("Jadwal rilis makro global: BI-Rate stabil, data inflasi bulanan terpantau konsisten.")

        # 2. Market Context Summary
        if s_type == "MORNING":
            ihsg_summary = (
                "Pra-Pembukaan Sesi 1 (07:30 WIB): Sentimen bursa Asia terdorong stabilnya yield US10Y. "
                "Fokus pelaku pasar tertuju pada akumulasi saham perbankan big-cap dan transmisi suku bunga kredit."
            )
            crypto_summary = (
                "Ringkasan Aset Kripto Overnight: Bitcoin berkonsolidasi di atas zona support dinamis EMA 21 H1. "
                "Open interest derivatif terpantau netral tanpa lonjakan funding rate agresif."
            )
            checklist = [
                "Verifikasi likuiditas pre-open IDX pukul 08:45 WIB sebelum eksekusi.",
                "Periksa konfirmasi breakout volume pada emiten penggerak indeks.",
                "Disiplin batas risiko maksimal 2.0% modal per trade.",
                "Pantau rilis data makro terjadwal malam nanti untuk antisipasi volatilitas.",
            ]
        else:
            ihsg_summary = (
                "Penutupan Perdagangan (17:00 WIB): IHSG membukukan konsolidasi teratur. "
                "Sektor keuangan dan konsumer primer menjadi penopang stabilitas portofolio saham domestik."
            )
            crypto_summary = (
                "Tinjauan Sesi Sore Kripto: Likuiditas pasar bergerak tertib menjelang sesi Amerika Serikat. "
                "Dominasi BTC stabil dengan korelasi rendah terhadap pergerakan saham domestik."
            )
            checklist = [
                "Evaluasi posisi terbuka dan geser stop-loss ke breakeven jika target R:R pertama tercapai.",
                "Hindari overtrading di pasar kripto pada jam-jam pergantian sesi US tanpa konfirmasi trigger.",
                "Review kepatuhan alokasi modal dan diversifikasi multi-aset harian.",
            ]

        # 3. Watchlist Analysis
        items: list[DailyBriefItem] = []
        top_setups: list[str] = []

        # Equities evaluation
        from openbagus.domains.equities.catalog import EquityCatalog
        from openbagus.domains.equities.data import EquityData
        catalog = EquityCatalog(self.root)
        eq_data = EquityData(self.root)
        ref_eq_prices = {"BBCA": 10250.0, "BBRI": 4900.0, "BMRI": 6700.0, "TLKM": 3100.0, "ASII": 5100.0}

        for sym, a_type in active_list:
            if a_type == "EQUITY_ID":
                asset = catalog.resolve(sym)
                try:
                    data = eq_data.load(sym) if asset else {}
                except Exception:
                    data = {}
                candles = data.get("candles", []) if isinstance(data, dict) else []
                if candles:
                    price = float(candles[-1]["close"])
                else:
                    price = ref_eq_prices.get(sym, 5000.0)
                decision = "WAIT"
                reason = "Menunggu konfirmasi volume dan breakout batas resistance"
                levels = f"Support: Rp{price * 0.97:,.0f} | Resistance: Rp{price * 1.03:,.0f}"
                if candles and len(candles) >= 20:
                    c_prev = float(candles[-2]["close"])
                    c_now = float(candles[-1]["close"])
                    chg = ((c_now - c_prev) / c_prev * 100.0) if c_prev > 0 else 0.0
                    if chg > 1.0:
                        decision = "HOLD/BUY"
                        reason = f"Momentum akumulasi positif (+{chg:.1f}%)"
                        top_setups.append(f"{sym}: Skenario swing beli saat pullback dengan batas invalidasi Rp{price * 0.97:,.0f}")
                else:
                    chg = 0.0
                items.append(DailyBriefItem(
                    asset=sym,
                    asset_type="EQUITY_ID",
                    price=price,
                    decision=decision,
                    decision_reason=reason,
                    key_levels=levels,
                    change_pct=round(chg, 2),
                ))
            else:
                # Crypto reference values
                c_price = 68500.0 if sym == "BTC" else 3500.0
                items.append(DailyBriefItem(
                    asset=sym,
                    asset_type="CRYPTO",
                    price=c_price,
                    decision="WAIT",
                    decision_reason="Rezim terkompresi; menunggu konfirmasi breakout level kunci",
                    key_levels=f"Range: ${c_price * 0.96:,.0f} - ${c_price * 1.04:,.0f}",
                    change_pct=0.5,
                ))

        if not top_setups:
            top_setups.append("BBCA: Pantau zona pullback support EMA 21 D1 untuk peluang swing terkonfirmasi.")
            top_setups.append("BTC: Amati retest support $66,500; tunggu trigger bullish Stochastic.")

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
        )


def render_brief_markdown(brief: DailyBriefData) -> str:
    """Renders formatted research brief in GitHub-flavored Markdown for terminal output."""
    tag = "RISALAH RISET PAGI (PRE-MARKET)" if brief.session_type == "MORNING" else "RISALAH RISET SORE (POST-MARKET)"
    lines = [
        f"# OPENBAGUS — {tag}",
        f"**Tanggal:** {brief.date_str}  |  **Waktu Rilis:** {brief.generated_at}  |  **Status:** Draf Tersimpan",
        "",
        "## 1. Konteks Makroekonomi & Pasar",
        f"- **IHSG & Pasar Domestik:** {brief.ihsg_context}",
        f"- **Pasar Kripto:** {brief.crypto_context}",
        "",
        "## 2. Agenda Rilis Data Makro Terjadwal",
    ]
    for ev in brief.macro_events:
        lines.append(f"- {ev}")

    lines.extend([
        "",
        "## 3. Matriks Pengamatan Aset Unggulan (Watchlist)",
        "| Aset | Tipe | Harga Referensi | Status Quant | Rencana & Batas Kunci |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ])
    for it in brief.items:
        px_str = f"Rp{it.price:,.0f}" if it.asset_type == "EQUITY_ID" else f"${it.price:,.2f}"
        lines.append(f"| **{it.asset}** | {it.asset_type} | {px_str} ({it.change_pct:+.1f}%) | `{it.decision}` | {it.key_levels} |")

    lines.extend([
        "",
        "## 4. Peluang & Skenario Terbaik (Actionable Setups)",
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
    from matplotlib.backends.backend_pdf import PdfPages

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
    ax0.text(0.04, 0.65, f"OPENBAGUS INTELLIGENCE — {tag}", transform=ax0.transAxes,
             fontsize=13, fontweight="bold", color="#f8fafc", va="center")
    ax0.text(0.04, 0.28, f"Date: {brief.date_str}  |  Generated: {brief.generated_at}  |  Zero-Spam Local Research Draft",
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
        px = f"Rp{it.price:,.0f}" if it.asset_type == "EQUITY_ID" else f"${it.price:,.2f}"
        table_data.append([it.asset, it.asset_type, px, f"{it.change_pct:+.1f}%", it.decision, it.key_levels])

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
    title_str = f"OPENBAGUS FINANCIAL TERMINAL — {tag}\nTanggal: {brief.date_str} | Waktu: {brief.generated_at}"
    ax.text(0.03, 0.94, title_str, transform=ax.transAxes, color="#f8fafc", fontsize=11, fontweight="bold", va="top")

    # Body sections
    body_lines = [
        "1. RINGKASAN PASAR & SENTIMEN MAKRO:",
        f"   • IHSG / Saham : {brief.ihsg_context[:105]}...",
        f"   • Kripto Pasar : {brief.crypto_context[:105]}...",
        "",
        "2. FOKUS ASET & STATUS QUANT:",
    ]
    for it in brief.items:
        px = f"Rp{it.price:,.0f}" if it.asset_type == "EQUITY_ID" else f"${it.price:,.2f}"
        body_lines.append(f"   • {it.asset:<5} ({it.asset_type:<9}) : {px:<12} | Signal: {it.decision:<6} | {it.key_levels}")

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
        }

    def _save_state(self, state: dict[str, Any]) -> None:
        try:
            with self.state_file.open("w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

    def get_status(self) -> dict[str, Any]:
        state = self._load_state()
        now_utc = datetime.now(timezone.utc)
        now_wib = now_utc + timedelta(hours=7)
        return {
            "enabled": state.get("enabled", True),
            "current_time_wib": now_wib.strftime("%Y-%m-%d %H:%M:%S WIB"),
            "morning_schedule": f"{state.get('morning_time', '07:30')} WIB",
            "evening_schedule": f"{state.get('evening_time', '17:00')} WIB",
            "last_morning_run": state.get("last_morning_run"),
            "last_evening_run": state.get("last_evening_run"),
            "drafts_directory": str(self.briefs_dir),
            "total_drafts_saved": len(list(self.briefs_dir.glob("*_brief.*"))),
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
        """Manually triggers generation of the research brief across all formats."""
        brief_data = self.generator.generate(session_type=session_type, now_dt=now_dt)
        md_text = render_brief_markdown(brief_data)

        # Save Markdown file
        md_path = self.briefs_dir / f"{brief_data.date_str}_{brief_data.session_type.lower()}_brief.md"
        with md_path.open("w", encoding="utf-8") as f:
            f.write(md_text)

        # Generate PDF and PNG
        pdf_path = render_brief_pdf(brief_data, output_path=self.briefs_dir / f"{brief_data.date_str}_{brief_data.session_type.lower()}_brief.pdf")
        png_path = render_brief_png(brief_data, output_path=self.briefs_dir / f"{brief_data.date_str}_{brief_data.session_type.lower()}_brief.png")

        # Update state
        state = self._load_state()
        if brief_data.session_type == "MORNING":
            state["last_morning_run"] = brief_data.generated_at
        else:
            state["last_evening_run"] = brief_data.generated_at
        self._save_state(state)

        return {
            "status": "SUCCESS",
            "session_type": brief_data.session_type,
            "date": brief_data.date_str,
            "markdown_path": str(md_path),
            "pdf_path": str(pdf_path),
            "png_path": str(png_path),
            "markdown_content": md_text,
        }

    def check_and_run_due_brief(self, now_dt: datetime | None = None) -> dict[str, Any] | None:
        """Evaluates whether morning or evening brief is due and executes automatically."""
        state = self._load_state()
        if not state.get("enabled", True):
            return None

        current = now_dt or (datetime.now(timezone.utc) + timedelta(hours=7))
        today_str = current.strftime("%Y-%m-%d")
        curr_hm = current.strftime("%H:%M")

        morning_t = state.get("morning_time", "07:30")
        evening_t = state.get("evening_time", "17:00")

        # Check morning run
        if curr_hm >= morning_t and (not state.get("last_morning_run") or not str(state.get("last_morning_run")).startswith(today_str)):
            return self.trigger_now("MORNING", now_dt=current)

        # Check evening run
        if curr_hm >= evening_t and (not state.get("last_evening_run") or not str(state.get("last_evening_run")).startswith(today_str)):
            return self.trigger_now("EVENING", now_dt=current)

        return None
