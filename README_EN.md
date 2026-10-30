**中文** · [README.md](./README.md)

<p align="center">
  <img src="assets/banner.svg" alt="FloatSnip">
</p>

<p align="center">
  <a href="#features">Features</a> · <a href="#quick-start">Quick start</a> · <a href="#how-it-works">Architecture</a> · <a href="#development--tests">Tests</a>
</p>

# FloatSnip · desktop floating-ball quick-paste tool

> A little ball that always floats on your desktop: your common snippets are "at your fingertips" — one click copies, never breaking your flow. Free, open-source, single-file, no install.

**⚡ A floating-ball quick-paste tool: one click copies your common snippets. Free, open-source, single-file, no install.**

[![License](https://img.shields.io/github/license/huanweide/floatsnip)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB)](https://www.python.org)
[![Release](https://img.shields.io/github/v/release/huanweide/floatsnip)](releases)

Copy-paste is one of the highest-frequency, most flow-breaking operations in daily work — looking up a prompt while coding, switching windows to send a scripted reply, copying account/command templates every day. FloatSnip does one simple thing: keep your common text resident on the desktop, drag it to a handy spot with zero latency, see it when you open the ball, click once to copy, done.

> **📦 Portability at a glance**
>
> - Windows 10/11 desktop tool; download `FloatSnip.exe` and **run without installing**; or run from source with `python main.py` (Python 3.x).
> - UI uses the standard-library `tkinter`, **zero extra GUI-framework dependencies**; data is a pure-local JSON file, uploaded to no server.
> - Can also be packaged into a single-file exe with PyInstaller.

## Who should use this

- You are on Windows 10/11 and repeatedly copy the same text (prompts, scripts, canned replies, command templates) and want it one click away without breaking flow.
- You want a local-only tool with no account, no cloud, no install.

## Who should NOT use this

- You are on macOS or Linux — the floating ball relies on Win32 APIs (window region, global hotkey) and is Windows-only.
- You need cross-device cloud sync of your snippets — FloatSnip stores everything locally and has no sync.

## Features

| Feature | Description |
|---------|-------------|
| Real floating ball (no white border) | Cuts the window into a circle via Win32 `SetWindowRgn`, floating on the desktop with no white border, not a square white block |
| Smooth dragging | Native mouse events + `geometry()` move directly, single-process zero-latency, follows your hand |
| Customizable summon hotkey | Default `Ctrl + \`` to show/hide; click the hotkey box in settings, press a combo to change and remember it; **must include a Ctrl / Alt / Shift / Win modifier** (a single bare key would pop the panel while you type — hard-blocked) |
| List is the home page | Expanding shows all snippets, scrollable; click any one to auto-copy with a green "copied" confirmation |
| Category tabs | Presets "All / AI / Everyday / Work / Study / Life", renameable and addable (max 10) |
| Edit on the fly | "＋ New snippet" at the bottom anytime; each entry has edit / delete; Chinese IME supported; per-entry soft cap 10,000 chars (clearly warned, not silently truncated) |
| Copy self-check | After copying, reads the clipboard back to verify: green on success, red on failure, ensuring "it really copied" |
| Pure-local · zero-account | All content stored at local `AppData\Local\FloatSnip\data.json`, editable / syncable, uploaded to no server |
| Optional auto-paste | After enabling in settings, copies then auto-pastes into the window you were just in (experimental) |
| HiDPI crisp | Windows DPI awareness on, no blur at 125% / 150% scaling |
| System tray resident | Left-click summons the ball, right-click menu (show / settings / exit), cleans up the icon on exit |
| Autostart (off by default) | See "Manual startup" below; can be enabled in settings |

## Quick start

1. Go to [Releases](releases) and download the latest `FloatSnip.exe`.
2. Double-click to run (no install needed); a small ball appears on the desktop.
3. **Drag** it to a handy spot; **click the ball** (or press `Ctrl + \``) to expand the panel.
4. Click any snippet in the panel → "copied" shows; go to the target and `Ctrl + V`.
5. Click "＋ New snippet" to add your own; the entry's edit icon modifies, the delete icon removes.

> Data file location: `%AppData%\Local\FloatSnip\data.json` (back up or edit directly).

## Manual startup (important: autostart is off)

The current build **does not** auto-start on system boot by default. Start it manually by one of these:

- **Run directly**: double-click `FloatSnip.exe`.
- **Startup folder (for autostart)**: put a shortcut to `FloatSnip.exe` into the startup folder. Press `Win + R`, type `shell:startup` to open it, drag the shortcut in.
- **Enable in settings**: after running, check "autostart" in the panel settings; next boot it appears automatically (writes registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\FloatSnip`).

To exit: right-click the system-tray icon → "Exit", or use the panel title-bar menu. Every borderless window offers at least two ways to close, so nothing gets "stuck".

## Run from source and package

Requirements: Windows 10/11, Python 3.x.

```bash
# 1. Run from source directly
python main.py

# 2. Package into a single-file exe (needs pip install pyinstaller first)
pyinstaller FloatSnip.spec
# output: dist/FloatSnip.exe
```

`FloatSnip.spec` already has the PyInstaller config preset (`console=False`, `upx=True`, single-file, no console window), targeting Windows 10/11.

## Configuration

All config is saved in a local JSON at `%AppData%\Local\FloatSnip\data.json`.

| Key | Meaning | Default |
|-----|---------|---------|
| `auto_paste` | Auto-paste after copy | off |
| `hotkey` | Global hotkey to show/hide | `ctrl+\`` |
| `autostart` | Start on boot | off |
| `active_cat` | Remember last selected category | `all` |
| `window_x` / `window_y` | Ball position (auto-remembered) | auto |

Category management and hotkey changes are done in the panel "Settings" (gear); changes take effect immediately and persist.

## How it works

```
Ball window ──Win32 SetWindowRgn/CreateEllipticRgn──▶ circular clip (no white border)
   │
   ├─ drag ──tkinter mouse events + geometry()──▶ zero-latency follow
   ├─ global hotkey ──Win32 RegisterHotKey──▶ show/hide (zero global hook, no more pynput)
   ├─ copy ──ctypes write clipboard + read-back self-check──▶ green/red feedback
   └─ data ──local JSON (data.json)──▶ pure-local, zero upload
```

- UI built with Python standard-library `tkinter`, zero extra GUI-framework dependencies (small, fast startup).
- Circular window: Win32 `SetWindowRgn` + `CreateEllipticRgn` clip, eliminating the white border entirely.
- Drag: native events + `geometry()` move (single process, smooth).
- Global hotkey: `RegisterHotKey` (no hook dependency); clipboard: ctypes; storage: local JSON.
- Packaging: PyInstaller single-file exe.

## Directory structure

```
floatsnip/
├── main.py          # all source (single file: ball / panel / settings / tray / autostart)
├── test_logic.py    # logic self-tests
├── FloatSnip.spec   # PyInstaller packaging config
├── LICENSE          # MIT
└── README.md
```

## Development · tests

```bash
pip install pytest
pytest -q
```

`test_logic.py` is fine-grained pytest cases (each assertion an independent test, locatable on failure, re-runnable with `-k`), covering: hotkey normalization (including the "must have a modifier" regression), display names, Win32 vk parsing, clipboard codec, the API business flow (snippet / category CRUD, sensitive-snippet export filtering, persistence, migration) and old-data migration. CI (`.github/workflows/ci.yml`) runs the same commands on `windows-latest`.

## License

MIT — completely free, Star and PRs welcome. See [LICENSE](LICENSE).

---

Maintained by **huanweide** · [GitHub](https://github.com/huanweide)

## More open-source tools by huanweide

- 🎬 Subtitle / video: [bili-subtitle-universal](https://github.com/huanweide/bili-subtitle-universal) · [live-subtitle](https://github.com/huanweide/live-subtitle) · [zhihuishu-helper](https://github.com/huanweide/zhihuishu-helper) · [video-brief](https://github.com/huanweide/video-brief)
- 🩺 Code-health family (18 zero-dep CLI axes): [family-showcase](https://github.com/huanweide/family-showcase)
- 🔧 CLI utilities: [idiot-index](https://github.com/huanweide/idiot-index) · [recall-cli](https://github.com/huanweide/recall-cli) · [forge-safeguard](https://github.com/huanweide/forge-safeguard-20260812)
- 🖥️ Desktop / news: [floatsnip](https://github.com/huanweide/floatsnip) · [tech-news-hub](https://github.com/huanweide/tech-news-hub)
- 📦 All repos: <https://github.com/huanweide?tab=repositories>
