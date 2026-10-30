<p align="center">
  <img src="assets/banner.svg" alt="FloatSnip">
</p>

<p align="center">
  <sub>**English** · [README_EN.md](./README_EN.md)</sub>
</p>

<p align="center">
  <a href="#features">Features</a> · <a href="#quick-start">Quick start</a> · <a href="#how-it-works">How it works</a> · <a href="#development-and-testing">Testing</a>
</p>

**⚡ A floating-ball quick-paste tool: one click copies your common snippets. Free, open-source, single file, no install.**

<!-- badges -->
[![License](https://img.shields.io/github/license/huanweide/floatsnip)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB)](https://www.python.org)
[![Release](https://img.shields.io/github/v/release/huanweide/floatsnip)](releases)
<!-- /badges -->

# FloatSnip · desktop floating-ball quick-paste tool

> A small ball that always floats on your desktop: your common text is "right at your fingertips" — click to copy, never breaking your flow. Free, open-source, single file, no install, fully local.

Copy-paste is one of the highest-frequency operations in daily work, and one of the most flow-breaking — hunting for a prompt while coding, switching windows to paste a canned reply, re-copying account/command templates every day. FloatSnip does one simple thing: keep your common text resident on the desktop, drag it to a handy spot with zero latency, see it the moment you open it, click to copy, done.

> **📦 Portability snapshot**
>
> - A Windows 10/11 desktop tool; download `FloatSnip.exe` and **run it without installing**; or run from source with `python main.py` (Python 3.x).
> - UI uses the standard-library `tkinter`, **zero extra GUI-framework dependency**; data is a local JSON file, nothing is uploaded to any server.
> - Can also be packaged into a single-file exe via PyInstaller for distribution.

## Who should use this

- Windows users who repeatedly copy the same prompts, canned replies, commands, or templates.
- Anyone who wants a zero-friction, always-on clipboard companion without accounts or cloud sync.
- People who value local-first tools (no telemetry, no upload).

## Who should not use this

- Non-Windows users — FloatSnip relies on Win32 APIs and is built for Windows 10/11.
- If you need cross-device sync — this deliberately stores data only on the local machine.

## Features

| Feature | Description |
|------|------|
| Real floating ball (no white border) | Uses Win32 `SetWindowRgn` to crop the window into a circle — floats on the desktop, no white border, not a square white block |
| Smooth dragging | Native mouse events + `geometry()` to move directly; single process, zero latency, follows the cursor |
| Customizable summon hotkey | Default `Ctrl + \`` to show/hide; click the hotkey box in settings and press a combo to change and remember it; **must include a Ctrl / Alt / Shift / Win modifier** (a single bare key would pop the panel up while typing, so it's hard-blocked) |
| List as home | Expanded view shows all snippets, scrollable; click any one to auto-copy with a green "copied" confirmation |
| Category tags | Preset "All / AI / Everyday / Work / Study / Life", renameable and addable (max 10) |
| On-the-fly editing | "＋ New snippet" at the bottom to add anytime; each entry has edit/delete; supports Chinese IME; per-entry soft cap of 10000 chars (over the cap shows a clear warning, no silent truncation) |
| Copy self-check | After copying, reads the clipboard back to verify: green on success, red on failure, so you know it "really copied" |
| Local-only · no account | All content stored in local `AppData\Local\FloatSnip\data.json`, editable/syncable, nothing uploaded |
| Optional auto-paste | When enabled in settings, auto-pastes to the previous window after copying (experimental) |
| Hi-DPI crisp | Windows DPI awareness enabled; no blur at 125%/150% scaling |
| System tray resident | Left-click to summon the ball, right-click menu (show / settings / exit), icon cleaned up on exit |
| Auto-start on boot (off by default) | See "Manual launch" below; can be enabled in settings |

## Quick start

1. Go to [Releases](releases) and download the latest `FloatSnip.exe`.
2. Double-click to run (no install); a small ball appears on the desktop.
3. **Drag** it to a handy spot; **single-click the ball** (or press `Ctrl + \``) to expand the panel.
4. Click any snippet in the panel → "copied" shows, then `Ctrl + V` at your destination.
5. Click "＋ New snippet" to add your own; click an entry's edit icon to modify, delete icon to remove.

> Data file location: `%AppData%\Local\FloatSnip\data.json` (back up or edit directly).

## Manual launch (important: auto-start is off)

The current version **does not** auto-start on system boot by default. Choose one of the following to start manually:

- **Run directly**: double-click `FloatSnip.exe`.
- **Put into the startup folder (to auto-start)**: drop a shortcut to `FloatSnip.exe` into the startup folder. Press `Win + R`, type `shell:startup` to open it, then drag the shortcut in.
- **Enable in settings**: after running, check "auto-start" in the panel settings; next boot it appears automatically (writes to registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\FloatSnip`).

To exit: right-click the tray icon → "Exit", or close via the panel title-bar menu. Every borderless window provides at least two ways to close, so there's never a "can't close" window.

## Run from source and package

Requirements: Windows 10/11, Python 3.x.

```bash
# 1. Run from source directly
python main.py

# 2. Package into a single-file exe (pip install pyinstaller first)
pyinstaller FloatSnip.spec
# output: dist/FloatSnip.exe
```

`FloatSnip.spec` is pre-configured for PyInstaller (`console=False`, `upx=True`, single file, no console window), targeting Windows 10/11.

## Configuration

All config is saved in a local JSON file at `%AppData%\Local\FloatSnip\data.json`.

| Key | Meaning | Default |
|--------|------|--------|
| `auto_paste` | auto-paste after copy | off |
| `hotkey` | global hotkey to show/hide | `ctrl+\`` |
| `autostart` | start on boot | off |
| `active_cat` | remember the last selected category | `all` |
| `window_x` / `window_y` | floating-ball position (auto-remembered) | auto |

Category management and hotkey changes are done in the panel "Settings" (gear); changes take effect immediately and persist.

## How it works

```
floating-ball window ──Win32 SetWindowRgn/CreateEllipticRgn──▶ circular crop (no white border)
   │
   ├─ drag ──tkinter mouse events + geometry()──▶ zero-latency follow
   ├─ global hotkey ──Win32 RegisterHotKey──▶ show/hide (zero global hook, pynput retired)
   ├─ copy ──ctypes write clipboard + read-back self-check──▶ green/red feedback
   └─ data ──local JSON (data.json)──▶ fully local, zero upload
```

- UI built with Python standard-library `tkinter`, zero extra GUI-framework dependency (small size, fast startup).
- Circular window: Win32 `SetWindowRgn` + `CreateEllipticRgn` crop, eliminating the white border entirely.
- Dragging: native events + `geometry()` to move directly (single process, smooth follow).
- Global hotkey: `RegisterHotKey` (no hook dependency); clipboard: ctypes; storage: local JSON.
- Packaging: PyInstaller single-file exe.

## Directory structure

```
floatsnip/
├── main.py          # all source (single file: ball/panel/settings/tray/autostart logic)
├── test_logic.py    # logic self-tests
├── FloatSnip.spec   # PyInstaller packaging config
├── LICENSE          # MIT
└── README.md
```

---

## Author

Maintained by **huanweide** · [GitHub](https://github.com/huanweide)

## Development · testing

```bash
pip install pytest
pytest -q
```

`test_logic.py` is granular pytest cases (each assertion is an independent example, locatable on failure and re-runnable with `-k`), covering: hotkey normalization (including the "must have a modifier" regression), display names, Win32 vk parsing, clipboard encode/decode, and the API business flow (snippet / category CRUD, sensitive-snippet export filtering, persistence, and legacy-data migration). CI (`.github/workflows/ci.yml`) runs the same commands on `windows-latest`.

## License

MIT — completely free, stars and PRs welcome. See [LICENSE](LICENSE).

---

## 🧰 More open-source tools (by huanweide)

- 🎬 Subtitles / video: [bili-subtitle-universal](https://github.com/huanweide/bili-subtitle-universal) · [live-subtitle](https://github.com/huanweide/live-subtitle) · [zhihuishu-helper](https://github.com/huanweide/zhihuishu-helper) · [video-brief](https://github.com/huanweide/video-brief)
- 🩺 Code-health family (18-axis zero-dependency CLI): [family-showcase](https://github.com/huanweide/family-showcase)
- 🔧 Command-line gems: [idiot-index](https://github.com/huanweide/idiot-index) · [recall-cli](https://github.com/huanweide/recall-cli) · [forge-safeguard](https://github.com/huanweide/forge-safeguard-20260812)
- 🖥️ Desktop / news: [floatsnip](https://github.com/huanweide/floatsnip) · [tech-news-hub](https://github.com/huanweide/tech-news-hub)
- 📦 All repos: <https://github.com/huanweide?tab=repositories>
