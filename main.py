# -*- coding: utf-8 -*-
"""FloatSnip 浮球快贴 · 后端（tkinter + Win32 原生透明/拖动版）

承载层：tkinter + ctypes Win32 API
  - FramelessWindowHint / 无边框：overrideredirect(True) + topmost
  - 真圆形浮球：CreateEllipticRgn + SetWindowRgn 把窗口剪成圆形，彻底无白边
  - 面板圆角：CreateRoundRectRgn + SetWindowRgn
  - 拖动：原生 tkinter 鼠标事件 + geometry 直接移动（单进程零延迟）
UI：tkinter 原生控件 + 深色 QSS-like 配色
业务逻辑复用：ctypes 剪贴板 / pynput 全局热键 / JSON 存储 / 分类 / 自动粘贴 / 开机自启

说明：WebView2/Chromium 在 Windows 上不支持真透明背景（会渲染成白底），这是浮球
白边的根因。GitHub 上真正无白边的悬浮球，都是用 Win32 窗口区域裁剪或 Qt 分层窗口。
这里用 tkinter（Python 自带、零额外体积）+ Win32 RGN 裁剪，实现完全无白边 + 平滑拖动。
"""
import os
import re
import sys
import json
import ctypes
import threading
import time

import tkinter as tk
from tkinter import ttk, messagebox

from pynput import keyboard

# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
BASE = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(os.path.expanduser("~"), "AppData", "Local", "FloatSnip")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "data.json")
GMEM_MOVEABLE = 0x0002
CF_UNICODETEXT = 13
DEFAULT_HOTKEY = "ctrl+`"

DEFAULT_DATA = {
    "settings": {"auto_paste": False, "hotkey": DEFAULT_HOTKEY, "window_x": None, "window_y": None},
    "categories": [
        {"id": "all", "name": "所有", "fixed": True},
        {"id": "c1", "name": "AI"},
        {"id": "c2", "name": "平常常用"},
        {"id": "c3", "name": "工作"},
        {"id": "c4", "name": "学习"},
        {"id": "c5", "name": "生活"},
    ],
    "snippets": [
        {"id": "s1", "content": "用费曼方式把这道题讲给我听，不要跳步。", "category": "c1"},
        {"id": "s2", "content": "帮我 review 这段代码，重点看边界情况和错误处理。", "category": "c1"},
        {"id": "s3", "content": "收到，马上安排。", "category": "c2"},
        {"id": "s4", "content": "这局对面太肉了，建议出点法穿。", "category": "c2"},
        {"id": "s5", "content": "周报已发，请查收。", "category": "c3"},
        {"id": "s6", "content": "这道题的核心思路是……", "category": "c4"},
        {"id": "s7", "content": "今天记得买菜。", "category": "c5"},
    ],
}

# ---------------------------------------------------------------------------
# DPI 感知（消除高分屏模糊）
# ---------------------------------------------------------------------------
try:
    # PROCESS_PER_MONITOR_DPI_AWARE = 2
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------
user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32


def set_circular_window(hwnd, size):
    """把窗口裁剪成圆形（完全无白边）"""
    rgn = gdi32.CreateEllipticRgn(0, 0, size, size)
    user32.SetWindowRgn(hwnd, rgn, True)


def set_rounded_window(hwnd, w, h, r):
    """把窗口裁剪成圆角矩形"""
    rgn = gdi32.CreateRoundRectRgn(0, 0, w, h, r, r)
    user32.SetWindowRgn(hwnd, rgn, True)


def get_hwnd(widget):
    """tkinter widget 的 win32 HWND"""
    return widget.winfo_id()


# ---------------------------------------------------------------------------
# 数据 / 剪贴板 / 热键规范化
# ---------------------------------------------------------------------------
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            # 兼容旧版缺字段
            for k, v in DEFAULT_DATA.items():
                if k not in data:
                    data[k] = v
            if "window_x" not in data["settings"]:
                data["settings"]["window_x"] = None
            if "window_y" not in data["settings"]:
                data["settings"]["window_y"] = None
            return data
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data):
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def copy_text(text):
    """写入剪贴板，返回是否成功"""
    if text is None:
        text = ""
    try:
        text = str(text)
        user32.OpenClipboard(0)
        user32.EmptyClipboard()
        buf = text.encode("utf-16-le") + b"\x00\x00"
        size = len(buf)
        h_global = ctypes.windll.kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        ptr = ctypes.windll.kernel32.GlobalLock(h_global)
        ctypes.memmove(ptr, buf, size)
        ctypes.windll.kernel32.GlobalUnlock(h_global)
        user32.SetClipboardData(CF_UNICODETEXT, h_global)
        user32.CloseClipboard()
        return True
    except Exception:
        return False


def read_clipboard():
    """读回剪贴板文本（用于复制自检）"""
    try:
        user32.OpenClipboard(0)
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            user32.CloseClipboard()
            return None
        ptr = ctypes.windll.kernel32.GlobalLock(h)
        size = ctypes.windll.kernel32.GlobalSize(h)
        buf = ctypes.string_at(ptr, size)
        ctypes.windll.kernel32.GlobalUnlock(h)
        user32.CloseClipboard()
        # 去掉末尾的 \x00\x00 (utf-16)
        text = buf.decode("utf-16-le", errors="ignore")
        return text.rstrip("\x00")
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass
        return None


def copy_and_verify(text):
    """复制并返回自检结果：'ok' / 'empty' / 'mismatch' / 'fail'"""
    if text is None or str(text).strip() == "":
        return "empty"
    ok = copy_text(text)
    if not ok:
        return "fail"
    got = read_clipboard()
    if got is None:
        # 读回失败（某些环境剪贴板被占用），但写入大概率成功，降级为 ok
        return "ok"
    if got == str(text):
        return "ok"
    return "mismatch"


def show_toast(parent, msg, kind="ok"):
    """底部居中提示：ok=绿 / err=红 / info=灰，给用户明确确认感"""
    try:
        t = tk.Toplevel(parent)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        palette = {"ok": "#1f7a44", "err": "#b23b3b", "info": "#2c3340"}
        bg = palette.get(kind, "#2c3340")
        t.configure(bg=bg)
        icon = {"ok": "✓", "err": "✕", "info": "ℹ"}.get(kind, "")
        text = (icon + "  " + msg) if icon else msg
        tk.Label(t, text=text, bg=bg, fg="white", font=("Microsoft YaHei UI", 10, "bold"), padx=16, pady=9).pack()
        t.update_idletasks()
        try:
            set_rounded_window(get_hwnd(t), t.winfo_width(), t.winfo_height(), 8)
        except Exception:
            pass
        px, py = parent.winfo_x(), parent.winfo_y()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        tx = px + pw // 2 - t.winfo_width() // 2
        ty = py + ph - t.winfo_height() - 14
        t.geometry("+%d+%d" % (max(0, tx), max(0, ty)))
        parent.after(1400, t.destroy)
    except Exception:
        pass


def _send_ctrl_v():
    """向后台窗口发送 Ctrl+V"""
    try:
        ctrl = keyboard.Key.ctrl
        v = keyboard.KeyCode.from_char("v")
        controller = keyboard.Controller()
        controller.press(ctrl)
        controller.press(v)
        controller.release(v)
        controller.release(ctrl)
    except Exception:
        pass


HOTKEY_KEYMAP = {
    "win": "cmd", "windows": "cmd", "command": "cmd", "cmd": "cmd",
    "alt": "alt", "shift": "shift", "ctrl": "ctrl", "control": "ctrl",
    "space": "space", " ": "space",
    "up": "up", "down": "down", "left": "left", "right": "right",
    "esc": "esc", "escape": "esc", "tab": "tab", "enter": "enter",
    "return": "enter", "backspace": "backspace", "delete": "delete", "del": "delete",
}
for i in range(1, 25):
    HOTKEY_KEYMAP["f%d" % i] = "f%d" % i

VALID_KEYS = set(
    list("abcdefghijklmnopqrstuvwxyz0123456789") +
    ["`", "-", "=", "[", "]", "\\", ";", "'", ",", ".", "/"] +
    ["space", "up", "down", "left", "right", "esc", "tab", "enter", "backspace", "delete"] +
    ["f%d" % i for i in range(1, 25)]
)


def normalize_hotkey(expr):
    """把用户输入的 'ctrl+alt+b' 转成 pynput 接受的 '<ctrl>+<alt>+b'"""
    if not expr or not isinstance(expr, str):
        return None
    parts = [p.strip().lower() for p in expr.split("+") if p.strip()]
    if not parts:
        return None
    mods = []
    key = None
    for p in parts:
        if p in ("ctrl", "control"):
            mods.append("<ctrl>")
        elif p in ("alt",):
            mods.append("<alt>")
        elif p in ("shift",):
            mods.append("<shift>")
        elif p in ("win", "windows", "command", "cmd"):
            mods.append("<cmd>")
        else:
            if key is not None:
                return None
            key = HOTKEY_KEYMAP.get(p, p)
    if key is None:
        return None
    if key not in VALID_KEYS:
        return None
    # pynput 对功能键/方向键/space 等需要 <key> 形式
    single_char = set("abcdefghijklmnopqrstuvwxyz0123456789`~!@#$%^&*()-_=+[]{}\\|;:'\",.<>/?")
    key_spec = key if (len(key) == 1 and key in single_char) else "<%s>" % key
    spec = "+".join(mods + [key_spec]) if mods else key_spec
    try:
        keyboard.HotKey.parse(spec)
    except Exception:
        return None
    return spec


# ---------------------------------------------------------------------------
# Api（业务逻辑，与 UI 分离）
# ---------------------------------------------------------------------------
class Api:
    def __init__(self):
        self.data = load_data()
        self.mode = "ball"
        self.hidden = False
        self._win = None  # 主窗口
        self._panel = None  # 面板引用
        self._listeners = []

    def set_win(self, win):
        self._win = win

    def set_panel(self, panel):
        self._panel = panel

    def ui(self, fn):
        """把 UI 操作调度到主线程（tkinter 线程安全）"""
        if self._win and hasattr(self._win, "root") and self._win.root:
            try:
                self._win.root.after(0, fn)
            except Exception:
                fn()
        else:
            fn()

    # ---- 数据 API ----
    def get_state(self):
        return self.data

    def get_mode(self):
        return self.mode

    def set_mode(self, m):
        self.mode = m
        return m

    def toggle_mode(self):
        self.mode = "panel" if self.mode == "ball" else "ball"
        return self.mode

    def save_snippet(self, sid, content, category):
        content = (content or "").strip()
        if not content:
            return {"ok": False, "msg": "内容不能为空"}
        if category == "all":
            category = "c1"
        if sid:
            for s in self.data["snippets"]:
                if s["id"] == sid:
                    s["content"] = content
                    s["category"] = category
                    break
        else:
            ids = [int(s["id"][1:]) for s in self.data["snippets"] if s["id"].startswith("s") and s["id"][1:].isdigit()]
            nid = "s%d" % (max(ids) + 1 if ids else 1)
            self.data["snippets"].append({"id": nid, "content": content, "category": category})
        save_data(self.data)
        return {"ok": True, "state": self.data}

    def delete_snippet(self, sid):
        self.data["snippets"] = [s for s in self.data["snippets"] if s["id"] != sid]
        save_data(self.data)
        return {"ok": True, "state": self.data}

    def add_category(self, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "msg": "名字不能为空"}
        cust = [c for c in self.data["categories"] if not c.get("fixed")]
        if len(cust) >= 5:
            return {"ok": False, "msg": "自定义分类最多 5 个"}
        ids = [int(c["id"][1:]) for c in self.data["categories"] if c["id"].startswith("c") and c["id"][1:].isdigit()]
        nid = "c%d" % (max(ids) + 1 if ids else 1)
        self.data["categories"].append({"id": nid, "name": name})
        save_data(self.data)
        return {"ok": True, "state": self.data}

    def rename_category(self, cid, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "msg": "名字不能为空"}
        found = False
        for c in self.data["categories"]:
            if c["id"] == cid:
                if c.get("fixed"):
                    return {"ok": False, "msg": "固定分类不可改名或不存在"}
                c["name"] = name
                found = True
                break
        if not found:
            return {"ok": False, "msg": "分类不存在"}
        save_data(self.data)
        return {"ok": True, "state": self.data}

    def set_auto_paste(self, flag):
        self.data["settings"]["auto_paste"] = bool(flag)
        save_data(self.data)
        return {"ok": True, "auto_paste": self.data["settings"]["auto_paste"]}

    def set_hotkey(self, expr):
        spec = normalize_hotkey(expr)
        if spec is None:
            return {"ok": False, "msg": "快捷键格式不合法"}
        self.data["settings"]["hotkey"] = expr
        save_data(self.data)
        register_hotkey(self)
        return {"ok": True, "hotkey": expr}

    def get_window_pos(self):
        if self._win:
            return [self._win.winfo_x(), self._win.winfo_y()]
        return [0, 0]

    def save_window_pos(self):
        if self._win:
            self.data["settings"]["window_x"] = self._win.winfo_x()
            self.data["settings"]["window_y"] = self._win.winfo_y()
            save_data(self.data)

    def hide_ball(self):
        self.hidden = True
        if self._win:
            self.ui(lambda: self._win.withdraw())
        return {"ok": True, "hidden": True}

    def show_ball(self):
        self.hidden = False
        if self._win:
            self.ui(lambda: self._win.deiconify())
        return {"ok": True, "hidden": False}

    def quit_app(self):
        self.save_window_pos()
        self.ui(lambda: self._win.root.destroy() if self._win else None)


# ---------------------------------------------------------------------------
# 全局热键
# ---------------------------------------------------------------------------
_current_listener = None


def register_hotkey(api):
    global _current_listener
    spec = normalize_hotkey(api.data["settings"].get("hotkey", DEFAULT_HOTKEY))
    if not spec:
        return
    combo = {}

    def cb():
        api.ui(lambda: _hotkey_handler(api))

    combo[spec] = cb
    if _current_listener:
        try:
            _current_listener.stop()
        except Exception:
            pass
    _current_listener = keyboard.GlobalHotKeys(combo)
    _current_listener.start()


def _hotkey_handler(api):
    if api.hidden:
        api.show_ball()
    api.toggle_mode()
    if api._panel:
        api._panel.sync_mode()


# ---------------------------------------------------------------------------
# UI：浮球
# ---------------------------------------------------------------------------
BALL_SIZE = 64


class FloatBall(tk.Toplevel):
    def __init__(self, root, api):
        super().__init__(root)
        self.root = root
        self.api = api
        api.set_win(self)

        self.title("FloatSnipBall")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.geometry("%dx%d+100+100" % (BALL_SIZE, BALL_SIZE))

        self.canvas = tk.Canvas(self, width=BALL_SIZE, height=BALL_SIZE, highlightthickness=0, bg="#0d1117")
        self.canvas.pack(fill="both", expand=True)
        self._draw_ball()

        # 裁剪成圆形
        self.update_idletasks()
        set_circular_window(get_hwnd(self), BALL_SIZE)

        # 拖动
        self._drag = None
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)

        # 恢复位置
        wx = api.data["settings"].get("window_x")
        wy = api.data["settings"].get("window_y")
        if wx is not None and wy is not None:
            self.geometry("+%d+%d" % (wx, wy))

    def _draw_ball(self):
        self.canvas.delete("all")
        # 渐变模拟：多层同心圆
        for i in range(20, 0, -2):
            ratio = i / 20
            r = int(BALL_SIZE / 2 * ratio)
            c = "#%02x%02x%02x" % (80 + int(44 * ratio), 60 + int(48 * ratio), 180 + int(75 * ratio))
            self.canvas.create_oval(BALL_SIZE / 2 - r, BALL_SIZE / 2 - r,
                                    BALL_SIZE / 2 + r, BALL_SIZE / 2 + r,
                                    fill=c, outline="")
        # 图标：三条横线
        self.canvas.create_line(22, 28, 42, 28, fill="white", width=2, capstyle="round")
        self.canvas.create_line(22, 34, 42, 34, fill="white", width=2, capstyle="round")
        self.canvas.create_line(22, 40, 42, 40, fill="white", width=2, capstyle="round")

    def _on_press(self, e):
        self._drag = {"sx": e.x_root, "sy": e.y_root, "wx": self.winfo_x(), "wy": self.winfo_y(), "moved": False}

    def _on_motion(self, e):
        if not self._drag:
            return
        dx = e.x_root - self._drag["sx"]
        dy = e.y_root - self._drag["sy"]
        if abs(dx) > 2 or abs(dy) > 2:
            self._drag["moved"] = True
        x = self._drag["wx"] + dx
        y = self._drag["wy"] + dy
        self.geometry("+%d+%d" % (x, y))

    def _on_release(self, e):
        if not self._drag:
            return
        moved = self._drag["moved"]
        self._drag = None
        self.api.save_window_pos()
        if not moved:
            # 单击 = 切换面板
            self.api.toggle_mode()
            if self.api._panel:
                self.api._panel.sync_mode()


# ---------------------------------------------------------------------------
# UI：面板
# ---------------------------------------------------------------------------
PANEL_W = 360
PANEL_H = 460

COLORS = {
    "bg": "#0d1117",
    "card": "#161922",
    "line": "#2a2f3a",
    "text": "#e8eaf6",
    "muted": "#8b92a8",
    "accent1": "#7c6cff",
    "accent2": "#a06bff",
}


class SnippetItem(tk.Frame):
    def __init__(self, parent, snip, on_click, on_edit, on_delete, **kw):
        super().__init__(parent, bg=COLORS["card"], highlightbackground=COLORS["line"], highlightthickness=1, **kw)
        self.snip = snip
        self.on_click = on_click
        self.on_edit = on_edit
        self.on_delete = on_delete

        self.lbl = tk.Label(self, text=snip["content"], bg=COLORS["card"], fg=COLORS["text"],
                            font=("Microsoft YaHei UI", 10), anchor="w", justify="left",
                            wraplength=250, padx=10, pady=8, cursor="hand2")
        self.lbl.pack(side="left", fill="both", expand=True)
        self.lbl.bind("<Button-1>", lambda e: self.on_click(self.snip))

        btn = tk.Label(self, text="✎", bg=COLORS["card"], fg=COLORS["muted"], cursor="hand2", padx=6)
        btn.pack(side="right")
        btn.bind("<Button-1>", lambda e: self.on_edit(self.snip))

        btn2 = tk.Label(self, text="✕", bg=COLORS["card"], fg="#ff6b6b", cursor="hand2", padx=6)
        btn2.pack(side="right")
        btn2.bind("<Button-1>", lambda e: self.on_delete(self.snip))

        self.bind("<Enter>", lambda e: self._hover(True))
        self.bind("<Leave>", lambda e: self._hover(False))

    def _hover(self, active):
        col = COLORS["line"] if active else COLORS["card"]
        self.config(bg=col)
        for w in [self.lbl, self.winfo_children()[-2], self.winfo_children()[-1]]:
            try:
                w.config(bg=col)
            except Exception:
                pass


class FloatPanel(tk.Toplevel):
    def __init__(self, root, api):
        super().__init__(root)
        self.root = root
        self.api = api
        api.set_panel(self)

        self.title("FloatSnipPanel")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.geometry("%dx%d+0+0" % (PANEL_W, PANEL_H))
        self.configure(bg=COLORS["bg"])
        self.withdraw()

        # 标题栏
        header = tk.Frame(self, bg=COLORS["card"], height=46)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)
        tk.Label(header, text="FloatSnip", bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(side="left", padx=14)
        tk.Label(header, text="▁", bg=COLORS["card"], fg=COLORS["muted"], cursor="hand2").pack(side="right", padx=12)
        tk.Label(header, text="⚙", bg=COLORS["card"], fg=COLORS["muted"], cursor="hand2").pack(side="right", padx=6)
        tk.Label(header, text="✕", bg=COLORS["card"], fg=COLORS["muted"], cursor="hand2").pack(side="right", padx=12)
        # 标题栏底部细线
        sep = tk.Frame(self, bg=COLORS["line"], height=1)
        sep.pack(fill="x", side="top")

        # 绑定标题栏按钮
        for w in header.winfo_children():
            t = w.cget("text")
            if t == "▁":
                w.bind("<Button-1>", lambda e: self.api.hide_ball())
            elif t == "⚙":
                w.bind("<Button-1>", lambda e: self.open_settings())
            elif t == "✕":
                w.bind("<Button-1>", lambda e: self.close_panel())

        # 拖动标题栏
        header.bind("<ButtonPress-1>", self._hdr_press)
        header.bind("<B1-Motion>", self._hdr_motion)

        # 分类标签
        self.cat_frame = tk.Frame(self, bg=COLORS["bg"])
        self.cat_frame.pack(fill="x", padx=12, pady=(10, 0))
        self.cat_buttons = {}
        self.active_cat = "all"

        # 列表区（可滚动）
        list_container = tk.Frame(self, bg=COLORS["bg"])
        list_container.pack(fill="both", expand=True, padx=12, pady=8)
        style = ttk.Style()
        style.configure("FS.Vertical.TScrollbar", troughcolor=COLORS["bg"],
                        background=COLORS["accent1"], borderwidth=0, arrowsize=0)
        self.canvas = tk.Canvas(list_container, bg=COLORS["bg"], highlightthickness=0, bd=0)
        self.scroll = ttk.Scrollbar(list_container, orient="vertical",
                                    command=self.canvas.yview, style="FS.Vertical.TScrollbar")
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.list_frame = tk.Frame(self.canvas, bg=COLORS["bg"])
        self._list_win = self.canvas.create_window((0, 0), window=self.list_frame, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfig(self._list_win, width=e.width))
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)

        # 底部新建
        add_btn = tk.Button(self, text="＋ 新建常用语", bg=COLORS["accent1"], fg="white",
                            activebackground=COLORS["accent2"], activeforeground="white",
                            font=("Microsoft YaHei UI", 10), bd=0, cursor="hand2",
                            command=self.open_editor)
        add_btn.pack(fill="x", padx=12, pady=(0, 12), ipady=8)

        # 圆角裁剪
        self.update_idletasks()
        set_rounded_window(get_hwnd(self), PANEL_W, PANEL_H, 16)

        self._drag = None
        self._load_cats()
        self._load_list()

    def _hdr_press(self, e):
        self._drag = {"sx": e.x_root, "sy": e.y_root, "wx": self.winfo_x(), "wy": self.winfo_y()}

    def _hdr_motion(self, e):
        if not self._drag:
            return
        dx = e.x_root - self._drag["sx"]
        dy = e.y_root - self._drag["sy"]
        self.geometry("+%d+%d" % (self._drag["wx"] + dx, self._drag["wy"] + dy))

    def _load_cats(self):
        for w in self.cat_frame.winfo_children():
            w.destroy()
        self.cat_buttons = {}
        for c in self.api.data["categories"]:
            btn = tk.Label(self.cat_frame, text=c["name"], bg=COLORS["card"], fg=COLORS["text"],
                           font=("Microsoft YaHei UI", 9), padx=10, pady=4, cursor="hand2")
            btn.pack(side="left", padx=(0, 6))
            btn.bind("<Button-1>", lambda e, cid=c["id"]: self._set_cat(cid))
            btn.bind("<Enter>", lambda e, b=btn: b.config(bg=COLORS["line"]))
            btn.bind("<Leave>", lambda e, cid=c["id"]: self._refresh_cat_style_one(cid))
            self.cat_buttons[c["id"]] = btn
        self._refresh_cat_style()

    def _refresh_cat_style_one(self, cid):
        btn = self.cat_buttons.get(cid)
        if not btn:
            return
        if cid == self.active_cat:
            btn.config(bg=COLORS["accent1"], fg="white")
        else:
            btn.config(bg=COLORS["card"], fg=COLORS["text"])

    def _refresh_cat_style(self):
        for cid, btn in self.cat_buttons.items():
            if cid == self.active_cat:
                btn.config(bg=COLORS["accent1"], fg="white")
            else:
                btn.config(bg=COLORS["card"], fg=COLORS["text"])

    def _set_cat(self, cid):
        self.active_cat = cid
        self._refresh_cat_style()
        self._load_list()

    def _load_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)
        items = [s for s in self.api.data["snippets"]
                 if self.active_cat == "all" or s["category"] == self.active_cat]
        if not items:
            tk.Label(self.list_frame, text="这里还没有内容\n点下方「＋ 新建常用语」添加第一条吧",
                     bg=COLORS["bg"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 10)).pack(expand=True)
        else:
            for s in items:
                it = SnippetItem(self.list_frame, s, self._on_copy, self._on_edit, self._on_delete)
                it.pack(fill="x", pady=(0, 6))
        self.list_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_mousewheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

    def _on_copy(self, snip):
        res = copy_and_verify(snip["content"])
        if res == "ok":
            self._toast("已复制 ✓", "ok")
        elif res == "empty":
            self._toast("内容为空", "err")
        elif res == "mismatch":
            self._toast("复制可能失败", "err")
        else:
            self._toast("复制失败", "err")
        if res == "ok" and self.api.data["settings"].get("auto_paste"):
            self.root.after(120, _send_ctrl_v)

    def _toast(self, msg, kind="ok"):
        show_toast(self, msg, kind)

    def _on_edit(self, snip):
        EditorDialog(self, self.api, snip["id"], self._after_edit)

    def _on_delete(self, snip):
        self.api.delete_snippet(snip["id"])
        self._load_list()
        self._toast("已删除", "info")

    def open_editor(self):
        EditorDialog(self, self.api, None, self._after_edit)

    def _after_edit(self, saved):
        if saved:
            self._load_cats()
            self._load_list()

    def open_settings(self):
        SettingsDialog(self, self.api, self._after_settings)

    def _after_settings(self):
        self._load_cats()
        self._load_list()

    def close_panel(self):
        self.api.set_mode("ball")
        self.sync_mode()

    def sync_mode(self):
        if self.api.mode == "ball":
            self.withdraw()
        else:
            self._place_near_ball()
            self.deiconify()
            self.lift()
            self._load_list()

    def _place_near_ball(self):
        if not self.api._win:
            return
        bx = self.api._win.winfo_x()
        by = self.api._win.winfo_y()
        sw = self.winfo_screenwidth()
        x = bx + BALL_SIZE + 12
        y = by
        if x + PANEL_W > sw:
            x = bx - PANEL_W - 12
        if y + PANEL_H > self.winfo_screenheight():
            y = self.winfo_screenheight() - PANEL_H - 10
        if y < 0:
            y = 0
        self.geometry("+%d+%d" % (x, y))


# ---------------------------------------------------------------------------
# UI：编辑弹窗
# ---------------------------------------------------------------------------
class EditorDialog(tk.Toplevel):
    def __init__(self, parent, api, sid, on_done):
        super().__init__(parent)
        self.parent_win = parent
        self.api = api
        self.sid = sid
        self.on_done = on_done
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])
        self.geometry("340x260")

        card = tk.Frame(self, bg=COLORS["card"])
        card.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(card, text="编辑常用语" if sid else "新建常用语", bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=12, pady=(10, 8))

        self.text = tk.Text(card, bg="#1c1f28", fg=COLORS["text"], insertbackground=COLORS["text"],
                            font=("Microsoft YaHei UI", 10), height=6, bd=0, padx=8, pady=8)
        self.text.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        cats = [c for c in api.data["categories"] if not c.get("fixed")]
        self.var_cat = tk.StringVar(value=cats[0]["id"] if cats else "c1")
        if sid:
            for s in api.data["snippets"]:
                if s["id"] == sid:
                    self.text.insert("1.0", s["content"])
                    self.var_cat.set(s["category"])
                    break

        if cats:
            row = tk.Frame(card, bg=COLORS["card"])
            row.pack(fill="x", padx=12, pady=(0, 8))
            tk.Label(row, text="分类", bg=COLORS["card"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 9)).pack(side="left")
            for c in cats:
                rb = tk.Radiobutton(row, text=c["name"], variable=self.var_cat, value=c["id"],
                                    bg=COLORS["card"], fg=COLORS["text"], selectcolor=COLORS["accent1"],
                                    activebackground=COLORS["card"], activeforeground=COLORS["text"])
                rb.pack(side="left", padx=(8, 0))

        btns = tk.Frame(card, bg=COLORS["card"])
        btns.pack(fill="x", padx=12, pady=(0, 10))
        tk.Button(btns, text="取消", bg=COLORS["line"], fg=COLORS["text"], bd=0, cursor="hand2",
                  command=self.destroy).pack(side="right", padx=(6, 0), ipadx=12, ipady=4)
        if sid:
            tk.Button(btns, text="删除", bg="#3a1c1c", fg="#ff6b6b", bd=0, cursor="hand2",
                      command=self._delete).pack(side="right", padx=(6, 0), ipadx=12, ipady=4)
        tk.Button(btns, text="保存", bg=COLORS["accent1"], fg="white", bd=0, cursor="hand2",
                  command=self._save).pack(side="right", ipadx=12, ipady=4)

        self.update_idletasks()
        set_rounded_window(get_hwnd(self), self.winfo_width(), self.winfo_height(), 12)
        self._center()

    def _center(self):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry("+%d+%d" % (sw / 2 - self.winfo_width() / 2, sh / 2 - self.winfo_height() / 2))

    def _save(self):
        content = self.text.get("1.0", "end-1c")
        r = self.api.save_snippet(self.sid, content, self.var_cat.get())
        if not r["ok"]:
            messagebox.showwarning("提示", r["msg"])
            return
        self.parent_win.after(0, lambda: show_toast(self.parent_win, "已保存 ✓", "ok"))
        self.on_done(True)
        self.destroy()

    def _delete(self):
        self.api.delete_snippet(self.sid)
        self.parent_win.after(0, lambda: show_toast(self.parent_win, "已删除", "info"))
        self.on_done(True)
        self.destroy()


# ---------------------------------------------------------------------------
# UI：设置弹窗
# ---------------------------------------------------------------------------
class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, api, on_done):
        super().__init__(parent)
        self.parent_win = parent
        self.api = api
        self.on_done = on_done
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"])
        self.geometry("360x420")

        card = tk.Frame(self, bg=COLORS["card"])
        card.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(card, text="设置", bg=COLORS["card"], fg=COLORS["text"],
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=12, pady=(10, 8))

        # 快捷键
        row = tk.Frame(card, bg=COLORS["card"])
        row.pack(fill="x", padx=12, pady=6)
        tk.Label(row, text="快捷键", bg=COLORS["card"], fg=COLORS["muted"], font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.hotkey_var = tk.StringVar(value=api.data["settings"].get("hotkey", DEFAULT_HOTKEY))
        self.hotkey_entry = tk.Entry(row, textvariable=self.hotkey_var, bg="#1c1f28", fg=COLORS["text"],
                                     insertbackground=COLORS["text"], font=("Microsoft YaHei UI", 10), width=14, bd=0)
        self.hotkey_entry.pack(side="right", padx=(10, 0), ipady=4)
        self.recording = False
        self.hotkey_entry.bind("<FocusIn>", lambda e: self._start_record())
        self.hotkey_entry.bind("<FocusOut>", lambda e: self._stop_record())
        self.hotkey_entry.bind("<KeyPress>", self._on_key)

        # 开关
        self.auto_paste = tk.BooleanVar(value=api.data["settings"].get("auto_paste", False))
        tk.Checkbutton(card, text="复制后自动粘贴", variable=self.auto_paste, bg=COLORS["card"], fg=COLORS["text"],
                       selectcolor=COLORS["accent1"], activebackground=COLORS["card"], activeforeground=COLORS["text"],
                       font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=12, pady=4)

        self.autostart = tk.BooleanVar(value=_is_autostart())
        tk.Checkbutton(card, text="开机自启", variable=self.autostart, bg=COLORS["card"], fg=COLORS["text"],
                       selectcolor=COLORS["accent1"], activebackground=COLORS["card"], activeforeground=COLORS["text"],
                       font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=12, pady=4)

        # 分类改名
        tk.Label(card, text="分类名称", bg=COLORS["card"], fg=COLORS["muted"],
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=12, pady=(10, 4))
        self.cat_vars = {}
        for c in api.data["categories"]:
            if c.get("fixed"):
                continue
            row = tk.Frame(card, bg=COLORS["card"])
            row.pack(fill="x", padx=12, pady=2)
            tk.Label(row, text=c["name"], bg=COLORS["card"], fg=COLORS["text"], font=("Microsoft YaHei UI", 10)).pack(side="left")
            var = tk.StringVar(value=c["name"])
            ent = tk.Entry(row, textvariable=var, bg="#1c1f28", fg=COLORS["text"], insertbackground=COLORS["text"], bd=0)
            ent.pack(side="right", fill="x", expand=True, ipady=3)
            self.cat_vars[c["id"]] = var

        # 按钮
        btns = tk.Frame(card, bg=COLORS["card"])
        btns.pack(fill="x", padx=12, pady=(14, 10))
        tk.Button(btns, text="隐藏悬浮球", bg=COLORS["line"], fg=COLORS["text"], bd=0, cursor="hand2",
                  command=self._hide).pack(side="left", ipadx=10, ipady=4)
        tk.Button(btns, text="退出程序", bg="#3a1c1c", fg="#ff6b6b", bd=0, cursor="hand2",
                  command=self.api.quit_app).pack(side="left", padx=(8, 0), ipadx=10, ipady=4)
        tk.Button(btns, text="保存", bg=COLORS["accent1"], fg="white", bd=0, cursor="hand2",
                  command=self._save).pack(side="right", ipadx=14, ipady=4)

        self.update_idletasks()
        set_rounded_window(get_hwnd(self), self.winfo_width(), self.winfo_height(), 12)
        self._center()

    def _center(self):
        sw = self.winfo_screenwidth()
        sh = self.winfo_screenheight()
        self.geometry("+%d+%d" % (sw / 2 - self.winfo_width() / 2, sh / 2 - self.winfo_height() / 2))

    def _start_record(self):
        self.recording = True
        self.hotkey_var.set("按下组合键…")

    def _stop_record(self):
        if self.recording:
            self.recording = False
            if self.hotkey_var.get() == "按下组合键…":
                self.hotkey_var.set(self.api.data["settings"].get("hotkey", DEFAULT_HOTKEY))

    def _on_key(self, e):
        if not self.recording:
            return "break"
        mods = []
        if e.state & 0x0004:
            mods.append("ctrl")
        if e.state & 0x0008:
            mods.append("alt")
        if e.state & 0x0001:
            mods.append("shift")
        if e.state & 0x00080:
            mods.append("win")
        key = e.keysym.lower()
        if key in ("control_l", "control_r", "alt_l", "alt_r", "shift_l", "shift_r",
                   "win_l", "win_r", "meta_l", "meta_r"):
            return "break"
        if key in ("grave", "asciitilde"):
            key = "`"
        parts = mods + [key]
        expr = "+".join(parts)
        self.hotkey_var.set(expr)
        self.recording = False
        return "break"

    def _hide(self):
        self.api.hide_ball()
        self.destroy()

    def _save(self):
        # 热键
        r = self.api.set_hotkey(self.hotkey_var.get())
        if not r["ok"]:
            messagebox.showwarning("提示", "快捷键格式不合法，已保留原设置")
            return
        # 自动粘贴
        self.api.set_auto_paste(self.auto_paste.get())
        # 开机自启
        try:
            if self.autostart.get():
                _enable_autostart()
            else:
                _disable_autostart()
        except Exception as e:
            messagebox.showwarning("提示", "开机自启设置失败：%s" % e)
        # 分类改名
        for cid, var in self.cat_vars.items():
            self.api.rename_category(cid, var.get())
        self.parent_win.after(0, lambda: show_toast(self.parent_win, "设置已保存 ✓", "ok"))
        self.on_done()
        self.destroy()


# ---------------------------------------------------------------------------
# 开机自启
# ---------------------------------------------------------------------------
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "FloatSnip"


def _is_autostart():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, AUTOSTART_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _enable_autostart():
    import winreg
    # PyInstaller onefile 运行时 sys.executable 就是用户的 exe 本体
    exe = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
    winreg.SetValueEx(key, AUTOSTART_NAME, 0, winreg.REG_SZ, '"%s"' % exe)
    winreg.CloseKey(key)


def _disable_autostart():
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_SET_VALUE)
    try:
        winreg.DeleteValue(key, AUTOSTART_NAME)
    except FileNotFoundError:
        pass
    winreg.CloseKey(key)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    root = tk.Tk()
    root.withdraw()  # 隐藏主窗口
    root.title("FloatSnip")

    api = Api()
    ball = FloatBall(root, api)
    panel = FloatPanel(root, api)

    register_hotkey(api)

    # 定时保存位置（拖动中不频繁写盘）
    def _save_pos():
        api.save_window_pos()
        root.after(3000, _save_pos)

    root.after(3000, _save_pos)

    # 启动模式
    root.after(100, panel.sync_mode)

    root.mainloop()


if __name__ == "__main__":
    main()
