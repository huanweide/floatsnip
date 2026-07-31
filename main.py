# -*- coding: utf-8 -*-
"""FloatSnip 浮球快贴 · 后端
Python 后端：全局热键（可配置、可热重载）、剪贴板（ctypes 零依赖）、
JSON 存储、窗口控制（拖动 / 隐藏 / 显示）、开机自启。
前端经 pywebview 承载于 Edge WebView2，做精致 UI 与平滑动画。
"""
import os
import re
import sys
import json
import ctypes
import threading

import webview
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
    "settings": {"auto_paste": False, "hotkey": DEFAULT_HOTKEY},
    "categories": [
        {"id": "all", "name": "所有", "fixed": True},
        {"id": "c1", "name": "AI"},
        {"id": "c2", "name": "平常常用"},
    ],
    "snippets": [
        {"id": "s1", "content": "用费曼方式把这道题讲给我听，不要跳步。", "category": "c1"},
        {"id": "s2", "content": "帮我 review 这段代码，重点看边界情况和错误处理。", "category": "c1"},
        {"id": "s3", "content": "收到，马上安排。", "category": "c2"},
        {"id": "s4", "content": "这局对面太肉了，建议出点法穿。", "category": "c2"},
    ],
}


# ---------------------------------------------------------------------------
# 存储
# ---------------------------------------------------------------------------
def load_data():
    if not os.path.exists(DATA_FILE):
        save_data(json.loads(json.dumps(DEFAULT_DATA)))
        return json.loads(json.dumps(DEFAULT_DATA))
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return json.loads(json.dumps(DEFAULT_DATA))


def save_data(data):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


# ---------------------------------------------------------------------------
# 剪贴板（ctypes，零依赖）
# ---------------------------------------------------------------------------
def copy_text(text):
    try:
        text = "" if text is None else str(text)
        u32 = ctypes.windll.user32
        k32 = ctypes.windll.kernel32
        u32.OpenClipboard(None)
        u32.EmptyClipboard()
        size = (len(text) + 1) * ctypes.sizeof(ctypes.c_wchar)
        h = k32.GlobalAlloc(GMEM_MOVEABLE, size)
        p = k32.GlobalLock(h)
        buf = ctypes.create_unicode_buffer(text)
        ctypes.memmove(p, buf, size)
        k32.GlobalUnlock(h)
        u32.SetClipboardData(CF_UNICODETEXT, h)
        u32.CloseClipboard()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 快捷键规范化（用户友好格式 <-> pynput 格式）
# 用户格式示例：ctrl+`  /  ctrl+alt+b  /  alt+space
# pynput 格式示例：<ctrl>+`  /  <ctrl><alt>b
# ---------------------------------------------------------------------------
def normalize_hotkey(hk):
    """把用户友好的 ctrl+` 转成 pynput 格式 <ctrl>+`；无法识别返回 None。"""
    if not hk:
        return None
    hk = (hk or "").strip().lower()
    parts = [p.strip() for p in hk.split("+") if p.strip()]
    if not parts:
        return None
    mods, key = [], None
    for p in parts:
        if p in ("ctrl", "control", "^", "<ctrl>"):
            mods.append("<ctrl>")
        elif p in ("alt", "option", "!", "<alt>"):
            mods.append("<alt>")
        elif p in ("shift", "<shift>"):
            mods.append("<shift>")
        elif p in ("win", "cmd", "super", "meta", "<cmd>"):
            mods.append("<cmd>")
        else:
            if key is not None:
                return None  # 多个主键，非法
            key = p
    if key is None:
        return None
    keymap = {
        "esc": "<esc>", "escape": "<esc>", "enter": "<enter>", "return": "<enter>",
        "tab": "<tab>", "space": "<space>", "backspace": "<backspace>",
        "delete": "<delete>", "del": "<delete>", "insert": "<insert>",
        "home": "<home>", "end": "<end>", "pageup": "<page_up>", "pagedown": "<page_down>",
        "pgup": "<page_up>", "pgdn": "<page_down>", "up": "<up>", "down": "<down>",
        "left": "<left>", "right": "<right>", "capslock": "<caps_lock>",
        "printscreen": "<print_screen>", "pause": "<pause>", "menu": "<menu>",
    }
    key = keymap.get(key, key)
    # 功能键 f1-f24 需写成 pynput 的 <f5> 形式
    if re.fullmatch(r"f([1-9]|1[0-9]|2[0-4])", key):
        key = "<" + key + ">"
    # pynput 语法：每个修饰键与主键之间都用 + 分隔，如 <ctrl>+<alt>+b
    spec = "+".join(mods + [key]) if mods else key
    # 交给 pynput 做最终合法性校验（解析失败即视为非法）
    try:
        keyboard.HotKey.parse(spec)
    except Exception:
        return None
    return spec


# ---------------------------------------------------------------------------
# 全局热键（支持热重载）
# ---------------------------------------------------------------------------
_hk_listener = None
_hk_lock = threading.Lock()


def _toggle_hotkey(api):
    """热键回调：隐藏中则唤回，否则切换 球/面板。"""
    try:
        if api.hidden:
            api.show_ball()
            return
        m = api.toggle_mode()
        if api._win:
            api._win.evaluate_js("setMode('%s')" % m)
    except Exception:
        pass


def register_hotkey(api, spec):
    try:
        hk = keyboard.GlobalHotKeys({spec: lambda: _toggle_hotkey(api)})
        hk.start()
        return hk
    except Exception:
        return None


def apply_hotkey(api):
    """按当前设置注册/重载全局热键（先停旧，再启新）。"""
    global _hk_listener
    with _hk_lock:
        old = _hk_listener
        _hk_listener = None
        if old is not None:
            try:
                old.stop()
            except Exception:
                pass
        spec = normalize_hotkey(api.data.get("settings", {}).get("hotkey", DEFAULT_HOTKEY))
        if not spec:
            spec = normalize_hotkey(DEFAULT_HOTKEY)
        _hk_listener = register_hotkey(api, spec)
    return spec


# ---------------------------------------------------------------------------
# API（暴露给前端 JS）
# ---------------------------------------------------------------------------
class Api:
    def __init__(self):
        self.data = load_data()
        s = self.data.setdefault("settings", {})
        s.setdefault("auto_paste", False)
        s.setdefault("hotkey", DEFAULT_HOTKEY)
        self.auto_paste = bool(s["auto_paste"])
        self.mode = "ball"  # ball | panel
        self.hidden = False
        self._win = None

    # ---- 状态 ----
    def get_state(self):
        return self.data

    def get_mode(self):
        return self.mode

    # ---- 复制 ----
    def copy(self, sid):
        s = next((x for x in self.data["snippets"] if x["id"] == sid), None)
        if not s:
            return False
        ok = copy_text(s["content"])
        if ok and self.auto_paste:
            self._auto_paste()
        return ok

    def _auto_paste(self):
        try:
            if self._win:
                self._win.hide()
            threading.Timer(0.12, self._send_ctrl_v).start()
        except Exception:
            pass

    def _send_ctrl_v(self):
        try:
            kb = keyboard.Controller()
            kb.press(keyboard.Key.ctrl_l)
            kb.press("v")
            kb.release("v")
            kb.release(keyboard.Key.ctrl_l)
        except Exception:
            pass

    # ---- 片段 CRUD ----
    def save_snippet(self, sid, content, category):
        content = (content or "").strip()
        if not content:
            return {"ok": False, "msg": "内容不能为空"}
        cat = category if category and category != "all" else "c1"
        if not any(c["id"] == cat for c in self.data["categories"]):
            cat = "c1"
        if sid:
            s = next((x for x in self.data["snippets"] if x["id"] == sid), None)
            if s:
                s["content"] = content
                s["category"] = cat
                save_data(self.data)
                return {"ok": True, "state": self.data}
        num = (max([int(x["id"][1:]) for x in self.data["snippets"] if x["id"][1:].isdigit()], default=0) + 1)
        new_id = "s" + str(num)
        self.data["snippets"].append({"id": new_id, "content": content, "category": cat})
        save_data(self.data)
        return {"ok": True, "state": self.data}

    def delete_snippet(self, sid):
        self.data["snippets"] = [x for x in self.data["snippets"] if x["id"] != sid]
        save_data(self.data)
        return {"ok": True, "state": self.data}

    # ---- 分类 ----
    def add_category(self, name):
        name = (name or "").strip()
        customs = [c for c in self.data["categories"] if not c.get("fixed")]
        if len(customs) >= 5:
            return {"ok": False, "msg": "自定义分类最多 5 个"}
        if not name:
            return {"ok": False, "msg": "名字不能为空"}
        cid = "c" + str(time_counter())
        self.data["categories"].append({"id": cid, "name": name})
        save_data(self.data)
        return {"ok": True, "state": self.data}

    def rename_category(self, cid, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "msg": "名字不能为空"}
        for c in self.data["categories"]:
            if c["id"] == cid and not c.get("fixed"):
                c["name"] = name
                save_data(self.data)
                return {"ok": True, "state": self.data}
        return {"ok": False, "msg": "该分类不可改名或不存在"}

    # ---- 窗口：拖动 / 位置 ----
    def get_window_pos(self):
        if self._win:
            try:
                return [int(self._win.x), int(self._win.y)]
            except Exception:
                pass
        return [0, 0]

    def move_to(self, x, y):
        if self._win:
            try:
                self._win.move(int(x), int(y))
                return True
            except Exception:
                pass
        return False

    # ---- 窗口：隐藏 / 显示 ----
    def hide_ball(self):
        self.hidden = True
        if self._win:
            try:
                self._win.hide()
            except Exception:
                pass
        return {"ok": True, "hidden": True}

    def show_ball(self):
        self.hidden = False
        self.mode = "ball"
        if self._win:
            try:
                self._win.show()
            except Exception:
                pass
        return {"ok": True, "hidden": False}

    # ---- 设置：自动粘贴 ----
    def set_auto_paste(self, val):
        self.auto_paste = bool(val)
        self.data.setdefault("settings", {})["auto_paste"] = self.auto_paste
        save_data(self.data)
        return {"ok": True, "auto_paste": self.auto_paste}

    # ---- 设置：快捷键 ----
    def get_hotkey(self):
        return self.data.get("settings", {}).get("hotkey", DEFAULT_HOTKEY)

    def set_hotkey(self, hk):
        spec = normalize_hotkey(hk)
        if not spec:
            return {"ok": False, "msg": "快捷键格式不对，示例：ctrl+` 或 ctrl+alt+b"}
        self.data.setdefault("settings", {})["hotkey"] = (hk or "").strip().lower()
        save_data(self.data)
        apply_hotkey(self)
        return {"ok": True, "hotkey": self.data["settings"]["hotkey"]}

    # ---- 设置：开机自启（当前用户注册表 Run 键） ----
    def get_autostart(self):
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
                0,
                winreg.KEY_READ,
            ) as k:
                winreg.QueryValueEx(k, "FloatSnip")
                return {"ok": True, "autostart": True}
        except Exception:
            return {"ok": True, "autostart": False}

    def set_autostart(self, val):
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            exe = sys.executable
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            ) as k:
                if val:
                    winreg.SetValueEx(k, "FloatSnip", 0, winreg.REG_SZ, '"%s"' % exe)
                else:
                    try:
                        winreg.DeleteValue(k, "FloatSnip")
                    except FileNotFoundError:
                        pass
            return {"ok": True, "autostart": bool(val)}
        except Exception as e:
            return {"ok": False, "msg": "设置开机自启失败：%s" % e}

    # ---- 模式切换 / 退出 ----
    def toggle_mode(self):
        if self.mode == "ball":
            self.mode = "panel"
            if self._win:
                self._win.resize(360, 560)
        else:
            self.mode = "ball"
            if self._win:
                self._win.resize(64, 64)
        return self.mode

    def set_mode(self, mode):
        self.mode = mode
        if self._win:
            if mode == "panel":
                self._win.resize(360, 560)
            else:
                self._win.resize(64, 64)
        return self.mode

    def quit_app(self):
        with _hk_lock:
            if _hk_listener is not None:
                try:
                    _hk_listener.stop()
                except Exception:
                    pass
        try:
            if self._win:
                self._win.destroy()
        except Exception:
            pass
        os._exit(0)


def time_counter():
    import time
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main():
    api = Api()
    html_path = os.path.join(BASE, "gui", "index.html")
    try:
        window = webview.create_window(
            "FloatSnip 浮球快贴",
            url=html_path,
            js_api=api,
            width=64,
            height=64,
            frameless=True,
            on_top=True,
            transparent=True,
            easy_drag=False,
        )
    except Exception:
        window = webview.create_window(
            "FloatSnip 浮球快贴",
            url=html_path,
            js_api=api,
            width=64,
            height=64,
            frameless=True,
            on_top=True,
        )
    api._win = window
    threading.Thread(target=apply_hotkey, args=(api,), daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
