# -*- coding: utf-8 -*-
"""FloatSnip 浮球快贴 · v2（最炫酷 · 最有料 · 最可验证）

架构：tkinter + Win32（零额外依赖，打包体积最小、最稳）
  - 浮球：圆形渐变、可拖动、单击切换面板、右键菜单（关闭 / 设置）
  - 面板：分类标签（可改名 / 新建）、列表（复制自检 + 反馈）、新建、教学提示
  - 设置：快捷键（Win32 冲突预检）、自动粘贴、开机自启、分类管理、保存 / 取消
  - 系统托盘：左键唤起浮球、右键菜单（显示 / 设置 / 退出），退出时清理图标
  - 关闭全覆盖：每个无边框窗口都 ≥2 种关闭路径，绝不留"关不掉"的窗口
说明：WebView2/Chromium 在 Windows 不支持真透明（白边死路），故用 tkinter + Win32 RGN
      裁剪实现真·无白边 + 平滑拖动。
"""
import os
import sys
import json
import ctypes
import threading

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, font as tkfont

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
    "settings": {"auto_paste": False, "hotkey": DEFAULT_HOTKEY, "window_x": None, "window_y": None,
                  "active_cat": "all", "autostart": True},
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
shell32 = ctypes.windll.shell32
kernel32 = ctypes.windll.kernel32

# 64 位指针安全：这些 API 返回 HANDLE / HGLOBAL / HMODULE，必须 c_void_p 避免高 32 位截断
kernel32.GlobalAlloc.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
kernel32.GlobalAlloc.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
kernel32.GlobalSize.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
kernel32.GetModuleHandleW.argtypes = [ctypes.c_void_p]
kernel32.GetModuleHandleW.restype = ctypes.c_void_p
user32.SetClipboardData.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
user32.SetClipboardData.restype = ctypes.c_void_p
user32.GetClipboardData.argtypes = [ctypes.c_ulong]
user32.GetClipboardData.restype = ctypes.c_void_p
# memmove / string_at 必须有显式 argtypes：否则 ctypes 在首次调用时按实参推断一个
# 过窄的整型，遇到 64 位大地址指针会抛 OverflowError，导致 copy_text 在真机失效。
ctypes.memmove.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
ctypes.string_at.argtypes = [ctypes.c_void_p, ctypes.c_size_t]


# SendInput 结构（用于「复制后自动粘贴」：替代 pynput Controller，去掉全局键盘钩子线程）
class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ctypes.c_void_p)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ctypes.c_void_p)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTUNION)]


user32.SendInput.argtypes = [ctypes.c_uint, ctypes.c_void_p, ctypes.c_int]
user32.SendInput.restype = ctypes.c_uint


def set_circular_window(hwnd, size):
    rgn = gdi32.CreateEllipticRgn(0, 0, size, size)
    user32.SetWindowRgn(hwnd, rgn, True)


def set_rounded_window(hwnd, w, h, r):
    rgn = gdi32.CreateRoundRectRgn(0, 0, w, h, r, r)
    user32.SetWindowRgn(hwnd, rgn, True)


def get_hwnd(widget):
    return widget.winfo_id()


def safe_popup_menu(menu, x_root, y_root):
    """统一的安全右键菜单弹出。

    关键： tk_popup 在 overrideredirect 父窗口下偶发 grab 残留，残留的 grab
    会锁死全局输入（表现为「点开设置再点浮窗就卡死、无法再操作」）。
    因此无论菜单是否正常关闭，都强制释放 grab。所有右键菜单必须走这里，
    禁止再散落在各组件里各自 try/except，避免漏写 release 导致复发。
    """
    try:
        menu.tk_popup(x_root, y_root)
    except Exception:
        pass
    finally:
        try:
            menu.grab_release()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 数据 / 剪贴板 / 热键规范化
# ---------------------------------------------------------------------------
def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_DATA.items():
                if k not in data:
                    data[k] = v
            # 回填缺失的设置子字段（含 autostart/auto_paste/hotkey/记忆分类等），
            # 保证旧版本 data.json 升级后不缺键、不报错
            for k, v in DEFAULT_DATA["settings"].items():
                if k not in data["settings"]:
                    data["settings"][k] = v
            existing_ids = {c.get("id") for c in data["categories"]}
            migrated = False
            for c in DEFAULT_DATA["categories"]:
                if c.get("id") and c["id"] not in existing_ids:
                    data["categories"].append(dict(c))
                    migrated = True
            if migrated:
                save_data(data)
            return data
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data):
    try:
        # 敏感片段（sensitive）只留内存、不落盘：写盘前剥离，重启即消失
        clean = data
        if isinstance(data, dict) and isinstance(data.get("snippets"), list):
            if any(s.get("sensitive") for s in data["snippets"]):
                clean = dict(data)
                clean["snippets"] = [s for s in data["snippets"] if not s.get("sensitive")]
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


def copy_text(text):
    """把文本写入系统剪贴板。健壮性要点：
    1) OpenClipboard 失败（被别的程序占用）直接返回 False，不抛异常；
    2) 无论成功失败都用 try/finally 关掉剪贴板，避免锁死导致后续复制全废；
    3) GMEM_MOVEABLE + 交还句柄给系统，符合 Win32 剪贴板规范。"""
    if text is None:
        text = ""
    text = str(text)
    if not text:
        return True
    try:
        if not user32.OpenClipboard(0):
            return False
        try:
            user32.EmptyClipboard()
            buf = text.encode("utf-16-le") + b"\x00\x00"
            size = len(buf)
            h_global = ctypes.windll.kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
            if not h_global:
                return False
            ptr = ctypes.windll.kernel32.GlobalLock(h_global)
            ctypes.memmove(ptr, buf, size)
            ctypes.windll.kernel32.GlobalUnlock(h_global)
            user32.SetClipboardData(CF_UNICODETEXT, h_global)
            return True
        finally:
            user32.CloseClipboard()
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass
        return False


def read_clipboard():
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
        text = buf.decode("utf-16-le", errors="ignore")
        return text.rstrip("\x00")
    except Exception:
        try:
            user32.CloseClipboard()
        except Exception:
            pass
        return None


def copy_and_verify(text):
    if text is None or str(text).strip() == "":
        return "empty"
    ok = copy_text(text)
    if not ok:
        ok = copy_text(text)  # 偶发被占用导致失败 → 重试一次，绝大多数能成功
    if not ok:
        return "fail"
    got = read_clipboard()
    if got is None:
        return "ok"
    if got == str(text):
        return "ok"
    return "mismatch"


def show_toast(parent, msg, kind="ok", ms=1500):
    try:
        if parent is None:
            return
        t = tk.Toplevel(parent)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        # surface1 卡片 + 1px 发丝描边；左侧状态点（绿/红/灰）替代彩色 emoji 图标
        dot = {"ok": COLORS["success"], "err": COLORS["danger"], "info": COLORS["text3"]}.get(kind, COLORS["text3"])
        t.configure(bg=COLORS["surface1"], highlightthickness=1, highlightbackground=COLORS["hairline"])
        dot_cv = tk.Canvas(t, width=8, height=8, bg=COLORS["surface1"], highlightthickness=0)
        dot_cv.pack(side="left", padx=(12, 0), pady=9)
        dot_cv.create_oval(1, 1, 7, 7, fill=dot, outline="")
        tk.Label(t, text=msg, bg=COLORS["surface1"], fg=COLORS["text"], font=FONT_EMPH,
                 padx=10, pady=9, justify="left", wraplength=320).pack(side="left")
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
        t.bind("<Button-1>", lambda e: t.destroy())  # 点击即消失
        t.after(int(ms), t.destroy)
    except Exception:
        pass


def _send_ctrl_v():
    """用 Win32 SendInput 发送 Ctrl+V（替代 pynput Controller，去掉全局键盘钩子线程）。"""
    try:
        VK_CONTROL = 0x11
        VK_V = 0x56
        KEYEVENTF_KEYUP = 0x0002
        inputs = []

        def _k(vk, flags=0):
            ki = KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
            inputs.append(INPUT(type=1, union=_INPUTUNION(ki=ki)))

        _k(VK_CONTROL)
        _k(VK_V)
        _k(VK_CONTROL, KEYEVENTF_KEYUP)
        _k(VK_V, KEYEVENTF_KEYUP)
        arr = (INPUT * len(inputs))(*inputs)
        user32.SendInput(len(inputs), ctypes.byref(arr), ctypes.sizeof(INPUT))
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


def _canon_mod(p):
    p = p.strip().lower().strip("<>")
    if p in ("ctrl", "control"):
        return "<ctrl>"
    if p in ("alt",):
        return "<alt>"
    if p in ("shift",):
        return "<shift>"
    if p in ("win", "windows", "command", "cmd", "meta"):
        return "<cmd>"
    return None


def normalize_hotkey(expr):
    if not expr or not isinstance(expr, str):
        return None
    parts = [p.strip() for p in expr.split("+") if p.strip()]
    if not parts:
        return None
    mods = []
    key = None
    for p in parts:
        m = _canon_mod(p)
        if m:
            mods.append(m)
            continue
        if key is not None:
            return None
        key = HOTKEY_KEYMAP.get(p.lower(), p.lower())
    if key is None:
        return None
    if key not in VALID_KEYS:
        return None
    single_char = set("abcdefghijklmnopqrstuvwxyz0123456789`~!@#$%^&*()-_=+[]{}\\|;:'\",.<>/?")
    key_spec = key if (len(key) == 1 and key in single_char) else "<%s>" % key
    spec = "+".join(mods + [key_spec]) if mods else key_spec
    # 自校验：用 Win32 vk 解析确认主键合法（不再依赖 pynput，去掉全局钩子依赖）
    _mods, vk = _spec_to_mod_vk(spec)
    if vk is None:
        return None
    return spec


def format_hotkey_display(expr):
    spec = normalize_hotkey(expr)
    if not spec:
        return expr if isinstance(expr, str) else ""
    disp = []
    for p in spec.split("+"):
        if p == "<ctrl>":
            disp.append("Ctrl")
        elif p == "<alt>":
            disp.append("Alt")
        elif p == "<shift>":
            disp.append("Shift")
        elif p == "<cmd>":
            disp.append("Win")
        else:
            k = p.strip("<>")
            disp.append(k.upper() if len(k) == 1 else k.capitalize())
    return "+".join(disp)


# ---------------------------------------------------------------------------
# Win32 热键冲突预检（确认快捷键没被别的程序占用）
# ---------------------------------------------------------------------------
_MOD_FLAGS = {"ctrl": 2, "alt": 1, "shift": 4, "cmd": 8}  # MOD_CONTROL/ALT/SHIFT/WIN
_FN_KEYS = {("f%d" % i): (0x70 + i - 1) for i in range(1, 25)}
_FN_KEYS.update({"esc": 0x1B, "tab": 0x09, "enter": 0x0D, "backspace": 0x08, "delete": 0x2E,
                 "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27, "space": 0x20})


def _spec_to_mod_vk(spec):
    if not spec:
        return (0, None)
    mods = 0
    vk = None
    for p in spec.split("+"):
        p = p.strip().strip("<>")
        if p in _MOD_FLAGS:
            mods |= _MOD_FLAGS[p]
        else:
            if len(p) == 1:
                vk = ctypes.windll.user32.VkKeyScanW(ctypes.c_wchar(p)) & 0xFF
            else:
                vk = _FN_KEYS.get(p.lower())
    return (mods, vk)


def hotkey_is_available(spec):
    """用 Win32 RegisterHotKey 预检：被占用返回 False。"""
    mods, vk = _spec_to_mod_vk(spec)
    if vk is None:
        return False
    ok = user32.RegisterHotKey(0, 0xED01, mods, vk)
    if ok:
        user32.UnregisterHotKey(0, 0xED01)
        return True
    return False


# ---------------------------------------------------------------------------
# Win32 全局热键监听（RegisterHotKey + 隐藏窗口消息循环）
#   替代 pynput.GlobalHotKeys（其底层是全局键盘钩子线程，会拦截所有按键、在
#   输入法全屏/游戏等场景易冲突）。RegisterHotKey 是 OS 级推荐方案，只在组合键
#   真正按下时触发，互不干扰；回调统一经 api.ui 切回主线程操作 tkinter。
# ---------------------------------------------------------------------------
class HotkeyListener:
    WM_HOTKEY = 0x0312

    def __init__(self, api, bindings):
        # bindings: list of (mods, vk, callback)
        self.api = api
        self.bindings = bindings
        self.hwnd = None
        self.running = False
        self._wndproc = WNDPROC(self._wnd_proc)  # 保持引用，防止 GC

    def run(self):
        hinst = kernel32.GetModuleHandleW(0)
        wc = WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(WNDCLASSEX)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "FloatSnipHotkey"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "FloatSnipHotkey", "hk", 0,
                                           0, 0, 0, 0, 0, 0, hinst, 0)
        for i, (mods, vk, _cb) in enumerate(self.bindings):
            user32.RegisterHotKey(self.hwnd, 0xED01 + i, mods, vk)
        msg = ctypes.wintypes.MSG()
        while self.running and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == HotkeyListener.WM_HOTKEY:
            hid = wparam & 0xFFFF
            for i, (_mods, _vk, cb) in enumerate(self.bindings):
                if 0xED01 + i == hid:
                    self.api.ui(cb)
                    break
            return 0
        if msg == WM_DESTROY:
            try:
                user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def close(self):
        self.running = False
        try:
            if self.hwnd:
                user32.PostMessageW(self.hwnd, WM_DESTROY, 0, 0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Api（业务逻辑，与 UI 分离）
# ---------------------------------------------------------------------------
class Api:
    def __init__(self):
        self.data = load_data()
        self.mode = "ball"
        self._win = None
        self._panel = None
        self._tray = None
        self._root = None
        self._save_timer = None

    def set_win(self, win):
        self._win = win

    def set_root(self, root):
        self._root = root

    def set_panel(self, panel):
        self._panel = panel

    def ensure_panel(self):
        """懒加载面板：首次需要时才创建 FloatPanel（避免启动时立即建大窗口）。"""
        if self._panel is None and self._root is not None:
            self._panel = FloatPanel(self._root, self)
        return self._panel

    def schedule_save(self):
        """异步防抖落盘：高频写操作后合并为一次后台写，避免频繁同步 IO 卡 UI。
        关键业务写（增删改）仍同步 save_data 保证持久化；此处仅用于可丢失的辅助状态。"""
        try:
            if self._save_timer is not None:
                self._root.after_cancel(self._save_timer)
        except Exception:
            pass
        try:
            self._save_timer = self._root.after(300, lambda: save_data(self.data))
        except Exception:
            save_data(self.data)

    def ui(self, fn):
        if self._win and hasattr(self._win, "root") and self._win.root:
            try:
                self._win.root.after(0, fn)
            except Exception:
                fn()
        else:
            fn()

    def get_state(self):
        return self.data

    def toggle_mode(self):
        self.mode = "panel" if self.mode == "ball" else "ball"
        return self.mode

    def set_mode(self, m):
        self.mode = m
        return m

    def save_snippet(self, sid, content, category, sensitive=False):
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
                    s["sensitive"] = bool(sensitive)
                    break
        else:
            ids = [int(s["id"][1:]) for s in self.data["snippets"] if s["id"].startswith("s") and s["id"][1:].isdigit()]
            nid = "s%d" % (max(ids) + 1 if ids else 1)
            self.data["snippets"].append({"id": nid, "content": content,
                                          "category": category, "sensitive": bool(sensitive)})
        save_data(self.data)
        return {"ok": True, "state": self.data}

    def export_backup(self, path):
        """导出整份数据为 JSON 备份（与 data.json 同结构，可直接导入还原）。"""
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True, ""
        except Exception as e:
            return False, str(e)

    def import_backup(self, path):
        """从 JSON 备份导入：覆盖式还原，导入前由 UI 二次确认。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict) or "snippets" not in d or "categories" not in d or "settings" not in d:
                return False, "文件格式不对（缺少 snippets / categories / settings）"
            for k, v in DEFAULT_DATA.items():
                if k not in d:
                    d[k] = v
            self.data = d
            save_data(self.data)
            return True, ""
        except Exception as e:
            return False, str(e)

    def clear_all(self):
        """清空全部常用语与自定义分类（保留「所有」固定分类），回到初始状态。"""
        self.data["snippets"] = []
        self.data["categories"] = [dict(c) for c in DEFAULT_DATA["categories"]]
        self.data["settings"]["active_cat"] = "all"
        save_data(self.data)
        return {"ok": True}

    def delete_snippet(self, sid):
        self.data["snippets"] = [s for s in self.data["snippets"] if s["id"] != sid]
        save_data(self.data)
        return {"ok": True, "state": self.data}

    def restore_snippet(self, snip):
        """撤销删除：按原 id 还原（id 已被复用则跳过，避免覆盖其它条目）。"""
        sid = snip.get("id")
        if any(s["id"] == sid for s in self.data["snippets"]):
            return
        self.data["snippets"].append(dict(snip))
        save_data(self.data)

    def add_category(self, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "msg": "名字不能为空"}
        # 重名拦截：避免造出同名分类导致下拉框无法区分、保存静默错分
        if any(c["name"] == name for c in self.data["categories"]):
            return {"ok": False, "msg": "分类名已存在"}
        cust = [c for c in self.data["categories"] if not c.get("fixed")]
        if len(cust) >= 10:
            return {"ok": False, "msg": "自定义分类最多 10 个"}
        ids = [int(c["id"][1:]) for c in self.data["categories"] if c["id"].startswith("c") and c["id"][1:].isdigit()]
        nid = "c%d" % (max(ids) + 1 if ids else 1)
        self.data["categories"].append({"id": nid, "name": name})
        save_data(self.data)
        return {"ok": True, "id": nid, "state": self.data}

    def delete_category(self, cid):
        # 固定分类（如「全部」）不可删
        target = None
        for c in self.data["categories"]:
            if c["id"] == cid:
                target = c
                break
        if not target:
            return {"ok": False, "msg": "分类不存在"}
        if target.get("fixed"):
            return {"ok": False, "msg": "固定分类不可删除"}
        # 连同该分类下的全部常用语一起删除（UI 二次确认时已告知数量）
        before = len(self.data["snippets"])
        self.data["snippets"] = [s for s in self.data["snippets"] if s.get("category") != cid]
        removed = before - len(self.data["snippets"])
        self.data["categories"] = [c for c in self.data["categories"] if c["id"] != cid]
        save_data(self.data)
        return {"ok": True, "removed": removed, "state": self.data}

    def rename_category(self, cid, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "msg": "名字不能为空"}
        # 重名拦截：排除自身，避免改名成已存在的名字引入歧义
        if any(c["name"] == name and c["id"] != cid for c in self.data["categories"]):
            return {"ok": False, "msg": "分类名已存在"}
        found = False
        for c in self.data["categories"]:
            if c["id"] == cid:
                if c.get("fixed"):
                    return {"ok": False, "msg": "固定分类不可改名"}
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

    def set_active_cat(self, cid):
        """记忆当前选中分类：每次切换/关闭都落盘，重启后停留在上次分类（用户要的'保存记忆'）"""
        self.data["settings"]["active_cat"] = cid
        save_data(self.data)
        return {"ok": True, "active_cat": cid}

    def set_hotkey(self, expr):
        spec = normalize_hotkey(expr)
        if spec is None:
            return {"ok": False, "msg": "快捷键格式不合法"}
        self.data["settings"]["hotkey"] = spec
        save_data(self.data)
        available = hotkey_is_available(spec)
        register_hotkey(self)
        return {"ok": True, "hotkey": spec, "available": available}

    def get_window_pos(self):
        if self._win:
            return [self._win.winfo_x(), self._win.winfo_y()]
        return [0, 0]

    def save_window_pos(self):
        if self._win:
            try:
                self.data["settings"]["window_x"] = self._win.winfo_x()
                self.data["settings"]["window_y"] = self._win.winfo_y()
            except Exception:
                # 窗口已销毁时静默跳过，避免退出路径抛异常卡死
                pass
        save_data(self.data)

    def quit_app(self):
        # 干净退出：先结束主循环再销毁窗口，避免残留 Toplevel 卡死主线程（防御性）
        if self._panel:
            try:
                self.set_active_cat(self._panel.active_cat)  # 退出前落盘当前分类（记忆）
            except Exception:
                pass
        self.save_window_pos()
        if self._tray:
            try:
                self._tray.close()
            except Exception:
                pass
        global _current_listener
        if _current_listener:
            try:
                _current_listener.close()
            except Exception:
                pass
            _current_listener = None

        def _teardown():
            try:
                if self._win and self._win.root:
                    self._win.root.quit()      # 先标记主循环退出
            except Exception:
                pass
            try:
                if self._win and self._win.root:
                    self._win.root.destroy()   # 再销毁所有窗口，释放资源
            except Exception:
                pass

        self.ui(_teardown)


# ---------------------------------------------------------------------------
# 全局热键
# ---------------------------------------------------------------------------
_current_listener = None


def register_hotkey(api):
    """用 Win32 RegisterHotKey 注册全局热键（替代 pynput 全局钩子）。
    失败/被占用时不阻断主流程：提示用户改用手动（浮球/托盘）打开。"""
    global _current_listener
    if _current_listener:
        try:
            _current_listener.close()
        except Exception:
            pass
        _current_listener = None
    spec = normalize_hotkey(api.data["settings"].get("hotkey", DEFAULT_HOTKEY))
    if not spec:
        return
    mods, vk = _spec_to_mod_vk(spec)
    if vk is None:
        return
    # 冲突预检：被占用则不注册，提示用户用托盘/浮球打开
    if not hotkey_is_available(spec):
        api.ui(lambda: show_toast(api._win if api._win else api._panel,
                                   "快捷键被占用，无法快速唤起 · 用托盘/浮球打开", "err"))
        return
    _current_listener = HotkeyListener(api, [(mods, vk, lambda: _hotkey_handler(api))])
    _current_listener.running = True
    try:
        threading.Thread(target=_current_listener.run, daemon=True).start()
    except Exception:
        _current_listener = None
        api.ui(lambda: show_toast(api._win if api._win else api._panel,
                                   "快捷键注册失败 · 用托盘/浮球打开", "err"))


def _hotkey_handler(api):
    api.ensure_panel()          # 首次触发时再懒加载面板
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

        self.canvas = tk.Canvas(self, width=BALL_SIZE, height=BALL_SIZE, highlightthickness=0, bg=COLORS["surface0"])
        self.canvas.pack(fill="both", expand=True)
        self._ball_state = "default"
        self._draw_ball()

        self.update_idletasks()
        set_circular_window(get_hwnd(self), BALL_SIZE)

        self._drag = None
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_motion)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_motion)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        # 悬浮 / 按压 视觉态（零依赖：只换色 + 1px inset 高光，不引模糊/阴影）
        self.bind("<Enter>", lambda e: self._set_ball_state("hover"))
        self.bind("<Leave>", lambda e: self._set_ball_state("default"))
        self.canvas.bind("<Enter>", lambda e: self._set_ball_state("hover"))
        self.canvas.bind("<Leave>", lambda e: self._set_ball_state("default"))

        # 右键菜单：关闭 / 设置
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="关闭悬浮窗", command=self.api.quit_app)
        self.menu.add_command(label="打开设置", command=lambda: self.api._panel.open_settings() if self.api._panel else None)
        self.bind("<Button-3>", self._on_right)
        self.canvas.bind("<Button-3>", self._on_right)
        self.after(900, lambda: show_toast(self, "右键可关闭悬浮窗", "info"))

        wx = api.data["settings"].get("window_x")
        wy = api.data["settings"].get("window_y")
        if wx is not None and wy is not None:
            self.geometry("+%d+%d" % (wx, wy))

    def _set_ball_state(self, state):
        if getattr(self, "_ball_state", "default") == state:
            return
        self._ball_state = state
        self._draw_ball()

    def _draw_ball(self):
        """纯 surface 实心圆 + 1px 发丝环 + 汉堡图标；hover 提亮、active 下沉(顶部 inset 高光)。
        砍掉旧的 10 层同心圆 fake 渐变（tkinter 物理不可行且显脏）。"""
        self.canvas.delete("all")
        c = BALL_SIZE / 2
        palette = {
            "default": (COLORS["surface1"], COLORS["hairline"]),
            "hover":   (COLORS["surface2"], "#3a4150"),
            "active":  (COLORS["surface3"], COLORS["hairline"]),
        }
        fill, ring = palette[self._ball_state]
        # 实心圆 + 极淡描边环（略内缩，避免被圆形窗口裁剪吃掉）
        self.canvas.create_oval(2, 2, BALL_SIZE - 2, BALL_SIZE - 2,
                                fill=fill, outline=ring, width=1)
        # 按压态：顶部 1px 浅色 inset 高光，模拟「按下去」的下沉感
        if self._ball_state == "active":
            self.canvas.create_line(8, 5, BALL_SIZE - 8, 5, fill="#2a3242", width=1)
        # 汉堡图标：三条白色横线（清晰「可戳」）
        for dy in (-6, 0, 6):
            self.canvas.create_line(c - 11, c + dy, c + 11, c + dy,
                                    fill="white", width=2, capstyle="round")

    def _on_press(self, e):
        self._set_ball_state("active")
        self._drag = {"sx": e.x_root, "sy": e.y_root, "wx": self.winfo_x(), "wy": self.winfo_y(), "moved": False}

    def _on_motion(self, e):
        if not self._drag:
            return
        dx = e.x_root - self._drag["sx"]
        dy = e.y_root - self._drag["sy"]
        if abs(dx) > 2 or abs(dy) > 2:
            self._drag["moved"] = True
        self.geometry("+%d+%d" % (self._drag["wx"] + dx, self._drag["wy"] + dy))

    def _on_release(self, e):
        if not self._drag:
            return
        moved = self._drag["moved"]
        self._drag = None
        self._set_ball_state("hover")
        self.api.save_window_pos()
        if not moved:
            self.api.toggle_mode()
            # 懒加载：首点浮球才创建面板，再同步显示
            self.api.ensure_panel().sync_mode()

    def _on_right(self, e):
        safe_popup_menu(self.menu, e.x_root, e.y_root)


# ---------------------------------------------------------------------------
# UI：面板
# ---------------------------------------------------------------------------
# 尺寸基础值（逻辑像素）。main() 会按 DPI 重新缩放，达成「高 DPI 屏不显小、窄屏不溢出」。
# 基础值已整体放宽：面板更宽、弹窗更高，避免「一页装不下/字太小看不清」。
_PANEL_W_BASE = 400
_PANEL_H_BASE = 600
_SETTINGS_W_BASE = 440
_SETTINGS_H_BASE = 580
_EDITOR_W_BASE = 400
_EDITOR_H_BASE = 430
_CATEGORY_W_BASE = 360
_CATEGORY_H_BASE = 175
PANEL_W = _PANEL_W_BASE
PANEL_H = _PANEL_H_BASE
SETTINGS_W = _SETTINGS_W_BASE
SETTINGS_H = _SETTINGS_H_BASE
EDITOR_W = _EDITOR_W_BASE
EDITOR_H = _EDITOR_H_BASE
CATEGORY_W = _CATEGORY_W_BASE
CATEGORY_H = _CATEGORY_H_BASE
HEADER_H = 48
SEP_H = 1
CAT_BAR_H = 34
TIP_H = 30
SEARCH_H = 56
FOOTER_H = 60

# 统一视觉 token（主席团规格 v14）：近黑底 + 明度分层 + 极淡发丝描边。
# 旧键保留以便逐组件迁移；新键语义清晰，后续组件优先用新键。
COLORS = {
    # —— 旧键（向后兼容，值已统一为新规范）——
    "bg": "#0d1117", "card": "#161b26", "line": "#2a3242",
    "text": "#e6e9f2", "muted": "#9aa3b8", "accent1": "#7c6cff", "accent2": "#a06bff",
    "input_bg": "#1c2230", "danger_bg": "#2a1518", "danger_fg": "#ff6b6b",
    "success_flash": "#1f7a44",
    # —— 新 token（语义分层，推荐）——
    "surface0": "#0d1117",   # 画布底（近黑带蓝调，非纯黑）
    "surface1": "#161b26",   # 卡片 / 面板
    "surface2": "#1c2230",   # 悬浮 / 输入
    "surface3": "#0a0d14",   # 按压 / 激活（比画布更暗，模拟下沉）
    "hairline": "#2a3242",   # 发丝描边（≈ rgba(255,255,255,.06)）
    "text2": "#9aa3b8",      # 次 / 弱文字
    "text3": "#5a6276",      # 禁用 / 极弱
    "accent": "#7c6cff",     # 品牌紫（强调）
    "accent2": "#a06bff",    # 强调悬浮
    "danger": "#ff6b6b",     # 危险文字
    "success": "#43c98a",    # 成功
}

# 间距（4/8/12/16）与圆角（6/12/16/pill），统一所有组件的内边距与边角。
SP = {"xs": 4, "sm": 8, "md": 12, "lg": 16}
R = {"sm": 6, "md": 12, "lg": 16, "pill": 9999}

# 统一设计 token：字号分级 + 按钮尺寸规范（消除散落不一致）。
# main() 会按 DPI 重新缩放字号与内边距，达成「高 DPI 屏不显小」。
FONT_TITLE = ["Microsoft YaHei UI", 12, "bold"]
FONT_BODY  = ["Microsoft YaHei UI", 10]
FONT_SMALL = ["Microsoft YaHei UI", 9]
FONT_TINY  = ["Microsoft YaHei UI", 8]
BTN_PADX = 14
BTN_PADY = 8
BTN_PADY_SM = 6
FONT_EMPH = ["Microsoft YaHei UI", 10, "bold"]

# 圆角体系（frontend-mastery 纪律：全页一套圆角，不混 sharp/soft/pill 多套）
RADIUS_SM = 6     # 小按钮 / 图标圆键 / 搜索清除
RADIUS_MD = 8     # 主按钮 / 页脚按钮 / 弹窗按钮
RADIUS_LG = 12    # 弹窗 / 卡片
RADIUS_PILL = 13  # 分类标签（药丸状，高≈26 → 两端半圆）


def _apply_ui_scale(scale):
    """按 DPI 缩放所有尺寸/字号/内边距，让面板在高分屏上也能舒适阅读。"""
    global PANEL_W, PANEL_H, SETTINGS_W, SETTINGS_H, EDITOR_W, EDITOR_H, CATEGORY_W, CATEGORY_H
    global HEADER_H, CAT_BAR_H, TIP_H, FOOTER_H, SEARCH_H, BTN_PADX, BTN_PADY, BTN_PADY_SM
    global RADIUS_SM, RADIUS_MD, RADIUS_LG, RADIUS_PILL
    s = max(1.0, scale)
    PANEL_W = int(_PANEL_W_BASE * s)
    PANEL_H = int(_PANEL_H_BASE * s)
    SETTINGS_W = int(_SETTINGS_W_BASE * s)
    SETTINGS_H = int(_SETTINGS_H_BASE * s)
    EDITOR_W = int(_EDITOR_W_BASE * s)
    EDITOR_H = int(_EDITOR_H_BASE * s)
    CATEGORY_W = int(_CATEGORY_W_BASE * s)
    CATEGORY_H = int(_CATEGORY_H_BASE * s)
    HEADER_H = int(48 * s)
    CAT_BAR_H = int(34 * s)
    TIP_H = int(30 * s)
    SEARCH_H = int(56 * s)
    FOOTER_H = int(60 * s)
    BTN_PADX = int(14 * s)
    BTN_PADY = int(8 * s)
    BTN_PADY_SM = int(6 * s)
    FONT_TITLE[1] = max(11, int(12 * s))
    FONT_BODY[1]  = max(10, int(10 * s))
    FONT_SMALL[1] = max(9,  int(9 * s))
    FONT_TINY[1]  = max(8,  int(8 * s))
    FONT_EMPH[1]  = max(10, int(10 * s))
    RADIUS_SM   = max(4, int(6 * s))
    RADIUS_MD   = max(6, int(8 * s))
    RADIUS_LG   = max(8, int(12 * s))
    RADIUS_PILL = max(8, int(13 * s))

# 悬浮态：提亮一档（明度层 +1）；按压态：压暗一档（明度层 -1 / 下沉）。
_HOVER_MAP = {
    "#7c6cff": "#a06bff",   # accent  -> accent2
    "#2a3242": "#3a4150",   # hairline/line -> 更亮 line
    "#161b26": "#1c2230",   # card  -> surface2
    "#2a1518": "#5a2a2a",   # danger_bg -> 亮红
    "#1c2230": "#2a3242",   # input_bg -> line
}
_ACTIVE_MAP = {
    "#161b26": "#0a0d14",   # card    -> surface3（下沉）
    "#2a3242": "#0a0d14",   # line    -> surface3
    "#1c2230": "#0a0d14",   # input_bg-> surface3
    "#7c6cff": "#5b4fd6",   # accent  -> 暗紫
    "#a06bff": "#5b4fd6",   # accent2 -> 暗紫
    "#2a1518": "#1a0d10",   # danger  -> 更暗红
}

def bind_states(w, default, hover, active, ring=True):
    """统一 5 态状态机（主席团规格 · 马斯克方案）：default / hover / active(按下) /
    focus(聚焦环) / Return·Space 触发。零依赖、无常驻循环；幂等：Enter→Leave→
    Press 必回确定态。聚焦环零成本：highlightthickness=1 + hairline，focus 时 accent。"""
    w._pressed = False

    def _enter(e):
        if not w._pressed:
            w.config(bg=hover)

    def _leave(e):
        w._pressed = False
        w.config(bg=default)

    def _press(e):
        w._pressed = True
        w.config(bg=active)

    def _release(e):
        w._pressed = False
        w.config(bg=hover)

    w.bind("<Enter>", _enter)
    w.bind("<Leave>", _leave)
    w.bind("<ButtonPress-1>", _press)
    w.bind("<ButtonRelease-1>", _release)
    if ring:
        try:
            w.config(highlightthickness=1, highlightbackground=COLORS["hairline"])
            w.bind("<FocusIn>", lambda e: w.config(highlightcolor=COLORS["accent"]))
            w.bind("<FocusOut>", lambda e: w.config(highlightcolor=COLORS["hairline"]))
        except Exception:
            pass


def bind_hover(w, hover=None, active=None):
    """向后兼容包装：调用统一状态机 bind_states。hover/active 不传则按当前 bg 查亮阶/暗阶。"""
    base = w.cget("bg")
    hv = hover if hover is not None else _HOVER_MAP.get(base, base)
    act = active if active is not None else _ACTIVE_MAP.get(base, base)
    bind_states(w, base, hv, act, ring=True)


class FSRButton(tk.Canvas):
    """圆角按钮（零依赖，Canvas 自绘）。统一 5 态 + 按下下沉 1px 触感。
    frontend-mastery 纪律：全页一套圆角体系；:active 用 translateY(1px) 下沉。
    尺寸自适应：pack/grid fill 时按实际宽高重画，文字始终居中。circle=True 画正圆图标键。"""
    def __init__(self, parent, text="", radius=RADIUS_MD, default=COLORS["surface2"],
                 fg=COLORS["text"], hover=None, active=None, font=FONT_BODY,
                 command=None, padx=12, pady=7, circle=False, focus_ring=True,
                 takefocus=True, **kw):
        self._text = text
        self._radius = radius
        self._default = default
        self._hoverc = hover if hover is not None else _HOVER_MAP.get(default, default)
        self._activec = active if active is not None else _ACTIVE_MAP.get(default, default)
        self._fg = fg
        self._font = font
        # 关键修复：Canvas.create_text 不认字体列表，必须传 Font 对象；否则回退默认大字体导致文字撑爆
        self._tkfont = tkfont.Font(font=font)
        self._command = command
        self._circle = circle
        self._padx = padx
        self._pady = pady
        self._focus_ring = focus_ring
        self._pressed = False
        self._hovering = False
        self._focus = False
        self._last = default
        try:
            f = tkfont.Font(font=font)
            tw = f.measure(text)
            th = f.metrics("linespace")
        except Exception:
            tw, th = max(1, len(text)) * 8, 16
        if circle:
            # 正圆图标键：用正方形，尺寸以字高为准并留足边距，避免符号字体量偏差导致溢出
            size = max(30, int(th) + pady * 2 + 8)
            mw = mh = size
        else:
            mw = max(28, int(tw) + padx * 2)
            mh = max(24, int(th) + pady * 2)
        # 关键修复：画布 bg 设为按钮默认色 → 圆角外 1px 边/四角透出默认色而非系统浅灰（白边根因）
        super().__init__(parent, width=mw, height=mh, bg=default, highlightthickness=0, bd=0,
                         cursor="hand2", takefocus=takefocus, **kw)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Configure>", self._on_configure)
        if focus_ring:
            self.bind("<FocusIn>", lambda e: (setattr(self, "_focus", True), self._redraw(self._current())))
            self.bind("<FocusOut>", lambda e: (setattr(self, "_focus", False), self._redraw(self._current())))
        if command:
            self.bind("<Return>", self._on_key)
            self.bind("<space>", self._on_key)

    def _current(self):
        if self._pressed:
            return self._activec
        return self._hoverc if self._hovering else self._default

    def _on_enter(self, e):
        self._hovering = True
        self._redraw(self._current())

    def _on_leave(self, e):
        self._hovering = False
        self._pressed = False
        self._redraw(self._default)

    def _on_press(self, e):
        self._pressed = True
        self._redraw(self._activec)

    def _on_release(self, e):
        if self._pressed:
            self._pressed = False
            self._redraw(self._hoverc if self._hovering else self._default)
            if self._command:
                self._command()

    def _on_key(self, e):
        if self._command:
            self._command()
        return "break"

    def _on_configure(self, e):
        self._redraw(self._last)

    def _redraw(self, fill):
        self._last = fill
        self.delete("all")
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 2 or h < 2:
            return
        dy = 1 if self._pressed else 0  # 按下下沉 1px 触感
        r = self._radius
        if self._circle:
            r = min(w, h) // 2
        # 圆角矩形铺满整块画布；画布 bg=默认色，故圆角外边/四角与填充同色 → 无白边、与背景贴合
        self._round_rect(0, 0, w, h, r, fill)
        if self._focus_ring and self._focus:
            self._round_rect(1.5, 1.5 + dy, w - 3, h - 3, max(2, r - 1), None,
                             outline=COLORS["accent"], width=1.5)
        self.create_text(w // 2, h // 2 + dy, text=self._text, fill=self._fg,
                         font=self._tkfont, anchor="center")

    def _round_rect(self, x, y, w, h, r, fill, outline=None, width=0):
        r = min(r, w // 2, h // 2)
        if r <= 0:
            self.create_rectangle(x, y, x + w, y + h, fill=fill, outline=outline or fill, width=width)
            return
        self.create_arc(x, y, x + 2 * r, y + 2 * r, start=90, extent=90, style="pieslice", fill=fill, outline=fill)
        self.create_arc(x + w - 2 * r, y, x + w, y + 2 * r, start=0, extent=90, style="pieslice", fill=fill, outline=fill)
        self.create_arc(x, y + h - 2 * r, x + 2 * r, y + h, start=180, extent=90, style="pieslice", fill=fill, outline=fill)
        self.create_arc(x + w - 2 * r, y + h - 2 * r, x + w, y + h, start=270, extent=90, style="pieslice", fill=fill, outline=fill)
        self.create_rectangle(x + r, y, x + w - r, y + h, fill=fill, outline=fill)
        self.create_rectangle(x, y + r, x + w, y + h - r, fill=fill, outline=fill)
        if outline and width:
            self.create_line(x + r, y, x + w - r, y, fill=outline, width=width)
            self.create_line(x + r, y + h, x + w - r, y + h, fill=outline, width=width)
            self.create_line(x, y + r, x, y + h - r, fill=outline, width=width)
            self.create_line(x + w, y + r, x + w, y + h - r, fill=outline, width=width)
            self.create_arc(x, y, x + 2 * r, y + 2 * r, start=90, extent=90, style="arc", outline=outline, width=width)
            self.create_arc(x + w - 2 * r, y, x + w, y + 2 * r, start=0, extent=90, style="arc", outline=outline, width=width)
            self.create_arc(x, y + h - 2 * r, x + 2 * r, y + h, start=180, extent=90, style="arc", outline=outline, width=width)
            self.create_arc(x + w - 2 * r, y + h - 2 * r, x + w, y + h, start=270, extent=90, style="arc", outline=outline, width=width)

    # 供分类标签等动态切换选中态
    def set_colors(self, default=None, fg=None, hover=None, active=None):
        if default is not None:
            self._default = default
        if fg is not None:
            self._fg = fg
        if hover is not None:
            self._hoverc = hover
        if active is not None:
            self._activec = active
        self._redraw(self._current())



def center_on_window(win, parent=None):
    """相对父窗口居中（父窗口不存在时回退屏幕居中），并夹在屏幕内。
    用于 overrideredirect 弹窗：避免浮在远离悬浮窗的位置、且保证可见。"""
    win.update_idletasks()
    w = win.winfo_width()
    h = win.winfo_height()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    if parent:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
    else:
        x = (sw - w) // 2
        y = (sh - h) // 2
    x = max(0, min(x, sw - w))
    y = max(0, min(y, sh - h))
    win.geometry("+%d+%d" % (x, y))


class SnippetItem(tk.Frame):
    """一条常用语：左 = 可点文本（点击即复制）；右 = 固定操作列（编辑/删除）。
    关键修复（用户反馈右侧按钮显示不全）：右侧操作列用固定宽 grid 列，
    文本再长也绝不挤压/遮挡按钮；文本换行宽度随条目实际宽度自适应，
    不再依赖外部传入的固定 wrap 值（旧值取了整画布宽，长文本会盖住按钮）。"""
    _ACT_W = 30  # 每个操作按钮列最小宽（px），固定 → 永远完整可见

    def __init__(self, parent, snip, on_click, on_edit, on_delete, wraplength=220, **kw):
        super().__init__(parent, bg=COLORS["card"], highlightbackground=COLORS["line"],
                         highlightthickness=1, **kw)
        self.snip = snip
        self.on_click = on_click
        self.on_edit = on_edit
        self.on_delete = on_delete
        self._hovered = False

        # 三列：0 文本(占满) | 1 编辑(固定) | 2 删除(固定)。操作列永不收缩。
        self.columnconfigure(0, weight=1, minsize=40)
        self.columnconfigure(1, weight=0, minsize=self._ACT_W)
        self.columnconfigure(2, weight=0, minsize=self._ACT_W)

        self.lbl = tk.Label(self, text=snip["content"], bg=COLORS["card"], fg=COLORS["text"],
                            font=FONT_BODY, anchor="w", justify="left",
                            wraplength=wraplength, padx=10, pady=8, cursor="hand2")
        self.lbl.grid(row=0, column=0, sticky="nsew")
        self.lbl.bind("<Button-1>", lambda e: self.flash(self.on_click(self.snip) == "ok"))

        # 左侧 2px 强调竖条：默认隐藏（与栏底同色），悬浮/选中才转 accent（清晰「当前行」定位）
        self.accent_bar = tk.Frame(self, bg=COLORS["line"], width=2)
        self.accent_bar.place(relx=0.0, rely=0.0, relheight=1.0, anchor="nw")

        # 操作列左侧加一道极淡分隔线，强化「这是操作区」的独立感，把文本与按钮清楚隔开
        self.divider = tk.Frame(self, bg=COLORS["line"], width=1)
        self.divider.place(relx=1.0, rely=0.12, relheight=0.76, anchor="e",
                           x=-(2 * self._ACT_W) - 1)

        self.btn_edit = FSRButton(self, text="✎", radius=RADIUS_SM,
                                  default=COLORS["card"], fg=COLORS["muted"],
                                  hover=COLORS["surface2"], active=COLORS["surface3"],
                                  font=("Segoe UI Symbol", 13), padx=4, pady=2,
                                  focus_ring=False, takefocus=False,
                                  command=lambda: self.on_edit(self.snip))
        self.btn_edit.grid(row=0, column=1, sticky="nsew")
        self.btn_del = FSRButton(self, text="✕", radius=RADIUS_SM,
                                 default=COLORS["card"], fg=COLORS["danger_fg"],
                                 hover=COLORS["danger_bg"], active=COLORS["danger_bg"],
                                 font=("Segoe UI Symbol", 13), padx=4, pady=2,
                                 focus_ring=False, takefocus=False,
                                 command=lambda: self.on_delete(self.snip))
        self.btn_del.grid(row=0, column=2, sticky="nsew")

        # 整行悬浮态：文本区 + 操作列一起提亮到 surface2，并显示左侧 accent 竖条。
        # 同时绑 self 与 lbl：指针在子部件间移动时靠「最后事件」归位，避免闪烁。
        for w in (self, self.lbl):
            w.bind("<Enter>", lambda e: (setattr(self, "_hovered", True), self._hover(True)))
            w.bind("<Leave>", lambda e: (setattr(self, "_hovered", False), self._hover(False)))
        # 条目宽度变化时，文本换行宽度跟着自适应（长文本不再溢出到按钮区）
        self.bind("<Configure>", lambda e: self._fit_wrap())

    def _fit_wrap(self):
        try:
            # 可用宽度 = 条目宽 − 两个操作列 − 文本左右内边距
            avail = self.winfo_width() - 2 * self._ACT_W - 20
            if avail >= 80:
                self.lbl.config(wraplength=avail)
        except Exception:
            pass

    def _hover(self, active):
        col = COLORS["surface2"] if active else COLORS["card"]
        self.config(bg=col)
        try:
            self.lbl.config(bg=col)
        except Exception:
            pass
        # 左侧 accent 竖条：悬浮显 accent、否则隐藏（与栏底同色）
        try:
            self.accent_bar.config(bg=COLORS["accent"] if active else COLORS["line"])
        except Exception:
            pass
        # 分隔线始终保持 line 色，作为操作区边界
        try:
            self.divider.config(bg=COLORS["line"])
        except Exception:
            pass

    def flash(self, ok=True):
        """复制反馈：整行闪一下成功/失败色，绝不弹窗遮挡删除键。"""
        try:
            col = COLORS["success_flash"] if ok else COLORS["danger_bg"]
            self.config(bg=col)
            try:
                self.lbl.config(bg=col)
            except Exception:
                pass
            for w in (self.btn_edit, self.btn_del):
                try:
                    w.config(bg=col)
                except Exception:
                    pass
            try:
                self.accent_bar.config(bg=col)
            except Exception:
                pass
            try:
                self.divider.config(bg=col)
            except Exception:
                pass
            # 650ms 后按当前是否悬浮恢复原色
            self.after(650, lambda: self._hover(self._hovered))
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

        # 顶层 grid：footer 用 minsize 钉死，列表 row weight=1 占满余量 → 页脚永远可见
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, minsize=HEADER_H)
        self.rowconfigure(1, minsize=SEP_H)
        self.rowconfigure(2, minsize=CAT_BAR_H)
        self.rowconfigure(3, minsize=SEARCH_H)  # 搜索框行
        self.rowconfigure(4, weight=1)          # 列表占满剩余空间
        self.rowconfigure(5, minsize=FOOTER_H)  # 页脚永远在底部

        self._items = []    # 列表项（供键盘导航）
        self._sel = -1      # 当前选中项索引

        header = tk.Frame(self, bg=COLORS["card"], height=HEADER_H, cursor="fleur")
        header.grid(row=0, column=0, sticky="ew")
        header.pack_propagate(False)
        tk.Label(header, text="FloatSnip  ▸ 可拖动", bg=COLORS["card"], fg=COLORS["text"],
                 font=FONT_TITLE).pack(side="left", padx=14)
        gear_btn = FSRButton(header, text="⚙", radius=RADIUS_SM, circle=True,
                             default=COLORS["card"], fg=COLORS["muted"],
                             hover=COLORS["surface2"], active=COLORS["surface3"],
                             font=("Segoe UI Symbol", 14), padx=6, pady=2,
                             focus_ring=False, takefocus=False, command=self.open_settings)
        gear_btn.pack(side="right", padx=6)
        close_btn = FSRButton(header, text="✕", radius=RADIUS_SM, circle=True,
                              default=COLORS["card"], fg=COLORS["danger_fg"],
                              hover=COLORS["danger_bg"], active=COLORS["danger_bg"],
                              font=("Segoe UI Symbol", 14), padx=6, pady=2,
                              focus_ring=False, takefocus=False, command=self.close_panel)
        close_btn.pack(side="right", padx=12)
        sep = tk.Frame(self, bg=COLORS["line"], height=SEP_H)
        sep.grid(row=1, column=0, sticky="ew")

        header.bind("<ButtonPress-1>", self._hdr_press)
        header.bind("<B1-Motion>", self._hdr_motion)

        # 分类标签 —— Canvas 横向可滚；两侧 ‹ › 悬浮箭头按钮：点左滑左、点右滑右
        cat_bar = tk.Frame(self, bg=COLORS["bg"])
        cat_bar.grid(row=2, column=0, sticky="ew", padx=8, pady=(8, 0))
        self.cat_left = FSRButton(cat_bar, text="‹", radius=RADIUS_SM, circle=True,
                                  default=COLORS["bg"], fg=COLORS["muted"],
                                  hover=COLORS["surface2"], active=COLORS["surface3"],
                                  font=("Segoe UI Symbol", 13), padx=4, pady=2,
                                  focus_ring=False, takefocus=False,
                                  command=lambda: self._cat_scroll(-1))
        self.cat_left.pack(side="left")
        self.cat_canvas = tk.Canvas(cat_bar, bg=COLORS["bg"], height=32, highlightthickness=0, bd=0)
        self.cat_canvas.pack(side="left", fill="x", expand=True, padx=2)
        self.cat_canvas.configure(xscrollincrement=1)  # 横向滚动以 1px 为步长，保证顺滑
        self.cat_frame = tk.Frame(self.cat_canvas, bg=COLORS["bg"])
        self._cat_win = self.cat_canvas.create_window((0, 0), window=self.cat_frame, anchor="nw")
        self.cat_canvas.bind("<Configure>", lambda e: self._on_cat_configure())
        self.cat_canvas.bind("<MouseWheel>", self._on_cat_wheel)
        self.cat_canvas.bind("<Shift-MouseWheel>", self._on_cat_wheel)  # 触控板横滑也走同一逻辑
        self.cat_right = FSRButton(cat_bar, text="›", radius=RADIUS_SM, circle=True,
                                   default=COLORS["bg"], fg=COLORS["muted"],
                                   hover=COLORS["surface2"], active=COLORS["surface3"],
                                   font=("Segoe UI Symbol", 13), padx=4, pady=2,
                                   focus_ring=False, takefocus=False,
                                   command=lambda: self._cat_scroll(1))
        self.cat_right.pack(side="left")
        # 分类创建入口收敛到此处：固定「＋ 新建」始终可见（不再在页脚/设置里重复出现）
        self.cat_add = FSRButton(cat_bar, text="＋ 新建分类", radius=RADIUS_PILL,
                                 default=COLORS["bg"], fg=COLORS["muted"],
                                 hover=COLORS["surface2"], active=COLORS["surface3"],
                                 font=FONT_SMALL, padx=10, pady=4,
                                 focus_ring=False, takefocus=False,
                                 command=self.open_new_category)
        self.cat_add.pack(side="left", padx=(6, 0))
        self.cat_right.bind("<Leave>", lambda e: self._refresh_arrows())
        self.cat_buttons = {}
        # 记忆当前分类：重启后停留在上次选中的分类（'all' 或某一分类 id）
        self.active_cat = api.data["settings"].get("active_cat", "all")
        if not any(c["id"] == self.active_cat for c in api.data["categories"]):
            self.active_cat = "all"

        # 搜索框（P0-A）：输入即跨分类即时筛选，纯前端过滤、不动数据层
        search_frame = tk.Frame(self, bg=COLORS["bg"])
        search_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 2))
        # 外层 surface2 容器 + 发丝描边，包裹「输入框 + 清除键」，统一输入框观感
        search_box = tk.Frame(search_frame, bg=COLORS["surface2"],
                              highlightthickness=1, highlightbackground=COLORS["hairline"])
        search_box.pack(fill="x")
        self.search_var = tk.StringVar()
        self.search_ent = tk.Entry(search_box, textvariable=self.search_var, bg=COLORS["surface0"],
                                   fg=COLORS["text"], insertbackground=COLORS["text"],
                                   font=FONT_BODY, bd=0, relief="flat")
        self.search_ent.pack(side="left", fill="x", expand=True, ipady=BTN_PADY_SM)
        self.search_ent.bind("<Return>", lambda e: "break")  # 搜索框回车不触发面板 Enter 复制
        # 聚焦环：focus 时整框描边转 accent，失焦回 hairline（零依赖，不引模糊/阴影）
        self.search_ent.bind("<FocusIn>", lambda e: search_box.config(highlightbackground=COLORS["accent"]))
        self.search_ent.bind("<FocusOut>", lambda e: search_box.config(highlightbackground=COLORS["hairline"]))
        clear_btn = FSRButton(search_box, text="✕", radius=RADIUS_SM, circle=True,
                              default=COLORS["surface2"], fg=COLORS["muted"],
                              hover=COLORS["danger_bg"],
                              command=lambda: (self.search_var.set(""), self.search_ent.focus_set()),
                              font=("Segoe UI Symbol", 12), padx=6, pady=2,
                              focus_ring=False, takefocus=False)
        clear_btn.pack_forget()  # 默认隐藏：仅在有内容时出现
        self.clear_btn = clear_btn
        tk.Label(search_frame, text="输入即筛选 · ↑↓ 选择 · Enter 复制",
                 bg=COLORS["bg"], fg=COLORS["muted"], font=FONT_TINY, anchor="w").pack(fill="x", pady=(4, 0))
        self.search_var.trace_add("write", lambda *a: (self._on_search(), self._sync_clear_btn()))

        list_container = tk.Frame(self, bg=COLORS["bg"])
        list_container.grid(row=4, column=0, sticky="nsew", padx=12, pady=8)
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
        # 滚轮绑定到面板整体：利用 Tk 事件冒泡，鼠标在列表项/list_frame 等子部件上滚动时，
        # 未处理的 MouseWheel 会冒泡到面板触发滚动；只绑 canvas 会因 list_frame 覆盖而失效。
        self.bind("<MouseWheel>", self._on_mousewheel)
        # 键盘流：↑↓ 选择、Enter 复制、Esc 收起（焦点在输入框时让位给输入）
        self.bind("<Up>", lambda e: self._kb_nav(-1))
        self.bind("<Down>", lambda e: self._kb_nav(1))
        self.bind("<Return>", lambda e: self._kb_enter())
        self.bind("<Escape>", lambda e: self.close_panel())

        # 固定页脚：新建按钮始终可见（不再埋进滚动列表底部），长列表也能一键新建
        # 用 grid 钉死在 row=5，与顶层 grid 布局一致 → 长列表时页脚也永远留在底部
        self.footer = tk.Frame(self, bg=COLORS["bg"])
        self.footer.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 8))
        # 常驻记忆提示：让「每次操作都会永久保存」从幕后搬到台前，解决「没看出有记忆」
        mem_mark = tk.Label(self.footer, text="✓ 每次操作自动永久保存", bg=COLORS["bg"],
                            fg=COLORS["muted"], font=FONT_TINY, anchor="center")
        mem_mark.pack(fill="x", pady=(0, 4))
        btn_row = tk.Frame(self.footer, bg=COLORS["bg"])
        btn_row.pack(fill="x")
        # 一键捕获剪贴板为草稿（P0-B）—— 次级按钮：幽灵态（默认与页脚同色，悬浮才浮起）
        cap_btn = FSRButton(btn_row, text="捕获剪贴板", radius=RADIUS_MD,
                            default=COLORS["bg"], fg=COLORS["muted"],
                            hover=COLORS["surface2"], command=self._capture_clipboard)
        cap_btn.pack(side="left", padx=(0, 6))
        # 单一主创建入口：新建常用语（新建分类已收敛到分类栏右端 ＋，不再在此重复）—— 主按钮：accent 实底
        new_snip_btn = FSRButton(btn_row, text="＋ 新建常用语", radius=RADIUS_MD,
                                 default=COLORS["accent"], fg="white",
                                 command=self.open_editor)
        new_snip_btn.pack(side="left", fill="x", expand=True)
        # 清空所有数据（危险操作，二次确认；与托盘菜单一致）—— 次级 + hover 转红
        clear_btn = FSRButton(btn_row, text="清空", radius=RADIUS_MD,
                              default=COLORS["bg"], fg=COLORS["danger"],
                              hover=COLORS["danger_bg"], command=self._clear_all_panel)
        clear_btn.pack(side="left", padx=(6, 0))

        self.update_idletasks()
        set_rounded_window(get_hwnd(self), PANEL_W, PANEL_H, 16)

        self._drag = None
        self._load_cats()
        self._load_list()

        # 右键菜单（冗余关闭）
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="关闭悬浮窗", command=self.api.quit_app)
        self.menu.add_command(label="打开设置", command=self.open_settings)
        self.menu.add_command(label="回到浮球", command=self.close_panel)
        self.bind("<Button-3>", lambda e: self._safe_popup(e))

    def _safe_popup(self, e):
        safe_popup_menu(self.menu, e.x_root, e.y_root)

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
            # 每个分类 = 药丸状圆角标签；选中时整 pill 转 accent（清晰「当前位置」）
            b = FSRButton(self.cat_frame, text=c["name"], radius=RADIUS_PILL,
                          default=COLORS["bg"], fg=COLORS["text"],
                          hover=COLORS["surface2"], active=COLORS["surface3"],
                          font=FONT_SMALL, padx=10, pady=4,
                          focus_ring=False, takefocus=False)
            b.pack(side="left", padx=(0, 6))
            b.bind("<Button-1>", lambda e, cid=c["id"]: self._set_cat(cid))
            self.cat_buttons[c["id"]] = b
        self._refresh_cat_style()
        # 更新横向滚动区域：按钮全 pack 后刷新 Canvas 的 scrollregion
        self._update_cat_scroll()

    def _refresh_cat_style_one(self, cid):
        btn = self.cat_buttons.get(cid)
        if not btn:
            return
        if cid == self.active_cat:
            btn.set_colors(default=COLORS["accent"], fg="white",
                           hover=COLORS["accent2"], active=COLORS["accent2"])
        else:
            btn.set_colors(default=COLORS["bg"], fg=COLORS["text"],
                           hover=COLORS["surface2"], active=COLORS["surface3"])

    def _refresh_cat_style(self):
        for cid, btn in self.cat_buttons.items():
            if cid == self.active_cat:
                btn.set_colors(default=COLORS["accent"], fg="white",
                               hover=COLORS["accent2"], active=COLORS["accent2"])
            else:
                btn.set_colors(default=COLORS["bg"], fg=COLORS["text"],
                               hover=COLORS["surface2"], active=COLORS["surface3"])

    def _update_cat_scroll(self):
        """统一刷新分类栏横向滚动区域（内容变宽后必须重算 scrollregion 才能滚动）"""
        self.cat_frame.update_idletasks()
        self.cat_canvas.configure(scrollregion=self.cat_canvas.bbox("all"))
        self._refresh_arrows()

    def _on_cat_configure(self):
        """Canvas 尺寸变化时更新横向滚动区域"""
        self._update_cat_scroll()

    def _on_cat_wheel(self, e):
        """鼠标悬停分类栏：纵向滚轮转为横向滚动；内容未溢出时交给列表做纵向滚动"""
        self._update_cat_scroll()
        bbox = self.cat_canvas.bbox("all")
        if not bbox:
            return
        content_w = bbox[2] - bbox[0]
        if content_w <= self.cat_canvas.winfo_width():
            return  # 没溢出：不拦截，滚轮继续冒泡到列表做纵向滚动
        # xscrollincrement=1 使 units=1px，按 delta 比例像素级平滑横滚（每格约 40px）
        self.cat_canvas.xview_scroll(-e.delta // 3, "units")
        self._refresh_arrows()
        return "break"

    def _cat_scroll(self, direction):
        """点击 ‹ / › 箭头：direction=-1 左滑，+1 右滑（按可视宽度约 1/3 步进）"""
        self._update_cat_scroll()
        bbox = self.cat_canvas.bbox("all")
        if not bbox:
            return
        if bbox[2] - bbox[0] <= self.cat_canvas.winfo_width():
            return
        step = max(40, self.cat_canvas.winfo_width() // 3)
        self.cat_canvas.xview_scroll(direction * step, "units")
        self._refresh_arrows()

    def _refresh_arrows(self):
        """无溢出时箭头变灰；到左/右边缘时对应箭头变灰（不可再滑）"""
        bbox = self.cat_canvas.bbox("all")
        overflow = bbox and (bbox[2] - bbox[0]) > self.cat_canvas.winfo_width()
        if not overflow:
            self.cat_left.config(fg=COLORS["muted"])
            self.cat_right.config(fg=COLORS["muted"])
            return
        frac = self.cat_canvas.xview()
        self.cat_left.set_colors(fg=COLORS["muted"] if frac[0] <= 0.001 else COLORS["text"])
        self.cat_right.set_colors(fg=COLORS["muted"] if frac[1] >= 0.999 else COLORS["text"])

    def _set_cat(self, cid):
        self.active_cat = cid
        self._refresh_cat_style()
        self.api.set_active_cat(cid)   # 每次切换分类即时落盘（记忆）
        self._load_list()
        # 若选中分类的按钮在画布可视区外，水平滚到可见位置
        btn = self.cat_buttons.get(cid)
        if btn:
            self.cat_canvas.update_idletasks()
            bx = btn.winfo_x()
            bw = btn.winfo_reqwidth()
            cvw = self.cat_canvas.winfo_width()
            if bx + bw > cvw or bx < 0:
                # 目标按钮偏右：滚到目标右边缘对齐画布右边缘
                frac = self.cat_canvas.bbox("all")
                if frac and frac[2] > cvw:
                    target = max(0, bx - cvw // 2)
                    self.cat_canvas.xview_moveto(target / frac[2] if frac[2] else 0)
        self._refresh_arrows()

    def _load_list(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        self.canvas.yview_moveto(0)
        self._items = []
        self._sel = -1
        kw = (self.search_var.get() if hasattr(self, "search_var") else "").strip().lower()
        items = [s for s in self.api.data["snippets"]
                 if (self.active_cat == "all" or s["category"] == self.active_cat)
                 and (not kw or kw in s["content"].lower())]
        if not items:
            msg = ("没有匹配的常用语" if kw else "这里还没有常用语\n点下方「＋ 新建常用语」添加第一条")
            tk.Label(self.list_frame, text=msg, bg=COLORS["bg"], fg=COLORS["muted"], font=FONT_BODY).pack(pady=(20, 10))
        else:
            # 动态计换行宽度：Canvas 实际宽 − 操作列与内边距，自适应面板尺寸与 DPI
            # （更精确的值会在每条目 <Configure> 时由 SnippetItem._fit_wrap 自适应校正）
            cw = self.canvas.winfo_width()
            wrap = max(160, cw - 80) if cw > 1 else 240
            for s in items:
                it = SnippetItem(self.list_frame, s, self._on_copy, self._on_edit, self._on_delete, wraplength=wrap)
                it.pack(fill="x", pady=(0, 6))
                self._items.append(it)
        self.list_frame.update_idletasks()
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_mousewheel(self, e):
        self.canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        return "break"

    def _on_search(self):
        try:
            self._load_list()
        except Exception:
            pass

    def _sync_clear_btn(self):
        """清除键仅在有内容时出现（零依赖，不引常驻循环）。"""
        try:
            if self.search_var.get():
                self.clear_btn.pack(side="right")
            else:
                self.clear_btn.pack_forget()
        except Exception:
            pass

    # ---- 键盘流（↑↓ 选择 · Enter 复制 · Esc 收起）----
    def _kb_nav(self, delta):
        try:
            if isinstance(self.focus_get(), tk.Entry):
                return
        except Exception:
            pass
        self._move_sel(delta)
        return "break"

    def _kb_enter(self):
        try:
            if isinstance(self.focus_get(), tk.Entry):
                return
        except Exception:
            pass
        self._copy_sel()
        return "break"

    def _move_sel(self, delta):
        if not self._items:
            return
        n = len(self._items)
        nxt = max(0, min(n - 1, (self._sel if self._sel >= 0 else -1) + delta))
        self._set_sel(nxt)

    def _set_sel(self, idx):
        if 0 <= self._sel < len(self._items):
            try:
                self._items[self._sel]._hover(False)
            except Exception:
                pass
        self._sel = idx
        if 0 <= idx < len(self._items):
            it = self._items[idx]
            try:
                it._hover(True)
            except Exception:
                pass
            try:
                y = it.winfo_y()
                h = self.canvas.winfo_height()
                if y < 0 or y + it.winfo_height() > h:
                    self.canvas.yview_moveto(max(0.0, y / max(1, self.list_frame.winfo_height())))
            except Exception:
                pass

    def _copy_sel(self):
        if 0 <= self._sel < len(self._items):
            self._on_copy(self._items[self._sel].snip)

    def _on_copy(self, snip):
        res = copy_and_verify(snip["content"])
        # 复制结果返回给 SnippetItem，由条目自身闪光如实反馈（成功绿/失败红），
        # 不再用弹窗遮挡右侧删除按钮
        if res == "empty":
            self._toast("内容为空", "err")
        elif res == "mismatch":
            self._toast("复制可能失败", "err")
        elif res == "fail":
            self._toast("复制失败", "err")
        if res == "ok" and self.api.data["settings"].get("auto_paste"):
            self.root.after(120, _send_ctrl_v)
        return res

    def _toast(self, msg, kind="ok"):
        show_toast(self, msg, kind)

    def _on_edit(self, snip):
        EditorDialog(self, self.api, snip["id"], self._after_edit)

    def _on_delete(self, snip):
        # 删除悔棋：暂存被删条目，3 秒内可一键撤销（见 _show_undo）
        removed = dict(snip)
        self.api.delete_snippet(snip["id"])
        self._load_list()
        self._show_undo(removed)

    def _show_undo(self, removed):
        """删除后弹出 3 秒可撤销提示（surface1 卡 + accent 撤销胶囊 + 3s 细进度条）；超时未点则永久生效。"""
        try:
            t = tk.Toplevel(self)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            t.configure(bg=COLORS["surface1"], highlightthickness=1, highlightbackground=COLORS["hairline"])
            tk.Label(t, text="已删除 · 3 秒内可撤销", bg=COLORS["surface1"],
                     fg=COLORS["text"], font=FONT_SMALL).pack(side="left", padx=12, pady=8)

            def undo():
                try:
                    self.api.restore_snippet(removed)
                    self._load_list()
                    self._toast("已撤销删除", "ok")
                except Exception:
                    pass
                try:
                    t.destroy()
                except Exception:
                    pass

            b = FSRButton(t, text="撤销", radius=RADIUS_MD,
                          default=COLORS["accent"], fg="white", command=undo,
                          font=FONT_SMALL, padx=12, pady=4)
            b.pack(side="left", padx=(0, 12), pady=8)
            t.update_idletasks()
            try:
                set_rounded_window(get_hwnd(t), t.winfo_width(), t.winfo_height(), 8)
            except Exception:
                pass
            # 3s 进度条（细，accent）：随卡片 3s 后销毁，提示撤销窗口
            bar = tk.Frame(t, bg=COLORS["accent"], height=2)
            bar.pack(side="bottom", fill="x")
            px, py = self.winfo_x(), self.winfo_y()
            t.geometry("+%d+%d" % (px + 12, py + self.winfo_height() - t.winfo_height() - 14))
            t.after(3000, lambda: t.destroy())
        except Exception:
            pass

    def _capture_clipboard(self):
        """一键捕获：把当前剪贴板内容存为当前分类的新常用语（草稿）。"""
        txt = read_clipboard()
        if not txt or not txt.strip():
            self._toast("剪贴板为空，未捕获", "err")
            return
        cat = self.active_cat if self.active_cat != "all" else "c1"
        r = self.api.save_snippet(None, txt.strip(), cat)
        if not r["ok"]:
            self._toast(r.get("msg", "捕获失败"), "err")
            return
        self._load_list()
        self._toast("已捕获剪贴板 ✓", "ok")

    def _clear_all_panel(self):
        if not messagebox.askyesno("清空所有数据", "将删除全部常用语与自定义分类（不可恢复），确定？"):
            return
        self.api.clear_all()
        self._load_cats()
        self._load_list()
        self._toast("已清空所有数据", "ok")

    def open_editor(self):
        EditorDialog(self, self.api, None, self._after_edit, default_cat=self.active_cat)

    def open_new_category(self):
        def done(name):
            r = self.api.add_category(name)
            if not r["ok"]:
                self._toast(r.get("msg", "创建失败"), "err")
                return
            # 切到新建的分类并刷新，确保用户立刻能看到新分类
            new_id = r.get("id") or r["state"]["categories"][-1]["id"]
            self.active_cat = new_id
            self._load_cats()
            self._set_cat(new_id)
            # 自动滚到右侧让新分类可见（新建的分类总是加在最右边）
            self.cat_canvas.update_idletasks()
            self.cat_canvas.xview_moveto(1.0)
            self._toast("已新建分类 ✓", "ok")
        CategoryDialog(self, self.api, done, "新建分类")

    def _after_edit(self, saved):
        if saved:
            self._load_cats()
            self._load_list()

    def open_settings(self):
        SettingsDialog(self, self.api, self._after_settings)

    def _after_settings(self):
        self._load_cats()
        self._load_list()

    _memory_announced = False  # 一进程只播报一次记忆

    def _announce_memory(self):
        """把「记忆」从幕后搬到台前：面板打开时，若有上次选中的偏好，告诉用户「已记住」。"""
        try:
            if FloatPanel._memory_announced:
                return
            cid = self.api.data["settings"].get("active_cat", "all")
            if cid == "all":
                return
            name = next((c["name"] for c in self.api.data["categories"] if c["id"] == cid), None)
            if not name:
                return
            FloatPanel._memory_announced = True
            show_toast(self, "已回到你上次选的「%s」✓" % name, "info")
        except Exception:
            pass

    _guide_seen = False  # 一进程只引导一次

    def _first_run_guide(self):
        """首屏引导：首次打开面板时，用一次轻量提示讲清核心操作（键盘流/搜索/捕获）。"""
        try:
            if FloatPanel._guide_seen:
                return
            FloatPanel._guide_seen = True
            guide = ("欢迎使用 FloatSnip ✓\n"
                     "· 顶部输入即跨分类筛选\n"
                     "· ↑↓ 选择 · Enter 复制 · Esc 收起\n"
                     "· 一键捕获剪贴板为常用语")
            show_toast(self, guide, "info", ms=4500)
        except Exception:
            pass

    def close_panel(self):
        self.api.set_active_cat(self.active_cat)  # 关闭到浮球时落盘当前分类（记忆）
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
            self._announce_memory()   # 首次显示时播报「记忆」（懒加载后也能触发）
            self._first_run_guide()   # 首屏引导（仅首次）

    def _place_near_ball(self):
        if not self.api._win:
            return
        bx = self.api._win.winfo_x()
        by = self.api._win.winfo_y()
        sw = self.winfo_screenwidth()
        gap = 20
        x = bx + BALL_SIZE + gap
        y = by
        if x + PANEL_W > sw:
            x = max(20, bx - PANEL_W - gap)
        if y + PANEL_H > self.winfo_screenheight():
            y = self.winfo_screenheight() - PANEL_H - 10
        if y < 0:
            y = 0
        self.geometry("+%d+%d" % (x, y))


# ---------------------------------------------------------------------------
# UI：编辑弹窗
# ---------------------------------------------------------------------------
class EditorDialog(tk.Toplevel):
    def __init__(self, parent, api, sid, on_done, default_cat=None):
        super().__init__(parent)
        self.parent_win = parent
        self.api = api
        self.sid = sid
        self.on_done = on_done
        self.default_cat = default_cat
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"], highlightthickness=1, highlightbackground=COLORS["hairline"])
        self.geometry("%dx%d" % (EDITOR_W, EDITOR_H))

        card = tk.Frame(self, bg=COLORS["card"])
        card.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(card, text="编辑常用语" if sid else "新建常用语", bg=COLORS["card"], fg=COLORS["text"],
                 font=FONT_TITLE).pack(anchor="w", padx=12, pady=(10, 8))

        # 关键修复：Text 固定在带滚动条的帧里（固定高度、不 expand），
        # 既避免把底部按钮挤出窗口，又让长文本片段可滚动查看（滚轮 + 右侧滚动条）。
        text_frame = tk.Frame(card, bg=COLORS["input_bg"], bd=0)
        text_frame.pack(fill="x", expand=False, padx=12, pady=(0, 8))
        self.text = tk.Text(text_frame, bg=COLORS["input_bg"], fg=COLORS["text"], insertbackground=COLORS["text"],
                            font=FONT_BODY, height=6, bd=0, padx=8, pady=8)
        self.text.pack(side="left", fill="both", expand=True)
        text_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.text.yview,
                                    style="FS.Vertical.TScrollbar")
        text_scroll.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=text_scroll.set)
        # 滚轮：直接绑在 Text 上滚动自身内容，长文本片段编辑时无需依赖外部滚动条
        self.text.bind("<MouseWheel>", lambda e: self.text.yview_scroll(int(-1 * e.delta / 120), "units"))

        self.cats = [c for c in api.data["categories"] if not c.get("fixed")]
        cats = self.cats

        # 默认选中分类：无自定义分类时回退 c1（默认分类）
        init_name = cats[0]["name"] if cats else ""
        if sid:
            for s in api.data["snippets"]:
                if s["id"] == sid:
                    self.text.insert("1.0", s["content"])
                    # 编辑时回显该条所属分类
                    for c in cats:
                        if c["id"] == s["category"]:
                            init_name = c["name"]
                            break
                    break
        elif default_cat and default_cat != "all":
            for c in cats:
                if c["id"] == default_cat:
                    init_name = c["name"]
                    break

        if cats:
            row = tk.Frame(card, bg=COLORS["card"])
            row.pack(fill="x", padx=12, pady=(0, 8))
            tk.Label(row, text="分类", bg=COLORS["card"], fg=COLORS["muted"], font=FONT_SMALL).pack(side="left")
            # 改用下拉框：分类多时不会像 Radiobutton 那样溢出窗口宽度
            self.var_cat_name = tk.StringVar(value=init_name)
            om = tk.OptionMenu(row, self.var_cat_name, *[c["name"] for c in cats])
            om.config(bg=COLORS["card"], fg=COLORS["text"], highlightthickness=0,
                      activebackground=COLORS["line"], activeforeground=COLORS["text"],
                      font=FONT_SMALL, bd=0, relief="flat")
            om["menu"].config(bg=COLORS["card"], fg=COLORS["text"],
                              activebackground=COLORS["accent1"], activeforeground="white")
            om.pack(side="left", padx=(8, 0), fill="x", expand=True)

        # 敏感内容开关：勾选后该条仅留内存、不落盘（重启即消失），用于临时口令/验证码
        self.sensitive_var = tk.BooleanVar(value=False)
        if sid:
            for s in api.data["snippets"]:
                if s["id"] == sid and s.get("sensitive"):
                    self.sensitive_var.set(True)
                    break
        chk = tk.Checkbutton(card, text="敏感内容 · 仅留内存不落盘（重启即消失）",
                             variable=self.sensitive_var, bg=COLORS["card"], fg=COLORS["muted"],
                             selectcolor=COLORS["accent1"], activebackground=COLORS["card"],
                             activeforeground=COLORS["text"], font=FONT_TINY)
        chk.pack(anchor="w", padx=12, pady=(0, 4))

        btns = tk.Frame(card, bg=COLORS["card"])
        btns.pack(fill="x", padx=12, pady=(0, 10))
        cancel = FSRButton(btns, text="取消", radius=RADIUS_MD,
                           default=COLORS["card"], fg=COLORS["text"], command=self.destroy)
        cancel.pack(side="right", padx=(6, 0))
        if sid:
            del_btn = FSRButton(btns, text="删除", radius=RADIUS_MD,
                                default=COLORS["danger_bg"], fg=COLORS["danger_fg"], command=self._delete)
            del_btn.pack(side="right", padx=(6, 0))
        save = FSRButton(btns, text="保存修改" if sid else "确认新建", radius=RADIUS_MD,
                         default=COLORS["accent"], fg="white", command=self._save)
        save.pack(side="right")

        self.update_idletasks()
        set_rounded_window(get_hwnd(self), self.winfo_width(), self.winfo_height(), 12)
        self._center()
        self.lift()
        self.focus_force()
        self.after(30, lambda: (self.lift(), self.focus_force()))
        self.bind("<Escape>", lambda e: self.destroy())  # Esc 关闭（等价取消）

    def _center(self):
        center_on_window(self, getattr(self, "parent_win", None))

    def _save(self):
        content = self.text.get("1.0", "end-1c")
        # 以下拉框当前选中的名称反查分类 id；分类重名已被后端拦截（名称唯一），反查无歧义
        cid = "c1"
        if self.cats:
            name = self.var_cat_name.get()
            for c in self.cats:
                if c["name"] == name:
                    cid = c["id"]
                    break
            else:
                # 兜底：下拉框只给合法名，理论上不会走到这里；取首个防止崩溃
                cid = self.cats[0]["id"]
        r = self.api.save_snippet(self.sid, content, cid, sensitive=self.sensitive_var.get())
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
# UI：新建分类弹窗（自建暗色对话框，替代 simpledialog）
#     修复：在 overrideredirect + 置顶父窗口下，simpledialog 模态框定位/焦点异常，
#           常导致 askstring 返回 None 而静默退出、分类建不出来。
# ---------------------------------------------------------------------------
class CategoryDialog(tk.Toplevel):
    def __init__(self, parent, api, on_done, title="新建分类"):
        super().__init__(parent)
        self.parent_win = parent
        self.api = api
        self.on_done = on_done
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.configure(bg=COLORS["bg"], highlightthickness=1, highlightbackground=COLORS["hairline"])
        self.geometry("%dx%d" % (CATEGORY_W, CATEGORY_H))

        card = tk.Frame(self, bg=COLORS["card"])
        card.pack(fill="both", expand=True, padx=10, pady=10)

        tk.Label(card, text=title, bg=COLORS["card"], fg=COLORS["text"],
                 font=FONT_TITLE).pack(anchor="w", padx=12, pady=(10, 8))

        self.ent = tk.Entry(card, bg=COLORS["input_bg"], fg=COLORS["text"],
                            insertbackground=COLORS["text"], font=FONT_BODY, bd=0)
        self.ent.pack(fill="x", padx=12, pady=(0, 10), ipady=BTN_PADY_SM)
        self.ent.focus_set()

        btns = tk.Frame(card, bg=COLORS["card"])
        btns.pack(fill="x", padx=12, pady=(0, 10))
        cancel = FSRButton(btns, text="取消", radius=RADIUS_MD,
                           default=COLORS["card"], fg=COLORS["text"], command=self.destroy)
        cancel.pack(side="right", padx=(6, 0))
        ok = FSRButton(btns, text="确认", radius=RADIUS_MD,
                       default=COLORS["accent"], fg="white", command=self._confirm)
        ok.pack(side="right")

        self.update_idletasks()
        set_rounded_window(get_hwnd(self), self.winfo_width(), self.winfo_height(), 12)
        center_on_window(self, parent)
        self.lift()
        self.focus_force()
        self.after(30, lambda: (self.lift(), self.focus_force()))
        try:
            self.transient(parent)
            # 注意：这里【刻意不调用 grab_set】。
            # 在 overrideredirect + 置顶父窗口下，grab_set 会锁死全局输入，
            # 导致输入框收不到键盘事件、「确认」无效甚至整个程序卡死。
            # 本对话框已 topmost + overrideredirect，天然浮在最上层，无需 grab 维持模态感。
        except Exception:
            pass
        self.bind("<Escape>", lambda e: self.destroy())
        self.ent.bind("<Return>", lambda e: self._confirm())

    def _confirm(self):
        name = self.ent.get().strip()
        if not name:
            # 空名：红色提示后恢复，不关闭
            self.ent.config(bg=COLORS["danger_bg"])
            self.after(600, lambda: self.ent.config(bg=COLORS["input_bg"]))
            return
        self.on_done(name)
        self.destroy()

    def _center(self):
        center_on_window(self, getattr(self, "parent_win", None))


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
        self.configure(bg=COLORS["bg"], highlightthickness=1, highlightbackground=COLORS["hairline"])
        self.geometry("%dx%d" % (SETTINGS_W, SETTINGS_H))

        card = tk.Frame(self, bg=COLORS["card"])
        card.pack(fill="both", expand=True, padx=10, pady=10)

        hdr = tk.Frame(card, bg=COLORS["card"])
        hdr.pack(fill="x", padx=12, pady=(10, 0))
        tk.Label(hdr, text="设置", bg=COLORS["card"], fg=COLORS["text"],
                 font=FONT_TITLE).pack(side="left")
        close_btn = FSRButton(hdr, text="✕", radius=RADIUS_SM, circle=True,
                              default=COLORS["card"], fg=COLORS["muted"],
                              hover=COLORS["danger_bg"], active=COLORS["danger_bg"],
                              font=("Segoe UI Symbol", 14), padx=6, pady=2,
                              focus_ring=False, takefocus=False, command=self.destroy)
        close_btn.pack(side="right")

        # 快捷键
        row = tk.Frame(card, bg=COLORS["card"])
        row.pack(fill="x", padx=12, pady=6)
        tk.Label(row, text="快捷键", bg=COLORS["card"], fg=COLORS["muted"], font=FONT_SMALL).pack(side="left")
        self.hotkey_var = tk.StringVar(value=format_hotkey_display(api.data["settings"].get("hotkey", DEFAULT_HOTKEY)))
        self.hotkey_entry = tk.Entry(row, textvariable=self.hotkey_var, bg=COLORS["input_bg"], fg=COLORS["text"],
                                     insertbackground=COLORS["text"], font=FONT_BODY, width=14, bd=0)
        self.hotkey_entry.pack(side="right", padx=(10, 0), ipady=BTN_PADY)
        self.recording = False
        self.hotkey_entry.bind("<FocusIn>", lambda e: self._start_record())
        self.hotkey_entry.bind("<FocusOut>", lambda e: self._stop_record())
        self.hotkey_entry.bind("<KeyPress>", self._on_key)
        tk.Label(card, text="快捷键用于快速唤起悬浮窗 · 点击输入框后按下组合键即可重新设置",
                 bg=COLORS["card"], fg=COLORS["muted"], font=FONT_TINY,
                 wraplength=SETTINGS_W-44, anchor="w", justify="left").pack(anchor="w", padx=12, pady=(0, 4))

        # 开关
        self.auto_paste = tk.BooleanVar(value=api.data["settings"].get("auto_paste", False))
        tk.Checkbutton(card, text="复制后自动粘贴", variable=self.auto_paste, bg=COLORS["card"], fg=COLORS["text"],
                       selectcolor=COLORS["accent1"], activebackground=COLORS["card"], activeforeground=COLORS["text"],
                       font=FONT_BODY).pack(anchor="w", padx=12, pady=4)

        self.autostart = tk.BooleanVar(value=api.data["settings"].get("autostart", True))
        tk.Checkbutton(card, text="开机自启", variable=self.autostart, bg=COLORS["card"], fg=COLORS["text"],
                       selectcolor=COLORS["accent1"], activebackground=COLORS["card"], activeforeground=COLORS["text"],
                       font=FONT_BODY).pack(anchor="w", padx=12, pady=4)

        # 分类管理（改名 + 删除；新建分类已收敛到主界面分类栏右端 ＋）
        tk.Label(card, text="分类管理", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONT_SMALL).pack(anchor="w", padx=12, pady=(10, 4))
        tk.Label(card, text="下方分类可改名；也可删除（固定分类除外）",
                 bg=COLORS["card"], fg=COLORS["muted"], font=FONT_TINY,
                 wraplength=SETTINGS_W-44, anchor="w", justify="left").pack(anchor="w", padx=12, pady=(0, 4))
        # 分类管理（改名 + 新建）—— Canvas 包裹 cat_section，分类多时纵向可滚
        cat_scroll_frame = tk.Frame(card, bg=COLORS["card"])
        cat_scroll_frame.pack(fill="x", padx=12, pady=(0, 4))
        self._cat_canvas = tk.Canvas(cat_scroll_frame, bg=COLORS["card"], height=120,
                                     highlightthickness=0, bd=0)
        self._cat_scroll = ttk.Scrollbar(cat_scroll_frame, orient="vertical",
                                         command=self._cat_canvas.yview, style="FS.Vertical.TScrollbar")
        self._cat_canvas.configure(yscrollcommand=self._cat_scroll.set)
        self._cat_scroll.pack(side="right", fill="y")
        self._cat_canvas.pack(side="left", fill="both", expand=True)
        self.cat_section = tk.Frame(self._cat_canvas, bg=COLORS["card"])
        self._cat_win_id = self._cat_canvas.create_window((0, 0), window=self.cat_section,
                                                           anchor="nw")
        self._cat_canvas.bind("<Configure>", lambda e: (
            self._cat_canvas.itemconfig(self._cat_win_id, width=e.width),
            self._cat_canvas.configure(scrollregion=self._cat_canvas.bbox("all"))
        ))
        self._cat_canvas.bind("<MouseWheel>", lambda e: self._cat_canvas.yview_scroll(
            int(-1 * (e.delta / 120)), "units"))
        self.cat_vars = {}
        self.cat_labels = {}
        self._build_cat_section()

        # 数据备份（导出/导入 JSON，与 data.json 同结构可直接还原）
        tk.Label(card, text="数据备份", bg=COLORS["card"], fg=COLORS["muted"],
                 font=FONT_SMALL).pack(anchor="w", padx=12, pady=(10, 4))
        backup_row = tk.Frame(card, bg=COLORS["card"])
        backup_row.pack(fill="x", padx=12, pady=(0, 4))
        export_btn = FSRButton(backup_row, text="导出备份", radius=RADIUS_MD,
                               default=COLORS["card"], fg=COLORS["text"],
                               command=self._export_backup, padx=BTN_PADX, pady=BTN_PADY_SM)
        export_btn.pack(side="left", padx=(0, 6))
        import_btn = FSRButton(backup_row, text="导入备份", radius=RADIUS_MD,
                               default=COLORS["card"], fg=COLORS["text"],
                               command=self._import_backup, padx=BTN_PADX, pady=BTN_PADY_SM)
        import_btn.pack(side="left")

        # 危险区：清空所有数据（二次确认，避免误触丢失）
        clear_btn = FSRButton(card, text="清空所有数据（不可恢复）", radius=RADIUS_MD,
                              default=COLORS["danger_bg"], fg=COLORS["danger_fg"],
                              command=self._clear_all, padx=BTN_PADX, pady=BTN_PADY_SM)
        clear_btn.pack(anchor="w", padx=12, pady=(10, 0))

        # 按钮
        btns = tk.Frame(card, bg=COLORS["card"])
        btns.pack(fill="x", padx=12, pady=(14, 10))
        quit_btn = FSRButton(btns, text="退出程序", radius=RADIUS_MD,
                             default=COLORS["danger_bg"], fg=COLORS["danger_fg"], command=self.api.quit_app)
        quit_btn.pack(side="left")
        cancel_btn = FSRButton(btns, text="取消", radius=RADIUS_MD,
                               default=COLORS["card"], fg=COLORS["text"], command=self.destroy)
        cancel_btn.pack(side="right", padx=(6, 0))
        save_btn = FSRButton(btns, text="保存", radius=RADIUS_MD,
                             default=COLORS["accent"], fg="white", command=self._save)
        save_btn.pack(side="right")

        self.update_idletasks()
        set_rounded_window(get_hwnd(self), self.winfo_width(), self.winfo_height(), 12)
        self._center()
        self.lift()
        self.focus_force()
        self.after(30, lambda: (self.lift(), self.focus_force()))
        self.bind("<Escape>", lambda e: self.destroy())  # Esc 关闭（等价取消）

    def _center(self):
        center_on_window(self, getattr(self, "parent_win", None))

    def _start_record(self):
        self.recording = True
        self.hotkey_var.set("按下组合键…")

    def _stop_record(self):
        if self.recording:
            self.recording = False
            if self.hotkey_var.get() == "按下组合键…":
                self.hotkey_var.set(format_hotkey_display(self.api.data["settings"].get("hotkey", DEFAULT_HOTKEY)))

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
        # Win/Super 键在 Tk 的 state 上不同 Windows 版本可能为 0x0040 或 0x0080，两种都认
        if (e.state & 0x0040) or (e.state & 0x0080):
            mods.append("win")
        key = e.keysym.lower()
        if key in ("control_l", "control_r", "alt_l", "alt_r", "shift_l", "shift_r",
                   "win_l", "win_r", "meta_l", "meta_r", "super_l", "super_r"):
            return "break"
        if key in ("grave", "asciitilde"):
            key = "`"
        parts = mods + [key]
        self.hotkey_var.set(format_hotkey_display("+".join(parts)))
        self.recording = False
        return "break"

    def _build_cat_section(self):
        for w in self.cat_section.winfo_children():
            w.destroy()
        self.cat_vars = {}
        self.cat_labels = {}
        for c in self.api.data["categories"]:
            if c.get("fixed"):
                continue
            row = tk.Frame(self.cat_section, bg=COLORS["card"])
            row.pack(fill="x", pady=2)

            name_lbl = tk.Label(row, text=c["name"], bg=COLORS["card"], fg=COLORS["text"],
                                font=FONT_BODY)
            name_lbl.pack(side="left")
            self.cat_labels[c["id"]] = name_lbl

            var = tk.StringVar(value=c["name"])
            ent = tk.Entry(row, textvariable=var, bg=COLORS["input_bg"], fg=COLORS["text"],
                           insertbackground=COLORS["text"], bd=0)
            ent.pack(side="left", fill="x", expand=True, ipady=BTN_PADY_SM, padx=6)
            self.cat_vars[c["id"]] = var

            # ✓ 确认改名 —— 按行即时生效，Label 同步更新 + 绿色闪动
            ok_btn = FSRButton(row, text="✓", radius=RADIUS_SM,
                               default=COLORS["card"], fg=COLORS["accent"],
                               hover=COLORS["accent"], active=COLORS["accent2"],
                               font=FONT_EMPH, padx=8, pady=2, focus_ring=False, takefocus=False,
                               command=lambda cid=c["id"], lbl=name_lbl, v=var, r=row, ent=ent:
                                        self._rename_one(cid, v, lbl, r, ent))
            ok_btn.pack(side="right")

            # ✗ 重置回原名
            rst_btn = FSRButton(row, text="✗", radius=RADIUS_SM,
                                default=COLORS["card"], fg=COLORS["muted"],
                                hover=COLORS["surface2"], active=COLORS["surface3"],
                                font=FONT_BODY, padx=6, pady=2, focus_ring=False, takefocus=False,
                                command=lambda v=var, old=c["name"]: v.set(old))
            rst_btn.pack(side="right")

            # 删 删除该分类（固定分类已在上方 continue 跳过）—— 二次确认后删除
            del_btn = FSRButton(row, text="删", radius=RADIUS_SM,
                                default=COLORS["card"], fg=COLORS["danger_fg"],
                                hover=COLORS["danger_bg"], active=COLORS["danger_bg"],
                                font=FONT_BODY, padx=6, pady=2, focus_ring=False, takefocus=False,
                                command=lambda cid=c["id"], name=c["name"]: self._delete_one(cid, name))
            del_btn.pack(side="right")

            # 回车同样触发改名
            ent.bind("<Return>",
                     lambda e, cid=c["id"], lbl=name_lbl, v=var, r=row, ent=ent:
                     self._rename_one(cid, v, lbl, r, ent))

    def _rename_one(self, cid, var, lbl, row, ent):
        """按行即时改名：调 API → 更新Label → 绿色闪动800ms → 恢复"""
        new_name = var.get().strip()
        # 空名：还原
        if not new_name:
            for c in self.api.data["categories"]:
                if c["id"] == cid:
                    var.set(c["name"])
                    break
            return
        r = self.api.rename_category(cid, new_name)
        if not r["ok"]:
            # 失败：保留原名
            for c in self.api.data["categories"]:
                if c["id"] == cid:
                    var.set(c["name"])
                    break
            return
        # 成功：设置框内 Label 同步 + 主界面分类栏即时同步 + 行绿色闪动 + toast
        lbl.config(text=new_name)
        try:
            self.parent_win._load_cats()  # 同步主界面顶部分类栏，避免改名后主界面还是旧名
        except Exception:
            pass
        self._flash_row(row, COLORS["card"])
        show_toast(self, "已改名 ✓", "ok")

    def _delete_one(self, cid, name):
        """删除分类：先统计该分类下常用语数量，二次确认告知用户，确认后调用后端删除并刷新"""
        count = sum(1 for s in self.api.data["snippets"] if s.get("category") == cid)
        msg = "确认删除分类「%s」？" % name
        if count:
            msg += "\n该分类下的 %d 条常用语将一并删除，且不可恢复。" % count
        else:
            msg += "\n该分类下暂无常用语。"
        if not messagebox.askyesno("删除分类", msg):
            return
        r = self.api.delete_category(cid)
        if not r["ok"]:
            messagebox.showwarning("提示", r["msg"])
            return
        self._build_cat_section()  # 重建设置区分类列表
        try:
            # 同步主界面顶部分类栏；若删掉的是当前选中分类，回退到「全部」
            if self.parent_win.active_cat == cid:
                self.parent_win.active_cat = "all"
                self.parent_win.api.set_active_cat("all")
            self.parent_win._load_cats()
            self.parent_win._load_list()
        except Exception:
            pass
        self.parent_win.after(0, lambda: show_toast(self.parent_win, "已删除分类「%s」" % name, "info"))

    def _flash_row(self, row, orig_bg):
        """行级绿色闪动反馈：绿底 → 800ms 后恢复（输入框背景不动，避免破坏暗色输入区）"""
        row.config(bg=COLORS["success_flash"])
        for child in row.winfo_children():
            if str(child.winfo_class()) == "Entry":
                continue
            try:
                child.config(bg=COLORS["success_flash"])
            except Exception:
                pass
        self.after(800, lambda: self._restore_row(row, orig_bg))

    def _restore_row(self, row, bg):
        try:
            row.config(bg=bg)
            for child in row.winfo_children():
                if str(child.winfo_class()) == "Entry":
                    continue
                child.config(bg=bg)
        except Exception:
            pass

    def _export_backup(self):
        try:
            path = filedialog.asksaveasfilename(
                title="导出 FloatSnip 备份", defaultextension=".json",
                filetypes=[("JSON 备份", "*.json"), ("所有文件", "*.*")],
                initialfile="floatsnip_backup.json")
            if not path:
                return
            ok, msg = self.api.export_backup(path)
            if not ok:
                messagebox.showwarning("导出失败", msg)
                return
            self.parent_win.after(0, lambda: show_toast(self.parent_win, "已导出备份 ✓", "ok"))
        except Exception as e:
            messagebox.showwarning("导出失败", str(e))

    def _import_backup(self):
        try:
            path = filedialog.askopenfilename(
                title="导入 FloatSnip 备份", filetypes=[("JSON 备份", "*.json"), ("所有文件", "*.*")])
            if not path:
                return
            if not messagebox.askyesno("导入备份",
                                       "导入将覆盖当前所有常用语与分类，确定继续？\n（建议先导出当前备份）"):
                return
            ok, msg = self.api.import_backup(path)
            if not ok:
                messagebox.showwarning("导入失败", msg)
                return
            self.parent_win.after(0, lambda: show_toast(self.parent_win, "已导入备份 ✓", "ok"))
            self.on_done()
            self.destroy()
        except Exception as e:
            messagebox.showwarning("导入失败", str(e))

    def _clear_all(self):
        if not messagebox.askyesno("清空所有数据",
                                   "将删除全部常用语与自定义分类（不可恢复），确定？"):
            return
        self.api.clear_all()
        self.parent_win.after(0, lambda: show_toast(self.parent_win, "已清空所有数据", "ok"))
        self.on_done()
        self.destroy()

    def _save(self):
        r = self.api.set_hotkey(self.hotkey_var.get())
        if not r["ok"]:
            messagebox.showwarning("提示", "快捷键格式不合法，已保留原设置")
            return
        if not r.get("available"):
            messagebox.showwarning("快捷键被占用",
                                    "该快捷键已被其他程序占用，已保存但无法快速唤起。\n可用系统托盘或浮球右键打开；建议换一个组合键。")
        self.api.set_auto_paste(self.auto_paste.get())
        # 持久化开机自启偏好（默认开，可在设置关闭）
        self.api.data["settings"]["autostart"] = bool(self.autostart.get())
        save_data(self.api.data)
        try:
            if self.autostart.get():
                _enable_autostart()
            else:
                _disable_autostart()
        except Exception as e:
            messagebox.showwarning("提示", "开机自启设置失败：%s" % e)
        for cid, var in self.cat_vars.items():
            self.api.rename_category(cid, var.get())
        self.parent_win.after(0, lambda: show_toast(self.parent_win, "设置已保存 ✓", "ok"))
        self.on_done()
        self.destroy()


# ---------------------------------------------------------------------------
# 系统托盘（纯 ctypes，零依赖；独立线程跑消息循环）
# ---------------------------------------------------------------------------
WM_DESTROY = 0x0002
WM_COMMAND = 0x0111
WM_USER = 0x0400
WM_TRAYICON = WM_USER + 1
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
NIM_ADD = 0
NIM_DELETE = 2
NIF_MESSAGE = 0x00000001
NIF_ICON = 0x00000002
NIF_TIP = 0x00000004
ID_TRAY = 1
MF_STRING = 0x0000
TPM_RIGHTBUTTON = 0x0002

user32.RegisterClassExW.argtypes = [ctypes.c_void_p]
user32.RegisterClassExW.restype = ctypes.c_ushort
user32.CreateWindowExW.argtypes = [ctypes.c_ulong, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_ulong,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
user32.CreateWindowExW.restype = ctypes.c_void_p
user32.DefWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p]
user32.DefWindowProcW.restype = ctypes.c_long
user32.DestroyWindow.argtypes = [ctypes.c_void_p]
user32.DestroyWindow.restype = ctypes.c_int
user32.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
user32.PostMessageW.restype = ctypes.c_int
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
user32.GetMessageW.restype = ctypes.c_int
user32.TranslateMessage.argtypes = [ctypes.c_void_p]
user32.TranslateMessage.restype = ctypes.c_int
user32.DispatchMessageW.argtypes = [ctypes.c_void_p]
user32.DispatchMessageW.restype = ctypes.c_long
user32.SetForegroundWindow.argtypes = [ctypes.c_void_p]
user32.SetForegroundWindow.restype = ctypes.c_int
user32.TrackPopupMenu.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.CreatePopupMenu.restype = ctypes.c_void_p
user32.AppendMenuW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_wchar_p]
user32.AppendMenuW.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [ctypes.c_void_p]
user32.DestroyMenu.restype = ctypes.c_int
user32.GetCursorPos.argtypes = [ctypes.c_void_p]
user32.GetCursorPos.restype = ctypes.c_int
shell32.Shell_NotifyIconW.argtypes = [ctypes.c_uint, ctypes.c_void_p]
shell32.Shell_NotifyIconW.restype = ctypes.c_int
user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.LoadIconW.restype = ctypes.c_void_p
user32.RegisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint, ctypes.c_uint]
user32.RegisterHotKey.restype = ctypes.c_int
user32.UnregisterHotKey.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.UnregisterHotKey.restype = ctypes.c_int


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p)


class WNDCLASSEX(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("style", ctypes.c_ulong),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", ctypes.c_void_p),
        ("hIcon", ctypes.c_void_p),
        ("hCursor", ctypes.c_void_p),
        ("hbrBackground", ctypes.c_void_p),
        ("lpszMenuName", ctypes.c_wchar_p),
        ("lpszClassName", ctypes.c_wchar_p),
        ("hIconSm", ctypes.c_void_p),
    ]


class NOTIFYICONDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_ulong),
        ("uFlags", ctypes.c_ulong),
        ("uCallbackMessage", ctypes.c_ulong),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_ulong),
        ("dwStateMask", ctypes.c_ulong),
        ("szInfo", ctypes.c_wchar * 256),
        ("uVersion", ctypes.c_ulong),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_ulong),
        ("guidItem", ctypes.c_byte * 16),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


class TrayIcon:
    def __init__(self, api, on_show, on_settings, on_quit):
        self.api = api
        self.on_show = on_show
        self.on_settings = on_settings
        self.on_quit = on_quit
        self.hwnd = None
        self.nid = None
        self.running = False
        self._wndproc = WNDPROC(self._wnd_proc)  # 保持引用，防止 GC

    def run(self):
        # 窗口创建 + 托盘注册 + 消息循环全部在同一线程，避免线程不亲和
        hinst = kernel32.GetModuleHandleW(0)
        wc = WNDCLASSEX()
        wc.cbSize = ctypes.sizeof(WNDCLASSEX)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "FloatSnipTray"
        user32.RegisterClassExW(ctypes.byref(wc))
        self.hwnd = user32.CreateWindowExW(0, "FloatSnipTray", "tray", 0,
                                           0, 0, 0, 0, 0, 0, hinst, 0)
        self.nid = NOTIFYICONDATA()
        self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATA)
        self.nid.hWnd = self.hwnd
        self.nid.uID = ID_TRAY
        self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self.nid.uCallbackMessage = WM_TRAYICON
        hicon = user32.LoadIconW(0, ctypes.c_void_p(32512))  # IDI_APPLICATION
        self.nid.hIcon = hicon if hicon else 0
        self.nid.szTip = "FloatSnip 浮球快贴"
        if shell32.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid)):
            self.running = True
        else:
            # 托盘注册失败（如无资源管理器/无桌面环境）：记为 None
            self.nid = None
            self.running = True
        msg = ctypes.wintypes.MSG()
        while self.running and user32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_TRAYICON:
            if lparam == WM_LBUTTONUP:
                self.api.ui(self.on_show)
            elif lparam == WM_RBUTTONUP:
                self._popup_menu()
            return 0
        if msg == WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == 1:
                self.api.ui(self.on_show)
            elif cmd == 2:
                self.api.ui(self.on_settings)
            elif cmd == 3:
                self.api.ui(self.on_quit)
            elif cmd == 4:
                self.api.ui(self._confirm_clear)
            return 0
        if msg == WM_DESTROY:
            try:
                user32.DestroyWindow(self.hwnd)
            except Exception:
                pass
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _confirm_clear(self):
        """托盘清空：在主线程弹二次确认，避免误触丢失数据。"""
        try:
            if messagebox.askyesno("清空所有数据", "将删除全部常用语与自定义分类（不可恢复），确定？"):
                self.api.clear_all()
                if self.api._panel:
                    self.api.ui(lambda: (self.api._panel._load_cats(), self.api._panel._load_list()))
        except Exception:
            pass

    def _popup_menu(self):
        if not self.hwnd:
            return
        hmenu = user32.CreatePopupMenu()
        user32.AppendMenuW(hmenu, MF_STRING, 1, "显示浮球")
        user32.AppendMenuW(hmenu, MF_STRING, 2, "打开设置")
        user32.AppendMenuW(hmenu, MF_STRING, 4, "清空所有数据")
        user32.AppendMenuW(hmenu, MF_STRING, 3, "退出")
        pt = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        user32.SetForegroundWindow(self.hwnd)
        user32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON, pt.x, pt.y, 0, self.hwnd, 0)
        user32.PostMessageW(self.hwnd, 0, 0, 0)  # 释放菜单所有权，避免二次弹出异常
        user32.DestroyMenu(hmenu)

    def close(self):
        self.running = False
        try:
            if self.nid:
                shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))
        except Exception:
            pass
        try:
            if self.hwnd:
                # 仅投递销毁消息，由消息线程内 WndProc 执行 DestroyWindow，线程安全
                user32.PostMessageW(self.hwnd, WM_DESTROY, 0, 0)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 开机自启
# ---------------------------------------------------------------------------
AUTOSTART_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
AUTOSTART_NAME = "FloatSnip"


def _is_autostart():
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, AUTOSTART_KEY, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, AUTOSTART_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


def _enable_autostart():
    import winreg
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
    root.withdraw()
    root.title("FloatSnip")

    # DPI 缩放：让面板/字号/内边距在高分屏上等比放大，避免「排版太小」；
    # 缩放后所有 UI 类读到的尺寸/字号/内边距都是放大后的值。
    try:
        dpi = root.winfo_fpixels("1i")
        scale = float(dpi) / 96.0
    except Exception:
        scale = 1.0
    _apply_ui_scale(scale)

    api = Api()
    api.set_root(root)           # 供 Api.ensure_panel 懒加载面板使用
    ball = FloatBall(root, api)
    # 默认开机自启（可在设置关闭）：按用户存储偏好幂等应用注册表
    try:
        if api.data["settings"].get("autostart", True):
            _enable_autostart()
        else:
            _disable_autostart()
    except Exception:
        pass
    # 面板懒加载：不在启动时创建，首次切换/快捷键/托盘操作时才建（见 Api.ensure_panel）

    # 系统托盘（左键唤起浮球，右键菜单：设置/退出）
    def _tray_show():
        api.set_mode("ball")
        if api._panel:
            api._panel.sync_mode()

    tray = TrayIcon(api, on_show=_tray_show,
                    on_settings=lambda: api.ensure_panel().open_settings(),
                    on_quit=api.quit_app)
    api._tray = tray
    threading.Thread(target=tray.run, daemon=True).start()

    register_hotkey(api)

    def _save_pos():
        if not root.winfo_exists():
            return
        api.save_window_pos()
        root.after(3000, _save_pos)

    root.after(3000, _save_pos)
    # 面板首次显示时由 sync_mode 触播报「记忆」，无需在此强建窗口

    # 自测模式：启动后自动退出，用于验证"关闭路径"有效（费曼门槛：证伪真懂）
    if os.environ.get("FLOATSNIP_AUTOTEST"):
        root.after(3000, api.quit_app)

    root.mainloop()


if __name__ == "__main__":
    main()
