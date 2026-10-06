"""Canonical command-line interface for OpenBagus."""

from __future__ import annotations

import argparse
import cmd
import getpass
import importlib
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openbagus import __version__
from openbagus.analysis.engine import run_real_analysis
from openbagus.core.env import RuntimeEnv, get_repo_root
from openbagus.data.ingestion import run_runtime_ingestion
from openbagus.data.providers import ProviderRegistry
from openbagus.delivery.mailbox import EMAIL_CONFIRMATION_PHRASE, SmtpConfig, SmtpTransport
from openbagus.delivery.runner import run_final_delivery
from openbagus.domains.crypto.catalog import CryptoAssetCatalog, TAXONOMY_CATEGORIES
from openbagus.domains.crypto.research import CryptoResearchRunner
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.intelligence.local_language import LocalLanguageEngine
from openbagus.storage.historical import HistoricalStorageRuntime
from openbagus.storage.spreadsheet import SpreadsheetExporter

REPO_ROOT = get_repo_root()
STATUS_PATH = REPO_ROOT / "reports/runtime/delivery/openbagus_final_run_status_latest.json"
DELIVERY_STATUS_PATH = REPO_ROOT / "reports/runtime/delivery/delivery_status_latest.json"
MODES = (
    "crypto",
    "crypto-daily",
    "manual-desk",
    "email",
    "macro-email",
    "doctor",
    "status",
    "providers",
    "assets",
    "categories",
    "config",
    "setup",
    "version",
    "harness",
    "idx-daily",
)

BANNER = r"""
  ___  ____  _____ _   _ ____    _    ____ _   _ ____
 / _ \|  _ \| ____| \ | | __ )  / \  / ___| | | / ___|
| | | | |_) |  _| |  \| |  _ \ / _ \| |  _| | | \___ \
| |_| |  __/| |___| |\  | |_) / ___ \ |_| | |_| |___) |
 \___/|_|   |_____|_| \_|____/_/   \_\____|\___/|____/
""".strip("\n")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _should_refresh(mode: str) -> bool:
    return mode in {"crypto-daily", "manual-desk"}


def _run_refresh_and_analysis(mode: str) -> list[dict[str, Any]]:
    if not _should_refresh(mode):
        return [
            {"step": "data_refresh", "status": "SKIPPED", "reason": "using latest runtime input"},
            {"step": "analysis", "status": "SKIPPED", "reason": "using latest analysis output"},
        ]

    steps: list[dict[str, Any]] = []
    try:
        ingestion = run_runtime_ingestion(mode="real", assets=[], all_core=True, repo_root=REPO_ROOT)
        steps.append({
            "step": "data_refresh",
            "status": "OK",
            "run_id": ingestion.get("run_id"),
            "market_rows": len(ingestion.get("market_rows", [])),
            "macro_rows": len(ingestion.get("macro_rows", [])),
        })
    except Exception as exc:
        steps.append({"step": "data_refresh", "status": "FAILED_STOP", "error": str(exc)[:220]})
        return steps

    try:
        analysis = run_real_analysis(assets=[], all_core=True, repo_root=REPO_ROOT)
        steps.append({
            "step": "analysis",
            "status": "OK",
            "overall_status": analysis.get("data_freshness_summary", {}).get("overall_analysis_status"),
            "assets_evaluated": list(analysis.get("asset_views", {}).keys()),
        })
    except Exception as exc:
        steps.append({"step": "analysis", "status": "FAILED_STOP", "error": str(exc)[:220]})
        return steps

    try:
        history = HistoricalStorageRuntime(REPO_ROOT).record_run(analysis)
        sheets = SpreadsheetExporter(REPO_ROOT).export_summary(analysis)
        steps.append({
            "step": "storage",
            "status": "OK",
            "history_rows": history.get("rows_written", 0),
            "sheets": sheets,
        })
    except Exception as exc:
        steps.append({"step": "storage", "status": "FAILED_CONTINUE", "error": str(exc)[:220]})
    return steps


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openbagus",
        description="OpenBagus quantitative research and market intelligence.",
        epilog=(
            "Examples:\n"
            "  openbagus doctor\n"
            "  openbagus setup\n"
            "  openbagus crypto-daily\n"
            "  openbagus manual-desk --query \"OpenBagus review BTC ETH\"\n"
            "  openbagus email --email-action draft"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("command", nargs="?", choices=MODES, metavar="COMMAND", help="operation to run")
    parser.add_argument("extra", nargs="*", help=argparse.SUPPRESS)
    parser.add_argument("--mode", choices=MODES, help=argparse.SUPPRESS)
    parser.add_argument("--query", help="manual-desk query containing exact trigger 'OpenBagus'")
    parser.add_argument("--email-action", choices=("draft", "check", "send"), default="draft")
    parser.add_argument("--network", "--check", dest="network", action="store_true", help="allow an explicit connectivity check; never sends email")
    parser.add_argument("--confirm-live-send", help=argparse.SUPPRESS)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON where supported")
    parser.add_argument("--version", action="version", version=f"OpenBagus {__version__}")
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command and args.mode and args.command != args.mode:
        parser.error("command and --mode must match when both are supplied")
    args.mode = args.command or args.mode
    if not args.mode:
        parser.error("a command or --mode is required")
    if args.email_action != "draft" and args.mode not in {"email", "macro-email"}:
        parser.error("--email-action is valid only for email")
    return args


def _email_config() -> SmtpConfig:
    return SmtpConfig.from_runtime_env(RuntimeEnv(REPO_ROOT))


def _run_doctor(*, network: bool, as_json: bool) -> int:
    checks: list[dict[str, str]] = []

    def add(status: str, name: str, detail: str) -> None:
        checks.append({"status": status, "name": name, "detail": detail})

    add("PASS" if sys.version_info >= (3, 11) else "FAIL", "Python", sys.version.split()[0])
    try:
        for module in ("openbagus.analysis.engine", "openbagus.data.ingestion", "openbagus.delivery.runner"):
            importlib.import_module(module)
        add("PASS", "Core imports", "available")
    except ImportError as exc:
        add("FAIL", "Core imports", str(exc))

    platform_config = _read_json(REPO_ROOT / "config/openbagus.example.json")
    active = platform_config.get("active_domains")
    disabled = platform_config.get("disabled_domains", [])
    add("PASS" if active == ["crypto"] and "equities" in disabled else "FAIL", "Domains", "crypto active; equities disabled")

    catalog = CryptoAssetCatalog(REPO_ROOT)
    catalog_count = len(catalog.assets)
    add("PASS" if catalog_count > 0 else "FAIL", "Crypto catalog", f"{catalog_count} cached; on-demand discovery enabled")
    registry = ProviderRegistry(REPO_ROOT)
    pub_count = len(registry.list_public())
    add("PASS" if pub_count > 0 else "FAIL", "Zero-Key Core", f"{pub_count} public providers available (no keys required)")
    fred_configured = bool(RuntimeEnv(REPO_ROOT).get("FRED_API_KEY"))
    add("PASS" if fred_configured else "OPTIONAL", "FRED API key", "configured" if fred_configured else "not configured")

    email_config = _email_config()
    add("PASS" if email_config.ready else "OPTIONAL", "Email", "configured" if email_config.ready else "not configured")

    output_dir = REPO_ROOT / "reports/runtime/delivery"
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=output_dir, prefix="doctor-", delete=True):
            pass
        add("PASS", "Runtime output", str(output_dir))
    except OSError as exc:
        add("FAIL", "Runtime output", str(exc))

    llm = LocalLanguageEngine(repo_root=REPO_ROOT)
    llm_state = llm.get_runtime_state()
    if llm_state == "ACTIVE":
        info = llm.get_status_info()
        add("PASS", "Local Language Model", f"ACTIVE ({info.get('model_name')}, {info.get('model_size_mb')}MB)")
    elif llm_state == "FALLBACK":
        add("OPTIONAL", "Local Language Model", "FALLBACK (deterministic engine active)")
    else:
        add("OPTIONAL", "Local Language Model", "UNAVAILABLE (offline / optional)")

    if network:
        registry = ProviderRegistry(REPO_ROOT)
        for res in registry.check_all_public(timeout=3.5):
            lat = f" ({res['latency_ms']}ms)" if res.get("latency_ms") else ""
            stat = "PASS" if res["status"] == "REACHABLE" else "WARN"
            add(stat, f"Provider {res['provider']}", f"{res['status']}{lat}")

        if email_config.ready:
            try:
                result = SmtpTransport(email_config).check()
                add("PASS", "SMTP network", result["status"])
            except Exception as exc:
                add("FAIL", "SMTP network", type(exc).__name__)
        else:
            add("OPTIONAL", "SMTP network", "not configured (email is optional)")

    final = "FAIL" if any(item["status"] == "FAIL" for item in checks) else (
        "WARN" if any(item["status"] == "OPTIONAL" for item in checks) else "PASS"
    )
    if as_json:
        print(json.dumps({"status": final, "checks": checks}, indent=2))
    else:
        for item in checks:
            print(f"[{item['status']}] {item['name']}: {item['detail']}")
        print(f"Overall CLI: {'PASS' if final != 'FAIL' else 'FAIL'}")
    return 1 if final == "FAIL" else 0


def _run_status(session: SessionState | None = None) -> int:
    registry = ProviderRegistry(REPO_ROOT)
    email = _email_config()
    latest = _read_json(STATUS_PATH)
    print("OpenBagus Status")
    print("================")
    print("")
    print("Runtime")
    print(f"  Version           {__version__}")
    print("  Active Domain     crypto (equities disabled)")
    print("  Mode              research-only (no live trading)")
    if session and session.last_quant_result:
        q = session.last_quant_result
        print(f"  Last Research     {q.asset} / {q.timeframe} / {q.decision}")
        print(f"  Last Research At  {session.last_research_at or 'timestamp unavailable'}")
    else:
        print(f"  Last Run          {latest.get('generated_at_utc', 'no runs yet')}")
    print("")
    print("Providers")
    print(f"  Public Sources    {len(registry.list_public())} active (no keys required)")
    print(f"  Capabilities      MARKET, METADATA, DERIVATIVES, ONCHAIN, DEFI, MACRO")
    counts = registry.key_validation_counts()
    print(f"  API Keys          {counts['present']} present / {counts['valid']} validated / {counts['invalid']} invalid / {counts['unverified']} unverified")
    print(f"  Crypto catalog    {len(CryptoAssetCatalog(REPO_ROOT).assets)} cached; on-demand discovery enabled")
    print("")
    print("Features")
    print("  Crypto Research   enabled")
    print(f"  Email Delivery    {'configured' if email.ready else 'optional / not configured'}")
    print("  Daily Email       off")
    print("  WhatsApp          disabled")
    print("  Equities          disabled")
    return 0


def _run_providers(check_network: bool = False) -> int:
    registry = ProviderRegistry(REPO_ROOT)
    print(registry.format_providers_view(run_live_check=check_network))
    return 0


def _run_assets(query: str = "") -> int:
    catalog = CryptoAssetCatalog(REPO_ROOT)
    query_clean = query.strip()
    if query_clean and any(query_clean.lower() in c.lower() for c in TAXONOMY_CATEGORIES):
        cat_name, assets = catalog.get_category_assets(query_clean, limit=15)
        print(f"Assets in Category: {cat_name} ({len(assets)})")
    else:
        assets = catalog.search_assets(query_clean, limit=10)
        title = f'Assets matching "{query_clean}"' if query_clean else "Top Crypto Assets"
        print(f"{title} ({len(assets)})")
    print("-" * 65)
    print(f"{'#':<4} {'Symbol':<8} {'Name':<26} {'Rank':<8} {'Category':<15}")
    print("-" * 65)
    for idx, a in enumerate(assets, 1):
        rank = f"#{a.rank}" if a.rank < 9000 else "N/A"
        cat = a.categories[0] if a.categories else "General"
        print(f"{idx:<4} {a.symbol:<8} {a.name:<26} {rank:<8} {cat:<15}")
    print("-" * 65)
    print("Type any coin symbol directly to analyze (e.g. 'ETH').")
    return 0


def _run_categories() -> int:
    catalog = CryptoAssetCatalog(REPO_ROOT)
    counts = catalog.get_all_categories()
    print("OpenBagus Crypto Taxonomy Categories")
    print("====================================")
    for cat, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:<24} ({count} assets in catalog)")
    print("\nUse '/assets <category>' to view assets (e.g. '/assets defi', '/assets layer2').")
    return 0


def _run_config() -> int:
    env = RuntimeEnv(REPO_ROOT)
    email = SmtpConfig.from_runtime_env(env)
    print("Data providers")
    print("  Binance public       configured")
    print("  CoinGecko public     configured")
    print("  Yahoo Finance        configured")
    print("  DefiLlama            configured")
    print(f"  FRED API key         {'configured' if env.get('FRED_API_KEY') else 'optional / not configured'}")
    print("Email")
    print(f"  SMTP host            {'configured' if email.host else 'not configured'}")
    print(f"  SMTP username        {'configured' if email.username else 'optional / not configured'}")
    print(f"  SMTP password        {'configured' if email.password else 'optional / not configured'}")
    print(f"  Sender               {'configured' if email.sender else 'not configured'}")
    print(f"  Recipient            {'configured' if email.recipients else 'not configured'}")
    print(f"  Delivery             {'configured' if email.ready else 'optional / disabled'}")
    return 0


def _run_setup() -> int:
    env_path = REPO_ROOT / ".env"
    example_path = REPO_ROOT / ".env.example"
    if not env_path.exists():
        if example_path.exists():
            shutil.copy(example_path, env_path)
            print("[PASS] Created local .env from .env.example")
        else:
            env_path.write_text("", encoding="utf-8")
            print("[PASS] Created empty local .env")
    else:
        print("[PASS] Existing local .env preserved")

    registry = ProviderRegistry(REPO_ROOT)
    content = env_path.read_text(encoding="utf-8", errors="replace")
    current_values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        if k.startswith("export "):
            k = k[7:].strip()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in {"'", '"'}:
            v = v[1:-1]
        current_values[k] = v

    updates: dict[str, str] = {}
    print("\n--- OpenBagus Configuration Wizard ---")
    print("All settings are optional. Press Enter to leave unchanged.\n")

    # 1. API Providers
    print("API Providers")
    print("-------------")
    missing_apis = registry.list_missing_apis()
    configured_apis = registry.list_configured_apis()
    for p in configured_apis:
        print(f"  [configured] {p.display_name}")
    for p in missing_apis:
        print(f"  [missing]    {p.display_name}")
    print(f"\n{registry.coverage_summary()}\n")

    try:
        ans = input("Configure API provider keys? (Y/N): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"

    if ans == "y":
        print("\nSelect a provider to configure:")
        configurable = [p for p in registry.list_all() if not p.public_access]
        for idx, p in enumerate(configurable, 1):
            status = "configured" if p.is_configured(current_values) else "missing"
            print(f"  {idx:<2}. [{status:<10}] {p.display_name}")
        print("  0. Done configuring API providers")

        while True:
            try:
                choice = input("\nEnter provider number to configure (0 to finish): ").strip()
                if not choice or choice == "0":
                    break
                c_idx = int(choice) - 1
                if 0 <= c_idx < len(configurable):
                    target_p = configurable[c_idx]
                    env_name = target_p.credential_env_names[0] if target_p.credential_env_names else f"{target_p.id.upper()}_API_KEY"
                    val = getpass.getpass(f"Enter API key for {target_p.display_name} (input hidden): ").strip()
                    if val:
                        print(f"Testing {target_p.display_name}...")
                        result_status = registry.validate_key(target_p.id, val)
                        if result_status == "VALID":
                            updates[env_name] = val
                            current_values[env_name] = val
                            print(f"{target_p.display_name} ........ VALID")
                        else:
                            print(f"{target_p.display_name} ........ {result_status} - not saved")
                else:
                    print("Invalid selection.")
            except (ValueError, EOFError, KeyboardInterrupt):
                break

    # 2. Email Delivery Configuration
    email_current = bool(current_values.get("OPENBAGUS_EMAIL_SMTP_HOST"))
    prompt_email = "Email SMTP is already configured. Reconfigure? (Y/N): " if email_current else "Configure optional email delivery? (Y/N): "
    try:
        ans = input(prompt_email).strip().lower()
    except (EOFError, KeyboardInterrupt):
        ans = "n"

    if ans == "y":
        try:
            host = input("SMTP Host (e.g. smtp.example.com): ").strip()
            port = input("SMTP Port [587]: ").strip() or "587"
            sec = input("Security mode (starttls/ssl/none) [starttls]: ").strip().lower() or "starttls"
            if sec not in {"starttls", "ssl", "none"}:
                sec = "starttls"
            user = input("SMTP Username (optional): ").strip()
            pwd = getpass.getpass("SMTP Password (input hidden): ").strip()
            sender = input("Sender Email Address: ").strip()
            recip = input("Recipient Email Address: ").strip()

            if host:
                updates["OPENBAGUS_EMAIL_SMTP_HOST"] = host
                updates["OPENBAGUS_EMAIL_SMTP_PORT"] = port
                updates["OPENBAGUS_EMAIL_SECURITY"] = sec
                updates["OPENBAGUS_EMAIL_SMTP_USERNAME"] = user
                if pwd:
                    updates["OPENBAGUS_EMAIL_SMTP_PASSWORD"] = pwd
                updates["OPENBAGUS_EMAIL_FROM"] = sender
                updates["OPENBAGUS_EMAIL_TO"] = recip
                updates["OPENBAGUS_EMAIL_LIVE_ENABLED"] = "false"
        except (EOFError, KeyboardInterrupt):
            pass

    if updates:
        lines = content.splitlines()
        updated_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                raw_k, _ = stripped.split("=", 1)
                k = raw_k.strip()
                if k.startswith("export "):
                    k = k[7:].strip()
                if k in updates:
                    new_lines.append(f"{k}={updates[k]}")
                    updated_keys.add(k)
                    continue
            new_lines.append(line)
        for k, v in updates.items():
            if k not in updated_keys:
                new_lines.append(f"{k}={v}")
        env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print("[PASS] Configuration saved to .env")
    else:
        print("[PASS] No configuration changes made")

    return 0


def _delivery_exit_code(steps: list[dict[str, Any]]) -> int:
    statuses = {str(step.get("status", "")) for step in steps}
    if any(status.startswith(("FAILED", "RUNTIME_FAILED", "SEND_FAILED")) or status in {"ANALYSIS_MISSING", "UNSUPPORTED_MODE"} for status in statuses):
        return 1
    if any(status.startswith("BLOCKED") or status in {"EMAIL_CONFIG_MISSING", "EMAIL_ACTION_INVALID"} for status in statuses):
        return 2
    return 0


def _run_pipeline(args: argparse.Namespace) -> int:
    mode = "crypto-daily" if args.mode == "crypto" else args.mode
    if mode == "idx-daily":
        print("EQUITY_DOMAIN_DISABLED: active domain is crypto")
        return 2
    if mode == "manual-desk" and (not args.query or not re.search(r"(?<!\w)OpenBagus(?!\w)", args.query)):
        print("BLOCKED_MANUAL_TRIGGER: manual-desk requires the exact trigger 'OpenBagus'.")
        return 2

    started = _utc_now()
    steps = _run_refresh_and_analysis(mode)
    if any(step.get("status") == "FAILED_STOP" for step in steps):
        print(json.dumps({"status": "PIPELINE_FAILED", "steps": steps}, indent=2))
        return 1

    delivery_mode = "email" if mode in {"email", "macro-email"} else mode
    delivery_name = {
        "crypto-daily": "crypto_daily_report",
        "manual-desk": "manual_crypto_report",
        "email": "email_report",
    }[delivery_mode]
    try:
        delivery = run_final_delivery(
            mode=delivery_mode,
            query=args.query,
            dry_run=args.email_action != "send",
            confirmation=args.confirm_live_send,
            email_action=args.email_action,
            network_check=args.network,
            repo_root=REPO_ROOT,
        )
        steps.append({"step": delivery_name, "status": delivery.get("status", "OK"), "mode": delivery_mode})
        aggregate_delivery = {delivery_name: delivery}
    except Exception as exc:
        steps.append({"step": delivery_name, "status": "RUNTIME_FAILED", "mode": delivery_mode, "error": str(exc)[:220]})
        aggregate_delivery = {}

    live_email_sent = any(result.get("status") == "EMAIL_SENT" for result in aggregate_delivery.values())
    consolidated = {
        "platform": "OpenBagus",
        "engine_version": "openbagus.final_runner.v3",
        "active_domain": "crypto",
        "disabled_domains": ["equities"],
        "generated_at_utc": _utc_now(),
        "started_at_utc": started,
        "mode": mode,
        "query": args.query,
        "manual_trigger": "OpenBagus",
        "research_only": True,
        "send_mode": "LIVE_EMAIL" if live_email_sent else "NO_SEND_FILE_ONLY",
        "numeric_decision_core": "Python Quant Engine",
        "steps": steps,
        "delivery_status": aggregate_delivery,
    }
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(consolidated, indent=2), encoding="utf-8")
    DELIVERY_STATUS_PATH.write_text(json.dumps(consolidated, indent=2), encoding="utf-8")

    summary = {
        "platform": "OpenBagus",
        "active_domain": "crypto",
        "generated_at_utc": consolidated["generated_at_utc"],
        "mode": mode,
        "steps": {step["step"]: step.get("status") for step in steps},
        "status_path": str(STATUS_PATH),
    }
    print(json.dumps(summary, indent=2))
    return _delivery_exit_code(steps)


def _namespace(mode: str, **values: Any) -> argparse.Namespace:
    defaults = {
        "mode": mode,
        "query": None,
        "email_action": "draft",
        "network": False,
        "confirm_live_send": None,
        "json": False,
    }
    defaults.update(values)
    return argparse.Namespace(**defaults)


class OpenBagusShell(cmd.Cmd):
    prompt = "openbagus > "

    def __init__(self) -> None:
        super().__init__()
        self.router = IntentRouter(repo_root=REPO_ROOT)
        self.researcher = CryptoResearchRunner(repo_root=REPO_ROOT)
        self.session = SessionState()

    def preloop(self) -> None:
        color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        banner = f"\033[36m{BANNER}\033[0m" if color else BANNER
        print(banner)
        print("Ask anything about a crypto asset.")
        print("Type a coin, symbol, or question. /help for commands.\n")

    def emptyline(self) -> None:
        return None

    def onecmd(self, line: str) -> bool:
        try:
            line_str = line.strip()
            if line_str.startswith("/"):
                cmd_line = line_str[1:].strip()
                return super().onecmd(cmd_line)
            return super().onecmd(line)
        except KeyboardInterrupt:
            print("\n[Analysis cancelled]")
            return False

    def do_help(self, _arg: str) -> None:
        print("OpenBagus Commands:")
        print("  /help                     show this help screen")
        print("  /harness [clear]          show or clear ephemeral session memory")
        print("  /switch <asset>           switch active research context directly")
        print("  /sources [on|off]         toggle display of data sources in research outputs")
        print("  /chart [asset] [tf]       open real browser chart in TradingView or GeckoTerminal")
        print("  /status                   show platform runtime and provider status")
        print("  /providers                show data providers and coverage (or /providers --check)")
        print("  /assets [query]           search crypto asset universe (e.g. /assets eth, /assets defi)")
        print("  /categories               list crypto taxonomy categories")
        print("  /setup                    configure optional API keys or email")
        print("  /doctor [network]         run local diagnostics (use /doctor network for live ping)")
        print("  /email                    manage optional email draft/check")
        print("  /version                  show OpenBagus version")
        print("  /clear                    clear the terminal screen")
        print("  /exit                     close OpenBagus\n")
        print("Research Queries:")
        print("  Type any coin, symbol, or question directly:")
        print("    ETH")
        print("    open position ETH")
        print("    risk DOGE")
        print("    support resistance AVAX")
        print("    is ARB attractive now")
        print("    BTC vs ETH")

    def do_harness(self, arg: str) -> None:
        cmd_str = arg.strip().lower()
        if cmd_str in ("clear", "reset"):
            self.session.clear()
            print("[PASS] Harness session memory cleared.")
        else:
            print(self.session.status_display())

    def do_switch(self, arg: str) -> None:
        target = arg.strip()
        if not target:
            print("Usage: /switch <ASSET>")
            return
        a_obj, _ = self.router.catalog.resolve_asset(target)
        sym = a_obj.symbol if a_obj else target.upper()
        self.session.last_asset = sym
        req = self.router.parse(f"/switch {target}", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_sources(self, arg: str) -> None:
        cmd_str = arg.strip().lower()
        if cmd_str in ("on", "true", "1", "show"):
            self.session.show_sources = True
            print("[PASS] Sources display enabled for research outputs.")
        elif cmd_str in ("off", "false", "0", "hide"):
            self.session.show_sources = False
            print("[PASS] Sources display disabled for research outputs.")
        else:
            status = "enabled" if self.session.show_sources else "disabled"
            print(f"Sources are currently {status}. Use '/sources on' or '/sources off' to toggle.")

    def do_chart(self, arg: str) -> None:
        cmd_str = arg.strip()
        req = self.router.parse(f"/chart {cmd_str}" if cmd_str else "/chart", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_status(self, _arg: str) -> None:
        _run_status(self.session)

    def do_providers(self, arg: str) -> None:
        check = "--check" in arg or "check" in arg
        _run_providers(check_network=check)

    def do_assets(self, arg: str) -> None:
        _run_assets(arg)

    def do_categories(self, _arg: str) -> None:
        _run_categories()

    def do_doctor(self, arg: str) -> None:
        net = "network" in arg
        _run_doctor(network=net, as_json=False)

    def do_setup(self, _arg: str) -> None:
        _run_setup()

    def do_config(self, _arg: str) -> None:
        _run_config()

    def do_version(self, _arg: str) -> None:
        print(f"OpenBagus {__version__}")

    def do_clear(self, _arg: str) -> None:
        os.system("cls" if os.name == "nt" else "clear")

    def do_exit(self, _arg: str) -> bool:
        self.session.clear()
        return True

    def do_quit(self, _arg: str) -> bool:
        self.session.clear()
        return True

    def do_EOF(self, _arg: str) -> bool:
        self.session.clear()
        print()
        return True

    def do_crypto(self, _arg: str) -> None:
        _run_pipeline(_namespace("crypto-daily"))

    def do_review(self, arg: str) -> None:
        assets = arg.strip()
        if not assets:
            print("Usage: review BTC ETH")
            return
        _run_pipeline(_namespace("manual-desk", query=f"OpenBagus review {assets}"))

    def do_email(self, arg: str) -> None:
        parts = shlex.split(arg)
        action = parts[0] if parts else "draft"
        if action not in {"draft", "check", "send"}:
            print("Usage: /email draft|check|send")
            return
        confirmation = parts[1] if len(parts) > 1 else None
        if action == "send" and confirmation != EMAIL_CONFIRMATION_PHRASE:
            print("[BLOCKED] Live email requires the exact confirmation phrase.")
            return
        _run_pipeline(_namespace("email", email_action=action, confirm_live_send=confirmation))

    def default(self, line: str) -> None:
        cleaned = line.strip()
        if not cleaned:
            return
        req = self.router.parse(cleaned, session=self.session)

        # Strict Asset Context Switch Confirmation (Section B)
        if req.needs_topic_switch_confirmation and req.switch_target_asset:
            target = req.switch_target_asset
            curr = self.session.last_asset or "BTC"
            prompt_str = f"Konteks aktif: {curr}.\nPindah fokus ke {target}? (Y/N): "
            try:
                ans = input(prompt_str).strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = "n"
            if ans in ("y", "yes", "ya"):
                # Switch active asset to target
                self.session.last_asset = target
                req.needs_topic_switch_confirmation = False
                req.asset = target
                req.target_assets = [target]
                result = self.researcher.execute(req, session=self.session)
                self.session.add_turn(cleaned, result[:300])
                print(result)
                print()
                return
            else:
                # Keep curr as active context
                print(f"[Konteks {curr} dipertahankan.]\n")
                return

        if req.needs_asset:
            print(req.clarification_prompt or "Which asset do you want to analyze?")
            print()
            return
        if req.request_type != "UNKNOWN" or req.asset or req.candidates or req.request_type in (
            "SYSTEM_INFO", "MARKET_OUTLOOK", "CATEGORY", "SCREEN", "PREFERENCE", "FEEDBACK", "HARNESS", "SETUP_CONFIG", "CHART"
        ):
            result = self.researcher.execute(req, session=self.session)
            self.session.add_turn(cleaned, result[:300])
            print(result)
            print()
            return
        print(f"Unknown coin or command: '{cleaned}'.")
        print("Type a coin symbol (e.g. 'ETH', 'SOL') or '/help' for commands.")


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        if sys.stdin.isatty() and sys.stdout.isatty():
            OpenBagusShell().cmdloop()
            return 0
        build_parser().print_help()
        return 2

    first_arg = arguments[0]
    if first_arg in MODES or first_arg.startswith("-"):
        args = parse_args(arguments)
        if args.mode == "doctor":
            return _run_doctor(network=args.network, as_json=args.json)
        if args.mode == "status":
            return _run_status()
        if args.mode == "providers":
            return _run_providers(check_network=args.network)
        if args.mode == "assets":
            query = " ".join(args.extra) if getattr(args, "extra", None) else (" ".join(arguments[1:]) if len(arguments) > 1 else "")
            return _run_assets(query)
        if args.mode == "categories":
            return _run_categories()
        if args.mode == "config":
            return _run_config()
        if args.mode == "setup":
            return _run_setup()
        if args.mode == "version":
            print(f"OpenBagus {__version__}")
            return 0
        if args.mode == "harness":
            sub = " ".join(args.extra).lower() if getattr(args, "extra", None) else (" ".join(arguments[1:]).lower() if len(arguments) > 1 else "")
            s = SessionState()
            if "clear" in sub or "reset" in sub:
                s.clear()
                print("[PASS] Harness session memory cleared.")
            else:
                print(s.status_display())
            return 0
        return _run_pipeline(args)

    query_text = " ".join(arguments)
    router = IntentRouter(repo_root=REPO_ROOT)
    researcher = CryptoResearchRunner(repo_root=REPO_ROOT)
    session = SessionState()
    req = router.parse(query_text, session=session)
    if req.needs_asset:
        print(req.clarification_prompt or "Which asset do you want to analyze?")
        return 0
    if req.request_type != "UNKNOWN" or req.asset or req.candidates or req.request_type in (
        "SYSTEM_INFO", "MARKET_OUTLOOK", "CATEGORY", "SCREEN", "PREFERENCE", "FEEDBACK", "HARNESS", "SETUP_CONFIG", "CHART"
    ):
        result = researcher.execute(req, session=session)
        print(result)
        return 0

    print(f"Unknown coin or command: '{query_text}'.")
    print("Type a coin symbol (e.g. 'ETH', 'SOL') or '/help' for commands.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
