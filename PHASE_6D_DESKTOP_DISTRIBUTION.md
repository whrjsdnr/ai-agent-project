# Phase 6D — Desktop distribution

## Result and scope

**PACKAGING CONFIGURATION VERIFIED.** Linux frozen acceptance verified.
**NATIVE WINDOWS ARTIFACT NOT VERIFIED. INSTALLER ARTIFACT NOT VERIFIED.**

The Windows build was attempted using native PowerShell/uv through WSL. Windows
uv rejected a WSL UNC checkout, so a separate allowlisted source copy was built
from a new native Windows temporary directory. Locked Python 3.12 dependencies
installed successfully. Windows application control then blocked the generated
pytest launcher, and standard `python -m pytest` encountered a blocked `_ssl`
DLL. No Windows security setting was changed. The native build could not proceed
to a verified executable. Inno Setup was not available at its normal location or
on PATH. No installer compilation or install/uninstall test is claimed locally.

The checked-in manual Windows CI workflow is the native release path; it has not
been dispatched from this session. No commit, push, release upload or final product
audit was performed.

## Packaging architecture

PyInstaller is the sole bundler, installed in a separate `build` dependency group.
The lock pins PyInstaller 6.22.2, hooks-contrib and platform-specific dependencies.
Inno Setup is an external Windows build tool, not a runtime Python dependency.

The explicit `packaging/pyinstaller/ai-agent.spec` builds a **one-directory**
application named `AI-Agent`. On Windows its executable is `AI-Agent.exe`, with
`console=False` and GUI subsystem verification. One-directory avoids one-file
extraction/startup complexity and makes Qt DLL/plugin collection inspectable.
The installer distributes the directory; end users need no Python or uv.
PyInstaller builds are platform-specific; Linux output is never renamed `.exe`.
See [PyInstaller's platform guidance](https://pyinstaller.org/en/stable/operating-mode.html).

The entry script invokes only `desktop_app.main:main`. Existing CLI and FastAPI
remain source capabilities and are excluded from the frozen product. Standard
PyInstaller PySide6 hooks collect imported Qt modules/platform plugins; there are
no speculative hidden imports or manual copies of all PySide6 resources. The
Windows bundle audit requires `qwindows.dll` and a 64-bit PE GUI executable.

An explicit asset allowlist includes the original geometric A SVG, a generated
multi-size ICO, and version metadata. No repository-wide data collection occurs.
PyInstaller's importlib metadata analysis also collected editable `direct_url.json`
on the first smoke build. The spec now removes those entries, and the bundle
audit rejects them. Embedded application code filenames are checked for absolute
build paths; excluded modules are checked inside PYZ as well as on disk.

## Build and installer

Prerequisites: a local Windows-drive checkout, native Windows uv, Python 3.12
(obtained by uv if needed), and Inno Setup 6 for installer compilation. The
configured x64 target is Windows 10 1809+ or Windows 11, consistent with
[Qt 6.11 platform support](https://doc.qt.io/qt-6/windows.html).

```powershell
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1
powershell -ExecutionPolicy Bypass -File packaging/windows/build.ps1 -Installer
```

The script fails fast, resolves its own repository root, uses
`build/windows-venv`, syncs `uv.lock`, runs packaging tests via `python -m pytest`,
invokes the explicit spec via `python -m PyInstaller`, and verifies the output.
It does not delete arbitrary paths; PyInstaller replaces only its known output.
Build paths containing a WSL UNC share are rejected with a clear instruction.

`-Installer` derives AppVersion from installed package metadata, invokes ISCC
with deterministic definitions and verifies `dist/installer/AI-Agent-Setup.exe`.
The `.iss` contains a stable AppId, version metadata, product icon, per-user
installation into `{localappdata}/Programs/AI Agent`, Start Menu shortcut, optional
desktop shortcut, and standard uninstall entry. No invented publisher is used.
`PrivilegesRequired=lowest` avoids elevation. See
[Inno Setup privilege behavior](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm).

Normal upgrades/uninstall touch application binaries and shortcuts only. The
installer has no user-data entries and no `[UninstallDelete]` rules. Config,
projects, research runs, handoffs and workspaces remain outside the install tree.

## Runtime paths and assets

`paths.py` centralizes config/data/cache resolution without creating directories
on import. Store constructors and explicit operations create needed directories.

| Runtime location | Windows | Linux/WSL |
| --- | --- | --- |
| Config | `%APPDATA%/ai-agent` | `$XDG_CONFIG_HOME/ai-agent` or `~/.config/ai-agent` |
| Data | `%LOCALAPPDATA%/ai-agent/data` | `$XDG_DATA_HOME/ai-agent` or `~/.local/share/ai-agent` |
| Cache | `%LOCALAPPDATA%/ai-agent/cache` | `$XDG_CACHE_HOME/ai-agent` or `~/.cache/ai-agent` |
| Frozen workspace | Data root + `workspaces/default` | Data root + `workspaces/default` |
| Startup diagnostic | Data root + `logs/startup.log` | Data root + `logs/startup.log` |

Missing Windows environment variables fall back to the current user's
`AppData/Roaming` and `AppData/Local`. Relative environment roots are ignored.
Existing explicit custom roots/workspaces still work. Source desktop development
keeps its cwd workspace default; frozen runtime uses the writable user workspace.
No workflow state is placed under the installation directory or permanent `/tmp`.
Explicit packaging smoke uses disposable temporary stores only.

`desktop_app/resources.py` resolves assets relative to `__file__`, which works
both in source and PyInstaller's preserved package layout. No `_MEIPASS` checks
are scattered through widgets. Qt uses the source SVG; the executable and
installer use the deterministic six-size ICO generated under ignored `build/assets`.
No third-party logo or binary artwork was added. `pyproject.toml` remains the one
version source; app metadata, Windows version resources and installer definitions
derive from the installed package version. Distribution versions must be numeric
`major.minor.patch`.

## Minimal portability fixes

Two pre-existing POSIX assumptions prevented Windows distribution:

- The snapshot store imported `fcntl` unconditionally. `file_lock.py` now supplies
  equivalent exclusive file locking with `msvcrt` on Windows and `flock` on Linux.
  The same authoritative bootstrap check and atomic snapshot write remain inside
  the lock; no state-machine or approval semantics changed.
- Safe artifact export used POSIX `dir_fd` operations. Windows export now holds
  ancestor directory handles denying write/delete sharing, rejects reparse points,
  writes a temporary file, and publishes via a no-overwrite hard link. Existing
  Linux export code and ownership checks remain unchanged. Unsupported or unsafe
  Windows destinations fail safely instead of bypassing checks.

Native execution of these Windows paths remains subject to the local application-
control limitation; the Windows packaging suite exercises them on the CI runner.

## Security and runtime behavior

Session credentials remain `SecretStr` values, never written to regular JSON,
installer scripts, executable metadata, logs or bundled environment files.
Settings still delegates endpoint/model/timeout and connection checks to Phase
6A/6B. The custom endpoint is not overridden. No real provider request was used
for acceptance. The endpoint must implement Responses API and the structured
output features used by the application.

Startup failures show a fixed safe GUI message and may overwrite one fixed-line
user-owned diagnostic file. No exception strings, tracebacks, credentials, request
bodies or transcripts are logged there. Normal expected errors retain the existing
GUI boundary. There is no daemon, polling system, workflow engine or auto-chaining.
The explicit `--packaging-smoke` maintenance option constructs three pages in
isolated stores, closes the window and writes only fixed acceptance metadata to
user cache; normal launch never triggers it.

Unsigned builds can show SmartScreen warnings or be blocked by organizational
application control. Production release signing requires a trusted certificate;
no signing claim, signing secrets or Windows security bypass is included.

## CI native acceptance path

`.github/workflows/windows-package.yml` is `workflow_dispatch` only, with
read-only repository permissions on `windows-2022`. It installs Python x64/uv,
ensures Inno Setup 6, then invokes the same build script with `-Installer`.
If Inno Setup is missing, it downloads official 6.7.3 and checks Authenticode
validity before installation. See the
[official Inno Setup download](https://jrsoftware.org/isdl.php).

The script runs locked packaging tests, a PyInstaller build, file/PYZ audits,
PE x64/GUI-subsystem and qwindows checks, and an isolated offscreen frozen smoke.
The installer compiles only after acceptance. Two workflow artifacts contain the
application directory and `AI-Agent-Setup.exe`. No secrets or automatic publishing
are needed. Download and extract the complete application artifact for portable
use, or run the installer artifact.

## Acceptance evidence

| Check | Local evidence |
| --- | --- |
| Packaging tests | 25 passed, provider-free |
| Phase 6C offscreen GUI | 20 passed |
| Desktop facade | 23 passed |
| Broad agent/LLM/integration/API/CLI regression | 547 passed, 12 opt-in live-provider tests skipped |
| Source native GUI smoke | `uv run ai-agent-desktop --packaging-smoke`, exit 0 |
| Linux PyInstaller build | Completed; output `dist/linux/AI-Agent/AI-Agent` |
| Output type | `file`: ELF 64-bit LSB x86-64, Linux; not a Windows executable |
| Linux frozen GUI / archive audit | `LINUX_PACKAGING_SMOKE=PASSED`; Dashboard, Projects, Settings, assets/version and normal exit |
| Windows native build | Attempted; blocked by Windows application control before bundling |
| Native installer | Not compiled locally; Inno Setup unavailable |
| CI execution | Configured, not dispatched |
| Ruff | All checks passed |
| Format | All checked files formatted |
| Git diff whitespace | `git diff --check` passed |

The packaging suite covers the requested spec/entry/version/resource cases,
Windows and XDG locations, writable frozen workspace/first run, credential safety,
explicit data/module exclusions, installer preservation/shortcuts, build/CI names,
icon generation, and platform snapshot locking/export.

Reproduce Linux architecture smoke (not Windows distribution):

```bash
uv run --group build python -m PyInstaller --noconfirm --distpath dist/linux --workpath build/linux packaging/pyinstaller/ai-agent.spec
file dist/linux/AI-Agent/AI-Agent
uv run --group build python packaging/verify_bundle.py dist/linux/AI-Agent --smoke
```

## Delivery files and hygiene

Added distribution configuration: `packaging/pyinstaller/{entrypoint.py,ai-agent.spec}`,
`packaging/windows/build.ps1`, `packaging/windows/installer/AI-Agent.iss`,
`packaging/assets/generate_icon.py`, `packaging/verify_bundle.py`, and the Windows
workflow. Added runtime helpers: `paths.py`, `file_lock.py`, `windows_files.py`,
`desktop_app/resources.py`, `desktop_app/packaging_smoke.py`, and the original SVG.
Added packaging tests and this release report.

Modified `.gitignore`, `pyproject.toml`, `uv.lock`, README, desktop startup/composition,
provider config path, the four store default paths, snapshot locking and Windows
artifact-export compatibility. Existing uncommitted Phase 6C changes to
`api/app.py`, `cli.py`, and untracked `composition.py` were present at the start
and were preserved; they are not new Phase 6D refactors.

`build/`, `dist/`, installer output and `.env` are ignored. No binaries, screenshots,
private fixtures, environment files or generated packaging outputs are staged.
The only explicitly bundled non-code inputs are artwork and version metadata.
The audit inspects both loose files and embedded modules; the initial editable
metadata leak was removed. No personal build path is retained in application
code filenames. Build logs and native staging diagnostics remain outside tracked
source. No commit or push was made.

## Limitations and exact next step

This is a verified packaging configuration and Linux architecture smoke, not a
verified Windows release. Native executable/installer acceptance must finish on
a Windows environment whose normal security policy permits the toolchain. The
installer's real install/upgrade/uninstall flow remains untested locally.

**Next step:** make this reviewed source available in the repository, then run
Actions → **Windows desktop distribution** → **Run workflow**. Download the
`AI-Agent-Installer` artifact containing `AI-Agent-Setup.exe`. Alternatively,
on a normal local Windows checkout with uv and Inno Setup 6, run the documented
`build.ps1 -Installer` command. Do not disable application-control protections.

The Windows desktop itself needs no Python/uv installation. Developer-generated
projects can still require their own project-specific build/test toolchains; this
phase does not bundle arbitrary compilers, uv, or an IDE. Windows export requires
a local filesystem supporting safe hard-link publication; reparse-point paths
are rejected. Multi-user services, workflow changes, code signing, auto-update,
credential-manager integration and final product audit remain outside this work.
