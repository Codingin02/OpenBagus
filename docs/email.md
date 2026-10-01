# Email Operations

Email is optional. The core CLI and crypto pipeline work without SMTP configuration. OpenBagus uses Python's provider-neutral SMTP and MIME support; Gmail is one possible provider, not a separate transport.

## Actions

Draft generates local text, HTML, EML, and print-ready attachment files without contacting a server:

```powershell
openbagus email --email-action draft
```

Check validates configuration without network access:

```powershell
openbagus email --email-action check
```

An explicit network check connects and authenticates but never sends a message:

```powershell
openbagus email --email-action check --network
```

## Configuration

Set values in the process environment or the ignored `config/openbagus_runtime_local.env`.

| Variable | Purpose |
| --- | --- |
| `OPENBAGUS_EMAIL_SMTP_HOST` | SMTP hostname |
| `OPENBAGUS_EMAIL_SMTP_PORT` | SMTP port |
| `OPENBAGUS_EMAIL_SECURITY` | `starttls`, `ssl`, or `none` |
| `OPENBAGUS_EMAIL_SMTP_USERNAME` | Optional username |
| `OPENBAGUS_EMAIL_SMTP_PASSWORD` | Password or application password when username is set |
| `OPENBAGUS_EMAIL_FROM` | Sender address |
| `OPENBAGUS_EMAIL_TO` | Comma-separated recipients |
| `OPENBAGUS_EMAIL_LIVE_ENABLED` | Must be `true` for live sending |

Authenticated SMTP requires `starttls` or `ssl`. Compatibility variables `OPENBAGUS_EMAIL_USE_TLS`, `OPENBAGUS_EMAIL_TO_MACRO`, and `OPENBAGUS_EMAIL_TO_OPERATOR` remain accepted.

## Live Send Safety

Live sending requires all of the following:

- Complete valid SMTP configuration
- `OPENBAGUS_EMAIL_LIVE_ENABLED=true`
- Explicit `send` action
- Exact confirmation phrase
- Non-dry-run execution

```powershell
openbagus email --email-action send --confirm-live-send I_UNDERSTAND_THIS_SENDS_REAL_EMAIL
```

Doctor, draft generation, local checks, and normal tests never send email.

## Optional Daily Scheduling

OpenBagus does not run a scheduler daemon. Use the operating system scheduler only after email is configured and tested.

Example Windows Task Scheduler action:

```text
Program: C:\path\to\openbagus\.venv\Scripts\openbagus.exe
Arguments: email --email-action send --confirm-live-send I_UNDERSTAND_THIS_SENDS_REAL_EMAIL
Start in: C:\path\to\openbagus
```

Scheduling is disabled by default. Keep credentials in the user environment or ignored local configuration, never in the scheduled command or Git.
