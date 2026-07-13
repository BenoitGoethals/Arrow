# Arrow Front — Windows installer

Builds a standard Windows installer (`ArrowFront-Setup-<version>.exe`) that
installs the Arrow Front desktop client to *Program Files*, with Start-menu and
optional desktop shortcuts and an uninstaller.

The build has two stages:

1. **PyInstaller** freezes the Python/PyQt6/QtWebEngine app into a self-contained
   folder `dist\ArrowFront\` (bundles Python, Qt, the Chromium WebEngine helper,
   the map assets and the default offline MBTiles map — no Python needed on the
   target machine).
2. **Inno Setup** packages that folder into a single `Setup.exe`.

> ⚠️ Windows binaries can only be built **on Windows** — PyInstaller does not
> cross-compile. Run these steps on a Windows 10/11 x64 machine.

## Prerequisites (on the Windows build machine)

| Tool | Why | Get it |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/) | Python 3.14 + dependency management | `winget install astral-sh.uv` |
| [Inno Setup 6](https://jrsoftware.org/isdl.php) | Builds the installer | installer, or `winget install JRSoftware.InnoSetup` |

PyInstaller itself is pulled in on demand by the build (`uv run --with pyinstaller`),
so you don't install it separately.

## Build

From the repository root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File front\packaging\build_windows.ps1
```

The finished installer lands in `dist\installer\ArrowFront-Setup-1.0.0.exe`.

## Build in CI (no Windows machine needed)

`.github/workflows/windows-installer.yml` builds the installer on a
`windows-latest` runner:

- **Pull requests** touching `front/`, `mortarcalc/`, or `pyproject.toml`, and
  **manual runs** (Actions → *Windows installer* → *Run workflow*) build the
  installer and upload it as a workflow **artifact**.
- **Pushing a `v*` tag** (e.g. `git tag v1.0.0 && git push --tags`) additionally
  publishes the `Setup.exe` to a **GitHub Release**.

The runner installs uv, Python 3.14 and Inno Setup, then runs
`build_windows.ps1` — the same script you'd run locally.

> The default `mapquest…mbtiles` map is untracked (~124 MB). CI checks out with
> `lfs: true`, so it's only bundled if you commit it via **Git LFS**; otherwise
> the CI installer is the slim, online-tiles build.

### Manual steps (if you prefer)

```powershell
uv sync --extra front
uv run --extra front --with pyinstaller pyinstaller --noconfirm front\packaging\arrow-front.spec
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" front\packaging\arrow-front.iss
```

## Files here

| File | Purpose |
| --- | --- |
| `arrow-front.spec` | PyInstaller recipe (onedir, WebEngine-aware, bundles data + icon) |
| `arrow_front_launch.py` | Clean frozen entry point (imports `front.main:main`) |
| `version_info.txt` | Windows version resource embedded in the `.exe` |
| `arrow-front.iss` | Inno Setup installer script (shortcuts, uninstaller) |
| `build_windows.ps1` | One-command build (sync → freeze → installer) |

## Versioning

Bump the version in **three** places together:

- `arrow-front.iss` → `#define AppVersion`
- `version_info.txt` → `filevers` / `prodvers` / the `FileVersion`/`ProductVersion` strings

Keep the Inno `AppId` GUID unchanged so Windows treats new builds as upgrades.

## Notes / trade-offs

- **Installer size:** the default offline map (`mapquest_2014-02-11_084957.mbtiles`,
  ~124 MB) is bundled, so the installer is large. To slim it down, comment out the
  `_default_mbtiles` block in `arrow-front.spec`; the app then relies on online
  tiles or a user-supplied MBTiles file.
- **Per-user (no-UAC) install:** in `arrow-front.iss` set `PrivilegesRequired=lowest`.
  `{autopf}` then resolves to a per-user location and no admin prompt appears.
- **Voice (push-to-talk):** requires the PortAudio DLL (from `sounddevice`) and an
  Opus DLL. The spec bundles PortAudio; if Opus is missing at runtime voice is
  simply disabled — the rest of the client works.
- **Code signing:** the produced `.exe` is unsigned, so SmartScreen will warn on
  first run. For distribution, sign both `dist\ArrowFront\ArrowFront.exe` and the
  final `Setup.exe` with `signtool` using your code-signing certificate.
- **Antivirus:** unsigned PyInstaller bundles occasionally trip heuristic AV.
  Code signing resolves most of it.
