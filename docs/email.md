# Email Operations

OpenBagus uses Python's standard SMTP and MIME libraries. Draft generation is the default and does not contact an SMTP server.

## Configuration

Set private values in the process environment or an ignored local environment file. Never commit SMTP credentials.

| Variable | Purpose |
| --- | --- |
| `OPENBAGUS_EMAIL_SMTP_HOST` | SMTP server hostname |
| `OPENBAGUS_EMAIL_SMTP_PORT` | SMTP port, usually `587` for STARTTLS or `465` for implicit TLS |
| `OPENBAGUS_EMAIL_SECURITY` | `starttls`, `ssl`, or `none` |
| `OPENBAGUS_EMAIL_SMTP_USERNAME` | Optional SMTP username |
| `OPENBAGUS_EMAIL_SMTP_PASSWORD` | Password or provider app password; required when username is set |
| `OPENBAGUS_EMAIL_FROM` | Sender address |
| `OPENBAGUS_EMAIL_TO` | Comma-separated recipient addresses |
| `OPENBAGUS_EMAIL_LIVE_ENABLED` | Must be `true` before real sending is allowed |

`OPENBAGUS_EMAIL_USE_TLS` and the older recipient variables remain accepted for compatibility, but new installations should use `OPENBAGUS_EMAIL_SECURITY` and `OPENBAGUS_EMAIL_TO`.

## Workflow

Generate local `.txt`, `.html`, `.eml`, and print-ready HTML attachment files:

```powershell
python -m openbagus email --email-action draft
```

Validate configuration without using the network:

```powershell
python -m openbagus email --email-action check
```

Explicitly test SMTP connectivity and authentication without sending a message:

```powershell
python -m openbagus email --email-action check --network
```

Real delivery requires complete configuration, `OPENBAGUS_EMAIL_LIVE_ENABLED=true`, the `send` action, and the exact confirmation phrase:

```powershell
python -m openbagus email --email-action send --confirm-live-send I_UNDERSTAND_THIS_SENDS_REAL_EMAIL
```

No live delivery should be used in automated tests. Authentication errors normally indicate invalid provider credentials or an application-password requirement. Network errors are reported without logging credentials.
