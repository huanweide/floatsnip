**中文** · [README.md](./README.md)

<p align="center">
  <img src="assets/banner.svg" alt="FloatSnip">
</p>

[![License](https://img.shields.io/github/license/huanweide/floatsnip)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB)](https://www.python.org)
[![Release](https://img.shields.io/github/v/release/huanweide/floatsnip)](releases)

# FloatSnip · Desktop Floating-Ball Quick-Paste Tool

> A little ball that always floats on your desktop: the text you use often stays "at your fingertips" — one click copies it, never breaking your flow. Free, open-source, single-file, no install, pure local.

Copy-paste is one of the most frequent operations in daily work, and one of the most flow-breaking — hunting for a prompt while coding, switching windows for a chat script, copying an account-command template every day. FloatSnip does one simple thing: keep your common text resident on the desktop, drag it to a handy spot with zero lag, open it to see, click to copy, done.

> **📦 Portability at a glance**
>
> - A Windows 10/11 desktop tool; download `FloatSnip.exe` and run it **without installing**; or run from source with `python main.py` (Python 3.x).
> - UI uses the standard-library `tkinter` — **zero extra GUI-framework dependency**; data is a local JSON, never uploaded to any server.
> - Can also be packaged into a single-file exe with PyInstaller for distribution.

[Features](#features) · [Quick Start](#quick-start) · [How It Works](#how-it-works) · [Development & Tests](#development--tests)

---

## Who Should Use It / Who Should NOT

**Good fit if —**

- You're on **Windows 10/11** and frequently copy the same text (AI prompts, message scripts, command/account templates, code snippets).
- You want a non-intrusive, always-visible helper that doesn't force you into a big app window.
- You prefer **local-only, no account** — your snippets never leave your machine.

**Not for you if —**

- **You're on macOS or Linux** — it's Windows 10/11 only (it uses Win32 APIs for the round window, global hotkey, and tray).
- **You want cloud sync across devices** — data is a local JSON file; there is no account or server, by design.

---

## Features

| Feature | Description |
|------|------|
| Real floating ball (no white border) | Win32 `SetWindowRgn` crops the window into a circle — floats on the desktop, no white border, not a square white block |
| Smooth dragging | native mouse events + `geometry()` move directly; single process, zero lag, follows the cursor |
| Customizable summon hotkey | default `Ctrl + \`` to show/hide; click the hotkey box in settings and press a combo to change and remember it; **must include a Ctrl / Alt / Shift / Win modifier** (a single bare key would pop the panel while you type — hard-blocked) |
| List is the home page | expand to see all snippets, scrollable; click any one to auto-copy with a green "Copied" confirmation |
| Category tags | presets "All / AI / Everyday / Work / Study / Life"; rename, create new (max 10) |
| On-the-fly editing | "+ New snippet" at the bottom anytime; each entry has edit and delete; Chinese IME supported; per-entry soft cap 10000 chars (over the cap is a clear prompt, not a silent truncate) |
| Copy self-check | after copying, reads the clipboard back to verify: green on success, red on failure — ensures "it really copied" |
| Pure local · zero account | everything in local `AppData\Local\FloatSnip\data.json`; editable, syncable, never uploaded |
| Optional auto-paste | when enabled in settings, auto-pastes into the last window after copying (experimental) |
| HiDPI crisp | Windows DPI awareness enabled, no blur at 125% / 150% scaling |
| System tray resident | left-click summons the ball, right-click menu (show / settings / exit), icon cleaned up on exit |
| Autostart (off by default) | see "Manual Launch" below; can be enabled in settings |

---

## Quick Start

1. Go to [Releases](releases) and download the latest `FloatSnip.exe`.
2. Double-click to run (no install); a small ball appears on the desktop.
3. **Drag** it to a handy spot; **click the ball** (or press `Ctrl + \``) to expand the panel.
4. Click any snippet in the panel → "Copied" shows, then `Ctrl + V` at the target.
5. Click "+ New snippet" to add your own; click an entry's edit icon to modify, delete icon to remove.

> Data file location: `%AppData%\Local\FloatSnip\data.json` (back up or edit directly).

## Manual Launch (important: autostart is off)

The current version **does not** auto-start on system boot by default. Choose one of the following to launch manually:

- **Run directly**: double-click `FloatSnip.exe`.
- **Put into the startup folder (to enable autostart)**: drop a shortcut to `FloatSnip.exe` into the startup folder.
  Press `Win + R`, type `shell:startup` to open it, then drag the shortcut in.
- **Enable in settings**: after running, check "Autostart" in the panel settings; next boot it appears automatically (writes to registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\FloatSnip`).

To exit: right-click the tray icon → "Exit", or close via the panel title-bar menu. Every borderless window offers at least two close paths — no "can't close" windows left behind.

## Run from Source & Package

Requirements: Windows 10/11, Python 3.x.

```bash
# 1. Run from source directly
python main.py

# 2. Package into a single-file exe (pip install pyinstaller first)
pyinstaller FloatSnip.spec
# output: dist/FloatSnip.exe
```

`FloatSnip.spec` already has PyInstaller configured (`console=False`, `upx=True`, single file, no console window), targeting Windows 10/11.

## Configuration

All config is kept in a local JSON at `%AppData%\Local\FloatSnip\data.json`.

| Key | Meaning | Default |
|--------|------|--------|
| `auto_paste` | auto-paste after copying | off |
| `hotkey` | global hotkey to show/hide | `ctrl+\`` |
| `autostart` | start on boot | off |
| `active_cat` | remember the last selected category | `all` |
| `window_x` / `window_y` | ball position (auto-remembered) | auto |

Category management and hotkey changes are done in the panel "Settings" (gear); changes take effect immediately and persist.

---

## How It Works

```text
Ball window ──Win32 SetWindowRgn/CreateEllipticRgn──▶ circular crop (no white border)
   │
   ├─ drag ──tkinter mouse events + geometry()──▶ zero-lag follow
   ├─ global hotkey ──Win32 RegisterHotKey──▶ show/hide (zero global hook, no more pynput)
   ├─ copy ──ctypes write clipboard + read-back self-check──▶ green/red feedback
   └─ data ──local JSON (data.json)──▶ pure local, zero upload
```

- UI is built with Python's standard-library `tkinter` — zero extra GUI-framework dependency (small, fast to start).
- Round window: Win32 `SetWindowRgn` + `CreateEllipticRgn` crop, completely removes the white border.
- Dragging: native events + `geometry()` move directly (single process, smooth follow).
- Global hotkey: `RegisterHotKey` (zero hook dependency); clipboard: ctypes; storage: local JSON.
- Packaging: PyInstaller single-file exe.

## Directory Structure

```
floatsnip/
├── main.py          # all source (single file: ball / panel / settings / tray / autostart)
├── test_logic.py    # logic self-test
├── FloatSnip.spec   # PyInstaller packaging config
├── LICENSE          # MIT
└── README.md
```

---

## Development & Tests

```bash
pip install pytest
pytest -q
```

`test_logic.py` is fine-grained pytest coverage (each assertion is its own case, failures are locatable, rerun individually with `-k`), covering: hotkey normalization (including the "must have a modifier" regression), display names, Win32 vk parsing, clipboard encode/decode, and the API business flow (snippet / category CRUD, sensitive-fragment export filtering, persistence, migration). CI (`.github/workflows/ci.yml`) runs the same suite on `windows-latest`.

---

## Author

Maintained by **huanweide** · [GitHub profile](https://github.com/huanweide)

## License

MIT — completely free, Star and PRs welcome. See [LICENSE](LICENSE).

---

## Other Tools by the Same Author

- 🎬 Subtitles / video: [bili-subtitle-universal](https://github.com/huanweide/bili-subtitle-universal) · [live-subtitle](https://github.com/huanweide/live-subtitle) · [zhihuishu-helper](https://github.com/huanweide/zhihuishu-helper) · [video-brief](https://github.com/huanweide/video-brief)
- 🩺 Code-health suite (18-axis zero-dependency CLI): [family-showcase](https://github.com/huanweide/family-showcase)
- 🔧 Command-line utilities: [idiot-index](https://github.com/huanweide/idiot-index) · [recall-cli](https://github.com/huanweide/recall-cli) · [forge-safeguard](https://github.com/huanweide/forge-safeguard-20260812)
- 🖥️ Desktop / news: [floatsnip](https://github.com/huanweide/floatsnip) · [tech-news-hub](https://github.com/huanweide/tech-news-hub)
- 📦 All repositories: <https://github.com/huanweide?tab=repositories>
