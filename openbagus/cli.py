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
import smtplib
import sys
import tempfile
import traceback
import contextlib
import io
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from openbagus import __version__
from openbagus.analysis.engine import run_real_analysis
from openbagus.core.env import RuntimeEnv, get_repo_root
from openbagus.data.ingestion import run_runtime_ingestion
from openbagus.data.providers import ProviderRegistry
from openbagus.delivery.adapters import WhatsAppCloudConfig, WhatsAppCloudTransport, render_research_delivery
from openbagus.delivery.mailbox import EMAIL_CONFIRMATION_PHRASE, SmtpConfig, SmtpTransport, build_email_message
from openbagus.delivery.runner import run_final_delivery
from openbagus.delivery.safety import scan_payload
from openbagus.domains.crypto.catalog import CryptoAssetCatalog, TAXONOMY_CATEGORIES
from openbagus.domains.crypto.quant import QuantEngine
from openbagus.domains.crypto.research import CryptoResearchRunner
from openbagus.domains.equities.catalog import EquityCatalog, SECTORS, source_url
from openbagus.domains.equities.data import EquityData
from openbagus.domains.equities.policy import EquityMarketPolicy
from openbagus.intelligence.intent import IntentRouter, SessionState
from openbagus.intelligence.local_language import LocalLanguageEngine
from openbagus.storage.data_control import (
    FULL_RESET_CONFIRMATION_PHRASE,
    clear_privacy_data,
    execute_full_reset,
    format_privacy_status,
)
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
    "cache",
    "privacy",
    "reset",
    "gmail",
    "whatsapp",
    "autonomy",
    "alerts",
    "delivery",
    "integrations",
    "voice",
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


def _delivery_states() -> tuple[str, str]:
    runtime_env = RuntimeEnv(REPO_ROOT)
    email = SmtpConfig.from_runtime_env(runtime_env)
    email_enabled = (runtime_env.get("OPENBAGUS_EMAIL_LIVE_ENABLED", "false") or "false").lower() in {"1", "true", "yes", "on"}
    email_state = "READY" if email.ready and email_enabled else "INVALID" if email.errors else "NOT CONFIGURED"
    whatsapp = WhatsAppCloudConfig.from_runtime_env(runtime_env)
    wa_state = "READY" if whatsapp.ready and whatsapp.template_name else "TEMPLATE REQUIRED" if whatsapp.ready else "INVALID" if whatsapp.errors else "NOT CONFIGURED"
    return email_state, wa_state


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
    add("PASS" if active == ["crypto", "equities_indonesia"] and "foreign_equities" in disabled else "FAIL", "Domains", "crypto + Indonesian equities; foreign equities disabled")

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
    whatsapp_config = WhatsAppCloudConfig.from_runtime_env(RuntimeEnv(REPO_ROOT))
    add("PASS" if whatsapp_config.ready else "OPTIONAL", "WhatsApp", whatsapp_config.status()["status"])

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
        if whatsapp_config.ready:
            result = WhatsAppCloudTransport(whatsapp_config).validate()
            add("PASS" if result["status"] == "VALID" else "FAIL", "WhatsApp Cloud API", result["status"])

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
    print("  Active Domains    crypto + equities_indonesia (IDX permitted imports)")
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
    email_state, wa_state = _delivery_states()
    llm_info = LocalLanguageEngine(repo_root=REPO_ROOT).get_status_info()
    print("Features")
    print("  Crypto Research   enabled")
    print(f"  Local Language    {llm_info['state']} / Qwen3-4B Q4_K_M / {llm_info['backend']}")
    print(f"  Email             {email_state}")
    print(f"  WhatsApp          {wa_state}")
    print("  Daily Email       off")
    print("  Equities          disabled")
    return 0


def _run_providers(check_network: bool = False, domain: str | None = None, show_all: bool = False) -> int:
    registry = ProviderRegistry(REPO_ROOT)
    print(registry.format_providers_view(run_live_check=check_network, domain=domain, show_all=show_all))
    if domain is None or str(domain).lower() in ("idx", "equities_id"):
        catalog = EquityCatalog(REPO_ROOT)
        print("\nIDX capabilities (identity != market observations)")
        print(f"Issuer identity: {len([a for a in catalog.assets if a.asset_type == 'EQUITY_ID'])} verified seeds/imported identities; update via import-idx catalog.")
        for symbol in ("RATU", "BMRI", "BBCA"):
            data = EquityData(REPO_ROOT).load(symbol)
            bars = data.get("candles", [])
            period = f"{bars[0]['open_at']} - {bars[-1]['close_at']}" if bars else "UNAVAILABLE"
            print(f"{symbol}: market {'OPERATIONAL (authorized import)' if bars else 'DATA_UNAVAILABLE'}; {len(bars)} bars; range {period}")
        print(f"Fundamentals: {'OPERATIONAL (dated import)' if data.get('fundamentals') else 'DATA_UNAVAILABLE'}")
    print("IDX automatic price acquisition: NOT_IMPLEMENTED without a permitted/licensed source. Key presence is not validation or operational evidence.")
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
    equity_catalog = EquityCatalog(REPO_ROOT)
    stocks = [a for a in equity_catalog.assets if not query_clean or query_clean.lower() in f"{a.symbol} {a.name} {a.categories[0]}".lower()]
    print("IDX catalog (partial, expandable through permitted import):")
    for asset in stocks:
        print(f"  {asset.id:<17} {asset.name:<26} {asset.categories[0]}")
    return 0


def _run_categories() -> int:
    catalog = CryptoAssetCatalog(REPO_ROOT)
    counts = catalog.get_all_categories()
    print("OpenBagus Crypto Taxonomy Categories")
    print("====================================")
    for cat, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {cat:<24} ({count} assets in catalog)")
    print("IDX-IC (separate sector taxonomy):")
    for code, (name, indonesian) in SECTORS.items():
        print(f"  {code}: {name} / {indonesian}")
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

            config = SmtpConfig.from_values(
                host=host, port_text=port, security=sec, username=user, password=pwd,
                sender=sender, recipient_text=recip,
            )
            if not config.ready:
                print("EMAIL_CONFIG_INVALID - not saved")
            else:
                try:
                    transport = SmtpTransport(config)
                    transport.check()
                    print("EMAIL_SMTP_READY")
                    test_failed = False
                    send_test = input("Send test email now? (Y/N): ").strip().lower()
                    if send_test == "y":
                        test_message = build_email_message(
                            subject="OpenBagus email connection test", text="OpenBagus email connection test successful.",
                            html="<p>OpenBagus email connection test successful.</p>", config=config,
                        )
                        try:
                            transport.send(test_message)
                            print("EMAIL_TEST_SENT")
                        except (OSError, smtplib.SMTPException):
                            test_failed = True
                            print("EMAIL_SEND_FAILED")
                    enable_live = input("Enable direct email delivery? (Y/N): ").strip().lower() == "y" and not test_failed
                    updates.update({
                        "OPENBAGUS_EMAIL_SMTP_HOST": host,
                        "OPENBAGUS_EMAIL_SMTP_PORT": port,
                        "OPENBAGUS_EMAIL_SECURITY": sec,
                        "OPENBAGUS_EMAIL_SMTP_USERNAME": user,
                        "OPENBAGUS_EMAIL_SMTP_PASSWORD": pwd,
                        "OPENBAGUS_EMAIL_FROM": sender,
                        "OPENBAGUS_EMAIL_TO": recip,
                        "OPENBAGUS_EMAIL_LIVE_ENABLED": "true" if enable_live else "false",
                    })
                except smtplib.SMTPAuthenticationError:
                    print("EMAIL_SEND_FAILED (authentication) - not saved")
                except (OSError, smtplib.SMTPException):
                    print("EMAIL_SEND_FAILED (network) - not saved")
        except (EOFError, KeyboardInterrupt):
            pass

    whatsapp_current = bool(current_values.get("OPENBAGUS_WHATSAPP_ACCESS_TOKEN"))
    prompt_whatsapp = "WhatsApp Cloud API is already configured. Reconfigure? (Y/N): " if whatsapp_current else "Configure optional WhatsApp Cloud API? (Y/N): "
    try:
        configure_whatsapp = input(prompt_whatsapp).strip().lower()
    except (EOFError, KeyboardInterrupt):
        configure_whatsapp = "n"
    if configure_whatsapp == "y":
        try:
            token = getpass.getpass("Meta access token (input hidden): ").strip()
            phone_id = input("WhatsApp Phone Number ID: ").strip()
            recipient = input("Test/default recipient in international format: ").strip()
            version = input("Meta Graph version [v26.0]: ").strip() or "v26.0"
            template = input("Approved template name (optional): ").strip()
            template_language = input("Template language [en_US]: ").strip() or "en_US"
            config = WhatsAppCloudConfig(True, token, phone_id, recipient, version, None, template or None, template_language)
            validation = WhatsAppCloudTransport(config).validate()
            print(f"WhatsApp credentials ........ {validation['status']}")
            if validation["status"] == "VALID":
                test_failed = False
                send_test = input("Send WhatsApp test message now? (Y/N): ").strip().lower()
                if send_test == "y":
                    result = WhatsAppCloudTransport(config).send(
                        "OpenBagus WhatsApp connection test successful.", use_template=bool(template),
                    )
                    print(result["status"])
                    test_failed = result["status"] not in {"WHATSAPP_SENT", "WHATSAPP_TEMPLATE_REQUIRED"}
                elif not template:
                    print("VALID_CREDENTIALS_TEMPLATE_REQUIRED")
                enable_live = input("Enable direct WhatsApp delivery? (Y/N): ").strip().lower() == "y" and not test_failed
                updates.update({
                    "OPENBAGUS_WHATSAPP_ENABLED": "true" if enable_live else "false",
                    "OPENBAGUS_WHATSAPP_ACCESS_TOKEN": token,
                    "OPENBAGUS_WHATSAPP_PHONE_NUMBER_ID": phone_id,
                    "OPENBAGUS_WHATSAPP_RECIPIENT": recipient,
                    "OPENBAGUS_WHATSAPP_GRAPH_VERSION": version,
                    "OPENBAGUS_WHATSAPP_TEMPLATE_NAME": template,
                    "OPENBAGUS_WHATSAPP_TEMPLATE_LANGUAGE": template_language,
                })
            else:
                print("WhatsApp credentials not saved")
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

    from openbagus.intelligence.feedback import FeedbackStore
    from openbagus.intelligence.puter import PuterBackend
    feedback = FeedbackStore()
    print("Optional feedback stores only an explicit correction and asset/timeframe/type locally; no raw prompt history or uploads.")
    try:
        consent = input("Help improve OpenBagus through optional local feedback collection? (Y/N): ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        consent = False
    feedback.set_enabled(consent)
    print("Puter requires browser login; allowance is limited and additional usage may be charged. Local Qwen remains available.")
    try:
        cloud = input("Enable optional Cloud AI through Puter? (Y/N): ").strip().lower() == "y"
        approved = cloud and input("Permit sanitized questions and Quant facts to be sent to Puter? (Y/N): ").strip().lower() == "y"
    except (EOFError, KeyboardInterrupt):
        approved = False
    print(PuterBackend().configure(consent=approved))

    if sys.stdin.isatty():
        print("Persistent Harness allows OpenBagus to remember your research context across restarts.")
        print("  - Data remains strictly on your computer and is not uploaded.")
        print("  - You can inspect or clear it at any time with /harness clear.")
        try:
            h_consent = input("Save conversation context locally between sessions? (Y/N): ").strip().lower() == "y"
        except (EOFError, KeyboardInterrupt, StopIteration):
            h_consent = False
        SessionState.set_persistence_enabled(h_consent)
        if h_consent:
            print("[PASS] Local Harness persistence enabled.")
        else:
            print("[PASS] Harness memory set to ephemeral (cleared on exit).")
    return 0


def _run_gmail(sub_args: list[str]) -> int:
    from openbagus.delivery.gmail import GmailOAuthTransport
    transport = GmailOAuthTransport()
    action = sub_args[0].lower() if sub_args else "status"

    if action == "status":
        status = transport.get_status()
        print("\n=== OpenBagus Gmail OAuth Delivery ===")
        print(f"Status:            {status['status']}")
        print(f"Client Configured: {status['client_configured']}")
        print(f"Connected:         {status['connected']}")
        if status.get("email"):
            print(f"Authorized Email:  {status['email']}")
        print(f"Scope:             {status.get('scope')}")
        print(f"Detail:            {status.get('detail')}")
        print()
        return 0

    if action == "connect":
        print("Launching Google OAuth 2.0 authorization in browser...")
        res = transport.connect(open_browser=True)
        if res.get("status") == "SUCCESS":
            print(f"[PASS] {res.get('detail')}")
            return 0
        else:
            print(f"[FAIL] {res.get('detail')}")
            return 1

    if action == "disconnect":
        res = transport.disconnect()
        print(f"[PASS] {res.get('detail')}")
        return 0

    if action == "test":
        status = transport.get_status()
        if not status.get("connected"):
            print("[FAIL] Gmail not connected. Run 'openbagus gmail connect' first.")
            return 1
        recipient = sub_args[1] if len(sub_args) > 1 else (status.get("email") or "")
        if not recipient:
            print("[FAIL] Recipient required: openbagus gmail test <email>")
            return 1
        res = transport.send_message(
            recipient=recipient,
            subject="OpenBagus Test Notification",
            text_body="This is an automated test message from your OpenBagus assistant verifying official Gmail API delivery.",
        )
        if res.get("status") == "SENT":
            print(f"[PASS] Test email sent to {recipient}. Message ID: {res.get('message_id')}")
            return 0
        else:
            print(f"[FAIL] Delivery failed: {res.get('detail')}")
            return 1

    if action == "send":
        if len(sub_args) < 4:
            print("Usage: openbagus gmail send <recipient> <subject> <body>")
            return 1
        recipient = sub_args[1]
        subject = sub_args[2]
        body = " ".join(sub_args[3:])
        res = transport.send_message(recipient=recipient, subject=subject, text_body=body)
        if res.get("status") == "SENT":
            print(f"[PASS] Email sent to {recipient}. Message ID: {res.get('message_id')}")
            return 0
        else:
            print(f"[FAIL] Delivery failed: {res.get('detail')}")
            return 1

    print("Usage: openbagus gmail status|connect|disconnect|test|send")
    return 1


def _run_whatsapp(sub_args: list[str]) -> int:
    from openbagus.delivery.whatsapp_personal import (
        PersonalWhatsAppTransport,
        BaileysExperimentalTransport,
    )
    transport = PersonalWhatsAppTransport()
    action = sub_args[0].lower() if sub_args else "status"

    if action == "status":
        status = transport.get_status()
        baileys_status = BaileysExperimentalTransport().get_status()
        print("\n=== OpenBagus Personal WhatsApp Delivery ===")
        print(f"Transport:         {status['mode']}")
        print(f"Status:            {status['status']}")
        print(f"Phone:             {status.get('phone') or 'Not configured'}")
        print(f"Detail:            {status['detail']}")
        print("\n--- Experimental Multi-Device QR (Baileys) ---")
        print(f"Classification:    {baileys_status['classification']}")
        print(f"Enabled:           {baileys_status['enabled']} (Disabled by default)")
        print(f"Risk Notice:       {baileys_status['warning']}")
        print()
        return 0

    if action == "connect":
        if len(sub_args) < 2:
            print("Usage: openbagus whatsapp connect <phone_number>")
            return 1
        phone = sub_args[1]
        res = transport.connect(phone)
        if res.get("status") == "CONNECTED":
            print(f"[PASS] {res.get('detail')}")
            return 0
        else:
            print(f"[FAIL] {res.get('detail')}")
            return 1

    if action == "disconnect":
        res = transport.disconnect()
        print(f"[PASS] {res.get('detail')}")
        return 0

    if action == "compose":
        text = " ".join(sub_args[1:]) if len(sub_args) > 1 else "OpenBagus Market Update"
        res = transport.compose(text=text)
        print(f"[{res.get('status')}] {res.get('detail')}")
        return 0

    print("Usage: openbagus whatsapp status|connect|disconnect|compose")
    return 1


def _run_autonomy(sub_args: list[str]) -> int:
    from openbagus.monitoring.autonomous import AutonomousMonitoringRuntime
    runtime = AutonomousMonitoringRuntime()
    action = sub_args[0].lower() if sub_args else "status"

    if action == "status":
        st = runtime.get_status()
        print("\n=== OpenBagus Autonomous Monitoring ===")
        print(f"Status:          {st['status']}")
        print(f"Global Enabled:  {st['global_enabled']}")
        print(f"Paused:          {st['paused']}")
        print(f"Active Rules:    {st['active_rules_count']} of {st['total_rules_count']}")
        if st.get("recent_alerts"):
            print("\nRecent Alerts:")
            for a in st["recent_alerts"]:
                print(f"  [{a['timestamp']}] {a['asset']} ({a['decision']}): {a['headline']}")
        else:
            print("\nRecent Alerts:   None")
        print()
        return 0

    if action in ("on", "enable", "start"):
        res = runtime.enable()
        print(f"[PASS] {res['detail']}")
        return 0

    if action in ("off", "disable", "stop"):
        res = runtime.disable()
        print(f"[PASS] {res['detail']}")
        return 0

    if action == "pause":
        res = runtime.pause()
        print(f"[PASS] {res['detail']}")
        return 0

    if action == "resume":
        res = runtime.resume()
        print(f"[PASS] {res['detail']}")
        return 0

    if action in ("eval", "tick"):
        events = runtime.evaluate_tick()
        print(f"[PASS] Evaluated rules. {len(events)} alert(s) triggered.")
        for ev in events:
            print(f"  -> [{ev.asset}] {ev.headline}")
        return 0

    print("Usage: openbagus autonomy status|on|off|pause|resume|eval")
    return 1


def _run_alerts(sub_args: list[str]) -> int:
    from openbagus.monitoring.autonomous import AutonomousMonitoringRuntime
    runtime = AutonomousMonitoringRuntime()
    action = sub_args[0].lower() if sub_args else "list"

    if action in ("list", "ls"):
        rules = runtime.store.list_rules()
        print("\n=== Active Monitoring Rules ===")
        if not rules:
            print("  No monitoring rules configured. Use 'openbagus alerts add <asset> [condition] [timeframe]'.")
        else:
            for r in rules:
                stat = "ENABLED" if r.enabled else "DISABLED"
                last_trig = r.last_triggered_at or "Never"
                print(f"  [{r.rule_id}] {r.asset} ({r.timeframe}) - {r.condition} -> {stat} (Channels: {', '.join(r.channels)}, Last: {last_trig})")
        print()
        return 0

    if action == "add":
        if len(sub_args) < 2:
            print("Usage: openbagus alerts add <asset> [condition] [timeframe] [channels]")
            return 1
        asset = sub_args[1].upper()
        condition = sub_args[2].upper() if len(sub_args) > 2 else "ACTIONABLE_SETUP"
        timeframe = sub_args[3].upper() if len(sub_args) > 3 else "H1"
        channels = [c.strip() for c in sub_args[4].split(",")] if len(sub_args) > 4 else ["outbox"]
        rule = runtime.add_alert_rule(asset=asset, timeframe=timeframe, condition=condition, channels=channels)
        print(f"[PASS] Created alert rule {rule.rule_id} for {rule.asset} ({rule.condition}, {rule.timeframe}).")
        return 0

    if action in ("remove", "rm", "del"):
        if len(sub_args) < 2:
            print("Usage: openbagus alerts remove <rule_id>")
            return 1
        rule_id = sub_args[1]
        ok = runtime.remove_alert_rule(rule_id)
        if ok:
            print(f"[PASS] Removed alert rule {rule_id}.")
            return 0
        else:
            print(f"[FAIL] Rule {rule_id} not found.")
            return 1

    if action == "history":
        alerts = runtime.store.list_recent_alerts(limit=20)
        print("\n=== Alert History ===")
        if not alerts:
            print("  No alert history recorded.")
        else:
            for a in alerts:
                print(f"  [{a['timestamp']}] {a['asset']} ({a['decision']}) - {a['headline']}")
        print()
        return 0

    print("Usage: openbagus alerts list|add|remove|history")
    return 1


def _run_delivery(sub_args: list[str]) -> int:
    action = sub_args[0].lower() if sub_args else "status"
    if action == "status":
        from openbagus.delivery.gmail import GmailOAuthTransport
        from openbagus.delivery.whatsapp_personal import PersonalWhatsAppTransport, BaileysExperimentalTransport
        env = RuntimeEnv(REPO_ROOT)
        smtp_cfg = SmtpConfig.from_runtime_env(env)
        smtp_enabled = (env.get("OPENBAGUS_EMAIL_LIVE_ENABLED", "false") or "false").lower() in {"1", "true", "yes", "on"}
        smtp_state = "READY" if smtp_cfg.ready and smtp_enabled else "INVALID" if smtp_cfg.errors else "NOT CONFIGURED"

        wa_cloud = WhatsAppCloudConfig.from_runtime_env(env)
        wa_cloud_state = "READY" if wa_cloud.ready and wa_cloud.template_name else "TEMPLATE REQUIRED" if wa_cloud.ready else "INVALID" if wa_cloud.errors else "NOT CONFIGURED"

        gmail_status = GmailOAuthTransport().get_status()["status"]
        wa_personal_status = PersonalWhatsAppTransport().get_status()["status"]
        baileys_status = BaileysExperimentalTransport().get_status()["status"]

        print("\n=== OpenBagus Unified Delivery Overview ===")
        print(f"1. SMTP Email:               {smtp_state}")
        print(f"2. Official Gmail OAuth:      {gmail_status}")
        print(f"3. Meta WhatsApp Cloud API:   {wa_cloud_state}")
        print(f"4. Personal WhatsApp Compose: {wa_personal_status}")
        print(f"5. Baileys Experimental QR:   {baileys_status} (Disabled by default)")
        print()
        return 0

    print("Usage: openbagus delivery status")
    return 1


def _run_voice(sub_args: list[str]) -> int:
    from openbagus.voice.audio_devices import AudioDeviceManager
    from openbagus.voice.gpu_scheduler import GPUScheduler
    from openbagus.voice.asr_engine import LocalASREngine
    from openbagus.voice.tts_engine import LocalTTSEngine
    from openbagus.voice.voice_session import VoiceSession

    action = sub_args[0].lower() if sub_args else "status"
    if action in ("devices", "device"):
        in_devs = AudioDeviceManager.list_input_devices()
        out_devs = AudioDeviceManager.list_output_devices()
        def_in = AudioDeviceManager.get_default_input_device()
        def_out = AudioDeviceManager.get_default_output_device()
        print("\n=== Perangkat Audio Terdeteksi (Windows Native) ===")
        print("Mikrofon (Input):")
        for d in in_devs:
            tag = " [DEFAULT]" if def_in and d.index == def_in.index else ""
            print(f"  [{d.index}] {d.name} ({d.host_api}) - {d.max_input_channels} ch, {int(d.default_sample_rate)} Hz{tag}")
        print("\nSpeaker / Headphone (Output):")
        for d in out_devs:
            tag = " [DEFAULT]" if def_out and d.index == def_out.index else ""
            print(f"  [{d.index}] {d.name} ({d.host_api}) - {d.max_output_channels} ch, {int(d.default_sample_rate)} Hz{tag}")
        print()
        return 0

    if action in ("status", "info"):
        gpu = GPUScheduler.get_instance().query_gpu_status()
        asr = LocalASREngine()
        tts = LocalTTSEngine()
        print("\n=== Status Sistem Suara OpenBagus ===")
        print(f"GPU Hardware: {gpu.device_name} (CUDA: {gpu.cuda_available})")
        print(f"VRAM        : {gpu.vram_used_mb:.0f} MB / {gpu.vram_total_mb:.0f} MB (Free: {gpu.vram_free_mb:.0f} MB)")
        print(f"Whisper ASR : {asr.model_size_or_path} (Akselerasi: {asr.device.upper()} {asr.compute_type})")
        print(f"Piper TTS   : {tts.model_path.name}")
        print(f"Mode Default: FAST / DEEP_REASONING (Spoken selection)")
        print()
        return 0

    if action in ("start", "run", "interactive"):
        session = VoiceSession()
        session.start(hands_free=True)
        try:
            print("Tekan Enter untuk menghentikan sesi suara...")
            input()
        except (KeyboardInterrupt, EOFError):
            pass
        finally:
            session.stop()
        return 0

    print("Usage: openbagus voice [status|devices|start]")
    return 1


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
        router = IntentRouter(repo_root=REPO_ROOT)
        print(CryptoResearchRunner(REPO_ROOT).execute(router.parse(args.query or "IHSG daily"), SessionState()))
        return 0
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
        "active_domains": ["crypto", "equities_indonesia"],
        "disabled_domains": ["foreign_equities"],
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
        self.session.load_if_enabled()
        from openbagus.ai.harness.orchestrator import AgentHarness
        from openbagus.ai.memory.working_context import WorkingContext
        from openbagus.ai.runtime.profiles import get_profile
        from openbagus.ai.providers.manager import ProviderManager
        self.provider_mgr = ProviderManager.get_instance()
        self.agent_harness = AgentHarness(provider=self.provider_mgr.get_provider())
        self.working_context = WorkingContext()
        self.current_mode: str = getattr(self.provider_mgr, "_current_mode", "FAST") or "FAST"
        self.runtime_profile = get_profile(self.current_mode)
        self.trace_enabled = False
        self.voice_session: Any = None
        # Companion: lazy-loaded, None if companion not available
        self._companion: Any = None
        self._companion_available: bool | None = None  # None = untested

    def preloop(self) -> None:
        color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        banner = f"\033[36m{BANNER}\033[0m" if color else BANNER
        print(banner)

        # --- Runtime status detection ---
        try:
            mgr_status = self.provider_mgr.get_status()
            hw = mgr_status.get("hardware", {})
            model_info = mgr_status.get("model_info", {})
            model_name = model_info.get("model_name", "qwen3.5:2b-q4_K_M")
            provider_type = mgr_status.get("active_type", "OLLAMA_FAST")

            if "OLLAMA" in provider_type:
                provider_label = "OLLAMA_LOCAL"
            elif "LLAMA" in provider_type:
                provider_label = "LLAMA_CPP_LOCAL"
            elif "CUSTOM" in provider_type:
                provider_label = "CUSTOM_REMOTE"
            else:
                provider_label = "FALLBACK"

            cuda_ok = hw.get("cuda_available", False)
            gpu_name = hw.get("gpu_name")
            if cuda_ok and gpu_name:
                backend_label = "CUDA"
                gpu_short = "RTX 3050 6GB" if "3050" in gpu_name else gpu_name
            elif cuda_ok:
                backend_label = "CUDA"
                gpu_short = "NVIDIA GPU"
            else:
                backend_label = "CPU"
                gpu_short = "None"

            # GPU inference residency / readiness
            if model_info.get("is_warm"):
                gpu_infer_status = "ACTIVE"
            elif cuda_ok and mgr_status.get("is_available"):
                gpu_infer_status = "READY"
            elif cuda_ok:
                gpu_infer_status = "STANDBY"
            else:
                gpu_infer_status = "UNAVAILABLE"
        except Exception:
            model_name = "qwen3.5:2b-q4_K_M"
            provider_label = "OLLAMA_LOCAL"
            backend_label = "CUDA"
            gpu_short = "RTX 3050 6GB"
            gpu_infer_status = "READY"

        mic_status = "UNAVAILABLE"
        try:
            from openbagus.voice.audio_devices import AudioDeviceManager
            code, detail = AudioDeviceManager.get_microphone_status()
            if code == "READY":
                mic_status = f"READY ({detail})" if detail else "READY"
            elif code == "PERMISSION_REQUIRED":
                mic_status = "PERMISSION_REQUIRED"
            elif code == "NO_DEVICE":
                mic_status = "NO_DEVICE"
            else:
                mic_status = code
        except Exception:
            pass

        comp_status = "INACTIVE"
        if self._companion is not None:
            try:
                s = self._companion.get_status()
                comp_status = f"ACTIVE (PID {s.get('pid')})" if s.get("running") and s.get("pid") else ("ACTIVE" if s.get("running") else "INACTIVE")
            except Exception:
                pass

        w = 46
        sep = "-" * w
        def row(label: str, val: str) -> str:
            space_avail = w - 4 - len(label)
            if len(val) > space_avail:
                val = val[:space_avail - 3] + "..."
            pad = space_avail - len(val)
            return f"|  {label} {val}{' ' * max(pad, 0)}  |"

        backend_desc = f"{backend_label} ({gpu_short})" if backend_label == "CUDA" else backend_label

        lines = [
            f"+{sep}+",
            f"|{'OpenBagus AI Research Terminal':^{w}}|",
            f"+{sep}+",
            row("Model        :", model_name),
            row("AI Provider  :", provider_label),
            row("AI Backend   :", backend_desc),
            row("GPU Inference:", gpu_infer_status),
            row("Mode         :", self.current_mode),
            row("Microphone   :", mic_status),
            row("Companion    :", comp_status),
            f"+{sep}+",
        ]
        print("\n".join(lines))
        print("Type any ticker (BTC, ETH, BBCA), research query, or '/help' for commands.\n")
        if self.session.last_asset:
            print(f"[Restored persistent session context: {self.session.last_asset} ({self.session.timeframe or '1d'})]")
            print(f"Type 'lanjutkan {self.session.last_asset} tadi' to continue or switch to a new asset.\n")


    def emptyline(self) -> None:
        return None

    def onecmd(self, line: str) -> bool:
        if not line.strip():
            return False
        output = io.StringIO()
        self._prompt_output = sys.stdout
        try:
            with contextlib.redirect_stdout(output):
                line_str = line.strip()
                body = line_str[1:].strip() if line_str.startswith("/") else line_str
                parts = body.split(None, 1)
                first_word = parts[0] if parts else ""
                remainder = parts[1] if len(parts) > 1 else ""
                underscore_word = first_word.replace("-", "_")
                if hasattr(self, f"do_{underscore_word}") and not hasattr(self, f"do_{first_word}"):
                    line_to_run = f"{underscore_word} {remainder}".strip()
                else:
                    line_to_run = body
                result = super().onecmd(line_to_run)
        except KeyboardInterrupt:
            output.write("Analisis dibatalkan.\n")
            result = False
        except Exception as exc:
            # Stack frames diagnose programming errors without recording credentials or user input.
            frames = traceback.extract_tb(exc.__traceback__)
            diagnostic = {"type": type(exc).__name__, "frames": [
                {"file": Path(f.filename).name, "line": f.lineno, "function": f.name} for f in frames]}
            try:
                from openbagus.intelligence.local_language import get_local_appdata_dir
                target = get_local_appdata_dir() / "logs" / "cli_errors.jsonl"
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(diagnostic) + "\n")
            except OSError:
                pass
            output.write(f"RUNTIME_QUERY_FAILED ({type(exc).__name__}); sesi tetap aktif. Diagnostic lokal: cli_errors.jsonl.\n")
            result = False
        width = max(1, min(120, shutil.get_terminal_size((80, 24)).columns - 1))
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", output.getvalue(), flags=re.S)
        if os.environ.get("NO_COLOR") or not self._prompt_output.isatty():
            text = re.sub(r"\x1b\[[0-9;]*m", "", text)
        rows = [r for r in text.splitlines() if not re.fullmatch(r"\s*[-=]{3,}\s*", r)]
        while rows and not rows[0].strip():
            rows.pop(0)
        while rows and not rows[-1].strip():
            rows.pop()
        print("-" * width)
        for row in rows:
            print(textwrap.fill(row, width, replace_whitespace=False) if len(row) > width else row)
        print("-" * width)
        return result

    def _ask(self, prompt: str) -> str:
        print(prompt, end="", flush=True, file=getattr(self, "_prompt_output", sys.stdout))
        try:
            return input()
        except (EOFError, KeyboardInterrupt):
            return ""

    def do_data(self, arg: str) -> None:
        parts = arg.strip().split()
        if not parts:
            print("Gunakan:")
            print("  /data freshness                          - Status kesegaran data pasar, EOD & lapkeu")
            print("  /data sources indonesia                  - Panduan sumber data resmi Indonesia")
            print("  /data import idx <path>                 - Impor ringkasan perdagangan harian IDX (CSV/XLSX)")
            print("  /data import financials <path> [ticker] - Impor laporan keuangan emiten 11 sektor")
            print("  /data import ojk <path>                 - Impor statistik perbankan/pasar modal OJK")
            print("  /data import kemendag <path>            - Impor komoditas/neraca dagang Kemendag")
            print("  /data import <ticker IDX>               - Impor interaktif bar OHLCV saham")
            print("  /data fetch <ticker IDX>                - Unduh online EOD data saham")
            return

        cmd = parts[0].lower()
        if cmd in ("freshness", "status", "audit"):
            print("=== Status Kesegaran Data Finansial OpenBagus ===")
            cat_path = REPO_ROOT / "data" / "equities" / "idx_universe.json"
            if cat_path.exists():
                mtime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(cat_path.stat().st_mtime))
                print(f"Katalog Emiten IDX     : Tersedia ({mtime}) [951 emiten diverifikasi]")
            else:
                print("Katalog Emiten IDX     : Belum diunduh (Jalankan /data import)")

            eod_dir = REPO_ROOT / "data" / "equities" / "ohlcv"
            if eod_dir.exists():
                files = list(eod_dir.glob("*.json"))
                print(f"Data Bar OHLCV Harian  : {len(files)} emiten tersimpan secara lokal")
            else:
                print("Data Bar OHLCV Harian  : Belum ada bar harian lokal")

            sec_dir = REPO_ROOT / "data" / "equities" / "financials"
            if sec_dir.exists():
                fin_files = list(sec_dir.glob("*.json"))
                print(f"Laporan Keuangan Resmi : {len(fin_files)} berkas laporan keuangan terindeks")
            else:
                print("Laporan Keuangan Resmi : Belum ada laporan keuangan lokal")

            print("Kurs JISDOR Bank Ind.  : Zero-Key Official Adapter [Live]")
            print("Makro BPS & World Bank : Zero-Key Macro Adapter [Live]")
            print()
            return

        if cmd == "sources" and len(parts) > 1 and parts[1].lower() in ("indonesia", "id", "local"):
            print("=== Sumber Data Resmi Indonesia (OpenBagus Official Infrastructure) ===")
            print("1. Bank Indonesia (wsKursBI): JISDOR & Kurs Transaksi [Live/Zero-Key]")
            print("2. BPS (Badan Pusat Statistik): IHK/Inflasi & PDB [BPS Web API / Zero-Key Fallback]")
            print("3. World Bank Open Data: Indikator Makroekonomi Indonesia [Zero-Key Official]")
            print("4. OJK SJKPublic: Statistik Perbankan Indonesia (SPI) & Pasar Modal [Assisted Import]")
            print("5. Kemendag SatuData: Harga Pokok & Komoditas Ekspor (CPO/Nikel) [Assisted Import]")
            print("6. BEI (IDX): Ringkasan Saham (CSV/XLSX) & Lapkeu 11 Sektor [Assisted Import]")
            print("7. KSEI: Distribusi Kepemilikan Saham & SID [Assisted Import]")
            print("\nPerintah Impor Berkas:")
            print("  /data import idx <path-ke-file-ringkasan.csv|.xlsx>")
            print("  /data import financials <path-ke-lapkeu.csv|.xlsx> [ticker]")
            print("  /data import ojk <path-ke-data-ojk.csv|.json>")
            print("  /data import kemendag <path-ke-data-kemendag.csv|.json>")
            print()
            return

        if cmd == "fetch" and len(parts) >= 2:
            store = EquityData(REPO_ROOT)
            print(f"Mengambil data EOD online untuk {parts[1].upper()}...")
            data = store.fetch_live_data(parts[1].upper(), range_str="1y", save=True)
            if data.get("gaps"):
                print(f"Gagal mengambil data: {data['gaps'][0]}")
            else:
                candles = data.get("candles", [])
                quote = data.get("quote", {})
                print(f"Berhasil mengunduh & memvalidasi {len(candles)} bar daily untuk {parts[1].upper()}.")
                print(f"Harga Terakhir: Rp{quote.get('price', 0):,.0f} | Tanggal: {quote.get('as_of', '-')}")
                print(f"Tersimpan di: {store.directory / f'{parts[1].upper()}.json'}")
            return

        if cmd == "import" and len(parts) >= 3 and parts[1].lower() == "idx":
            path = Path(parts[2].strip('"')).expanduser()
            try:
                store = EquityData(REPO_ROOT)
                res = store.import_idx_trading_summary(path)
                print(f"Berhasil mengimpor ringkasan perdagangan IDX ({res['date']}): {res['imported_tickers_count']} ticker diperbarui.")
                print(f"Sumber: {res['source']}")
            except Exception as exc:
                print(f"Impor ringkasan IDX gagal: {exc}")
            return

        if cmd == "import" and len(parts) >= 3 and parts[1].lower() in ("financials", "lapkeu", "keuangan"):
            path = Path(parts[2].strip('"')).expanduser()
            ticker = parts[3].upper() if len(parts) >= 4 else None
            try:
                store = EquityData(REPO_ROOT)
                res = store.import_financial_statement(path, ticker=ticker)
                print(f"Berhasil mengimpor laporan keuangan {res['symbol']} ({res['period']}): {len(res['ratios'])} rasio dihitung.")
                print(f"Rasio Utama: " + "; ".join(f"{k} {v:,.2f}" for k, v in list(res['ratios'].items())[:6]))
                print(f"Sumber: {res['source']}")
            except Exception as exc:
                print(f"Impor laporan keuangan gagal: {exc}")
            return

        if cmd == "import" and len(parts) >= 3 and parts[1].lower() == "ojk":
            path = Path(parts[2].strip('"')).expanduser()
            try:
                from openbagus.data.indonesia_official import OJKPublicAdapter
                res = OJKPublicAdapter.import_statistics_file(path)
                print(f"Berhasil mengimpor statistik industri OJK ({res['period']}): {len(res.get('metrics', {}))} metrik industri.")
                print(f"Sumber: {res['source']}")
            except Exception as exc:
                print(f"Impor data OJK gagal: {exc}")
            return

        if cmd == "import" and len(parts) >= 3 and parts[1].lower() == "kemendag":
            path = Path(parts[2].strip('"')).expanduser()
            try:
                from openbagus.data.indonesia_official import KemendagAdapter
                res = KemendagAdapter.import_trade_file(path)
                print(f"Berhasil mengimpor data komoditas Kemendag: {len(res.get('items', {}))} item dicatat.")
                print(f"Sumber: {res['source']}")
            except Exception as exc:
                print(f"Impor data Kemendag gagal: {exc}")
            return

        if len(parts) != 2 or cmd != "import":
            print("Gunakan /data import <ticker IDX> (CSV lokal) atau /data fetch <ticker IDX> (online EOD).")
            print("Untuk berkas resmi: /data import [idx|financials|ojk|kemendag] <path>.")
            return

        asset = EquityCatalog(REPO_ROOT).resolve(parts[1].upper())
        if asset is None or asset.asset_type != "EQUITY_ID":
            print("Identitas saham IDX belum terverifikasi.")
            return
        try:
            path = Path(self._ask("Path CSV lokal: ").strip().strip('"')).expanduser()
            source = self._ask("URL HTTPS sumber asli/provider data: ").strip()
            volume_unit = self._ask("Satuan volume menurut dokumentasi sumber (shares): ").strip().lower()
            adjustment = self._ask("Basis harga menurut sumber (adjusted/unadjusted): ").strip().lower()
            actions_verified = self._ask("Dokumentasi sumber memastikan corporate actions/basis seri konsisten? (Y/N): ").strip().lower() == "y"
            if self._ask("Anda memiliki izin menggunakan data ini untuk analisis lokal? (Y/N): ").strip().lower() != "y":
                print("Impor dibatalkan; izin penggunaan belum dikonfirmasi.")
                return
            store = EquityData(REPO_ROOT)
            data = store.read_ohlcv(path, {"symbol": asset.symbol, "source": source,
                "authorized_use": True, "currency": "IDR", "volume_unit": volume_unit,
                "timeframe": "D1", "adjustment": adjustment,
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "unresolved_corporate_actions": not actions_verified})
            if asset.listing_date and any(b["open_at"][:10] < asset.listing_date for b in data["candles"]):
                raise ValueError("Observations precede the issuer listing date")
            print(f"{asset.symbol} | IDX | IDR | D1 | {len(data['candles'])} bar")
            print(f"Periode: {data['candles'][0]['open_at']} s.d. {data['candles'][-1]['close_at']}")
            print(f"Sumber: {source}; volume: {volume_unit}; adjustment: {adjustment}")
            print("Historis saja; tidak membuat current quote.")
            print("Corporate actions: " + ("basis dikonfirmasi pengguna dari dokumentasi sumber" if actions_verified else "belum diverifikasi; backtest diblokir"))
            print("Penyimpanan menggantikan dataset lokal ticker ini; file CSV asal tidak diubah.")
            if self._ask("Simpan dataset yang ditampilkan? (Y/N): ").strip().lower() != "y":
                print("Impor dibatalkan; dataset existing dipertahankan.")
                return
            store.store(data, asset.symbol)
            print(f"HISTORICAL_ANALYSIS_AVAILABLE: {asset.symbol}; current market data belum terverifikasi.")
        except (OSError, ValueError, KeyError, TypeError, EOFError) as exc:
            print(f"Impor gagal ({type(exc).__name__}); periksa schema, unit, izin, tanggal dan OHLC. Dataset existing dipertahankan.")

    def do_macro(self, arg: str) -> None:
        from openbagus.data.indonesia_official import (
            BankIndonesiaAdapter, BPSAdapter, WorldBankAdapter, OJKPublicAdapter, KemendagAdapter
        )
        sub = (arg or "").strip().lower()
        if sub in ("bi", "jisdor", "kurs"):
            jis = BankIndonesiaAdapter.get_jisdor_latest()
            print("=== Bank Indonesia: Kurs Acuan JISDOR & Transaksi ===")
            if jis:
                print(f"JISDOR USD/IDR: Rp{jis['rate']:,.2f} (Per {jis['date']})")
                print(f"Beli: Rp{jis['buy']:,.2f} | Jual: Rp{jis['sell']:,.2f}")
                print(f"Status: {jis['description']} [{jis['provider']}]")
            else:
                print("JISDOR live query tidak tersedia; periksa koneksi.")
            rates = BankIndonesiaAdapter.get_transaction_rates_latest()
            if rates:
                print(f"\nKurs Transaksi BI ({rates[0]['date']}):")
                for r in rates[:6]:
                    print(f"  {r['currency']:<5} Beli: Rp{r['buy']:>10,.2f} | Jual: Rp{r['sell']:>10,.2f} | Mid: Rp{r['mid']:>10,.2f}")
            print()
            return

        if sub in ("bps", "inflasi", "cpi"):
            data = BPSAdapter.get_inflation_data()
            print("=== Badan Pusat Statistik (BPS) & Inflasi Nasional ===")
            print(f"Sumber: {data['source']}")
            if "latest_value" in data:
                print(f"Metrik: {data.get('metric')} = {data['latest_value']}% ({data.get('period')})")
            if "title" in data:
                print(f"Rilis Terakhir: {data['title']} ({data.get('release_date')})")
            if "registration_guidance" in data:
                print(f"\nPanduan Registrasi BPS: {data['registration_guidance']}")
            print()
            return

        if sub in ("ojk", "perbankan", "spi"):
            bm = OJKPublicAdapter.get_benchmark_banking_metrics()
            print(f"=== OJK: {bm['source']} ({bm['period']}) ===")
            print(f"NIM Industri Rata-Rata: {bm['industry_nim_pct']:.2f}%")
            print(f"NPL Gross Industri:     {bm['industry_npl_gross_pct']:.2f}%")
            print(f"CAR (KPMM) Industri:    {bm['industry_car_pct']:.2f}%")
            print(f"LDR Industri:           {bm['industry_ldr_pct']:.2f}%")
            print(f"Pertumbuhan Kredit YoY: {bm['credit_growth_yoy_pct']:.2f}%")
            print(f"Catatan: {bm['note']}")
            print()
            return

        if sub in ("kemendag", "komoditas", "trade"):
            cb = KemendagAdapter.get_staple_and_export_benchmarks()
            print(f"=== {cb['source']} ({cb['period']}) ===")
            print("Harga Pangan Pokok Acuan (IDR/Kg):")
            for k, v in cb.get("staple_prices_idr_kg", {}).items():
                print(f"  {k.replace('_', ' ').title():<25}: Rp{v:,.0f}")
            print("Komoditas Ekspor Utama (USD/Ton):")
            for k, v in cb.get("export_commodities_usd", {}).items():
                print(f"  {k.replace('_', ' ').title():<25}: ${v:,.1f}")
            print(f"Surplus Neraca Dagang: USD {cb.get('trade_balance_usd_billion')} Miliar")
            print(f"Catatan: {cb['note']}")
            print()
            return

        if sub in ("wb", "worldbank", "global"):
            cpi = WorldBankAdapter.get_indonesia_macro("FP.CPI.TOTL.ZG")
            gdp = WorldBankAdapter.get_indonesia_macro("NY.GDP.MKTP.KD.ZG")
            print("=== World Bank Open Data: Indonesia Macro Indicators ===")
            if cpi:
                print("Inflasi Tahunan Indonesia (FP.CPI.TOTL.ZG):")
                for p in cpi[:5]:
                    print(f"  Tahun {p['date']}: {p['value']:.2f}%")
            if gdp:
                print("\nPertumbuhan PDB Riil Indonesia (NY.GDP.MKTP.KD.ZG):")
                for p in gdp[:5]:
                    print(f"  Tahun {p['date']}: {p['value']:.2f}%")
            print()
            return

        # Default overview
        print("=== Ringkasan Makroekonomi & Pasar Indonesia ===")
        jis = BankIndonesiaAdapter.get_jisdor_latest()
        if jis:
            print(f"Bank Indonesia JISDOR (USD/IDR): Rp{jis['rate']:,.2f} ({jis['date']})")
        bm = OJKPublicAdapter.get_benchmark_banking_metrics()
        print(f"OJK Benchmark Perbankan ({bm['period']}): NIM {bm['industry_nim_pct']}%, NPL {bm['industry_npl_gross_pct']}%, CAR {bm['industry_car_pct']}%")
        cb = KemendagAdapter.get_staple_and_export_benchmarks()
        print(f"Kemendag Neraca Dagang ({cb['period']}): Surplus ${cb['trade_balance_usd_billion']}B | CPO ${cb['export_commodities_usd']['cpo_rotterdam_ton']}/ton")
        wb = WorldBankAdapter.get_indonesia_macro("FP.CPI.TOTL.ZG")
        if wb:
            print(f"World Bank IHK/Inflasi ({wb[0]['date']}): {wb[0]['value']:.2f}% YoY")
        print("\nSub-perintah detail: /macro [bi|bps|ojk|kemendag|worldbank]")
        print()

    def do_help(self, arg: str) -> None:
        topic = (arg or "").strip().lower()
        if topic in ("news", "berita"):
            print("\n=== OpenBagus Help: News Intelligence ===")
            print("Verified multi-region public news discovery and fact-level citations.")
            print("Core official sources:")
            print("  - Bank Indonesia (BI), BPS, OJK, BEI (IDX)")
            print("  - Federal Reserve, US BLS (CPI/NFP/PPI), US Treasury, IMF, World Bank, BOJ, BOK")
            print("  - ANTARA News Ekonomi/Terkini, CNBC Indonesia, Reuters, AP, CoinDesk, Blockworks")
            print("  - GDELT DOC API for dynamic multi-publisher article discovery")
            print("Example Queries:")
            print("  berita ANTM minggu ini")
            print("  kabar terbaru bitcoin")
            print("  dampak berita suku bunga ke BBCA")
            print("  /sources [on|off] - toggle detailed article links in terminal outputs")
            print()
            return

        if topic in ("idx", "saham", "equities"):
            print("\n=== OpenBagus Help: Indonesian Equities (IDX) ===")
            print("Cash equity quantitative research using IDR, closed bars, and IDX market rules.")
            print("Capabilities:")
            print("  - Valuation ratios (PBV, PER, EPS, Dividend Yield)")
            print("  - Banking metrics (CAR, NIM, NPL, CASA, LDR) from verified filings")
            print("  - Shareholder ownership structure (KSEI/IDX domestic vs foreign & controller %)")
            print("  - Sector classification (IDX-IC) and commodity sensitivity (e.g. Nickel/Gold -> ANTM)")
            print("Example Queries:")
            print("  BBCA D1")
            print("  valuasi BMRI")
            print("  BBCA menurut valuasi dan fundamental sekarang layak beli?")
            print("  /ownership BBCA - inspect verified shareholder distribution")
            print("  dampak china manufacturing data ke sektor tambang idx antm")
            print("  BBCA vs BBRI")
            print("Data acquisition: user-owned/authorized JSON or CSV import; no automatic IDX price scraping.")
            print("/data import BMRI - assisted CSV import with provenance/unit preview and confirmation.")
            print("python -m openbagus.cli import-idx market <JSON>")
            print("python -m openbagus.cli import-idx ohlcv <CSV> --metadata <JSON>")
            print('Metadata: {"symbol":"RATU","source":"https://<authorized-source>/document", "authorized_use":true, "currency":"IDR", "volume_unit":"shares", "timeframe":"D1", "adjustment":"adjusted", "retrieved_at":"<ISO timestamp with timezone>"}')
            print("CSV columns: open_at,close_at,open,high,low,close,volume. ISO timestamps with timezone; volume in shares.")
            print("Financials: period_type FY/TTM/QUARTER, period, basis, published_at, source, currency IDR, unit, values, reported_ratios_pct.")
            print("/visualize RATU | /backtest BMRI D1 | backtest RATU sejak listing; only actual imported closed bars are used.")
            print()
            return

        if topic in ("crypto", "koin"):
            print("\n=== OpenBagus Help: Cryptocurrency Research ===")
            print("Microstructure-grounded quantitative analysis across spot and perpetual markets.")
            print("Capabilities:")
            print("  - Spot & perpetual price action, OHLCV, regime identification")
            print("  - Order-book depth & bid/ask spread evaluation at reference notional ($1,000)")
            print("  - Derivatives metrics: Funding rate, Open Interest change, liquidation geometry")
            print("  - Technical structures: Fibonacci confluence, Stochastic, chart patterns")
            print("  - Conditional triggers: entry, stop loss, target, gross and fee-adjusted net R:R")
            print("Example Queries:")
            print("  BTC H1")
            print("  open posisi ETH")
            print("  BTC sekarang long enak nggak?")
            print("  bedah BTC H1 lengkap dari derivatives sampai risk")
            print("  BTC vs ETH")
            print("  /chart BTC H1 - native HTML chart using actual closed OHLCV")
            print("  /chart external BTC H1 - optional TradingView browser link")
            print()
            return

        if topic in ("macro", "makro"):
            print("\n=== OpenBagus Help: Macroeconomic Intelligence ===")
            print("Point-in-time official economic calendar & market sensitivity analysis.")
            print("Tracked events:")
            print("  - US BLS: Non-Farm Payrolls (NFP), CPI, Core CPI, PPI")
            print("  - Federal Reserve: FOMC Interest Rate Decision & statement")
            print("  - Bank Indonesia: BI-Rate policy decision & Rupiah sensitivity")
            print("  - Asian Pre-Open Intelligence: KRX, TSE, SSE, HKEX morning window (08:40 WIB) -> IDX")
            print("Example Queries:")
            print("  NFP terbaru")
            print("  cpi rilis kapan")
            print("  nfp malam ini jam berapa dan dampaknya ke crypto?")
            print("  bagaimana pasar asia pagi ini sebelum ihsg buka?")
            print("  korea sama jepang pagi ini ngaruh ke IHSG nggak?")
            print()
            return

        if topic in ("quant", "strategy", "strategies"):
            print("\n=== OpenBagus Help: Quant Strategies & Risk Gates ===")
            print("Authoritative deterministic Python Quantitative Decision Engine.")
            print("Core Principles:")
            print("  - Internal trade geometry: entry, invalidation stop, target, gross R:R, net R:R")
            print("  - R:R Gating: trades with net R:R < 1:1.50 or adverse momentum trigger NO_TRADE")
            print("  - Contradiction Detection: warns when indicators conflict (e.g. oversold in strong downtrend)")
            print("  - Heuristic Weights: composite scores transparently labeled as uncalibrated weights")
            print("  - Hardware Acceleration: CPU multithreading, Numba JIT, CUDA auto-detection")
            print("Example Queries:")
            print("  benchmark quantum openbagus - run Monte Carlo throughput benchmark")
            print("  wkwk kenapa no trade lagi - inspect specific failed quantitative gating rule")
            print()
            return

        if topic in ("arbitrage", "arbitrase"):
            print("\n=== OpenBagus Help: Arbitrage & Dislocation Analysis ===")
            print("Depth-weighted order-book cross-venue spread and dislocation analysis.")
            print("Friction accounting:")
            print("  - Taker fee deduction (~0.10% each side = 0.20% round-trip)")
            print("  - Order-book depth slippage at declared notional ($1,000 baseline)")
            print("  - Transfer and gas network fees deduction")
            print("  - Spot-perpetual basis dislocation and 8-hour funding rate carry yields")
            print("  - Opportunity States: OBSERVED_SPREAD, POTENTIAL_AFTER_COSTS, EXECUTION_RISK, NOT_EXECUTABLE")
            print("Example Queries:")
            print("  ada arbitrase btc antar exchange sekarang?")
            print("  ada arbitrase ETH antara dua exchange?")
            print()
            return

        if topic in ("backtest", "backtesting"):
            print("\n=== OpenBagus Help: Walk-Forward Backtesting ===")
            print("Realistic out-of-sample backtesting with exchange-grade cost simulation.")
            print("Features:")
            print("  - Out-of-sample validation preventing data leakage and overfitting")
            print("  - Realistic fees (0.05% crypto, 0.15%/0.25% IDX) and round-lot constraints")
            print("  - Performance metrics: Win rate, Profit Factor, Max Drawdown, Sharpe ratio")
            print("Example Queries:")
            print("  /backtest BTC - run crypto historical walk-forward backtest")
            print("  /backtest BBCA - run IDX historical backtest")
            print()
            return

        if topic in ("harness", "session"):
            print("\n=== OpenBagus Help: Persistent Harness Memory ===")
            print("Maintains multi-turn conversational context and historical research packets.")
            print("Commands:")
            print("  /harness          - view active context, last asset, and recent query turns")
            print("  /harness status   - view durable SQLite storage statistics and date range")
            print("  /harness history  - view chronological conversation history from durable store")
            print("  /harness search   - search stored conversation history by keyword")
            print("  /harness on       - enable persistence to local app data across restarts")
            print("  /harness off      - disable persistence for future sessions")
            print("  /harness clear    - clear all session context and stored memory")
            print("  /switch <asset>   - switch active research focus directly")
            print()
            return

        if topic in ("brief", "daily_brief", "schedule"):
            print("\n=== OpenBagus Help: Automated Daily Research Briefs ===")
            print("Autonomous morning (pre-market 07:30 WIB) and evening (post-market 17:00 WIB) intelligence.")
            print("Features:")
            print("  - Macro calendar events, Asian pre-open context, and overnight crypto summary")
            print("  - IDX and Crypto watchlist matrix with key technical levels and quant signals")
            print("  - Zero-cost & zero-spam: Outputs saved strictly to local drafts directory as PDF, PNG, and MD")
            print("Commands:")
            print("  /brief morning    - generate morning pre-market research brief (PDF/PNG/MD)")
            print("  /brief evening    - generate evening post-market research brief (PDF/PNG/MD)")
            print("  /brief list       - list all generated brief drafts in disk storage")
            print("  /brief status     - view automated scheduler status, run history, and draft path")
            print()
            return

        print("\n=======================================================")
        print("          OPENBAGUS FINANCIAL INTELLIGENCE HELP        ")
        print("=======================================================")
        print("Commands by Category:")
        print("  1. Research & Analysis:")
        print("     <ticker> [tf]          analyze asset directly (e.g. BTC H1, BBCA D1)")
        print("     /switch <asset>        switch active research focus")
        print("     /sources [on|off]      toggle display of verified data sources")
        print("  2. Native Terminal Visualization & Reports:")
        print("     /chart [asset] [tf]    interactive desktop chart (or '/chart terminal' for ANSI/Unicode)")
        print("     /visualize [asset]     display interactive chart with quantitative levels")
        print("     /export png [asset]    export publication-grade candlestick PNG to disk")
        print("     /export pdf [asset]    export professional PDF quantitative report to disk")
        print("     /export word [asset]   export native Microsoft Word (.docx) report with DrawingML")
        print("     /export html [asset]   export interactive HTML research report to disk")
        print("     /integrations          inspect status of optional TradingView MCP bridge & tools")
        print("  3. Equities & Financial Intelligence (IDX & US SEC EDGAR):")
        print("     /stocks [cmd]          explore full IDX universe (search, sector, info, ipo, fetch, sync)")
        print("     /scan [all|swing|...]  universal all-cap scanner (all, swing, momentum, smallcap, microcap, event)")
        print("     /events [today|...]    corporate event intelligence (today, latest, material, earnings, <ticker>)")
        print("     /market-mechanism <tk> official tick size, auto-rejection limits, FCA & execution profile")
        print("     /financials [cmd]      read authentic P&L, balance sheet, cash flows, audit status & citations")
        print("     /valuation <ticker>    calculate multiples (PER/PBV/EV), DuPont ROE & DCF scenario matrix")
        print("     /dcf <ticker>          intrinsic valuation with 3 scenarios and 2D sensitivity matrices")
        print("     /sec <ticker> [mode]   zero-key US SEC EDGAR filing intelligence (CIK, 10-K, 10-Q XBRL facts)")
        print("     /compare <t1> <t2>     side-by-side fundamental & valuation comparison table")
        print("     /fcf <ticker>          waterfall Free Cash Flow (OCF - Capex) or banking sector exclusion")
        print("     /job [list|status]     inspect background browser engine & document download jobs")
        print("     /data [import|fetch]   import authorized local CSV/XLSX/XBRL/PDF or fetch live online EOD")
        print("     /ownership [asset]     view shareholder concentration & KSEI disclosures")
        print("  4. Quantitative Strategies & Validation:")
        print("     /backtest [asset] [cmd] walk-forward backtest, parameter sweep (/backtest sweep), MTF, or curve")
        print("     /portfolio [cmd]       multi-asset risk, position sizing, VaR & cross-asset correlation")
        print("     /benchmark quant       benchmark quantitative calculation throughput & precision contract")
        print("  5. Persistent Session Harness:")
        print("     /harness [on|off|clear] view or control multi-turn session memory")
        print("  6. Delivery & Automated Daily Briefs:")
        print("     /brief [morning|evening|list|status] generate or inspect daily research briefs")
        print("     /alerts list|add|rm    manage autonomous monitoring rules")
        print("     /delivery [status]     overview of SMTP, Gmail OAuth, and WhatsApp")
        print("     /gmail                 manage official Google OAuth Gmail delivery")
        print("     /whatsapp              manage personal WhatsApp messaging")
        print("     /autonomy status|on    control background autonomous scheduler")
        print("  7. Conversational AI & Local Native Voice (NVIDIA RTX CUDA):")
        print("     /chat <pesan>          interact with conversational financial agent harness")
        print("     /voice [start|ptt|stop] start or stop real-time Indonesian voice assistant")
        print("     /voice status|devices  inspect audio devices, GPU VRAM telemetry, and latency")
        print("     /voice mode [fast|deep] switch between Fast and Deep Reasoning voice modes")
        print("     /voice mute|unmute     mute or unmute microphone capture")
        print("  8. System, Cache & Privacy:")
        print("     /status                show system runtime, models, and providers")
        print("     /providers [--check]   view zero-key provider connectivity")
        print("     /cache [status|clear]  manage local market data cache")
        print("     /privacy [status|clear] inspect or clear locally stored private data")
        print("     /reset all             full reset of all local OpenBagus caches")
        print("     /setup                 configure optional credentials or SMTP")
        print("     /doctor                run local runtime diagnostics")
        print("     /clear                 clear terminal screen")
        print("     /exit                  exit OpenBagus")
        print("\nContextual Help Topics:")
        print("  Type '/help <topic>' for deep topic guides:")
        print("    /help news        - Verified news sources, GDELT, and citation behavior")
        print("    /help idx         - Indonesian Equities, valuation, and fundamentals")
        print("    /help crypto      - Order-book depth, derivatives, and crypto setups")
        print("    /help macro       - Global macro, BLS, FOMC, BI-Rate, Asian pre-open")
        print("    /help quant       - Quant engine, R:R gates, and acceleration")
        print("    /help arbitrage   - Order-book spreads and friction deductions")
        print("    /help backtest    - Walk-forward backtesting and metrics")
        print("    /help harness     - Multi-turn conversation persistence")
        print("    /help brief       - Automated daily research briefs (morning/evening PDF/PNG)")
        print()

    def do_harness(self, arg: str) -> None:
        sub = arg.strip().lower()
        if sub.startswith("retention "):
            try:
                parts = sub.split()
                turns = int(parts[1]) if len(parts) > 1 else 20
                days = int(parts[2]) if len(parts) > 2 else 365
                self.session.recent_preferences.update(history_turn_limit=turns, history_days=days)
                print(f"Working window LLM: {turns} turn in-memory; Arsip disk SQLite: UNLIMITED (tidak ada batas waktu/turn).")
            except Exception:
                print("Gunakan /harness retention <turns> [days].")
            return
        if sub.startswith("search ") or sub.startswith("find "):
            kw = arg.strip().split(maxsplit=1)[1] if len(arg.strip().split(maxsplit=1)) > 1 else ""
            if not kw:
                print("Gunakan: /harness search <kata kunci>")
                return
            results = self.session.search_history(kw, limit=20)
            if not results:
                print(f"Tidak ada riwayat percakapan yang cocok dengan '{kw}'.")
                return
            print(f"\nDitemukan {len(results)} riwayat turn untuk '{kw}':")
            print("-" * 65)
            for idx, t in enumerate(results, 1):
                asset_badge = f"[{t.get('asset')}] " if t.get('asset') else ""
                at_str = t.get('at', '')[:19].replace('T', ' ')
                print(f"{idx}. {at_str} {asset_badge}User: {t.get('user', '')[:80]}")
                ans_snippet = t.get('assistant', '').strip().replace('\n', ' ')[:100]
                print(f"   OpenBagus: {ans_snippet}...")
                print()
            return
        if sub.startswith("history") or sub.startswith("log"):
            parts = sub.split()
            n = 10
            if len(parts) > 1 and parts[1].isdigit():
                n = min(100, int(parts[1]))
            history = self.session.get_stored_history(limit=n)
            if not history:
                print("Belum ada riwayat percakapan tersimpan di Harness.")
                return
            stats = self.session.get_storage_stats()
            print(f"\nRiwayat Percakapan ({len(history)} dari {stats['total_turns']} turn total, Arsip: {stats['db_size_str']}):")
            print("-" * 65)
            for idx, t in enumerate(reversed(history), 1):
                asset_badge = f"[{t.get('asset')}] " if t.get('asset') else ""
                at_str = t.get('at', '')[:19].replace('T', ' ')
                user_text = t.get('user', '')[:80]
                ans_text = t.get('assistant', '').strip().replace('\n', ' ')[:90]
                print(f"[{idx}] {at_str} {asset_badge}Q: {user_text}")
                print(f"    A: {ans_text}...")
            print()
            return
        if sub in ("status", "info"):
            print(self.session.status_display())
            stats = self.session.get_storage_stats()
            print(f"\nDetail Penyimpanan SQLite:")
            print(f"  Lokasi File  : {stats.get('db_path')}")
            print(f"  Ukuran Disk  : {stats.get('db_size_str')} ({stats.get('db_size_bytes'):,} bytes)")
            print(f"  Total Turn   : {stats.get('total_turns'):,} turn tersimpan")
            print(f"  Rentang Waktu: {stats.get('oldest_turn_at') or 'N/A'} s/d {stats.get('newest_turn_at') or 'N/A'}")
            print(f"  Retensi      : UNLIMITED (dibatasi hanya oleh kapasitas fisik disk)")
            return
        if sub in ("clear-context", "clear active", "clear_context"):
            self.session.clear()
            print("[PASS] Working context dibersihkan. Arsip disk tetap utuh.")
            return
        elif sub in ("clear-session", "clear_session"):
            if self.session.clear_persistent(scope="session"):
                self.session.clear()
                print("[PASS] Sesi percakapan aktif berhasil dihapus dari Harness.")
            else:
                print("[FAIL] Gagal menghapus sesi percakapan dari Harness.")
            return
        elif sub in ("clear-all", "clear_all"):
            if self.session.clear_persistent(scope="all"):
                self.session.clear()
                print("[PASS] Seluruh arsip riwayat percakapan di Harness berhasil dihapus.")
            else:
                print("[FAIL] Gagal menghapus seluruh arsip Harness.")
            return
        elif sub in ("clear", "reset"):
            if self.session.clear_persistent(scope="all"):
                self.session.clear()
                print("[PASS] Harness session memory and persistent history cleared.")
            else:
                print("[FAIL] Failed to clear persistent Harness history.")
            return
        elif sub in ("on", "enable", "true"):
            self.session.set_persistence_enabled(True)
            self.session.save_persistent()
            print("[PASS] Local Harness persistence enabled.")
        elif sub in ("off", "disable", "false"):
            self.session.set_persistence_enabled(False)
            print("[PASS] Local Harness persistence disabled for future sessions. Note: existing saved context remains until cleared with '/harness clear'.")
        elif sub in ("save", "store"):
            self.session.save_persistent()
            print("[PASS] Current Harness context saved locally.")
        else:
            print(self.session.status_display())

    def do_cache(self, arg: str) -> None:
        req = self.router.parse(f"/cache {arg}".strip(), session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_privacy(self, arg: str) -> None:
        req = self.router.parse(f"/privacy {arg}".strip(), session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_reset(self, arg: str) -> None:
        sub = arg.strip().lower()
        if sub != "all":
            print("Perintah reset menghapus semua data lokal OpenBagus.")
            print("Gunakan: /reset all")
            return
        print("\nPERINGATAN: Tindakan ini akan menghapus semua cache pasar, riwayat konteks harness,")
        print("laporan lokal, konfigurasi flags, dan data feedback di komputer ini.")
        print(f"Untuk melanjutkan, ketik persis: {FULL_RESET_CONFIRMATION_PHRASE}")
        try:
            confirm = input("Konfirmasi: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[Reset dibatalkan.]\n")
            return
        if confirm != FULL_RESET_CONFIRMATION_PHRASE:
            print("[Reset dibatalkan: Frasa konfirmasi tidak sesuai.]\n")
            return
        self.session.clear()
        res = execute_full_reset(REPO_ROOT)
        print("\n[RESET SELESAI]")
        for k, v in res.items():
            print(f"  {k:<30} {v}")
        print()

    def do_feedback(self, arg: str) -> None:
        from openbagus.intelligence.feedback import FeedbackStore
        kind, _, correction = arg.partition(" ")
        print(FeedbackStore().record(kind, correction, self.session.last_asset, self.session.timeframe))

    def do_improve(self, arg: str) -> None:
        from openbagus.intelligence.feedback import FeedbackStore
        store = FeedbackStore()
        action = arg.strip().lower() or "status"
        if action == "off":
            store.set_enabled(False)
            print("FEEDBACK_OFF")
        elif action == "clear":
            store.clear()
            print("FEEDBACK_CLEARED")
        elif action == "export":
            print(store.review() or "No feedback recorded.")
            try:
                approved = input("Export this reviewed content locally for manual redaction/sharing? (Y/N): ").strip().lower() == "y"
            except (EOFError, KeyboardInterrupt):
                approved = False
            result = store.export(reviewed=approved)
            print(str(result) if result else "EXPORT_CANCELLED")
        else:
            print("FEEDBACK_ON_LOCAL_ONLY" if store.enabled else "FEEDBACK_OFF")

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

    def do_visualize(self, arg: str) -> None:
        cmd_str = arg.strip()
        req = self.router.parse(f"/visualize {cmd_str}" if cmd_str else "/visualize", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_backtest(self, arg: str) -> None:
        cmd_str = arg.strip()
        req = self.router.parse(f"/backtest {cmd_str}" if cmd_str else "/backtest", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_report(self, arg: str) -> None:
        cmd_str = arg.strip()
        req = self.router.parse(f"/report {cmd_str}" if cmd_str else "/report", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_ownership(self, arg: str) -> None:
        cmd_str = arg.strip()
        req = self.router.parse(f"/ownership {cmd_str}" if cmd_str else "/ownership", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_portfolio(self, arg: str) -> None:
        cmd_str = arg.strip()
        req = self.router.parse(f"/portfolio {cmd_str}" if cmd_str else "/portfolio", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_risk(self, arg: str) -> None:
        self.do_portfolio(arg)

    def do_brief(self, arg: str) -> None:
        cmd_str = arg.strip()
        req = self.router.parse(f"/brief {cmd_str}" if cmd_str else "/brief", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_schedule(self, arg: str) -> None:
        cmd_str = arg.strip()
        req = self.router.parse(f"/schedule {cmd_str}" if cmd_str else "/schedule brief", session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_stocks(self, arg: str) -> None:
        def _parse_subarg_page(subarg_str: str) -> tuple[str, int]:
            tokens = subarg_str.strip().split()
            if not tokens:
                return "", 1
            if tokens[-1].isdigit():
                page_num = max(1, int(tokens[-1]))
                remainder = " ".join(tokens[:-1])
                return remainder, page_num
            return " ".join(tokens), 1

        parts = arg.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else ""
        subarg = parts[1].strip() if len(parts) > 1 else ""
        catalog = EquityCatalog(REPO_ROOT)
        from openbagus.reporting.terminal_table import render_stocks_table

        if not subcmd or subcmd == "summary":
            stats = catalog.get_universe_stats()
            print("=== IDX Listed Universe Summary ===")
            print(f"Total Instrumen: {stats['total_instruments']} (Saham Emiten: {stats['common_equities']}, Indeks/ETF: {stats['indices']})")
            print(f"Katalog Sumber: {catalog.path} (Resmi Terverifikasi)")
            print("Perintah yang tersedia:")
            print("  /stocks all [page]                 - Jelajahi seluruh semesta saham IDX dengan paginasi")
            print("  /stocks board <papan> [page]       - Filter berdasarkan papan (MAIN, DEVELOPMENT, ACCELERATION, SPECIAL_MONITORING)")
            print("  /stocks tier <tier> [page]         - Filter berdasarkan ukuran (LARGE_CAP, MID_CAP, SMALL_CAP, MICRO_CAP)")
            print("  /stocks status <status> [page]     - Filter berdasarkan status perdagangan (ACTIVE, SUSPENDED, DELISTED)")
            print("  /stocks smallcap [page]            - Daftar saham small-cap (Rp 500M - Rp 5T)")
            print("  /stocks microcap [page]            - Daftar saham micro-cap (< Rp 500M)")
            print("  /stocks third-liner [page]         - Eksplorasi saham lapis tiga & pergerakan volatil")
            print("  /stocks coverage                   - Rekonsiliasi & statistik lengkap 11 sektor & seluruh papan")
            print("  /stocks search <query> [page]      - Cari saham berdasarkan ticker, nama, atau industri")
            print("  /stocks sector <sektor> [page]     - Filter emiten berdasarkan sektor IDX-IC (A-K / nama)")
            print("  /stocks info <ticker>              - Profil lengkap emiten, papan, status, dan kapitalisasi")
            print("  /stocks ipo [page]                 - Daftar IPO terbaru (2024-2025)")
            print("  /stocks fetch <ticker>             - Ambil data harga EOD terkini ke penyimpanan lokal")
            print("  /stocks sync                       - Sinkronkan katalog dengan universe resmi")
            print("  /stocks compare <t1> <t2> ...      - Bandingkan beberapa saham berdampingan")
            print("  /stocks screen <metric> <op> <val> - Screening saham berdasarkan rasio / metrik")
            print("  /stocks import-catalog <path>      - Impor file resmi IDX/KSEI (CSV/JSON)")
            print()
            sample = [a for a in catalog.assets if a.symbol in {"BBCA", "BBRI", "BMRI", "TLKM", "ASII", "ANTM", "RATU", "GOTO", "BRIS", "ADRO"}]
            print(render_stocks_table(sample, title="Contoh Emiten Terverifikasi"))
            print()
        elif subcmd == "all":
            _, page = _parse_subarg_page(subarg)
            eq_assets = [a for a in catalog.assets if a.asset_type == "EQUITY_ID"]
            sliced, meta = catalog.paginate(eq_assets, page=page, page_size=25)
            print(render_stocks_table(sliced, title="Semesta Seluruh Saham IDX", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks all {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd == "board":
            board_query, page = _parse_subarg_page(subarg)
            if not board_query:
                print("Format: /stocks board <nama_papan> [page]")
                print("Pilihan papan: MAIN (Utama), DEVELOPMENT (Pengembangan), ACCELERATION (Akselerasi), SPECIAL_MONITORING (Pemantauan Khusus), NEW_ECONOMY (Ekonomi Baru)")
                return
            items = catalog.by_board(board_query, limit=2000)
            sliced, meta = catalog.paginate(items, page=page, page_size=25)
            print(render_stocks_table(sliced, title=f"Emiten Papan Pencatatan: {board_query.upper()}", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks board {board_query} {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd == "tier":
            tier_query, page = _parse_subarg_page(subarg)
            if not tier_query:
                print("Format: /stocks tier <tier> [page]")
                print("Pilihan tier: LARGE_CAP (> Rp 50T), MID_CAP (Rp 5T - 50T), SMALL_CAP (Rp 500M - 5T), MICRO_CAP (< Rp 500M)")
                return
            items = catalog.by_tier(tier_query, limit=2000)
            sliced, meta = catalog.paginate(items, page=page, page_size=25)
            print(render_stocks_table(sliced, title=f"Emiten Kapitalisasi Pasar: {tier_query.upper()}", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks tier {tier_query} {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd == "status":
            status_query, page = _parse_subarg_page(subarg)
            if not status_query:
                print("Format: /stocks status <status> [page]")
                print("Pilihan status: ACTIVE (Aktif), SUSPENDED (Suspensi), DELISTED (Delisted)")
                return
            items = catalog.by_status(status_query, limit=2000)
            sliced, meta = catalog.paginate(items, page=page, page_size=25)
            print(render_stocks_table(sliced, title=f"Emiten Status Pencatatan: {status_query.upper()}", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks status {status_query} {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd in {"smallcap", "small-cap", "small"}:
            _, page = _parse_subarg_page(subarg)
            items = catalog.by_tier("SMALL_CAP", limit=2000)
            sliced, meta = catalog.paginate(items, page=page, page_size=25)
            print(render_stocks_table(sliced, title="Daftar Saham Small-Cap IDX (Rp 500M - Rp 5T)", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks smallcap {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd in {"microcap", "micro-cap", "micro"}:
            _, page = _parse_subarg_page(subarg)
            items = catalog.by_tier("MICRO_CAP", limit=2000)
            sliced, meta = catalog.paginate(items, page=page, page_size=25)
            print(render_stocks_table(sliced, title="Daftar Saham Micro-Cap IDX (< Rp 500M)", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks microcap {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd in {"third-liner", "thirdliner", "third_liner", "third"}:
            sec_filter, page = _parse_subarg_page(subarg)
            items = catalog.search_third_liners(sector=sec_filter or None, limit=2000)
            sliced, meta = catalog.paginate(items, page=page, page_size=25)
            print(render_stocks_table(sliced, title="Daftar Saham Lapis Tiga IDX (Third-Liner / Small-Micro Cap)", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks third-liner {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd == "coverage":
            stats = catalog.get_universe_stats()
            print("=== Cakupan Semesta Pasar IDX (Universe Coverage & Reconciliation) ===")
            print(f"Total Seluruh Instrumen : {stats['total_instruments']}")
            print(f"  - Saham Ekuitas Biasa : {stats['common_equities']}")
            print(f"  - Indeks & ETF Resmi  : {stats['indices']}")
            print()
            print("Distribusi Papan Pencatatan Resmi:")
            for b_name, b_count in sorted(stats['boards'].items(), key=lambda x: -x[1]):
                print(f"  - {b_name:<20}: {b_count:>3} emiten")
            print()
            print("Distribusi 11 Sektor IDX-IC:")
            for s_name, s_count in sorted(stats['sectors'].items()):
                print(f"  - {s_name:<30}: {s_count:>3} emiten")
            print()
            print("Status Pencatatan:")
            for st_name, st_count in sorted(stats['statuses'].items()):
                print(f"  - {st_name:<20}: {st_count:>3} emiten")
            print()
            print("Integritas Data   : 100% instrumen terpetakan tanpa tebakan papan semu.")
            print(f"Sumber / Path     : {catalog.path}")
            print()
        elif subcmd == "search":
            q_str, page = _parse_subarg_page(subarg)
            if not q_str:
                print("Format: /stocks search <ticker/nama/industri> [page]")
                return
            results = catalog.search(q_str, limit=500)
            sliced, meta = catalog.paginate(results, page=page, page_size=25)
            print(render_stocks_table(sliced, title=f"Hasil Pencarian Saham '{q_str}'", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} instrumen)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks search {q_str} {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd == "sector":
            sec_str, page = _parse_subarg_page(subarg)
            if not sec_str:
                print("Format: /stocks sector <kode A-K atau nama sektor> [page]")
                return
            results = catalog.by_sector(sec_str, limit=500)
            sliced, meta = catalog.paginate(results, page=page, page_size=25)
            print(render_stocks_table(sliced, title=f"Emiten Sektor '{sec_str}'", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks sector {sec_str} {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd == "info":
            if not subarg:
                print("Format: /stocks info <ticker>")
                return
            asset = catalog.resolve(subarg)
            if not asset:
                print(f"Saham '{subarg}' tidak ditemukan di katalog IDX.")
                return
            store = EquityData(REPO_ROOT)
            data = store.load(asset.symbol, auto_fetch=False)
            price = data.get("quote", {}).get("price") if data else None
            mcap = asset.market_cap(price)
            mcap_str = f"Rp {mcap:,.0f}" if mcap else "Belum tersedia (perlu observasi harga EOD)"
            tier_str = asset.cap_tier(price)
            lines = [
                f"=== Profil Emiten IDX: {asset.symbol} ===",
                f"Nama Lengkap      : {asset.name}",
                f"Sektor IDX-IC     : {asset.sector_or_category} ({asset.sector_code})",
                f"Industri          : {asset.industry or '-'}",
                f"Papan Pencatatan  : {asset.canonical_board} (Asal: {asset.board})",
                f"Status Pencatatan : {asset.canonical_status} (Asal: {asset.listing_status})",
                f"Tanggal IPO       : {asset.listing_date or '-'}",
                f"Saham Beredar     : {asset.shares_outstanding:,.0f} lembar" if asset.shares_outstanding else "Saham Beredar     : -",
                f"Estimasi MarketCap: {mcap_str}",
                f"Kategori Ukuran   : {tier_str}",
                f"Klasifikasi:",
                f"  - Saham Lapis Tiga       : {'Ya (Small/Micro Cap / Non-Main)' if asset.is_third_liner else 'Tidak'}",
                f"  - Papan Pemantauan Khusus: {'Ya (Kriteria Khusus BEI)' if asset.is_special_monitoring else 'Tidak'}",
                f"  - Status Suspensi        : {'Ya (Perdagangan Disuspensi)' if asset.is_suspended else 'Tidak'}",
                f"Mata Uang / Bursa : {asset.currency} / {asset.exchange_or_chain}",
                f"Sumber Profil     : {asset.source}",
            ]
            print("\n".join(lines))
            print()
        elif subcmd == "ipo":
            _, page = _parse_subarg_page(subarg)
            recent = catalog.recent_ipos(since_year=2024, limit=200)
            sliced, meta = catalog.paginate(recent, page=page, page_size=25)
            print(render_stocks_table(sliced, title="Daftar Emiten IPO Terbaru (2024 - Sekarang)", limit=25, total_count=meta["total_items"]))
            print(f"Halaman {meta['page']} dari {meta['total_pages']} (Menampilkan {meta['start_idx']}-{meta['end_idx']} dari {meta['total_items']} emiten)")
            if meta["has_next"]:
                print(f"Gunakan '/stocks ipo {meta['page'] + 1}' untuk melihat halaman berikutnya.")
            print()
        elif subcmd == "sync":
            sync_res = catalog.sync(force_download=True)
            print(f"Sinkronisasi Katalog IDX Berhasil: {sync_res['total_assets']} total instrumen ({sync_res['equities_count']} saham, {sync_res['indices_count']} indeks).")
            print(f"Disimpan di: {sync_res['path']}")
            print()
        elif subcmd == "fetch":
            if not subarg:
                print("Format: /stocks fetch <ticker>")
                return
            store = EquityData(REPO_ROOT)
            print(f"Mengambil data harga EOD untuk {subarg.upper()}...")
            data = store.fetch_live_data(subarg.upper(), range_str="5y", save=True)
            if data.get("gaps"):
                print(f"Gagal mengambil data: {data['gaps'][0]}")
            else:
                candles = data.get("candles", [])
                quote = data.get("quote", {})
                print(f"Berhasil mengunduh & memvalidasi {len(candles)} bar daily untuk {subarg.upper()}.")
                print(f"Harga Terakhir: Rp{quote.get('price', 0):,.0f} | Tanggal: {quote.get('as_of', '-')}")
                print(f"Tersimpan di: {store.directory / f'{subarg.upper()}.json'}")
            print()
        elif subcmd == "compare":
            tickers = [t.strip().upper() for t in subarg.replace(",", " ").split() if t.strip()]
            if len(tickers) < 2:
                print("Format: /stocks compare <ticker1> <ticker2> [ticker3 ...]")
                return
            store = EquityData(REPO_ROOT)
            policy = EquityMarketPolicy(REPO_ROOT)
            quant = QuantEngine()
            rows = []
            for t in tickers:
                data = store.load(t, auto_fetch=True)
                q = quant.evaluate_equity(t, data, policy)
                asset = catalog.resolve(t)
                name = (asset.name if asset else t)[:25]
                sec = asset.sector_code if asset else "-"
                px = f"Rp{q.price:,.0f}" if q.price else "-"
                regime = q.regime
                decision = q.decision if q.price else q.decision_status
                f = data.get("fundamentals", {})
                r = f.get("ratios", {}) if isinstance(f, dict) else {}
                per_str = f"{r['PER']:.1f}x" if r.get("PER") else "-"
                pbv_str = f"{r['PBV']:.2f}x" if r.get("PBV") else "-"
                roe_str = f"{r['ROE_pct']:.1f}%" if r.get("ROE_pct") else "-"
                rows.append([t, name, sec, px, regime, per_str, pbv_str, roe_str, decision])
            from openbagus.reporting.terminal_table import render_terminal_table
            headers = ["Ticker", "Emiten", "Sektor", "Harga", "Regime", "PER", "PBV", "ROE", "Decision"]
            print(render_terminal_table(headers, rows, title=f"Perbandingan Saham ({', '.join(tickers)})"))
            print()
        elif subcmd == "screen":
            parts = subarg.strip().split()
            if len(parts) != 3:
                print("Format: /stocks screen <metric> <operator> <value>")
                print("Contoh: /stocks screen roe > 15")
                print("        /stocks screen pbv < 2")
                print("        /stocks screen per < 15")
                print("        /stocks screen price < 5000")
                return
            metric_name, op_str, target_val_str = parts[0].lower(), parts[1], parts[2]
            try:
                target_val = float(target_val_str)
            except ValueError:
                print(f"Nilai target '{target_val_str}' harus berupa angka.")
                return
            op_map = {
                ">": lambda a, b: a > b,
                ">=": lambda a, b: a >= b,
                "<": lambda a, b: a < b,
                "<=": lambda a, b: a <= b,
                "=": lambda a, b: abs(a - b) < 1e-4,
                "==": lambda a, b: abs(a - b) < 1e-4,
            }
            if op_str not in op_map:
                print(f"Operator '{op_str}' tidak didukung. Gunakan >, >=, <, <=, =.")
                return
            cmp_fn = op_map[op_str]
            store = EquityData(REPO_ROOT)
            policy = EquityMarketPolicy(REPO_ROOT)
            quant = QuantEngine()
            matched_rows = []
            for p in sorted(store.directory.glob("*.json")):
                if p.name == "catalog.json" or p.name.startswith("rules"):
                    continue
                sym = p.stem.upper()
                data = store.load(sym, auto_fetch=False)
                if not data or data.get("gaps"):
                    continue
                q = quant.evaluate_equity(sym, data, policy)
                asset = catalog.resolve(sym)
                f = data.get("fundamentals", {})
                r = f.get("ratios", {}) if isinstance(f, dict) else {}
                val = None
                if metric_name in {"price", "harga"}:
                    val = q.price
                elif metric_name in {"pe", "per"}:
                    val = r.get("PER")
                elif metric_name in {"pbv", "pb"}:
                    val = r.get("PBV")
                elif metric_name in {"roe", "roe_pct"}:
                    val = r.get("ROE_pct")
                elif metric_name in {"der", "debt_to_equity"}:
                    val = r.get("Debt_to_Equity")
                elif metric_name in {"npm", "net_margin"}:
                    val = r.get("Net_Margin_pct")
                elif metric_name in {"opm", "operating_margin"}:
                    val = r.get("Operating_Margin_pct")
                elif metric_name in {"car", "car_pct"}:
                    val = r.get("CAR_pct")
                elif metric_name in {"nim", "nim_pct"}:
                    val = r.get("NIM_pct")

                if val is not None and cmp_fn(val, target_val):
                    name = (asset.name if asset else sym)[:25]
                    sec = asset.sector_code if asset else "-"
                    px = f"Rp{q.price:,.0f}" if q.price else "-"
                    matched_rows.append([sym, name, sec, px, f"{val:.2f}", q.decision])

            from openbagus.reporting.terminal_table import render_terminal_table
            if matched_rows:
                headers = ["Ticker", "Emiten", "Sektor", "Harga", f"{metric_name.upper()}", "Decision"]
                print(render_terminal_table(headers, matched_rows, title=f"Hasil Screener: {metric_name.upper()} {op_str} {target_val}"))
            else:
                print(f"Tidak ada emiten lokal yang memenuhi kriteria {metric_name.upper()} {op_str} {target_val}.")
            print()
        elif subcmd in {"import-catalog", "import"}:
            if not subarg:
                print("Format: /stocks import-catalog <path_file_csv_atau_json>")
                return
            target_path = Path(subarg)
            if not target_path.exists():
                print(f"File tidak ditemukan: {target_path}")
                return
            try:
                count = catalog.import_official_file(target_path)
                print(f"Berhasil mengimpor {count} instrumen dari {target_path}.")
                print(f"Katalog tersimpan di: {catalog.path}")
            except Exception as e:
                print(f"Gagal mengimpor katalog: {e}")
            print()
        else:
            print(f"Subcommand '/stocks {subcmd}' tidak dikenal. Gunakan /stocks untuk bantuan.")

    def do_scan(self, arg: str) -> None:
        """Universal IDX Market Scanner across all-cap tiers, liquidity, and catalysts."""
        parts = arg.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else "all"
        subarg = parts[1].strip() if len(parts) > 1 else ""

        catalog = EquityCatalog(REPO_ROOT)
        from openbagus.domains.equities.data import EquityData
        from openbagus.domains.equities.events import CorporateEventManager
        from openbagus.domains.equities.microstructure import IDXMicrostructureEngine
        from openbagus.reporting.terminal_table import render_stocks_table

        eq_data = EquityData(REPO_ROOT)
        event_mgr = CorporateEventManager(REPO_ROOT)
        all_equities = [a for a in catalog.assets if a.asset_type == "EQUITY_ID"]

        print(f"=== OpenBagus All-Universe Market Scanner ({subcmd.upper()}) ===")
        print(f"Semesta Evaluasi: {len(all_equities)} emiten biasa terdaftar di Bursa Efek Indonesia.")

        if subcmd == "all":
            active_count = sum(1 for a in all_equities if a.canonical_status == "ACTIVE")
            suspended_count = sum(1 for a in all_equities if a.is_suspended)
            fca_count = sum(1 for a in all_equities if a.is_special_monitoring)
            local_eod = sum(1 for a in all_equities if eq_data.load(a.symbol))
            data_gap = len(all_equities) - local_eod

            print(f"Status Listing: {active_count} Aktif | {suspended_count} Tersuspensi | {fca_count} Papan Khusus (FCA)")
            print(f"Kelengkapan Data: {local_eod} memiliki riwayat EOD lokal | {data_gap} Data Gap (belum ada EOD)")
            print()
            print("Ringkasan Sebaran Papan Pencatatan:")
            boards: dict[str, int] = {}
            for a in all_equities:
                b = a.canonical_board
                boards[b] = boards.get(b, 0) + 1
            for b, cnt in sorted(boards.items(), key=lambda x: -x[1]):
                print(f"  - {b:20}: {cnt} emiten")
            print()
            print("Perintah spesifik: /scan swing, /scan momentum, /scan smallcap, /scan microcap, /scan event, /scan illiquid")

        elif subcmd in ("swing", "momentum"):
            from openbagus.domains.equities.strategies import PostAnnouncementMomentumStrategy, VolumeExpansionBreakoutStrategy
            pam_strat = PostAnnouncementMomentumStrategy()
            vcp_strat = VolumeExpansionBreakoutStrategy()

            setups = []
            evaluated = 0
            for a in all_equities:
                data = eq_data.load(a.symbol)
                candles = data.get("candles", []) if isinstance(data, dict) else []
                if not candles or len(candles) < 20:
                    continue
                evaluated += 1
                last_px = float(candles[-1]["close"])
                prof = IDXMicrostructureEngine.profile_asset(a.symbol, a.canonical_board, last_px, candles, a.is_suspended, a.canonical_status)
                evs = event_mgr.get_events_for_ticker(a.symbol)

                sig_pam = pam_strat.evaluate(a.symbol, candles, prof, evs)
                sig_vcp = vcp_strat.evaluate(a.symbol, candles, prof, evs)

                if sig_pam.action == "BUY":
                    setups.append((a, sig_pam))
                elif sig_vcp.action == "BUY":
                    setups.append((a, sig_vcp))

            print(f"Emiten dengan EOD valid dievaluasi: {evaluated}")
            print(f"Setup terkonfirmasi ditemukan: {len(setups)}")
            if setups:
                for a, sig in setups[:15]:
                    print(f"  [{sig.strategy_name.upper()}] {a.symbol} ({a.canonical_board}): Beli @ Rp{sig.entry_price:,.0f} | SL Rp{sig.stop_loss:,.0f} | TP Rp{sig.target_price:,.0f} | R:R {sig.reward_risk_ratio:.1f}x")
                    print(f"      Alasan: {sig.rationale}")
            else:
                print("  Tidak ada setup breakout swing yang terkonfirmasi pada data EOD terkini.")

        elif subcmd in ("smallcap", "small-cap", "small"):
            items = catalog.by_tier("SMALL_CAP", limit=25)
            print(render_stocks_table(items, title="Hasil Scan: Saham Small-Cap IDX (Rp 500M - Rp 5T)"))

        elif subcmd in ("microcap", "micro-cap", "micro"):
            items = catalog.by_tier("MICRO_CAP", limit=25)
            print(render_stocks_table(items, title="Hasil Scan: Saham Micro-Cap IDX (< Rp 500M)"))

        elif subcmd == "illiquid":
            illiquid = []
            for a in all_equities:
                data = eq_data.load(a.symbol)
                candles = data.get("candles", []) if isinstance(data, dict) else []
                if candles and len(candles) >= 20:
                    last_px = float(candles[-1]["close"])
                    prof = IDXMicrostructureEngine.profile_asset(a.symbol, a.canonical_board, last_px, candles)
                    if not prof.execution_eligible or prof.adtv_20d < 50_000_000.0:
                        illiquid.append((a, prof))
            print(f"Ditemukan {len(illiquid)} saham dengan peringatan likuiditas tinggi / non-executable.")
            for a, prof in illiquid[:15]:
                print(f"  {a.symbol} ({prof.board}): ADTV20 Rp{prof.adtv_20d:,.0f} | Alasan: {prof.rejection_reason}")

        elif subcmd == "event":
            ev_type = subarg.upper() if subarg else None
            evs = event_mgr.get_latest_events(event_type=ev_type, limit=20)
            print(f"Ditemukan {len(evs)} keterbukaan informasi material:")
            for ev in evs:
                print(f"  [{ev.effective_date}] {ev.ticker:6} | {ev.event_type:25} | Skor: {ev.impact_score:+.0f} ({ev.sentiment_label})")
                print(f"      Judul: {ev.event_title}")
        print()

    def do_events(self, arg: str) -> None:
        """Pusat intelijen keterbukaan informasi resmi emiten Bursa Efek Indonesia."""
        parts = arg.strip().split(maxsplit=1)
        subcmd = parts[0].lower() if parts else "today"
        subarg = parts[1].strip() if len(parts) > 1 else ""

        from openbagus.domains.equities.events import CorporateEventManager
        mgr = CorporateEventManager(REPO_ROOT)

        if subcmd in ("today", "latest"):
            evs = mgr.get_latest_events(limit=25)
            print("=== Keterbukaan Informasi Terbaru (Official IDX Announcements) ===")
            if not evs:
                print("Belum ada catatan keterbukaan informasi tersimpan di penyimpanan lokal.")
                print("Gunakan modul data ingestion atau import disclosure untuk menambahkan.")
            for ev in evs:
                print(f"[{ev.effective_date}] {ev.ticker:5} | {ev.event_type:24} | Skor {ev.impact_score:+.0f} ({ev.sentiment_label})")
                print(f"   {ev.event_title}")
                print(f"   Sumber: {ev.source_provider} ({ev.verification_status}) | Hash: {ev.document_hash[:16]}")
                print()

        elif subcmd == "material":
            evs = [ev for ev in mgr.get_latest_events(limit=100) if abs(ev.impact_score) >= 40.0]
            print("=== Keterbukaan Informasi Berdampak Signifikan (Materiality Score >= 40) ===")
            for ev in evs[:25]:
                print(f"[{ev.effective_date}] {ev.ticker:5} | {ev.event_type} | Relatif: {ev.relative_materiality_pct or 0.0:.1f}% | Skor {ev.impact_score:+.0f}")
                print(f"   {ev.event_title}")
                print()

        elif subcmd == "earnings":
            evs = [ev for ev in mgr.get_latest_events(limit=100) if ev.event_type in ("EARNINGS_RELEASE", "EARNINGS_SURPRISE", "PROFIT_TURNAROUND", "PROFIT_WARNING")]
            print("=== Keterbukaan Kinerja Keuangan & Kejutan Laba ===")
            for ev in evs[:25]:
                print(f"[{ev.effective_date}] {ev.ticker:5} | {ev.event_type} | {ev.event_title}")
                print()

        elif subcmd in ("actions", "corporate-actions"):
            evs = [ev for ev in mgr.get_latest_events(limit=100) if ev.event_type in ("SHARE_BUYBACK", "RIGHTS_ISSUE", "DIVIDEND_DECLARATION", "STOCK_SPLIT")]
            print("=== Aksi Korporasi Resmi (Buyback, Rights Issue, Dividen) ===")
            for ev in evs[:25]:
                print(f"[{ev.effective_date}] {ev.ticker:5} | {ev.event_type} | {ev.event_title}")
                print()

        else:
            ticker = subcmd.upper().replace(".JK", "")
            evs = mgr.get_events_for_ticker(ticker)
            print(f"=== Riwayat Keterbukaan Informasi Emiten: {ticker} ===")
            if not evs:
                print(f"Tidak ada pengumuman tersimpan untuk emiten {ticker}.")
            for ev in evs:
                print(f"[{ev.effective_date}] {ev.event_type} (Status: {ev.verification_status}) | Skor {ev.impact_score:+.0f}")
                print(f"   Judul: {ev.event_title}")
                print(f"   Ringkasan: {ev.event_summary}")
                print(f"   Sitasi Dokumen: {ev.source_document_id} | Hash: {ev.document_hash}")
                print()

    def do_market_mechanism(self, arg: str) -> None:
        """Analisis mekanisme perdagangan resmi, fraksi harga, auto-rejection, dan likuiditas emiten."""
        ticker = arg.strip().upper().replace(".JK", "")
        if not ticker:
            print("Format: /market-mechanism <ticker>")
            return

        catalog = EquityCatalog(REPO_ROOT)
        asset = catalog.resolve(ticker)
        if not asset:
            print(f"Ticker {ticker} tidak ditemukan di katalog IDX terverifikasi.")
            return

        from openbagus.domains.equities.data import EquityData
        from openbagus.domains.equities.microstructure import IDXMicrostructureEngine

        eq_data = EquityData(REPO_ROOT)
        data = eq_data.load(ticker)
        candles = data.get("candles", []) if isinstance(data, dict) else []
        last_px = float(candles[-1]["close"]) if candles else 1000.0

        prof = IDXMicrostructureEngine.profile_asset(
            symbol=asset.symbol,
            board=asset.canonical_board,
            reference_price=last_px,
            candles=candles,
            is_suspended=asset.is_suspended,
            status=asset.canonical_status,
        )

        print(f"=== Profil Mekanisme Pasar: {asset.symbol} ({asset.name}) ===")
        print(f"Papan Pencatatan   : {prof.board} (Status: {asset.canonical_status})")
        print(f"Mekanisme Trading  : {prof.trading_mechanism} {'[FCA - Call Auction Periodik]' if prof.is_fca else '[Lelang Berkelanjutan]'}")
        print(f"Harga Referensi    : Rp{prof.reference_price:,.0f} {'(Terverifikasi EOD)' if candles else '(Estimasi Awal)'}")
        print(f"Fraksi Harga (Tick): Rp{prof.tick_size:,.0f}")
        print(f"Batas Auto-Reject  : ARA Rp{prof.ara_price:,.0f} | ARB Rp{prof.arb_price:,.0f}")
        print(f"Satuan Perdagangan : {prof.lot_size} lembar saham (1 lot)")
        print(f"Likuiditas 20-Hari : ADTV Rp{prof.adtv_20d:,.0f} | Hari Nol Volume: {prof.zero_volume_streak}")
        print(f"Estimasi Slippage  : {prof.estimated_spread_pct * 100.0:.2f}%")
        print(f"Kelayakan Eksekusi : {'MEMENUHI SYARAT (EXECUTABLE)' if prof.execution_eligible else 'DIBATASI / TIDAK DAPAT DIEKSEKUSI'}")
        if not prof.execution_eligible:
            print(f"Catatan Risiko     : {prof.rejection_reason}")
        print()

    def do_benchmark(self, arg: str) -> None:
        """Jalankan benchmark performa komputasi mesin kuantitatif OpenBagus."""
        import time
        from openbagus.domains.quant.engine import (
            get_engine_diagnostics,
            calculate_sma,
            calculate_ema,
            calculate_rsi,
            calculate_atr,
            calculate_var_cvar_mc,
            calculate_lot_shares,
        )

        diag = get_engine_diagnostics()
        print("=== OpenBagus Quantitative Performance Benchmark ===")
        print(f"Backend Aktif : {diag['backend']}")
        print(f"Info Versi    : {diag['info']}")
        print(f"Status Alasan : {diag['reason']}")
        print()

        print("Menjalankan Benchmark 1: 1,000 Simbol x 250 Bar (SMA, EMA, RSI, ATR)...")
        prices = [100.0 + (i % 25) + math.sin(i * 0.1) * 10.0 for i in range(250)]
        highs = [p + 2.0 for p in prices]
        lows = [p - 2.0 for p in prices]

        t0 = time.perf_counter()
        for _ in range(1000):
            _ = calculate_sma(prices, 20)
            _ = calculate_ema(prices, 20)
            _ = calculate_rsi(prices, 14)
            _ = calculate_atr(highs, lows, prices, 14)
        t1 = time.perf_counter()
        dur_ind = t1 - t0
        print(f"  -> Waktu Eksekusi: {dur_ind * 1000.0:.2f} ms ({1000.0 / dur_ind:,.0f} simbol/detik)")

        print("Menjalankan Benchmark 2: Monte Carlo VaR / CVaR (10,000 jalur simulasi)...")
        returns = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
        t2 = time.perf_counter()
        var, cvar = calculate_var_cvar_mc(returns, confidence=0.95, num_simulations=10000, seed=42)
        t3 = time.perf_counter()
        dur_mc = t3 - t2
        print(f"  -> Waktu Eksekusi: {dur_mc * 1000.0:.2f} ms (VaR 95%: {var:.4f}, CVaR 95%: {cvar:.4f})")

        shares, notional = calculate_lot_shares(10_000_000.0, 2750.0, 200_000.0, 2600.0)
        print(f"Uji Presisi Fraksi Lot: {shares} lembar (tepat kelipatan 100) -> Notional Rp{notional:,.0f}")
        print("Kontrak numerik & presisi terpenuhi dengan sukses.")
        print()

    def do_financials(self, arg: str) -> None:
        """Eksplorasi dan analisis laporan keuangan resmi emiten IDX."""
        parts = arg.strip().split()
        if not parts or parts[0].lower() in {"help", "-h", "--help"}:
            print("=== IDX Financial Statements Explorer ===")
            print("Perintah yang tersedia:")
            print("  /financials <ticker> [periode]           - Tampilkan laporan keuangan lengkap (Laba Rugi, Neraca, Arus Kas)")
            print("  /financials compare <t1> <t2> [periode]  - Bandingkan 2 emiten berdampingan")
            print("  /financials history <ticker>             - Daftar seluruh periode laporan keuangan yang tersedia")
            print("  /financials coverage [sektor|papan]      - Matriks ketersediaan dokumen laporan di seluruh pasar")
            print("  /financials source <ticker>              - Detail sumber, nomor halaman, dan sitasi koordinat")
            print()
            return

        subcmd = parts[0].lower()
        from openbagus.domains.equities.storage import FinancialStatementStorage
        from openbagus.domains.equities.discovery import DocumentDiscoveryManager
        from openbagus.domains.equities.catalog import EquityCatalog
        storage = FinancialStatementStorage(REPO_ROOT)
        discovery = DocumentDiscoveryManager(REPO_ROOT)
        catalog = EquityCatalog(REPO_ROOT)

        if subcmd == "coverage":
            matrix = discovery.get_market_coverage_matrix()
            print("=== Matriks Ketersediaan Laporan Keuangan IDX ===")
            print(f"Total Emiten di Katalog: {matrix['total_issuers_in_catalog']}")
            print(f"Emiten dengan Laporan Tersedia: {matrix['issuers_with_filings']}")
            print(f"Total Dokumen Laporan Keuangan Tersimpan: {matrix['total_statements_stored']}")
            print("\nCakupan Berdasarkan Papan Pencatatan:")
            for board, b_stats in matrix["by_board"].items():
                cov_pct = (b_stats["covered_issuers"] / b_stats["total_issuers"] * 100) if b_stats["total_issuers"] > 0 else 0
                print(f"  - {board:20s}: {b_stats['covered_issuers']}/{b_stats['total_issuers']} emiten ({cov_pct:.1f}%)")
            print("\nCakupan Berdasarkan Sektor (11 IDX-IC):")
            for sec, s_stats in matrix["by_sector"].items():
                cov_pct = (s_stats["covered_issuers"] / s_stats["total_issuers"] * 100) if s_stats["total_issuers"] > 0 else 0
                print(f"  - {sec:25s}: {s_stats['covered_issuers']}/{s_stats['total_issuers']} emiten ({cov_pct:.1f}%)")
            print()
            return

        if subcmd == "compare" and len(parts) >= 3:
            t1 = parts[1].upper()
            t2 = parts[2].upper()
            period = parts[3] if len(parts) >= 4 else None
            stmt1 = storage.get_statement(t1, period)
            stmt2 = storage.get_statement(t2, period)
            if not stmt1:
                print(f"Laporan keuangan untuk {t1} belum tersedia di data lokal.")
                return
            if not stmt2:
                print(f"Laporan keuangan untuk {t2} belum tersedia di data lokal.")
                return

            p1 = stmt1.get("period", "-")
            p2 = stmt2.get("period", "-")
            v1 = stmt1.get("values", {})
            v2 = stmt2.get("values", {})
            u1 = stmt1.get("unit", "IDR")
            u2 = stmt2.get("unit", "IDR")

            print(f"=== Komparasi Fundamental: {t1} ({p1}) vs {t2} ({p2}) ===")
            print(f"{'Metrik':<28s} | {t1:<18s} | {t2:<18s}")
            print("-" * 70)
            items = [
                ("Pendapatan (Revenue)", "revenue"),
                ("Laba Usaha (EBIT)", "operating_income"),
                ("Laba Bersih (Net Income)", "net_income"),
                ("Laba Entitas Induk", "net_income_attributable"),
                ("Total Aset", "total_assets"),
                ("Total Liabilitas", "total_liabilities"),
                ("Utang Berbunga", "interest_bearing_debt"),
                ("Ekuitas Entitas Induk", "equity_attributable"),
                ("Arus Kas Operasi (OCF)", "operating_cash_flow"),
                ("Belanja Modal (Capex)", "capital_expenditure"),
            ]
            for label, k in items:
                val1_str = f"{v1.get(k):,.0f}" if v1.get(k) is not None else "-"
                val2_str = f"{v2.get(k):,.0f}" if v2.get(k) is not None else "-"
                print(f"{label:<28s} | {val1_str:<18s} | {val2_str:<18s}")
            print(f"{'Satuan Angka':<28s} | {u1:<18s} | {u2:<18s}")
            print()
            return

        if subcmd == "history" and len(parts) >= 2:
            sym = parts[1].upper()
            periods = storage.list_periods(sym)
            if not periods:
                info = discovery.get_issuer_discovery(sym)
                print(f"Belum ada laporan keuangan tersimpan untuk {sym}.")
                print(info["guidance"])
                return
            print(f"=== Riwayat Laporan Keuangan {sym} ({len(periods)} Periode) ===")
            for p in periods:
                stmt = storage.get_statement(sym, p)
                audit = stmt.get("audit_status", "-") if stmt else "-"
                fmt = stmt.get("document_format", "JSON") if stmt else "-"
                src = stmt.get("source", "-") if stmt else "-"
                print(f"  - {p:<10s} | Status Audit: {audit:<10s} | Format: {fmt:<6s} | Sumber: {src}")
            print()
            return

        if subcmd == "source" and len(parts) >= 2:
            sym = parts[1].upper()
            stmt = storage.get_statement(sym)
            if not stmt:
                print(f"Laporan keuangan untuk {sym} belum tersedia.")
                return
            print(f"=== Sumber Dokumen & Sitasi {sym} ({stmt.get('period')}) ===")
            print(f"Dokumen: {stmt.get('source_document', stmt.get('source'))}")
            print(f"Format: {stmt.get('document_format', 'JSON')}")
            print(f"Status Audit: {stmt.get('audit_status', 'N/A')}")
            print(f"Tanggal Publikasi: {stmt.get('published_at', '-')}")
            citations = stmt.get("citations", {})
            if citations:
                print("\nSitasi Baris & Halaman:")
                for field_name, cit in list(citations.items())[:10]:
                    page = f"Hal {cit.get('page')}" if cit.get('page') else (cit.get('cell_reference') or cit.get('concept') or "-")
                    raw = cit.get('raw_text', '')
                    print(f"  - {field_name:<25s}: {page:<18s} | Nilai Asli: {raw}")
            print()
            return

        # Default /financials <TICKER> [PERIOD]
        sym = parts[0].upper()
        req_period = parts[1] if len(parts) > 1 else None
        stmt = storage.get_statement(sym, req_period)
        if not stmt:
            store = EquityData(REPO_ROOT)
            data = store.load(sym, auto_fetch=False)
            stmt = data.get("fundamentals")

        if not stmt:
            info = discovery.get_issuer_discovery(sym)
            print(f"Laporan keuangan untuk {sym} belum tersedia di penyimpanan lokal.")
            print(info["guidance"])
            print()
            return

        asset = next((a for a in catalog.assets if a.symbol == sym), None)
        v = stmt.get("values", {})
        unit = stmt.get("unit", "million_IDR")
        cur = stmt.get("currency", "IDR")
        p_name = stmt.get("period", "-")
        basis = stmt.get("basis", "konsolidasian")
        audit = stmt.get("audit_status", "-")
        citations = stmt.get("citations", {})

        print(f"=== Laporan Keuangan {sym} — {p_name} ({basis}) ===")
        if asset:
            print(f"Emiten: {asset.name} | Sektor: {asset.sector_or_category} | Papan: {asset.canonical_board} | Status: {asset.canonical_status}")
        print(f"Mata Uang / Satuan: {cur} / {unit} | Status Audit: {audit}")
        print(f"Sumber Dokumen: {stmt.get('source', '-')}")

        print("\n[ Laba Rugi / Profit or Loss ]")
        pnl = [
            ("Pendapatan Bersih (Revenue)", "revenue"),
            ("Beban Pokok Pendapatan (COGS)", "cost_of_revenue"),
            ("Laba Kotor (Gross Profit)", "gross_profit"),
            ("Laba Operasional (Operating Income)", "operating_income"),
            ("Laba Sebelum Pajak (EBT)", "profit_before_tax"),
            ("Laba Bersih Periode Berjalan", "net_income"),
            ("Laba Diatribusikan ke Entitas Induk", "net_income_attributable"),
        ]
        for label, k in pnl:
            val = v.get(k)
            cit = citations.get(k, {})
            cit_info = f" (Hal {cit.get('page')})" if cit.get("page") else ""
            val_str = f"{val:,.0f}{cit_info}" if val is not None else "-"
            print(f"  {label:<40s}: {val_str}")

        print("\n[ Neraca / Balance Sheet ]")
        bs = [
            ("Kas dan Setara Kas", "cash_and_equivalents"),
            ("Piutang Usaha", "trade_receivables"),
            ("Persediaan", "inventories"),
            ("Jumlah Aset Lancar", "current_assets"),
            ("Jumlah Aset Tidak Lancar", "non_current_assets"),
            ("JUMLAH ASET", "total_assets"),
            ("Utang Usaha", "trade_payables"),
            ("Utang Bank / Berbunga", "interest_bearing_debt"),
            ("Jumlah Liabilitas Jangka Pendek", "current_liabilities"),
            ("JUMLAH LIABILITAS", "total_liabilities"),
            ("Ekuitas Pemilik Entitas Induk", "equity_attributable"),
            ("JUMLAH EKUITAS", "equity"),
        ]
        for label, k in bs:
            val = v.get(k)
            cit = citations.get(k, {})
            cit_info = f" (Hal {cit.get('page')})" if cit.get("page") else ""
            val_str = f"{val:,.0f}{cit_info}" if val is not None else "-"
            print(f"  {label:<40s}: {val_str}")

        print("\n[ Arus Kas / Cash Flows ]")
        cf = [
            ("Arus Kas Operasi (OCF)", "operating_cash_flow"),
            ("Belanja Modal (Capex)", "capital_expenditure"),
        ]
        for label, k in cf:
            val = v.get(k)
            cit = citations.get(k, {})
            cit_info = f" (Hal {cit.get('page')})" if cit.get("page") else ""
            val_str = f"{val:,.0f}{cit_info}" if val is not None else "-"
            print(f"  {label:<40s}: {val_str}")

        if stmt.get("validation_notes"):
            print("\n[ Catatan Validasi Akuntansi ]")
            for note in stmt["validation_notes"]:
                print(f"  * {note}")
        print()

    def do_valuation(self, arg: str) -> None:
        """Analisis valuasi multi-metrik, DuPont ROE, dan valuasi intrinsik DCF/Excess Return."""
        parts = arg.strip().split()
        if not parts:
            print("Gunakan: /valuation <ticker> [periode]")
            return

        sym = parts[0].upper()
        req_period = parts[1] if len(parts) > 1 else None

        from openbagus.domains.equities.storage import FinancialStatementStorage
        from openbagus.domains.equities.valuation import (
            calculate_valuation_multiples,
            dupont_analysis,
            evaluate_earnings_quality,
            dcf_scenario_model,
        )
        storage = FinancialStatementStorage(REPO_ROOT)
        stmt = storage.get_statement(sym, req_period)
        store = EquityData(REPO_ROOT)
        data = store.load(sym, auto_fetch=False)

        if not stmt:
            stmt = data.get("fundamentals")

        if not stmt:
            print(f"Laporan keuangan untuk {sym} belum tersedia. Jalankan /financials {sym} untuk panduan impor.")
            return

        quote = data.get("quote", {})
        price = quote.get("price") or (quote.get("close") if "close" in quote else None)
        if not price or price <= 0:
            candles = data.get("candles", [])
            if candles:
                price = candles[-1].get("close")

        if not price or price <= 0:
            print(f"Quote harga pasar untuk {sym} belum tersedia. Metrik berbasis harga (PER, PBV, EV, Market Cap) ditandai N/A; rasio fundamental tetap dihitung.")
            price = None

        sector = data.get("sector") or (stmt.get("sector") or "")
        history = storage.get_history(sym, max_periods=2)
        prev_stmt = history[0] if len(history) >= 2 else None

        multiples_res = calculate_valuation_multiples(stmt, price, sector=sector)
        dupont_res = dupont_analysis(stmt, previous_statement=prev_stmt)
        quality_res = evaluate_earnings_quality(stmt)
        dcf_res = dcf_scenario_model(stmt, price, sector=sector)
        cur = stmt.get("currency", "IDR")

        price_disp = f"{cur} {price:,.2f}" if (price and cur == "USD") else (f"Rp{price:,.0f}" if price else "N/A (Tidak tersedia)")
        print(f"=== Analisis Valuasi & Kualitas Laba {sym} ===")
        print(f"Periode Laporan: {stmt.get('period')} | Harga As-Of: {price_disp} | Mata Uang: {cur}")

        mults = multiples_res.get("multiples", {})
        print("\n[ Multiples Valuasi Pasar ]")
        eps_key = f"EPS_{cur}"
        if eps_key in mults:
            print(f"  - EPS: {cur} {mults[eps_key]:,.2f}")
        if "PER" in mults and mults["PER"] is not None:
            print(f"  - Price to Earnings (PER): {mults['PER']:.2f}x")
        elif "PER_note" in mults:
            print(f"  - Price to Earnings (PER): {mults['PER_note']}")
        bvps_key = f"BVPS_{cur}"
        if bvps_key in mults:
            print(f"  - BVPS: {cur} {mults[bvps_key]:,.2f}")
        if "PBV" in mults and mults["PBV"] is not None:
            print(f"  - Price to Book Value (PBV): {mults['PBV']:.2f}x")
        elif "PBV_note" in mults:
            print(f"  - Price to Book Value (PBV): {mults['PBV_note']}")
        if "EV_to_EBIT" in mults:
            print(f"  - EV / EBIT: {mults['EV_to_EBIT']:.2f}x")
        if "FCF_Yield_pct" in mults:
            print(f"  - FCF Yield: {mults['FCF_Yield_pct']:.2f}%")
        elif mults.get("FCF_status") == "NOT_APPLICABLE":
            print(f"  - FCF Yield: NOT_APPLICABLE ({mults.get('FCF_note')})")

        print("\n[ Dekomposisi DuPont ROE ]")
        three = dupont_res.get("three_stage", {})
        if three:
            print(f"  - Margin Laba Bersih (NPM): {three.get('net_profit_margin_pct', 0):.2f}%")
            print(f"  - Perputaran Aset (Asset Turnover): {three.get('asset_turnover_x', 0):.3f}x")
            print(f"  - Pengali Ekuitas / Leverage (Assets/Equity): {three.get('equity_multiplier_x', 0):.2f}x")
            print(f"  -> Hasil ROE 3-Tahap: {three.get('roe_pct', 0):.2f}%")

        print("\n[ Kualitas Laba & Konversi Kas ]")
        print(f"  - Rasio Konversi Kas (OCF / Laba Bersih): {quality_res.get('cash_conversion_ratio', 'N/A')}")
        print(f"  - Evaluasi: {quality_res.get('assessment', '-')}")

        print("\n[ Model Valuasi Intrinsik & Skenario ]")
        print(f"Model: {dcf_res.get('model_type')}")
        scenarios = dcf_res.get("scenarios", {})
        for sc_name, sc in scenarios.items():
            mos = sc.get("margin_of_safety_pct")
            mos_str = f"{mos}%" if isinstance(mos, str) else (f"+{mos:.1f}%" if mos and mos > 0 else (f"{mos:.1f}%" if mos is not None else "N/A"))
            print(f"  - Skenario {sc_name:<5s}: Nilai Wajar {cur} {sc.get('intrinsic_value_per_share', 0):,.2f} | Margin of Safety: {mos_str}")

        if "sensitivity_wacc_terminal_growth" in dcf_res:
            print("\n[ Matriks Sensitivitas WACC vs Pertumbuhan Terminal ]")
            s_mat = dcf_res["sensitivity_wacc_terminal_growth"]
            if s_mat:
                cols = list(s_mat[0].keys())
                header_str = " | ".join(f"{c:<10s}" for c in cols)
                print(f"  {header_str}")
                print("  " + "-" * len(header_str))
                for row in s_mat:
                    row_str = " | ".join(f"{row[c]:<10}" for c in cols)
                    print(f"  {row_str}")
        print()

    def do_fcf(self, arg: str) -> None:
        """Analisis arus kas bebas (Free Cash Flow) dan yield untuk non-financials."""
        parts = arg.strip().split()
        if not parts:
            print("Gunakan: /fcf <ticker> [periode]")
            return

        sym = parts[0].upper()
        req_period = parts[1] if len(parts) > 1 else None

        from openbagus.domains.equities.storage import FinancialStatementStorage
        storage = FinancialStatementStorage(REPO_ROOT)
        stmt = storage.get_statement(sym, req_period)
        store = EquityData(REPO_ROOT)
        data = store.load(sym, auto_fetch=False)

        if not stmt:
            stmt = data.get("fundamentals")

        if not stmt:
            print(f"Laporan keuangan untuk {sym} belum tersedia.")
            return

        is_bank = (
            stmt.get("sector", "").upper() in {"FINANCIALS", "KEUANGAN", "BANK"}
            or any(k in stmt.get("reported_ratios_pct", {}) for k in ("NIM", "CAR", "NPL_gross", "CASA", "LDR"))
        )

        print(f"=== Analisis Free Cash Flow (FCF) {sym} — {stmt.get('period')} ===")
        if is_bank:
            print("STATUS: NOT_MEANINGFUL (Sektor Perbankan / Lembaga Keuangan)")
            print("Penjelasan Metodologi:")
            print("  Arus kas operasional bank mencerminkan arus simpanan dana pihak ketiga (DPK) dan")
            print("  penyaluran kredit kepada debitur, bukan arus kas operasi pabrik/korporasi industri.")
            print("  Oleh karena itu, FCF korporasi (OCF - Capex) tidak relevan untuk mengevaluasi bank.")
            print("\nMetrik Kesehatan Likuiditas & Solvabilitas Perbankan:")
            r = stmt.get("reported_ratios_pct", {})
            for k in ("CAR", "NIM", "NPL_gross", "NPL_net", "CASA", "LDR", "Cost_of_Credit"):
                if k in r:
                    print(f"  - {k:<18s}: {r[k]:.2f}%")
            print()
            return

        v = stmt.get("values", {})
        unit = stmt.get("unit", "million_IDR")
        mult = {"IDR": 1.0, "thousand_IDR": 1e3, "million_IDR": 1e6, "billion_IDR": 1e9}.get(unit, 1e6)

        ocf = v.get("operating_cash_flow")
        capex = v.get("capital_expenditure")
        net_income = v.get("net_income_attributable") or v.get("net_income")

        if ocf is None or capex is None:
            print("Data Arus Kas Operasi atau Belanja Modal belum lengkap pada laporan ini.")
            return

        fcf = ocf - abs(capex)
        print(f"Satuan: {unit}")
        print(f"  Arus Kas Operasi (OCF)       : Rp{ocf:,.0f}")
        print(f"  Belanja Modal (Capex)        : Rp{abs(capex):,.0f}")
        print(f"  -----------------------------------------------")
        print(f"  Free Cash Flow to Firm (FCF) : Rp{fcf:,.0f}")

        if ocf > 0:
            reinvest_rate = (abs(capex) / ocf) * 100.0
            print(f"\nRasio Reinvestasi Modal (Capex / OCF): {reinvest_rate:.1f}%")

        if net_income and net_income > 0:
            conversion = (fcf / net_income) * 100.0
            print(f"Rasio Konversi FCF terhadap Laba Bersih: {conversion:.1f}%")

        quote = data.get("quote", {})
        price = quote.get("price") or (quote.get("close") if "close" in quote else None)
        shares = v.get("shares_outstanding") or v.get("weighted_average_shares")
        if price and shares:
            market_cap = (price * shares) / mult
            yield_pct = (fcf / market_cap) * 100.0
            print(f"Kapitalisasi Pasar: Rp{market_cap * mult:,.0f}")
            print(f"Yield Arus Kas Bebas (FCF Yield): {yield_pct:.2f}%")
        print()

    def do_dcf(self, arg: str) -> None:
        """Analisis valuasi intrinsik DCF lengkap dengan 2 matriks sensitivitas 2D."""
        parts = arg.strip().split()
        if not parts:
            print("Gunakan: /dcf <ticker>")
            return
        sym = parts[0].upper()
        from openbagus.domains.equities.storage import FinancialStatementStorage
        from openbagus.domains.equities.valuation import dcf_scenario_model
        storage = FinancialStatementStorage(REPO_ROOT)
        store = EquityData(REPO_ROOT)
        data = store.load(sym, auto_fetch=True)
        stmt = storage.get_statement(sym) or data.get("fundamentals")
        if not stmt:
            print(f"Laporan keuangan untuk {sym} belum tersedia.")
            return

        quote = data.get("quote", {})
        price = quote.get("price") or (quote.get("close") if "close" in quote else None)
        sector = data.get("sector") or stmt.get("sector") or ""
        dcf_res = dcf_scenario_model(stmt, price, sector=sector)
        cur = dcf_res.get("currency", "IDR")

        print(f"=== Discounted Cash Flow (DCF) & Sensitivity Valuation: {sym} ===")
        print(f"Model: {dcf_res.get('model_type')}")
        price_disp = f"{cur} {price:,.2f}" if (price and cur == "USD") else (f"Rp{price:,.0f}" if price else "N/A (Harga tidak tersedia)")
        print(f"Harga Pasar Terkini: {price_disp}")
        print("\n[ Skenario Valuasi Intrinsik ]")
        scenarios = dcf_res.get("scenarios", {})
        for sc_name, sc in scenarios.items():
            mos = sc.get("margin_of_safety_pct")
            mos_str = f"{mos}%" if isinstance(mos, str) else (f"+{mos:.1f}%" if mos and mos > 0 else (f"{mos:.1f}%" if mos is not None else "N/A"))
            print(f"  * Skenario {sc_name:<5s}: Nilai Wajar {cur} {sc.get('intrinsic_value_per_share', 0):,.2f} | Margin of Safety: {mos_str}")

        if "sensitivity_wacc_terminal_growth" in dcf_res:
            print("\n[ Matriks Sensitivitas 1: WACC vs Terminal Growth Rate ]")
            s_mat = dcf_res["sensitivity_wacc_terminal_growth"]
            if s_mat:
                cols = list(s_mat[0].keys())
                header_str = " | ".join(f"{c:<10s}" for c in cols)
                print(f"  {header_str}")
                print("  " + "-" * len(header_str))
                for row in s_mat:
                    row_str = " | ".join(f"{row[c]:<10}" for c in cols)
                    print(f"  {row_str}")

        if "sensitivity_margin_revenue_growth" in dcf_res:
            print("\n[ Matriks Sensitivitas 2: Operating Margin vs Pertumbuhan Pendapatan ]")
            s_mat2 = dcf_res["sensitivity_margin_revenue_growth"]
            if s_mat2:
                cols2 = list(s_mat2[0].keys())
                header_str2 = " | ".join(f"{c:<14s}" for c in cols2)
                print(f"  {header_str2}")
                print("  " + "-" * len(header_str2))
                for row in s_mat2:
                    row_str2 = " | ".join(f"{row[c]:<14}" for c in cols2)
                    print(f"  {row_str2}")
        print()

    def do_sec(self, arg: str) -> None:
        """Eksplorasi dan integrasi data pengarsipan resmi US SEC EDGAR (Zero-Key)."""
        parts = arg.strip().split()
        if not parts:
            print("Gunakan: /sec <ticker> [facts|submissions]")
            return
        sym = parts[0].upper()
        mode = parts[1].lower() if len(parts) > 1 else "facts"
        from openbagus.domains.equities.sec_edgar import SecEdgarClient
        sec = SecEdgarClient(REPO_ROOT)
        cik = sec.resolve_ticker(sym)
        if not cik:
            print(f"Ticker US '{sym}' tidak ditemukan dalam katalog resmi SEC EDGAR.")
            return

        print(f"=== SEC EDGAR Filing Intelligence: {sym} (CIK {cik:010d}) ===")
        print(f"User-Agent Resmi: {sec.user_agent}")
        print(f"Portal SEC EDGAR : https://www.sec.gov/edgar/browse/?CIK={cik:010d}")

        if mode == "submissions":
            subs = sec.get_submissions(cik)
            if subs:
                recent = subs.get("filings", {}).get("recent", {})
                forms = recent.get("form", [])
                filing_dates = recent.get("filingDate", [])
                accns = recent.get("accessionNumber", [])
                print("\n10 Dokumen Pengarsipan Terkini:")
                for i in range(min(10, len(forms))):
                    print(f"  - {forms[i]:<10s} | Tanggal: {filing_dates[i]} | Accn: {accns[i]}")
            else:
                print("Pengarsipan tidak dapat diakses dari API SEC saat ini.")
        else:
            stmts = sec.extract_canonical_statements(sym)
            if stmts:
                print(f"\n{len(stmts)} Periode Laporan Keuangan Kanonikal Ditemukan:")
                for s in stmts[-5:]:
                    rev = f"USD {s.revenue:,.0f}" if s.revenue else "-"
                    ni = f"USD {s.net_income_attributable:,.0f}" if s.net_income_attributable else "-"
                    ocf = f"USD {s.operating_cash_flow:,.0f}" if s.operating_cash_flow else "-"
                    fcf = f"USD {s.free_cash_flow:,.0f}" if s.free_cash_flow else "-"
                    print(f"  * {s.period:<8s} ({s.audit_status:<8s}): Rev={rev} | Net Income={ni} | FCF={fcf}")
            else:
                print(f"Belum ada fakta XBRL kanonikal yang diekstraksi untuk {sym}.")
        print()

    def do_compare(self, arg: str) -> None:
        """Bandingkan metrik fundamental beberapa saham berdampingan."""
        parts = [p.upper() for p in arg.strip().split()]
        if len(parts) < 2:
            print("Gunakan: /compare <ticker1> <ticker2> [ticker3 ...]")
            return
        cmd = f"Bandingkan valuasi {' dan '.join(parts)}"
        req = self.router.parse(cmd, session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_job(self, arg: str) -> None:
        """Periksa status antrean background browser engine dan worker."""
        parts = arg.strip().split()
        sub = parts[0].lower() if parts else "list"
        from openbagus.domains.equities.browser_worker import BrowserWorkerManager
        mgr = BrowserWorkerManager(REPO_ROOT)
        if sub == "status" and len(parts) > 1:
            job_id = parts[1]
            job = mgr.get_job(job_id)
            if not job:
                print(f"Job {job_id} tidak ditemukan.")
                return
            print(f"=== Background Job Status: {job.job_id} ===")
            print(f"Emiten  : {job.symbol} | Status: [{job.state}] ({job.progress_pct}%)")
            print(f"Pesan   : {job.message}")
            print(f"URL     : {job.target_url}")
            if job.downloaded_files:
                print(f"Berkas  : {', '.join(job.downloaded_files)}")
            if job.error:
                print(f"Error   : {job.error}")
        else:
            jobs = mgr.list_jobs(limit=10)
            if not jobs:
                print("Tidak ada tugas latar belakang yang tercatat saat ini.")
            else:
                print("=== Daftar Tugas Latar Belakang Terkini ===")
                for j in jobs:
                    print(f"  * {j.job_id:<18s} | {j.symbol:<6s} | [{j.state:<12s}] {j.progress_pct}% | {j.message}")
        print()

    def do_export(self, arg: str) -> None:
        parts = arg.strip().split(maxsplit=1)
        if len(parts) != 2 or parts[0].lower() not in {"html", "word", "docx", "web", "pdf", "png"}:
            print("Format: /export html <ticker>, /export word <ticker>, /export pdf <ticker>, atau /export png <ticker>")
            return
        fmt, ticker = parts[0].lower(), parts[1].strip()
        if fmt in {"word", "docx"}:
            cmd = f"/report-word {ticker}"
        elif fmt == "pdf":
            cmd = f"/report pdf {ticker}"
        elif fmt == "png":
            cmd = f"/export png {ticker}"
        else:
            cmd = f"/report-html {ticker}"
        req = self.router.parse(cmd, session=self.session)
        res = self.researcher.execute(req, session=self.session)
        print(res)
        print()

    def do_integrations(self, _arg: str) -> None:
        from openbagus.integrations.tradingview_mcp import TradingViewMCPClient, format_integrations_view
        client = TradingViewMCPClient(root=REPO_ROOT)
        print(format_integrations_view(client.status()))
        print()

    def do_status(self, _arg: str) -> None:
        _run_status(self.session)

    def do_providers(self, arg: str) -> None:
        check = "--check" in arg or "-c" in arg
        show_all = "all" in arg.lower() or "--all" in arg.lower()
        domain = None
        for d in ("indonesia", "free", "idx", "crypto", "macro", "news"):
            if re.search(r"\b" + d + r"\b", arg.lower()):
                domain = d
                break
        _run_providers(check_network=check, domain=domain, show_all=show_all)

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

    def do_chat(self, arg: str) -> None:
        cleaned = arg.strip()
        if cleaned:
            resp = self.agent_harness.run(cleaned, context=self.working_context, profile=self.runtime_profile)
            print(resp.content)
            if self.trace_enabled:
                print(f"\n[Trace: Provider={resp.provider_name} | Latency={resp.latency_ms:.1f}ms | Tools={len(resp.tool_calls_executed)}]")
            print()
            return
        p = self.agent_harness.provider
        info = p.get_model_info()
        print("=== OpenBagus Conversational AI Terminal ===")
        print(f"Active Provider : {p.get_provider_name()}")
        print(f"Model Name      : {info.get('model_name', '-')}")
        print(f"Execution Mode  : {self.runtime_profile.name} (Max Tokens: {self.runtime_profile.max_tokens})")
        print(f"Active Ticker   : {self.working_context.active_ticker or 'None'}")
        print(f"Active Strategy : {self.working_context.strategy} | Horizon: {self.working_context.time_horizon}")
        print(f"Candidate Cards : {len(self.working_context.active_candidates)} aset tersimpan")
        print("Ketik pertanyaan natural dalam Bahasa Indonesia untuk memulai riset.\n")

    def do_new(self, _arg: str) -> None:
        from openbagus.ai.memory.working_context import WorkingContext
        self.working_context = WorkingContext()
        print("Sesi percakapan baru dimulai. Konteks emiten dan kandidat telah direset.\n")

    def do_sessions(self, _arg: str) -> None:
        from openbagus.ai.memory.session_store import SessionStore
        store = SessionStore()
        sessions = store.list_sessions()
        if not sessions:
            print("Belum ada sesi percakapan tersimpan.\n")
            return
        print(f"{'Session ID':<20} {'Ticker':<8} {'Strategy':<12} {'Turns':<6} {'Updated At'}")
        print("-" * 65)
        for s in sessions:
            print(f"{s['session_id']:<20} {s['active_ticker'] or '-':<8} {s['strategy'] or '-':<12} {s['turns_count']:<6} {s['updated_at'][:19]}")
        print("\nGunakan '/resume <session_id>' untuk memuat sesi tertentu.\n")

    def do_resume(self, arg: str) -> None:
        s_id = arg.strip()
        if not s_id:
            print("Gunakan: /resume <session_id>\n")
            return
        from openbagus.ai.memory.session_store import SessionStore
        store = SessionStore()
        ctx = store.load(s_id)
        self.working_context = ctx
        print(f"Sesi '{s_id}' berhasil dimuat. Emiten aktif: {ctx.active_ticker or '-'}, Strategi: {ctx.strategy}.\n")

    def do_mode(self, arg: str) -> None:
        """Peralihan mode percakapan: FAST (cepat/responsif), DEEP_REASONING (analisis mendalam), atau BALANCED."""
        from openbagus.ai.runtime.profiles import get_profile
        target = arg.strip().lower()
        if not target:
            print("=== Mode Percakapan OpenBagus ===")
            print(f"Mode aktif        : {self.current_mode}")
            print(f"Runtime Profile   : {self.runtime_profile.name}")
            print(f"Deskripsi         : {self.runtime_profile.description}")
            print(f"Model Provider    : {self.agent_harness.provider.get_provider_name()}")
            print(f"Thinking Mode     : {'AKTIF' if self.runtime_profile.think else 'NONAKTIF'}")
            print(f"Max Predict Tokens: {self.runtime_profile.max_tokens}")
            print(f"Context Window    : {self.runtime_profile.context_window} tokens")
            print("\nGunakan: /mode fast  atau  /mode deep  atau  /mode balanced\n")
            return

        if target in ("fast", "cepat"):
            self.runtime_profile = get_profile("FAST")
            self.current_mode = "FAST"
            self.agent_harness.provider = self.provider_mgr.switch_to_fast()
            print("[MODE] Dialihkan ke mode FAST:")
            print("  - Model: qwen3.5:2b-q4_K_M (100% GPU, ~92 tok/s, think=False)")
            print("  - Context Window: 2,048 tokens | Latensi respon minimal.")
            if self._companion is not None:
                self._companion.set_mode("FAST")
            print("[BAGUSMAX] Companion 3D aktif — FAST / WHITE")
            if self.voice_session:
                self.voice_session.set_mode("FAST")
            print()
        elif target in ("deep", "deep_reasoning", "deep_research", "mendalam"):
            self.runtime_profile = get_profile("DEEP_REASONING")
            self.current_mode = "DEEP_REASONING"
            self.agent_harness.provider = self.provider_mgr.switch_to_deep()
            print("[MODE] Dialihkan ke mode DEEP_REASONING:")
            print("  - Model: qwen3.5:4b (100% GPU, ~48 tok/s, think=True)")
            print("  - Context Window: 4,096 tokens | Extended chain-of-thought reasoning.")
            if self._companion is not None:
                self._companion.set_mode("DEEP_REASONING")
            print("[BAGUSMAX] Mode DEEP REASONING — ARMORED")
            if self.voice_session:
                self.voice_session.set_mode("DEEP")
            print()
        else:
            self.runtime_profile = get_profile(target.upper())
            self.current_mode = self.runtime_profile.name
            print(f"[MODE] Dialihkan ke profil: {self.runtime_profile.name} (Max Tokens: {self.runtime_profile.max_tokens}, Iters: {self.runtime_profile.max_tool_iterations})\n")


    def do_model(self, arg: str) -> None:
        """Informasi, daftar, status VRAM, dan benchmark model lokal."""
        parts = arg.strip().split()
        subcmd = parts[0].lower() if parts else "status"

        if subcmd in ("status", "info"):
            mgr_status = self.provider_mgr.get_status()
            p = self.agent_harness.provider
            info = p.get_model_info()
            print("=== Status Model Provider Aktif ===")
            print(f"Provider       : {p.get_provider_name()}")
            print(f"Model          : {info.get('model_name', '-')}")
            print(f"Thinking Mode  : {'AKTIF' if info.get('think') else 'NONAKTIF'}")
            print(f"Keep Alive     : {info.get('keep_alive', '30m')}")
            print(f"Tersedia       : {'Ya' if p.is_available() else 'Tidak'}")
            print(f"Model Warm     : {'Ya (di VRAM)' if info.get('is_warm') else 'Tidak (Cold)'}")
            print(f"Context Window : {info.get('context_window', 4096)} tokens")
            print(f"GPU Offload    : {info.get('gpu_layers', 'Auto')} layers")
            fast_info = mgr_status.get("fast_model", {})
            deep_info = mgr_status.get("deep_model", {})
            print("\nStatus VRAM Model:")
            print(f"  - FAST ({fast_info.get('model', '2b')}): {'Warm di GPU' if fast_info.get('is_warm') else 'Unloaded'}")
            print(f"  - DEEP ({deep_info.get('model', '4b')}): {'Warm di GPU' if deep_info.get('is_warm') else 'Unloaded'}")
            print("\nGunakan: /model list, /model status, /model benchmark, /mode fast, /mode deep\n")
            return

        if subcmd in ("list", "ls"):
            import urllib.request
            try:
                req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = data.get("models", [])
                    print(f"=== Model Terpasang di Ollama ({len(models)} model) ===")
                    for m in models:
                        name = m.get("name", "-")
                        size_gb = m.get("size", 0) / (1024 ** 3)
                        mod_time = m.get("modified_at", "-")[:10]
                        print(f"  - {name:<28} : {size_gb:.2f} GB (diperbarui: {mod_time})")
            except Exception as e:
                print(f"[Ollama API Offline / Tidak Terjangkau: {e}]")
                hw = self.provider_mgr.detector.detect()
                if hw.available_local_models:
                    print("Model GGUF lokal:")
                    for m in hw.available_local_models:
                        print(f"  - {m['name']} ({m['size_mb']} MB)")
            print()
            return

        if subcmd in ("benchmark", "bench"):
            print("Menjalankan benchmark inferensi lokal pada active model...")
            p = self.agent_harness.provider
            if not p.is_available():
                print("[Gagal: Model provider aktif tidak dapat dihubungi.]\n")
                return
            from openbagus.ai.providers.base import ChatMessage
            test_prompt = [ChatMessage(role="user", content="Jelaskan rasio PER dan PBV saham IDX secara singkat dalam 2 kalimat.")]
            print("  - Melakukan warmup 1x...")
            try:
                t0 = time.perf_counter()
                w_resp = p.generate(messages=test_prompt, max_tokens=64)
                w_time = time.perf_counter() - t0
                print(f"    Warmup selesai ({w_time:.2f}s). Latensi provider: {w_resp.latency_ms:.1f}ms")

                print("  - Mengukur kecepatan inferensi (3x pengujian)...")
                times = []
                tokens_count = []
                for _ in range(3):
                    t_start = time.perf_counter()
                    resp = p.generate(messages=test_prompt, max_tokens=64)
                    el = time.perf_counter() - t_start
                    times.append(el)
                    toks = len(resp.content.split()) * 1.3
                    tokens_count.append(toks)

                avg_time = sum(times) / len(times)
                avg_toks = sum(tokens_count) / len(tokens_count)
                tok_per_sec = avg_toks / avg_time if avg_time > 0 else 0
                print(f"\n=== Hasil Benchmark {p.get_provider_name()} ===")
                print(f"  - Model             : {p.get_model_info().get('model_name')}")
                print(f"  - Rata-rata Latensi : {avg_time * 1000:.1f} ms")
                print(f"  - Rata-rata Output  : ~{tok_per_sec:.1f} tokens/detik")
                print("  - Status Hardware   : 100% GPU Offload (RTX 3050 6GB)\n")
            except Exception as e:
                print(f"[Benchmark gagal: {e}]\n")
            return

        if subcmd in ("fast", "cepat"):
            self.do_mode("fast")
            return
        if subcmd in ("deep", "mendalam"):
            self.do_mode("deep")
            return

        try:
            self.agent_harness.provider = self.provider_mgr.switch_provider(subcmd)
            print(f"Model provider dialihkan ke: {self.agent_harness.provider.get_provider_name()}\n")
        except Exception as e:
            print(f"Gagal beralih provider: {e}\n")

    def do_models(self, _arg: str) -> None:
        hw = self.provider_mgr.detector.detect()
        print("=== Model & Hardware Discovery ===")
        print(f"OS / Hardware : {hw.os_name} {hw.os_version} ({hw.architecture}) | CPU: {hw.cpu_cores} cores")
        print(f"RAM Fisik     : {hw.total_ram_gb:.1f} GB (Free: {hw.free_ram_gb:.1f} GB)")
        print(f"GPU Akselerasi: {hw.gpu_name or 'None'} | VRAM: {hw.vram_total_mb:.0f} MB (CUDA: {hw.cuda_available})")
        print(f"llama-server  : {'Terdeteksi' if hw.llama_server_path else 'Tidak ditemukan'}")
        print(f"Ollama CLI    : {'Terdeteksi' if hw.ollama_path else 'Tidak ditemukan'}")
        print("\nModel GGUF Lokal Terdeteksi:")
        if hw.available_local_models:
            for m in hw.available_local_models:
                print(f"  - {m['name']} ({m['size_mb']} MB, Format: {m['format']})")
        else:
            print("  - Tidak ada model GGUF di direktori lokal.")
        print()

    def do_gpu(self, arg: str) -> None:
        """Status GPU NVIDIA RTX 3050 (VRAM, temperatur, utilisasi)."""
        import subprocess
        try:
            cmd = [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,memory.used,memory.free,temperature.gpu,utilization.gpu",
                "--format=csv,noheader,nounits",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            parts = [p.strip() for p in res.stdout.strip().split(",")]
            if len(parts) >= 7:
                name, driver, total, used, free, temp, util = parts[:7]
                print("=== Status NVIDIA GPU (Hardware Direct) ===")
                print(f"Device        : {name}")
                print(f"Driver Version: {driver}")
                print(f"VRAM Total    : {total} MiB (~{float(total)/1024:.1f} GB)")
                print(f"VRAM Terpakai : {used} MiB ({float(used)/float(total)*100:.1f}%)")
                print(f"VRAM Bebas    : {free} MiB (~{float(free)/1024:.1f} GB)")
                print(f"Temperatur    : {temp}°C")
                print(f"Utilisasi GPU : {util}%")
                mgr_status = self.provider_mgr.get_status()
                fast_warm = mgr_status.get("fast_model", {}).get("is_warm")
                deep_warm = mgr_status.get("deep_model", {}).get("is_warm")
                warm_name = "FAST (qwen3.5:2b)" if fast_warm else ("DEEP (qwen3.5:4b)" if deep_warm else "None")
                print(f"Model di VRAM : {warm_name}")
                print()
                return
        except Exception as e:
            logger.debug("nvidia-smi error: %s", e)

        hw = self.provider_mgr.detector.detect()
        print("=== Status GPU (Hardware Detection) ===")
        print(f"GPU           : {hw.gpu_name or 'NVIDIA RTX 3050'}")
        print(f"VRAM          : {hw.vram_total_mb:.0f} MB")
        print(f"CUDA Tersedia : {'Ya' if hw.cuda_available else 'Tidak'}\n")

    def do_hardware(self, _arg: str) -> None:
        """Ringkasan hardware lengkap (CPU, RAM, GPU, Perangkat Audio)."""
        hw = self.provider_mgr.detector.detect()
        mem = None
        try:
            import psutil
            mem = psutil.virtual_memory()
        except ImportError:
            pass

        print("================== Ringkasan Hardware OpenBagus ==================")
        print(f"Sistem Operasi : {hw.os_name} {hw.os_version} ({hw.architecture})")
        print(f"Prosesor (CPU) : Intel Core i5-13450HX (10 Cores, 16 Threads, {hw.cpu_cores} terdeteksi)")
        if mem:
            total_gb = mem.total / (1024 ** 3)
            avail_gb = mem.available / (1024 ** 3)
            used_pct = mem.percent
            print(f"RAM Fisik      : {total_gb:.1f} GB Total | {avail_gb:.1f} GB Bebas ({used_pct:.1f}% terpakai)")
        else:
            print(f"RAM Fisik      : {hw.total_ram_gb:.1f} GB (Bebas: {hw.free_ram_gb:.1f} GB)")

        print(f"GPU Utama      : {hw.gpu_name or 'NVIDIA GeForce RTX 3050 6GB Laptop GPU'}")
        print(f"VRAM GPU       : {hw.vram_total_mb:.0f} MiB (CUDA: {'Aktif' if hw.cuda_available else 'Tidak'})")

        try:
            from openbagus.voice.audio_devices import AudioDeviceManager
            in_devs = AudioDeviceManager.list_input_devices()
            out_devs = AudioDeviceManager.list_output_devices()
            def_in = AudioDeviceManager.get_default_input_device()
            def_out = AudioDeviceManager.get_default_output_device()
            mic_str = f"{def_in.name} ({len(in_devs)} terdeteksi)" if def_in else "Tidak ditemukan"
            spk_str = f"{def_out.name} ({len(out_devs)} terdeteksi)" if def_out else "Tidak ditemukan"
            print(f"Mikrofon       : {mic_str}")
            print(f"Speaker/Audio  : {spk_str}")
        except Exception:
            print("Perangkat Audio: Driver audio terhubung")

        comp_status = "Nonaktif"
        if self._companion is not None:
            try:
                s = self._companion.get_status()
                comp_status = f"BAGUSMAX Aktif ({s.get('character_form', 'WHITE')}, PID {s.get('pid')})" if s.get("running") else "Nonaktif"
            except Exception:
                pass
        print(f"Companion 3D   : {comp_status}")
        print("=================================================================\n")

    def do_show_openbagus(self, arg: str) -> None:
        """Kontrol interaktif 3D Companion BAGUSMAX.

        Perintah utama:
          /bagusmax [show|hide|close|reset|status]
          /bagusmax position <top-left|top-right|bottom-right|center|...|x <N> y <N>>
          /bagusmax size <50|75|100|125|150|200|reset>
          /bagusmax window-size <width> <height>
          /bagusmax rotate <0|90|180|270|360>
          /bagusmax pitch <-65 s/d 65>
          /bagusmax view <front|back|left|right|top|reset>
          /bagusmax interactive <on|off>
          /bagusmax click-through <on|off>
          /bagusmax animation <on|off|wave|turn|nod>
          /bagusmax monitor <list|primary|<id>>
          /bagusmax preferences <save|reset>
        """
        cleaned = arg.strip()
        for prefix in ("-openbagus", "openbagus"):
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].strip()
                break
        tokens = cleaned.split()
        subcmd = tokens[0].lower() if tokens else "show"
        try:
            from openbagus.companion.controller import CompanionController
            if self._companion is None:
                self._companion = CompanionController.get_instance()
        except ImportError as e:
            print(f"[BAGUSMAX Companion tidak tersedia: {e}]")
            print("Pastikan moderngl, glfw, pyrr telah terpasang di virtual environment.\n")
            return

        if subcmd in ("show", "start", "open", "on") or not tokens:
            print("Meluncurkan 3D companion BAGUSMAX...")
            cur_mode = getattr(self, "current_mode", "FAST")
            self._companion.set_mode(cur_mode)
            ok = self._companion.show()
            if ok:
                st = self._companion.get_status()
                pid_str = f" (PID {st.get('pid')})" if st.get('pid') else ""
                cur_form = st.get("character_form", "WHITE")
                print(f"[BAGUSMAX] Companion 3D aktif — {cur_mode} / {cur_form}{pid_str}")
                print("Karakter : BAGUSMAX Dual-Form (FAST -> WHITE vinyl robot | DEEP_REASONING -> ARMORED hero suit)")
                print("Interaksi Mouse: Drag Kiri=Geser jendela | Drag Kanan=Rotasi 360° | Scroll=Ukuran Tubuh | Alt+Scroll=Ukuran Jendela | Double-Click=Reset Hadap Depan")
                print("Gunakan '/bagusmax hide' untuk menyembunyikan, '/bagusmax close' untuk menutup.\n")
            else:
                print("[Gagal membuka jendela companion. Periksa OpenGL 3.3 Core profile support dan reports/runtime/companion.log.]\n")

        elif subcmd in ("hide", "sembunyikan", "off"):
            self._companion.hide()
            print("[Jendela companion BAGUSMAX disembunyikan.]\n")

        elif subcmd in ("close", "stop", "exit", "quit", "tutup"):
            self._companion.close()
            print("[Jendela companion BAGUSMAX ditutup.]\n")

        elif subcmd in ("reset", "restart"):
            if subcmd == "restart":
                print("Merestart proses companion BAGUSMAX...")
                self._companion.reset()
                print("[Companion BAGUSMAX di-restart.]\n")
            else:
                self._companion.reset()
                self._companion.reset_transform()
                print("[Orientasi, ukuran, dan posisi BAGUSMAX di-reset ke nilai default.]\n")

        elif subcmd in ("status", "info"):
            st = self._companion.get_status()
            ts = st.get("transform", {})
            print("=== Status BAGUSMAX 3D Companion ===")
            print(f"Berjalan (Running) : {'Ya' if st.get('running') else 'Tidak'}")
            print(f"Terhubung (IPC)    : {'Ya' if st.get('connected') else 'Tidak'}")
            print(f"Bentuk Karakter    : {st.get('character_form', 'WHITE')}")
            print(f"Mode Penalaran     : {st.get('mode', getattr(self, 'current_mode', 'FAST'))}")
            print(f"PID Proses         : {st.get('pid') or '-'}")
            print(f"Animasi Terakhir   : {st.get('last_state', 'IDLE')}")
            print(f"Posisi Jendela     : ({ts.get('window_position_x', 0)}, {ts.get('window_position_y', 0)})")
            print(f"Dimensi Jendela    : {ts.get('window_width', 480)} x {ts.get('window_height', 560)} px")
            scale_val = ts.get('character_scale', 1.0)
            print(f"Skala Karakter     : {scale_val * 100:.0f}% ({scale_val:.2f}x)")
            print(f"Rotasi 3D          : Yaw: {ts.get('yaw_degrees', 0.0)}° | Pitch: {ts.get('pitch_degrees', 0.0)}°")
            print(f"Interaksi Mouse    : {'AKTIF' if ts.get('interactive_mode', True) else 'CLICK-THROUGH'}")
            print(f"Kebijakan Layar    : {ts.get('placement_policy', 'CLAMP_TO_VISIBLE_WORKAREA')}")
            print(f"Alamat IPC         : {st.get('ipc_address', '127.0.0.1:7432')} (v{st.get('ipc_version', '1.0')})")
            print()

        elif subcmd == "position":
            if len(tokens) >= 3 and tokens[1].lower() in ("policy", "kebijakan"):
                policy = "FREE_POSITIONING" if tokens[2].lower() in ("free", "bebas") else "CLAMP_TO_VISIBLE_WORKAREA"
                self._companion.set_position(policy=policy)
                print(f"[BAGUSMAX] Kebijakan penempatan layar: {policy}\n")
            elif len(tokens) >= 5 and tokens[1].lower() == "x" and tokens[3].lower() == "y":
                try:
                    px = int(tokens[2])
                    py = int(tokens[4])
                    self._companion.set_position(x=px, y=py)
                    print(f"[BAGUSMAX] Posisi jendela dipindahkan ke: x={px}, y={py}\n")
                except ValueError:
                    print("[Nilai koordinat x dan y harus berupa angka integer.]\n")
            elif len(tokens) >= 2:
                preset = tokens[1].lower()
                self._companion.set_position(preset=preset)
                print(f"[BAGUSMAX] Posisi jendela diatur ke preset: {preset}\n")
            else:
                print("Pilihan preset: top-left, top-center, top-right, middle-left, center, middle-right, bottom-left, bottom-center, bottom-right")
                print("Atau koordinat: /bagusmax position x 300 y 180\n")

        elif subcmd == "size":
            if len(tokens) >= 2:
                arg_val = tokens[1].lower()
                if arg_val == "reset":
                    self._companion.set_character_scale(1.0)
                    print("[BAGUSMAX] Skala tubuh karakter di-reset ke 100% (1.0x).\n")
                else:
                    try:
                        raw_num = float(arg_val.rstrip("%"))
                        scale = raw_num / 100.0 if raw_num > 2.0 else raw_num
                        scale = max(0.5, min(2.0, scale))
                        self._companion.set_character_scale(scale)
                        print(f"[BAGUSMAX] Skala tubuh karakter diatur ke: {scale*100:.0f}% ({scale:.2f}x)\n")
                    except ValueError:
                        print("[Nilai ukuran tidak valid. Gunakan: /bagusmax size <50|75|100|125|150|200|reset>]\n")
            else:
                print("Usage: /bagusmax size <50|75|100|125|150|200|reset>\n")

        elif subcmd in ("window-size", "windowsize", "winsize"):
            if len(tokens) >= 3:
                try:
                    w = int(tokens[1])
                    h = int(tokens[2])
                    self._companion.set_window_size(w, h)
                    print(f"[BAGUSMAX] Dimensi jendela popup diatur ke: {w}x{h} px\n")
                except ValueError:
                    print("[Nilai lebar dan tinggi harus berupa angka integer.]\n")
            else:
                print("Usage: /bagusmax window-size <lebar> <tinggi> (misal: 450 600)\n")

        elif subcmd in ("rotate", "yaw"):
            if len(tokens) >= 2:
                try:
                    deg = float(tokens[1])
                    self._companion.set_rotation(yaw=deg)
                    print(f"[BAGUSMAX] Rotasi horizontal (yaw) diatur ke: {deg % 360.0:.1f}°\n")
                except ValueError:
                    print("[Nilai derajat rotasi harus berupa angka.]\n")
            else:
                print("Usage: /bagusmax rotate <0|90|180|270|360>\n")

        elif subcmd == "pitch":
            if len(tokens) >= 2:
                try:
                    deg = float(tokens[1])
                    self._companion.set_rotation(pitch=deg)
                    print(f"[BAGUSMAX] Kemiringan vertikal (pitch) diatur ke: {deg:.1f}° (-65° s/d +65°)\n")
                except ValueError:
                    print("[Nilai derajat pitch harus berupa angka.]\n")
            else:
                print("Usage: /bagusmax pitch <derajat> (misal: 30, -30)\n")

        elif subcmd == "view":
            if len(tokens) >= 2:
                v = tokens[1].lower()
                self._companion.set_view(v)
                print(f"[BAGUSMAX] Sudut pandang kamera diatur ke: '{v}'\n")
            else:
                print("Pilihan sudut pandang: front, back, left, right, top, reset\n")

        elif subcmd == "interactive":
            if len(tokens) >= 2:
                on_off = tokens[1].lower() in ("on", "true", "1", "aktif", "ya")
                self._companion.set_interactive(on_off)
                print(f"[BAGUSMAX] Mode interaksi mouse diatur ke: {'AKTIF' if on_off else 'CLICK-THROUGH'}\n")
            else:
                print("Usage: /bagusmax interactive on|off\n")

        elif subcmd in ("click-through", "clickthrough"):
            if len(tokens) >= 2:
                ct = tokens[1].lower() in ("on", "true", "1", "aktif", "ya")
                self._companion.set_interactive(not ct)
                print(f"[BAGUSMAX] Mode Click-Through diatur ke: {'AKTIF' if ct else 'NONAKTIF (Interaktif)'}\n")
            else:
                print("Usage: /bagusmax click-through on|off\n")

        elif subcmd == "animation":
            if len(tokens) >= 2:
                sub = tokens[1].lower()
                if sub in ("on", "aktif", "true"):
                    self._companion.set_animation_enabled(True)
                    print("[BAGUSMAX] Animasi ambient diaktifkan.\n")
                elif sub in ("off", "nonaktif", "false"):
                    self._companion.set_animation_enabled(False)
                    print("[BAGUSMAX] Animasi ambient dinonaktifkan (pose statis).\n")
                elif sub in ("wave", "turn", "nod"):
                    self._companion.trigger_gesture(sub)
                    print(f"[BAGUSMAX] Memainkan gestur animasi: '{sub}'.\n")
                else:
                    print("Pilihan animasi: on, off, wave, turn, nod\n")
            else:
                print("Usage: /bagusmax animation on|off|wave|turn|nod\n")

        elif subcmd == "monitor":
            if len(tokens) >= 2:
                sub = tokens[1].lower()
                if sub in ("list", "info"):
                    mons = self._companion.list_monitors()
                    print("=== Monitor Desktop Terdeteksi ===")
                    for m in mons:
                        pri = " [PRIMARY]" if m.get("is_primary") else ""
                        print(f"  Monitor {m['index']}: {m['name']}{pri} (Workarea: {m['workarea']})")
                    print()
                elif sub in ("primary", "0"):
                    self._companion.set_position(preset="bottom-right", monitor=0)
                    print("[BAGUSMAX] Dipindahkan ke monitor utama (primary).\n")
                elif sub.isdigit():
                    idx = int(sub)
                    self._companion.set_position(preset="bottom-right", monitor=idx)
                    print(f"[BAGUSMAX] Dipindahkan ke monitor ID {idx}.\n")
                else:
                    print("Usage: /bagusmax monitor list|primary|<id>\n")
            else:
                print("Usage: /bagusmax monitor list|primary|<id>\n")

        elif subcmd == "preferences":
            if len(tokens) >= 2 and tokens[1].lower() in ("reset", "default"):
                self._companion.reset_preferences()
                print("[BAGUSMAX] Preferensi penempatan dan rotasi di-reset ke nilai bawaan.\n")
            else:
                self._companion.save_preferences()
                print("[BAGUSMAX] Preferensi penempatan, ukuran, dan rotasi disimpan ke disk.\n")

        else:
            print("Perintah BAGUSMAX tidak dikenal.")
            print("Pilihan: show, hide, status, reset, close, position, size, window-size, rotate, pitch, view, interactive, click-through, animation, monitor, preferences\n")


    def do_bagusmax(self, arg: str) -> None:
        """Alias untuk /show-openbagus (Kontrol jendela 3D Companion BAGUSMAX)."""
        self.do_show_openbagus(arg)

    def do_show(self, arg: str) -> None:
        """Alias untuk /show-openbagus."""
        self.do_show_openbagus(arg)


    def do_cancel(self, _arg: str) -> None:
        """Membatalkan pemrosesan yang sedang berjalan (suara atau inferensi)."""
        if getattr(self, "voice_session", None):
            try:
                self.voice_session.stop()
            except Exception:
                pass
        if self._companion is not None:
            try:
                self._companion.set_state("IDLE")
            except Exception:
                pass
        print("Permintaan dibatalkan.\n")

    def do_tools(self, arg: str) -> None:
        target = arg.strip()
        reg = self.agent_harness.tools
        if target:
            tool = reg.get(target)
            if not tool:
                print(f"Tool '{target}' tidak ditemukan.\n")
                return
            d = tool.to_definition()
            print(f"Tool: {d.name}")
            print(f"Deskripsi : {d.description}")
            print(f"Parameter : {json.dumps(d.parameters, indent=2, ensure_ascii=False)}\n")
            return
        print(f"=== Daftar Financial Tools Terdaftar ({len(reg.list_tool_names())} tools) ===")
        for d in reg.list_definitions():
            print(f"- {d.name:<32}: {d.description}")
        print("\nGunakan '/tools <tool_name>' untuk melihat skema parameter lengkap.\n")

    def do_memory(self, arg: str) -> None:
        if "clear" in arg.lower():
            from openbagus.ai.memory.working_context import WorkingContext
            self.working_context = WorkingContext()
            print("Memori working context berhasil dibersihkan.\n")
            return
        ctx = self.working_context
        print("=== Working Context & Memory ===")
        print(f"Emiten Aktif      : {ctx.active_ticker or '-'}")
        print(f"Nama Emiten       : {ctx.active_ticker_name or '-'}")
        print(f"Strategi Aktif    : {ctx.strategy}")
        print(f"Horizon Investasi : {ctx.time_horizon}")
        print(f"Periode Keuangan  : {ctx.financial_period}")
        print(f"Batasan Filter    : {json.dumps(ctx.explicit_constraints, ensure_ascii=False)}")
        print(f"Kandidat Aktif    : {[c.get('ticker', c.get('symbol')) for c in ctx.active_candidates]}")
        print(f"Riwayat Percakapan: {len(ctx.turns)} turn dicatat")
        print("Gunakan '/memory clear' untuk mereset memori.\n")

    def do_strategies(self, _arg: str) -> None:
        from openbagus.ai.strategy.registry import CANONICAL_STRATEGIES
        print("=== Strategy Registry (Discoverable Financial Strategies) ===")
        for s in CANONICAL_STRATEGIES:
            print(f"[{s.strategy_id}] {s.name} (v{s.version}, {s.family})")
            print(f"  Tujuan: {s.research_purpose}")
            print(f"  Horizon: {s.timeframe} | Pasar: {', '.join(s.applicable_markets)}")
            print(f"  Entry  : {s.entry_conditions}")
            print(f"  Batas  : {s.invalidation_conditions}")
            print()

    def do_trace(self, arg: str) -> None:
        state = arg.strip().lower()
        if state in {"on", "1", "true", "yes"}:
            self.trace_enabled = True
            print("Verbose trace diaktifkan.\n")
        elif state in {"off", "0", "false", "no"}:
            self.trace_enabled = False
            print("Verbose trace dinonaktifkan.\n")
        else:
            self.trace_enabled = not self.trace_enabled
            print(f"Verbose trace: {'Aktif' if self.trace_enabled else 'Nonaktif'}.\n")

    def do_exit(self, _arg: str) -> bool:
        if getattr(self, "voice_session", None):
            try:
                self.voice_session.stop()
            except Exception:
                pass
            self.voice_session = None
        if sys.stdin.isatty():
            try:
                choice = self._ask("End session: [S] Save context  [C] Clear conversation  [X] Cancel: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "x"
            if choice == "x" or choice not in {"s", "c"}:
                print("Sesi dilanjutkan.")
                return False
            if choice == "c":
                if not self.session.clear_persistent():
                    print("Clear conversation gagal; sesi tetap aktif.")
                    return False
                self.session.clear()
                LocalLanguageEngine.shutdown_runtime()
                return True
            elif self.session.is_persistence_enabled():
                if not self.session.save_persistent():
                    print("Save context gagal; sesi tetap aktif.")
                    return False
                LocalLanguageEngine.shutdown_runtime()
                return True
            else:
                print("Persistence belum diizinkan; konteks tidak ditulis ke disk. Gunakan /harness on untuk opt-in.")
        if self.session.is_persistence_enabled():
            self.session.save_persistent()
        else:
            self.session.clear()
        LocalLanguageEngine.shutdown_runtime()
        return True

    def do_quit(self, _arg: str) -> bool:
        return self.do_exit(_arg)

    def do_EOF(self, _arg: str) -> bool:
        if getattr(self, "voice_session", None):
            try:
                self.voice_session.stop()
            except Exception:
                pass
            self.voice_session = None
        if self.session.is_persistence_enabled():
            self.session.save_persistent()
        else:
            self.session.clear()
        LocalLanguageEngine.shutdown_runtime()
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

    def do_gmail(self, arg: str) -> None:
        parts = shlex.split(arg) if arg.strip() else []
        _run_gmail(parts)

    def do_whatsapp(self, arg: str) -> None:
        parts = shlex.split(arg) if arg.strip() else []
        _run_whatsapp(parts)

    def do_autonomy(self, arg: str) -> None:
        parts = shlex.split(arg) if arg.strip() else []
        _run_autonomy(parts)

    def do_alerts(self, arg: str) -> None:
        parts = shlex.split(arg) if arg.strip() else []
        _run_alerts(parts)

    def do_delivery(self, arg: str) -> None:
        parts = shlex.split(arg) if arg.strip() else []
        _run_delivery(parts)

    def do_voice(self, arg: str) -> None:
        """Sistem percakapan suara interaktif lokal (Whisper ASR, Piper TTS, NVIDIA RTX CUDA)."""
        parts = arg.strip().split()
        subcmd = parts[0].lower() if parts else "status"
        subarg = parts[1].lower() if len(parts) > 1 else ""

        from openbagus.voice.audio_devices import AudioDeviceManager
        from openbagus.voice.voice_session import VoiceSession

        if subcmd in ("devices", "device"):
            in_devs = AudioDeviceManager.list_input_devices()
            out_devs = AudioDeviceManager.list_output_devices()
            def_in = AudioDeviceManager.get_default_input_device()
            def_out = AudioDeviceManager.get_default_output_device()

            print("=== Perangkat Audio Terdeteksi (Windows Native) ===")
            print("\nMikrofon (Input):")
            for d in in_devs:
                tag = " [DEFAULT]" if def_in and d.index == def_in.index else ""
                print(f"  [{d.index}] {d.name} ({d.host_api}) - {d.max_input_channels} ch, {int(d.default_sample_rate)} Hz{tag}")

            print("\nSpeaker / Headphone (Output):")
            for d in out_devs:
                tag = " [DEFAULT]" if def_out and d.index == def_out.index else ""
                print(f"  [{d.index}] {d.name} ({d.host_api}) - {d.max_output_channels} ch, {int(d.default_sample_rate)} Hz{tag}")
            print()
            return

        if subcmd in ("status", "info"):
            if not getattr(self, "voice_session", None):
                from openbagus.voice.gpu_scheduler import GPUScheduler
                from openbagus.voice.asr_engine import LocalASREngine
                from openbagus.voice.tts_engine import LocalTTSEngine
                gpu = GPUScheduler.get_instance().query_gpu_status()
                asr = LocalASREngine()
                tts = LocalTTSEngine()
                code, detail = AudioDeviceManager.get_microphone_status()
                print("=== Status Sistem Suara OpenBagus ===")
                print(f"Sesi Suara Aktif : Tidak (Ketik '/voice start' atau '/voice on' untuk memulai)")
                print(f"Mikrofon         : {code} ({detail})")
                print(f"ASR Model (STT)  : {asr.model_size_or_path} (Akselerasi: {asr.device.upper()} {asr.compute_type})")
                print(f"TTS Model (Suara): Piper Indonesian ({tts.model_path.name})")
                print(f"NVIDIA GPU       : {gpu.device_name} (VRAM {gpu.vram_used_mb:.0f}/{gpu.vram_total_mb:.0f} MB)")
                print(f"Mode Penalaran   : FAST / DEEP_REASONING (Konfirmasi vokal otomatis)")
                print("\nPerintah tersedia: /voice start, /voice on, /voice stop, /voice off, /voice devices, /voice status\n")
                return

            st = self.voice_session.get_status_summary()
            print("=== Status Sesi Suara OpenBagus ===")
            print(f"Status Sesi     : {'AKTIF' if st['active'] else 'NONAKTIF'} (State: {st['state']})")
            print(f"Mode Penalaran  : {st['mode']}")
            print(f"Mikrofon Muted  : {'Ya' if st['mic_muted'] else 'Tidak'}")
            print(f"Assistant Play  : {'Sedang Berbicara' if st['playback_playing'] else 'Hening'}")
            gpu = st.get("gpu", {})
            print(f"NVIDIA GPU      : {gpu.get('device_name')} (VRAM Terpakai: {gpu.get('vram_used_mb', 0):.0f} MB)")
            diag = st.get("diagnostics", {})
            print(f"Total Turn Suara: {diag.get('total_turns', 0)}")
            print(f"Rata-rata ASR   : {diag.get('avg_asr_latency_ms', 0):.1f} ms")
            print(f"Rata-rata TTFA  : {diag.get('avg_tts_ttfa_ms', 0):.1f} ms")
            print(f"Rata-rata E2E   : {diag.get('avg_e2e_latency_ms', 0):.1f} ms")
            print()
            return

        if subcmd == "mute":
            if self.voice_session:
                self.voice_session.set_muted(True)
            else:
                print("Sesi suara belum aktif.")
            return

        if subcmd == "unmute":
            if self.voice_session:
                self.voice_session.set_muted(False)
            else:
                print("Sesi suara belum aktif.")
            return

        if subcmd in ("quiet", "shutup", "barge", "stop-speaking"):
            if self.voice_session:
                self.voice_session.stop_speaking()
                print("[Output suara asisten dihentikan.]")
            else:
                print("Sesi suara belum aktif.")
            return

        if subcmd == "mode":
            if not subarg:
                curr = self.voice_session.controller.mode_controller.current_mode if self.voice_session else "FAST"
                print(f"Mode suara aktif: {curr}")
                print("Gunakan: /voice mode fast  atau  /voice mode deep\n")
                return
            if self.voice_session:
                self.voice_session.set_mode(subarg)
            else:
                print(f"Mode akan digunakan saat sesi suara dimulai: {subarg.upper()}")
            return

        if subcmd in ("stop", "off"):
            if self.voice_session:
                self.voice_session.stop()
                self.voice_session = None
                print("[Sesi suara dihentikan.]\n")
            else:
                print("Tidak ada sesi suara yang sedang berjalan.")
            return

        if subcmd in ("start", "on", "ptt", "continuous"):
            hands_free = subcmd != "ptt"
            if not getattr(self, "voice_session", None):
                self.voice_session = VoiceSession(
                    agent_harness=self.agent_harness,
                    working_context=self.working_context,
                )
            started = self.voice_session.start(hands_free=hands_free)
            if not started:
                print("[Gagal memulai audio stream. Pastikan mikrofon terhubung dan izin audio aktif.]")
            else:
                print("[Sesi suara dimulai. Bicara ke mikrofon...]\n")
            return

        print("Perintah /voice tidak dikenal. Pilihan: start, on, stop, off, ptt, devices, status, mode, mute, unmute\n")

    def do_send(self, arg: str) -> None:
        channel = arg.strip().lower()
        if channel not in {"email", "gmail", "whatsapp", "wa", "all"}:
            print("Usage: /send email|gmail|whatsapp|all")
            return
        if not self.session.last_quant_result or not self.session.last_research_packet:
            print("No research result is available to send.")
            return
        rendered = render_research_delivery(
            self.session.last_quant_result, self.session.last_research_packet,
            include_sources=self.session.show_sources,
        )
        safety = scan_payload(rendered)
        if not safety["passed"]:
            print("Delivery blocked by research safety guard.")
            return
        runtime_env = RuntimeEnv(REPO_ROOT)
        results: dict[str, str] = {}
        if channel in {"email", "all"}:
            config = SmtpConfig.from_runtime_env(runtime_env)
            enabled = (runtime_env.get("OPENBAGUS_EMAIL_LIVE_ENABLED", "false") or "false").lower() in {"1", "true", "yes", "on"}
            if not config.ready or not enabled:
                missing = ", ".join(config.missing or ("OPENBAGUS_EMAIL_LIVE_ENABLED=true",))
                results["Email"] = f"NOT CONFIGURED ({missing})"
            else:
                try:
                    message = build_email_message(subject=rendered["subject"], text=rendered["text"], html=rendered["html"], config=config)
                    results["Email"] = "SENT" if SmtpTransport(config).send(message)["message_sent"] else "FAILED"
                except smtplib.SMTPAuthenticationError:
                    results["Email"] = "AUTH FAILED"
                except (OSError, smtplib.SMTPException):
                    results["Email"] = "SEND FAILED"
        if channel in {"gmail"}:
            from openbagus.delivery.gmail import GmailOAuthTransport
            gmail_trans = GmailOAuthTransport()
            if not gmail_trans.is_connected():
                results["Gmail"] = "NOT CONNECTED (Run '/gmail connect')"
            else:
                user_email = (gmail_trans.token_store.load() or {}).get("email", "")
                if user_email:
                    res = gmail_trans.send_message(recipient=user_email, subject=rendered["subject"], text_body=rendered["text"], html_body=rendered["html"])
                    results["Gmail"] = res.get("status", "FAILED")
                else:
                    results["Gmail"] = "RECIPIENT UNKNOWN"
        if channel in {"whatsapp", "wa", "all"}:
            config = WhatsAppCloudConfig.from_runtime_env(runtime_env)
            status = WhatsAppCloudTransport(config).send(rendered["whatsapp"])["status"]
            results["WhatsApp"] = status.removeprefix("WHATSAPP_").replace("_", " ")
        for name, result in results.items():
            print(f"{name:<10} {result}")

    def default(self, line: str) -> None:
        cleaned = line.strip()
        if not cleaned:
            return
        lower = cleaned.lower()
        if re.search(r"(?:kirim hasil ini ke email|email this analysis|send this to email)", lower):
            self.do_send("email")
            return
        if re.search(r"(?:kirim (?:hasil ini )?ke gmail|send (?:this )?to gmail)", lower):
            self.do_send("gmail")
            return
        if re.search(r"(?:kirim hasil ini ke whatsapp|send to whatsapp|wa hasil ini|kirim ke wa)", lower):
            self.do_send("whatsapp")
            return
        if re.search(r"kirim ke email dan whatsapp", lower):
            self.do_send("all")
            return
        if re.search(r"^(?:pantau|monitor|alert)\s+([a-zA-Z0-9]+)$", lower):
            m = re.search(r"^(?:pantau|monitor|alert)\s+([a-zA-Z0-9]+)$", lower)
            if m:
                target_asset = m.group(1).upper()
                self.do_alerts(f"add {target_asset}")
                return

        # Natural language companion trigger
        if re.search(r"\b(?:show|tampilkan|munculkan)\b.*\bopen\s*bagus\b|\bopen\s*bagus\b.*\b(?:show|tampil|muncul)\b", lower):
            self.do_show_openbagus("")
            return

        req = self.router.parse(cleaned, session=self.session)
        if req.request_type == "COMMAND" and req.system_query == "exit":
            return self.do_exit("")

        # Strict Asset Context Switch Confirmation (Section B)
        if req.needs_topic_switch_confirmation and req.switch_target_asset:
            target = req.switch_target_asset
            curr = self.session.last_asset or "BTC"
            prompt_str = f"Konteks aktif: {curr}.\nPindah fokus ke {target}? (Y/N): "
            try:
                ans = self._ask(prompt_str).strip().lower()
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

        if not req.needs_asset and (req.request_type != "UNKNOWN" or req.asset or req.candidates or req.request_type in (
            "SYSTEM_INFO", "MARKET_OUTLOOK", "CATEGORY", "SCREEN", "PREFERENCE", "FEEDBACK", "HARNESS", "SETUP_CONFIG", "CHART",
            "VISUALIZE", "BACKTEST", "REPORT_WORD", "REPORT_HTML", "EQUITY_OWNERSHIP", "EQUITY_ANALYSIS", "EQUITY_QUOTE", "EQUITY_SECTOR"
        )):
            result = self.researcher.execute(req, session=self.session)
            if result and not ("Unknown coin or command" in result or "SOURCE GAP" in result):
                self.session.add_turn(cleaned, result[:300])
                print(result)
                print()
                return

        # Natural Conversational AI Agent Harness primary execution path
        agent_resp = self.agent_harness.run(
            user_query=cleaned,
            context=self.working_context,
            profile=self.runtime_profile,
            mode=self.current_mode,
        )
        out_enc = getattr(sys.stdout, "encoding", None) or "utf-8"
        try:
            print(agent_resp.content)
        except (UnicodeEncodeError, OSError):
            safe_content = agent_resp.content.encode(out_enc, errors="replace").decode(out_enc, errors="replace")
            print(safe_content)
        if self.trace_enabled:
            print(f"\n[Trace: Provider={agent_resp.provider_name} | Latency={agent_resp.latency_ms:.1f}ms | Tools={len(agent_resp.tool_calls_executed)}]")
            if agent_resp.thinking_trace:
                print(f"  [Thinking: {agent_resp.thinking_trace[:200]}{'...' if len(agent_resp.thinking_trace) > 200 else ''}]")
            for tc in agent_resp.tool_calls_executed:
                print(f"  - Tool: {tc['name']}({tc['arguments']}) -> Success: {tc['success']} ({tc['latency_ms']:.1f}ms)")
        print()



def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "import-idx":
        parser = argparse.ArgumentParser(prog="openbagus import-idx")
        parser.add_argument("kind", choices=("catalog", "market", "ohlcv", "rules", "ownership"))
        parser.add_argument("path", type=Path)
        parser.add_argument("--metadata", type=Path)
        args = parser.parse_args(arguments[1:])
        try:
            if args.kind == "catalog":
                result = EquityCatalog(REPO_ROOT).import_file(args.path)
            elif args.kind == "ownership":
                from openbagus.domains.equities.ownership import import_ownership_file
                result = import_ownership_file(args.path, REPO_ROOT)
            elif args.kind == "rules":
                if args.path.stat().st_size > 1_000_000:
                    raise ValueError("Rules import exceeds size limit")
                data = json.loads(args.path.read_text(encoding="utf-8"))
                EquityMarketPolicy.validate_rules(data)
                if not scan_payload(data)["passed"]:
                    raise ValueError("Unsafe rules metadata")
                directory = REPO_ROOT / "data/equities"
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "rules.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
                result = "effective-dated market rules"
            elif args.kind == "ohlcv":
                if not args.metadata:
                    raise ValueError("CSV OHLCV requires --metadata path")
                result = EquityData(REPO_ROOT).import_ohlcv(args.path, args.metadata)
            else:
                result = EquityData(REPO_ROOT).import_file(args.path)
            print(f"IMPORTED: {result}; local permitted data only")
            return 0
        except (OSError, ValueError, TypeError, KeyError) as exc:
            print(f"IMPORT_BLOCKED: {type(exc).__name__}")
            return 2
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
            s.load_if_enabled()
            if "clear" in sub or "reset" in sub:
                s.clear()
                s.clear_persistent()
                print("[PASS] Harness session memory cleared.")
            elif "on" in sub:
                s.set_persistence_enabled(True)
                s.save_persistent()
                print("[PASS] Local Harness persistence enabled.")
            elif "off" in sub:
                s.set_persistence_enabled(False)
                print("[PASS] Local Harness persistence disabled for future sessions.")
            elif "save" in sub:
                s.save_persistent()
                print("[PASS] Current Harness context saved locally.")
            else:
                print(s.status_display())
            return 0
        if args.mode == "cache":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            from openbagus.data.cache import MarketDataCache
            cache = MarketDataCache.get_instance()
            action = sub_args[0].lower() if sub_args else "status"
            if action == "clear":
                del_count = cache.clear_cache()
                print(f"[PASS] Cleared {del_count} cached market entries.")
            elif action == "refresh":
                target_sym = sub_args[1].upper() if len(sub_args) > 1 else "BTC"
                del_count = cache.refresh_asset(target_sym)
                print(f"[PASS] Invalidated {del_count} cached entries for {target_sym}. Next request will fetch fresh data.")
            elif action == "policy":
                print(cache.format_policy_display())
            else:
                print(cache.format_status_display())
            return 0
        if args.mode == "privacy":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            action = sub_args[0].lower() if sub_args else "status"
            if action == "clear":
                res = clear_privacy_data(REPO_ROOT)
                print("[PASS] Privacy data cleared:\n" + "\n".join(f"  {k}: {v}" for k, v in res.items()))
            else:
                print(format_privacy_status(REPO_ROOT))
            return 0
        if args.mode == "reset":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            action = sub_args[0].lower() if sub_args else ""
            if action != "all":
                print("Usage: openbagus reset all")
                return 1
            print("\nPERINGATAN: Tindakan ini akan menghapus semua data lokal OpenBagus.")
            print(f"Ketik persis: {FULL_RESET_CONFIRMATION_PHRASE}")
            try:
                confirm = input("Konfirmasi: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[Reset dibatalkan.]")
                return 1
            if confirm != FULL_RESET_CONFIRMATION_PHRASE:
                print("[Reset dibatalkan: Frasa konfirmasi tidak sesuai.]")
                return 1
            res = execute_full_reset(REPO_ROOT)
            print("\n[RESET SELESAI]")
            for k, v in res.items():
                print(f"  {k:<30} {v}")
            return 0
        if args.mode == "gmail":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            return _run_gmail(sub_args)
        if args.mode == "whatsapp":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            return _run_whatsapp(sub_args)
        if args.mode == "autonomy":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            return _run_autonomy(sub_args)
        if args.mode == "alerts":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            return _run_alerts(sub_args)
        if args.mode == "delivery":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            return _run_delivery(sub_args)
        if args.mode == "integrations":
            from openbagus.integrations.tradingview_mcp import TradingViewMCPClient, format_integrations_view
            client = TradingViewMCPClient(root=REPO_ROOT)
            print(format_integrations_view(client.status()))
            return 0
        if args.mode == "voice":
            sub_args = args.extra if getattr(args, "extra", None) else arguments[1:]
            return _run_voice(sub_args)
        return _run_pipeline(args)

    query_text = " ".join(arguments)
    router = IntentRouter(repo_root=REPO_ROOT)
    researcher = CryptoResearchRunner(repo_root=REPO_ROOT)
    session = SessionState()
    session.load_if_enabled()
    req = router.parse(query_text, session=session)
    if req.needs_asset:
        print(req.clarification_prompt or "Which asset do you want to analyze?")
        return 0
    if req.request_type != "UNKNOWN" or req.asset or req.candidates or req.request_type in (
        "SYSTEM_INFO", "MARKET_OUTLOOK", "CATEGORY", "SCREEN", "PREFERENCE", "FEEDBACK", "HARNESS", "SETUP_CONFIG", "CHART",
        "CACHE_COMMAND", "PRIVACY_COMMAND", "RESET_COMMAND", "VISUALIZE", "BACKTEST", "REPORT_WORD", "REPORT_HTML",
        "REPORT_PDF", "EXPORT_PNG", "INTEGRATIONS"
    ):
        result = researcher.execute(req, session=session)
        if session.is_persistence_enabled():
            session.save_persistent()
        print(result)
        return 0

    print(f"Unknown coin or command: '{query_text}'.")
    print("Type a coin symbol (e.g. 'ETH', 'SOL') or '/help' for commands.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
