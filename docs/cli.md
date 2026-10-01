# CLI Reference

OpenBagus exposes one CLI implementation through both `openbagus` and `python -m openbagus`.

## Interactive Mode

Run `openbagus` in a terminal. The shell provides:

| Command | Purpose |
| --- | --- |
| `help` | Show commands |
| `status` | Show compact runtime status |
| `doctor` | Run local diagnostics |
| `crypto` | Run the public-data crypto pipeline |
| `review BTC ETH` | Run a manual research review |
| `email draft` | Generate local email artifacts |
| `email check` | Validate email configuration locally |
| `config` | Show configuration status without values |
| `version` | Show the package version |
| `clear` | Clear the terminal |
| `exit` | Exit the shell |

Set `NO_COLOR=1` for plain output.

## Non-Interactive Commands

```powershell
openbagus doctor
openbagus status
openbagus config
openbagus crypto-daily
openbagus manual-desk --query "OpenBagus review BTC ETH"
openbagus email --email-action draft
openbagus email --email-action check
```

`manual-desk` requires the exact trigger `OpenBagus`. The spaced form `Open Bagus` is invalid.

Successful operations return exit code `0`. Runtime failures return `1`; blocked or incomplete requested operations return `2`. Interactive errors do not terminate the shell.

## Disabled Commands

`idx-daily` remains available only as a compatibility guard and returns `EQUITY_DOMAIN_DISABLED`. WhatsApp and OpenClaw have no active CLI delivery command.
