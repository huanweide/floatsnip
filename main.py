# -*- coding: utf-8 -*-
"""FloatSnip 浮球快贴 · 后端
Python 后端：全局热键、剪贴板（ctypes 零依赖）、JSON 存储、窗口控制。
前端经 pywebview 承载于 Edge WebView2，做精致 UI 与平滑动画。
"""
import os
import sys
import json
import ctypes
import threading
import webbrowser

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

DEFAULT_DATA = {
    "settings": {"auto_paste": False, "hotkey": "<ctrl>+`"},
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
        save_data(dict(DEFAULT_DATA))
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
# API（暴露给前端 JS）
# ---------------------------------------------------------------------------
class Api:
    def __init__(self):
        self.data = load_data()
        self.mode = "ball"  # ball | panel
        self.auto_paste = self.data.get("settings", {}).get("auto_paste", False)
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
            # 给目标窗口一点时间重新获得焦点
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
        # 校验分类存在
        if not any(c["id"] == cat for c in self.data["categories"]):
            cat = "c1"
        if sid:
            s = next((x for x in self.data["snippets"] if x["id"] == sid), None)
            if s:
                s["content"] = content
                s["category"] = cat
                save_data(self.data)
                return {"ok": True, "state": self.data}
        # sid 未提供或没找到 -> 新建
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
        cid = "c" + str(int(time_counter()))
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

    # ---- 设置 ----
    def set_auto_paste(self, val):
        self.auto_paste = bool(val)
        self.data.setdefault("settings", {})["auto_paste"] = self.auto_paste
        save_data(self.data)
        return {"ok": True, "auto_paste": self.auto_paste}

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
# 全局热键
# ---------------------------------------------------------------------------
def start_hotkey(api):
    def toggle():
        try:
            m = api.toggle_mode()
            if api._win:
                api._win.evaluate_js("setMode('%s')" % m)
        except Exception:
            pass

    try:
        hk = keyboard.GlobalHotKeys({"<ctrl>+`": toggle})
        hk.start()
    except Exception:
        pass


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
    threading.Thread(target=start_hotkey, args=(api,), daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
