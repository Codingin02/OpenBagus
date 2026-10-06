import json
import io
from contextlib import redirect_stdout
import os
import subprocess
import sys
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import MagicMock, patch

from openbagus.core.env import RuntimeEnv
from openbagus.cli import main as cli_main
from openbagus import cli
from openbagus.data.providers import ProviderRegistry, VALIDATORS
from openbagus.delivery.adapters import WhatsAppCloudConfig, WhatsAppCloudTransport
from openbagus.delivery.mailbox import EMAIL_CONFIRMATION_PHRASE, SmtpConfig, SmtpTransport
from openbagus.domains.crypto.quant import QuantEngine
from openbagus.domains.crypto.research import ResearchPacket
from openbagus.delivery.runner import ManualQueryParser, run_final_delivery
from scripts.openbagus_run_final import _delivery_exit_code, main as compatibility_main


ANALYSIS = {
    "generated_at_utc": "2026-10-01T00:00:00Z",
    "data_freshness_summary": {"overall_analysis_status": "OK"},
    "source_health_summary": {"fail": 0},
    "asset_views": {
        "BTC/USD": {
            "current_price": 65000.0,
            "portfolio_stance": "Hold",
            "conviction_score": 60,
            "actionability_score": 50,
            "invalidation_level": 60000.0,
            "risk_note": "Volatility remains elevated.",
        }
    },
    "macro_views": {},
}


class TestCliEmail(unittest.TestCase):
    def test_setup_saves_only_valid_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".env").write_text("", encoding="utf-8")
            registry = ProviderRegistry(root)
            configurable = [p for p in registry.list_all() if not p.public_access]
            alpha = str(next(i for i, p in enumerate(configurable, 1) if p.id == "alpha_vantage"))
            fred = str(next(i for i, p in enumerate(configurable, 1) if p.id == "fred"))
            output = io.StringIO()
            with patch.dict(os.environ, {}, clear=True), patch.object(cli, "REPO_ROOT", root), patch("builtins.input", side_effect=["y", alpha, fred, "0", "n", "n"]) as inputs, patch("getpass.getpass", side_effect=["fixture-alpha", "fixture-fred"]), patch.dict(VALIDATORS, {"alpha_vantage": lambda key: "VALID", "fred": lambda key: "INVALID"}), redirect_stdout(output):
                self.assertEqual(cli._run_setup(), 0)
                cli._run_status()
            content = (root / ".env").read_text(encoding="utf-8")
            self.assertIn("ALPHAVANTAGE_API_KEY=", content)
            self.assertNotIn("FRED_API_KEY=", content)
            self.assertIn("INVALID - not saved", output.getvalue())
            self.assertIn("1 present / 1 validated", output.getvalue())
            self.assertNotIn("fixture-alpha", output.getvalue())
            self.assertNotIn("fixture-fred", output.getvalue())
            self.assertTrue(all("(Y/N)::" not in call.args[0] for call in inputs.call_args_list))

    def test_powershell_setup_prompt_and_active_output(self):
        root = Path(__file__).resolve().parents[1]
        script = (root / "scripts/setup_openbagus.ps1").read_text(encoding="utf-8")
        self.assertNotIn('(Y/N):"', script)
        self.assertEqual(script.count('Write-Host "[PASS] Local Language Engine: ACTIVE'), 1)
        self.assertIn("Qwen3-0.6B -> Qwen3-4B Q4_K_M", script)
        self.assertIn("Qwen3-4B-Q4_K_M.gguf", script)

    def test_runtime_failure_has_nonzero_exit_code(self):
        self.assertEqual(_delivery_exit_code([{"status": "RUNTIME_FAILED"}]), 1)
        self.assertEqual(_delivery_exit_code([{"status": "EMAIL_CONFIG_MISSING"}]), 2)
        self.assertEqual(_delivery_exit_code([{"status": "EMAIL_DRAFT_READY"}]), 0)

    def test_module_entrypoint_and_unknown_command(self):
        root = Path(__file__).resolve().parents[1]
        help_result = subprocess.run(
            [sys.executable, "-m", "openbagus", "--help"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0)

        invalid_result = subprocess.run(
            [sys.executable, "-m", "openbagus", "not-a-command"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(invalid_result.returncode, 0)

    def test_compatibility_script_uses_canonical_cli(self):
        self.assertIs(compatibility_main, cli_main)

    def test_manual_trigger_is_exact(self):
        parser = ManualQueryParser()
        self.assertTrue(parser.parse("OpenBagus review BTC")["trigger_ok"])
        self.assertFalse(parser.parse("Open Bagus review BTC")["trigger_ok"])
        self.assertFalse(parser.parse("prefixOpenBagusSuffix BTC")["trigger_ok"])

    def test_email_draft_has_mime_attachment(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            analysis_path = root / "reports/runtime/openbagus_real_analysis_latest.json"
            analysis_path.parent.mkdir(parents=True)
            analysis_path.write_text(json.dumps(ANALYSIS), encoding="utf-8")

            result = run_final_delivery(mode="email", repo_root=root)

            self.assertEqual(result["status"], "EMAIL_DRAFT_READY")
            eml_path = Path(result["artifacts"]["eml"])
            message = BytesParser(policy=policy.default).parsebytes(eml_path.read_bytes())
            attachments = list(message.iter_attachments())
            self.assertEqual(len(attachments), 1)
            self.assertEqual(attachments[0].get_content_type(), "text/html")
            self.assertEqual(attachments[0].get_filename(), "EMAIL_MACRO_DAILY_report_latest.html")
            self.assertIsNotNone(message["Date"])
            self.assertIsNotNone(message["Message-ID"])

    def test_authenticated_smtp_rejects_plaintext_transport(self):
        env = {
            "OPENBAGUS_EMAIL_SMTP_HOST": "smtp.example.test",
            "OPENBAGUS_EMAIL_SMTP_PORT": "25",
            "OPENBAGUS_EMAIL_SECURITY": "none",
            "OPENBAGUS_EMAIL_SMTP_USERNAME": "user@example.test",
            "OPENBAGUS_EMAIL_SMTP_PASSWORD": "x",
            "OPENBAGUS_EMAIL_FROM": "sender@example.test",
            "OPENBAGUS_EMAIL_TO": "recipient@example.test",
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, env, clear=False):
            config = SmtpConfig.from_runtime_env(RuntimeEnv(Path(temp_dir)))

        self.assertFalse(config.ready)
        self.assertIn("Authenticated SMTP requires starttls or ssl", config.errors)

    def test_starttls_check_authenticates_without_sending(self):
        env = {
            "OPENBAGUS_EMAIL_SMTP_HOST": "smtp.example.test",
            "OPENBAGUS_EMAIL_SMTP_PORT": "587",
            "OPENBAGUS_EMAIL_SECURITY": "starttls",
            "OPENBAGUS_EMAIL_SMTP_USERNAME": "user@example.test",
            "OPENBAGUS_EMAIL_SMTP_PASSWORD": "x",
            "OPENBAGUS_EMAIL_FROM": "sender@example.test",
            "OPENBAGUS_EMAIL_TO": "recipient@example.test",
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, env, clear=False):
            config = SmtpConfig.from_runtime_env(RuntimeEnv(Path(temp_dir)))
            smtp_instance = MagicMock()
            smtp_session = MagicMock()
            smtp_instance.__enter__.return_value = smtp_session
            with patch("openbagus.delivery.mailbox.smtplib.SMTP", return_value=smtp_instance):
                result = SmtpTransport(config).check()

            self.assertEqual(result, {"status": "EMAIL_SMTP_READY", "message_sent": False})
            smtp_instance.starttls.assert_called_once()
            smtp_session.login.assert_called_once_with("user@example.test", "x")
            smtp_session.noop.assert_called_once()
            smtp_session.send_message.assert_not_called()

    def test_ssl_send_authenticates_and_sends(self):
        config = SmtpConfig.from_values(
            host="smtp.example.test", port_text="465", security="ssl",
            username="user@example.test", password="secret", sender="sender@example.test",
            recipient_text="recipient@example.test",
        )
        smtp_instance = MagicMock()
        smtp_session = MagicMock()
        smtp_instance.__enter__.return_value = smtp_session
        with patch("openbagus.delivery.mailbox.smtplib.SMTP_SSL", return_value=smtp_instance):
            result = SmtpTransport(config).send(MagicMock())
        self.assertEqual(result["status"], "EMAIL_SENT")
        smtp_session.login.assert_called_once_with("user@example.test", "secret")
        smtp_session.send_message.assert_called_once()

    def test_smtp_authentication_and_send_failures_are_propagated_without_secret(self):
        config = SmtpConfig.from_values(
            host="smtp.example.test", port_text="587", security="starttls",
            username="user@example.test", password="local-secret", sender="sender@example.test",
            recipient_text="recipient@example.test",
        )
        smtp_instance = MagicMock()
        smtp_session = MagicMock()
        smtp_instance.__enter__.return_value = smtp_session
        smtp_session.login.side_effect = __import__("smtplib").SMTPAuthenticationError(535, b"rejected")
        with patch("openbagus.delivery.mailbox.smtplib.SMTP", return_value=smtp_instance):
            with self.assertRaises(__import__("smtplib").SMTPAuthenticationError) as failure:
                SmtpTransport(config).send(MagicMock())
        self.assertNotIn("local-secret", str(failure.exception))

    def test_live_send_requires_local_enablement(self):
        env = {
            "OPENBAGUS_EMAIL_SMTP_HOST": "smtp.example.test",
            "OPENBAGUS_EMAIL_SMTP_PORT": "587",
            "OPENBAGUS_EMAIL_SECURITY": "starttls",
            "OPENBAGUS_EMAIL_FROM": "sender@example.test",
            "OPENBAGUS_EMAIL_TO": "recipient@example.test",
            "OPENBAGUS_EMAIL_LIVE_ENABLED": "false",
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, env, clear=False):
            root = Path(temp_dir)
            analysis_path = root / "reports/runtime/openbagus_real_analysis_latest.json"
            analysis_path.parent.mkdir(parents=True)
            analysis_path.write_text(json.dumps(ANALYSIS), encoding="utf-8")
            result = run_final_delivery(
                mode="email",
                email_action="send",
                confirmation=EMAIL_CONFIRMATION_PHRASE,
                dry_run=False,
                repo_root=root,
            )

        self.assertEqual(result["status"], "BLOCKED_LIVE_EMAIL_NOT_ENABLED")
        self.assertNotIn('"password"', json.dumps(result).lower())

    def test_dry_run_blocks_email_send(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            analysis_path = root / "reports/runtime/openbagus_real_analysis_latest.json"
            analysis_path.parent.mkdir(parents=True)
            analysis_path.write_text(json.dumps(ANALYSIS), encoding="utf-8")
            result = run_final_delivery(mode="email", email_action="send", dry_run=True, repo_root=root)

        self.assertEqual(result["status"], "BLOCKED_DRY_RUN")

    def test_whatsapp_cloud_validate_text_template_and_sanitized_failure(self):
        config = WhatsAppCloudConfig(True, "local-secret", "12345", "+628111111111", template_name="hello_world")
        transport = WhatsAppCloudTransport(config)
        with patch.object(transport, "_request", return_value=(200, {"id": "12345"})):
            self.assertEqual(transport.validate()["status"], "VALID")
        with patch.object(transport, "_request", return_value=(401, {"error": {"message": "invalid token"}})):
            self.assertEqual(transport.validate(), {"status": "INVALID"})
        with patch.object(transport, "_request", return_value=(200, {"messages": [{"id": "wamid"}]})) as request:
            self.assertEqual(transport.send("Current research")["status"], "WHATSAPP_SENT")
            self.assertEqual(request.call_args.kwargs["payload"]["type"], "text")
        with patch.object(transport, "_request", return_value=(200, {"messages": [{"id": "wamid"}]})) as request:
            self.assertEqual(transport.send("ignored", use_template=True)["status"], "WHATSAPP_SENT")
            self.assertEqual(request.call_args.kwargs["payload"]["type"], "template")
        with patch.object(transport, "_request", return_value=(400, {"error": {"code": 131047, "message": "secret detail"}})):
            failure = transport.send("Current research")
        self.assertEqual(failure, {"status": "WHATSAPP_TEMPLATE_REQUIRED"})
        self.assertNotIn("secret", json.dumps(failure).lower())
        with patch.object(transport, "_request", return_value=(500, {"error": {"message": "local-secret"}})):
            failure = transport.send("Current research")
        self.assertEqual(failure["status"], "WHATSAPP_SEND_FAILED")
        self.assertNotIn("local-secret", json.dumps(failure))

    def test_direct_send_reuses_current_session_without_research_fetch(self):
        quant = QuantEngine().evaluate("BTC", {"price": 65000.0, "high": 66000.0, "low": 64000.0})
        packet = ResearchPacket(
            asset="BTC", market="GENERAL / SPOT REFERENCE", timeframe="H1", price=quant.price,
            decision=quant.decision, data_quality=quant.data_quality, setup_quality=quant.setup_quality,
            decision_reason=quant.decision_reason, narrative="BTC remains conditional on the stated levels.",
        )
        shell = cli.OpenBagusShell()
        shell.session.last_quant_result = quant
        shell.session.last_research_packet = packet
        env = {
            "OPENBAGUS_EMAIL_SMTP_HOST": "smtp.example.test", "OPENBAGUS_EMAIL_SMTP_PORT": "587",
            "OPENBAGUS_EMAIL_SECURITY": "starttls", "OPENBAGUS_EMAIL_FROM": "sender@example.test",
            "OPENBAGUS_EMAIL_TO": "recipient@example.test", "OPENBAGUS_EMAIL_LIVE_ENABLED": "true",
            "OPENBAGUS_WHATSAPP_ENABLED": "true", "OPENBAGUS_WHATSAPP_ACCESS_TOKEN": "local-secret",
            "OPENBAGUS_WHATSAPP_PHONE_NUMBER_ID": "12345", "OPENBAGUS_WHATSAPP_RECIPIENT": "+628111111111",
        }
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temp_dir, patch.dict(os.environ, env, clear=False), patch.object(cli, "REPO_ROOT", Path(temp_dir)), patch.object(SmtpTransport, "send", return_value={"status": "EMAIL_SENT", "message_sent": True}) as email_send, patch.object(WhatsAppCloudTransport, "send", return_value={"status": "WHATSAPP_SENT"}) as wa_send, patch.object(shell.researcher, "execute") as research, redirect_stdout(output):
            shell.do_send("all")
        email_send.assert_called_once()
        wa_send.assert_called_once()
        research.assert_not_called()
        self.assertIn("Email      SENT", output.getvalue())
        self.assertIn("WhatsApp   SENT", output.getvalue())

    def test_natural_send_phrases_delegate_to_direct_delivery(self):
        shell = cli.OpenBagusShell()
        cases = {
            "kirim hasil ini ke email": "email",
            "send to whatsapp": "whatsapp",
            "kirim ke email dan whatsapp": "all",
        }
        for phrase, channel in cases.items():
            with self.subTest(phrase=phrase), patch.object(shell, "do_send") as send:
                shell.default(phrase)
                send.assert_called_once_with(channel)


if __name__ == "__main__":
    unittest.main()
