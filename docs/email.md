# Email Operations

Email delivery is strictly optional. The core OpenBagus CLI and crypto research pipeline function completely without any SMTP configuration. If email is not configured, reports are generated locally on disk without error.

OpenBagus uses Python's standard library for provider-neutral SMTP and MIME message building. Any standard RFC-compliant SMTP provider can be used.

## Operations Overview

OpenBagus strictly separates draft generation, configuration checking, and live delivery:

| Action | Network Delivery | Purpose |
| --- | --- | --- |
| `openbagus email --email-action draft` | No | Generates local text, HTML, and EML files in `reports/runtime/delivery/`. |
| `openbagus email --email-action check` | No | Verifies local environment configuration format without contacting a server. |
| `openbagus email --email-action check --network` | Auth test only (no message) | Connects to SMTP host and authenticates credentials, but sends no email. |
| `openbagus email --email-action send` | Yes (guarded) | Delivers the latest report. Requires explicit safety flags. |

## Configuration Variables

Configure these settings in your process environment or in a local ignored file (`.env` or `config/openbagus_runtime_local.env`):

| Variable | Description | Example / Default |
| --- | --- | --- |
| `OPENBAGUS_EMAIL_SMTP_HOST` | SMTP server hostname | `smtp.example.com` |
| `OPENBAGUS_EMAIL_SMTP_PORT` | SMTP port | `587` (STARTTLS) or `465` (SSL) |
| `OPENBAGUS_EMAIL_SECURITY` | Connection security | `starttls`, `ssl`, or `none` |
| `OPENBAGUS_EMAIL_SMTP_USERNAME` | SMTP account username | `user@example.com` |
| `OPENBAGUS_EMAIL_SMTP_PASSWORD` | SMTP password / app password | `secret_password` |
| `OPENBAGUS_EMAIL_FROM` | Sender address | `reports@example.com` |
| `OPENBAGUS_EMAIL_TO` | Comma-separated recipient addresses | `analyst@example.com,desk@example.com` |
| `OPENBAGUS_EMAIL_LIVE_ENABLED` | Global live delivery gate | `false` (set to `true` to allow live sending) |

### Generic SMTP Example

Add to your local `.env`:

```env
OPENBAGUS_EMAIL_SMTP_HOST=smtp.mailprovider.com
OPENBAGUS_EMAIL_SMTP_PORT=587
OPENBAGUS_EMAIL_SECURITY=starttls
OPENBAGUS_EMAIL_SMTP_USERNAME=myuser@mailprovider.com
OPENBAGUS_EMAIL_SMTP_PASSWORD=my_secure_smtp_password
OPENBAGUS_EMAIL_FROM=myuser@mailprovider.com
OPENBAGUS_EMAIL_TO=recipient@domain.com
OPENBAGUS_EMAIL_LIVE_ENABLED=false
```

> [!NOTE]
> If using Gmail as an example provider, use `smtp.gmail.com`, port `587`, `starttls`, and a 16-character Google Account App Password. Gmail is just one example; any standard SMTP server is supported.

## Live Send Safety Gates

Live sending is heavily protected against accidental dispatch. All five conditions must be met simultaneously:

1. Complete and valid SMTP configuration present
2. `OPENBAGUS_EMAIL_LIVE_ENABLED=true` set in environment or local config
3. Explicit `--email-action send` CLI flag
4. Exact safety confirmation argument: `--confirm-live-send I_UNDERSTAND_THIS_SENDS_REAL_EMAIL`
5. Dry-run mode inactive

Example live delivery command:

```powershell
openbagus email --email-action send --confirm-live-send I_UNDERSTAND_THIS_SENDS_REAL_EMAIL
```

## Optional Daily Scheduling

OpenBagus does **not** run persistent background daemon processes or schedulers. Daily execution should be driven by the host operating system's native scheduler (Windows Task Scheduler, Linux `cron`, or `systemd` timers) calling the CLI command.

Daily email scheduling is **disabled by default**.

### Windows Task Scheduler Example

1. Open **Task Scheduler** and select **Create Basic Task**.
2. Set trigger to **Daily** at your preferred time (e.g., 07:00 AM).
3. Set action to **Start a program**:
   - **Program/script**: `C:\path\to\openbagus\.venv\Scripts\openbagus.exe`
   - **Add arguments**: `email --email-action send --confirm-live-send I_UNDERSTAND_THIS_SENDS_REAL_EMAIL`
   - **Start in**: `C:\path\to\openbagus`

Keep your credentials in the local `.env` or user environment. Never put passwords in the scheduled task command line or commit them to Git.
