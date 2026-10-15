# Windows Local Trial

The canonical application entrypoint is `openbagus.bootstrap.main`.
Interactive `python -m openbagus.cli` and the frozen executable use this bootstrap.
Explicit legacy CLI subcommands remain available from source.

Build with Python 3.14, the project dependencies, PyInstaller 6.22.3,
pyinstaller-hooks-contrib 2026.8 and the official signed Inno Setup 6.7.3 compiler.
Packaging dependencies must remain in the private `.packaging-venv`, not a global install.
The current machine uses the project venv's dependencies and the private build tool path:

```powershell
$env:PYTHONPATH = "$PWD\.packaging-venv\Lib\site-packages"
& 'E:\Projects\OpenBagus\.venv\Scripts\python.exe' packaging/windows/build.py --inno '.cache/build-tools/InnoSetup/ISCC.exe'
```

The result is an onedir application plus `E:\Projects\OpenBagus\release\OpenBagus-Setup.exe`.
The installed executable does not use this venv or run a PowerShell launcher.
It includes Python, native voice libraries and the local Ollama server.
It starts an isolated loopback server with cloud disabled and one model resident at a time.
It never terminates an unrelated server. A Windows job object owns its process tree.

Shared weights remain outside the package at `E:\Projects\OpenBagus\models`.
The installer preserves the application-level `openbagus.json` during upgrade/uninstall.
User preferences, sessions and datasets are outside the installation directory.
Per-user install, desktop/start-menu shortcuts and an uninstaller require no administrator.

Reference: [PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html),
[child-process DLL handling](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html),
[Inno Setup post-install launch](https://jrsoftware.org/ishelp/topic_runsection.htm).

See THIRD_PARTY_NOTICES.md before redistributing; this unsigned package is a private local trial.
