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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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

    def preloop(self) -> None:
        color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        banner = f"\033[36m{BANNER}\033[0m" if color else BANNER
        print(banner)
        print("Ask anything about a crypto asset.")
        print("Type a coin, symbol, or question. /help for commands.\n")
        if self.session.last_asset:
            print(f"[Restored persistent session context: {self.session.last_asset} ({self.session.timeframe or '1d'})]")
            print(f"Type 'lanjutkan {self.session.last_asset} tadi' to continue or switch to a new asset.\n")

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
        print("  /feedback <type> <text>    explicit correction, opt-in local storage")
        print("  /improve status|off|clear|export  review and control local feedback")
        print("  /help                     show this help screen")
        print("  /harness [on|off|save|clear] show or control persistent session memory")
        print("  /cache [status|clear|refresh <asset>|policy] inspect or manage market cache")
        print("  /privacy [status|clear]    inspect or clear local privacy data")
        print("  /reset all                 full reset of local OpenBagus data (requires confirmation)")
        print("  /switch <asset>           switch active research context directly")
        print("  /sources [on|off]         toggle display of data sources in research outputs")
        print("  /chart [asset] [tf]       open real browser chart in TradingView or GeckoTerminal")
        print("  /visualize [asset]        open native interactive HTML dashboard (candlestick, radar, sunburst)")
        print("  /backtest [asset]         run walk-forward backtest with realistic costs & promotion gate")
        print("  /report word|html [asset] generate Word (.docx with native chart) or HTML report")
        print("  /ownership [asset]        show verified shareholder ownership structure (IDX/KSEI)")
        print("  /status                   show platform runtime and provider status")
        print("  /providers                show data providers and coverage (or /providers --check)")
        print("  /assets [query]           search crypto asset universe (e.g. /assets eth, /assets defi)")
        print("  /categories               list crypto taxonomy categories")
        print("  /setup                    configure optional API keys or email")
        print("  /doctor [network]         run local diagnostics (use /doctor network for live ping)")
        print("  /email                    manage optional email draft/check")
        print("  /gmail [cmd]              manage official Google OAuth Gmail delivery")
        print("  /whatsapp [cmd]           manage personal WhatsApp compose")
        print("  /autonomy [cmd]           control autonomous monitoring runtime")
        print("  /alerts [cmd]             manage monitoring and alert rules")
        print("  /delivery [status]        unified delivery channels overview")
        print("  /send email|gmail|wa|all  send the current research result")
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
        sub = arg.strip().lower()
        if sub in ("clear", "reset"):
            self.session.clear()
            self.session.clear_persistent()
            print("[PASS] Harness session memory cleared.")
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
        if self.session.is_persistence_enabled():
            self.session.save_persistent()
        else:
            self.session.clear()
        LocalLanguageEngine.shutdown_runtime()
        return True

    def do_quit(self, _arg: str) -> bool:
        if self.session.is_persistence_enabled():
            self.session.save_persistent()
        else:
            self.session.clear()
        LocalLanguageEngine.shutdown_runtime()
        return True

    def do_EOF(self, _arg: str) -> bool:
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
            "SYSTEM_INFO", "MARKET_OUTLOOK", "CATEGORY", "SCREEN", "PREFERENCE", "FEEDBACK", "HARNESS", "SETUP_CONFIG", "CHART",
            "VISUALIZE", "BACKTEST", "REPORT_WORD", "REPORT_HTML", "EQUITY_OWNERSHIP", "EQUITY_ANALYSIS", "EQUITY_QUOTE", "EQUITY_SECTOR"
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
        "CACHE_COMMAND", "PRIVACY_COMMAND", "RESET_COMMAND", "VISUALIZE", "BACKTEST", "REPORT_WORD", "REPORT_HTML"
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
