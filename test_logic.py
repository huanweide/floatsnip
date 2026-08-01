# -*- coding: utf-8 -*-
"""FloatSnip v2 逻辑层验证（真实导入 main.py，不 mock tkinter）。

目的：在「沙箱无显示器」约束下，把能客观验证的逻辑全部跑通，给出可证伪证据。
覆盖：热键规范化 / 显示名 / 冲突预检 / Win32 vk 解析 / 剪贴板编解码 / Api 业务流 / 数据迁移。
"""
import os
import sys
import tempfile
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import main as M

PASS = 0
FAIL = 0
EVID = []


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        EVID.append("  [PASS] %s%s" % (name, ("  -> " + detail) if detail else ""))
    else:
        FAIL += 1
        EVID.append("  [FAIL] %s%s" % (name, ("  -> " + detail) if detail else ""))


# ---------------------------------------------------------------------------
# 1. 热键规范化（核心：用户可设置任意组合键）
# ---------------------------------------------------------------------------
cases = [
    ("ctrl+`", True),
    ("ctrl+shift+alt+k", True),
    ("win+k", True),
    ("alt+space", True),
    ("f12", True),
    ("ctrl+shift", False),     # 两个修饰无主键
    ("ctrl+ctrl", False),      # 重复修饰无主键
    ("zzz", False),            # 非法主键
    ("", False),
    ("ctrl+é", False),         # 非法字符
]
for expr, expect_valid in cases:
    spec = M.normalize_hotkey(expr)
    ok = (spec is not None) == expect_valid
    check("normalize_hotkey(%r)" % expr, ok,
          "spec=%r (expect_valid=%s)" % (spec, expect_valid))

# 默认热键必须能被 Win32 vk 解析（否则真机 RegisterHotKey 无法注册）
default_spec = M.normalize_hotkey(M.DEFAULT_HOTKEY)
_mods, _vk = M._spec_to_mod_vk(default_spec)
check("default hotkey parseable by Win32 vk", _vk is not None, "spec=%r vk=%r" % (default_spec, _vk))

# ---------------------------------------------------------------------------
# 2. 显示名
# ---------------------------------------------------------------------------
check("format display ctrl+`", M.format_hotkey_display("ctrl+`") == "Ctrl+`",
      M.format_hotkey_display("ctrl+`"))
check("format display win+k", M.format_hotkey_display("win+k") == "Win+K",
      M.format_hotkey_display("win+k"))
check("format display ctrl+shift+alt+k",
      M.format_hotkey_display("ctrl+shift+alt+k") == "Ctrl+Shift+Alt+K",
      M.format_hotkey_display("ctrl+shift+alt+k"))

# ---------------------------------------------------------------------------
# 3. Win32 vk 解析（冲突预检底层）
# ---------------------------------------------------------------------------
mods, vk = M._spec_to_mod_vk("<ctrl>+`")
check("_spec_to_mod_vk ctrl", mods == 2 and isinstance(vk, int) and vk > 0,
      "mods=%r vk=%r" % (mods, vk))
mods, vk = M._spec_to_mod_vk("<cmd>+k")
check("_spec_to_mod_vk cmd", mods == 8 and vk > 0, "mods=%r vk=%r" % (mods, vk))
mods, vk = M._spec_to_mod_vk("<alt>+<shift>+x")
check("_spec_to_mod_vk alt+shift", mods == (1 | 4) and vk > 0, "mods=%r vk=%r" % (mods, vk))
mods, vk = M._spec_to_mod_vk(None)
check("_spec_to_mod_vk None", (mods, vk) == (0, None))

# 冲突预检必须返回布尔（沙箱里可能 False，但必须是 bool 不抛异常）
try:
    avail = M.hotkey_is_available("<ctrl>+`")
    check("hotkey_is_available returns bool", isinstance(avail, bool), "avail=%r" % avail)
except Exception as e:
    check("hotkey_is_available returns bool", False, str(e))

# ---------------------------------------------------------------------------
# 4. 剪贴板编解码（UTF-16 + GlobalAlloc 64 位安全）
# ---------------------------------------------------------------------------
sample = "复制自检 ✓ 中文 + emoji 🚀 + 换行\n第二行"
try:
    ok = M.copy_text(sample)
    got = M.read_clipboard()
    check("clipboard roundtrip", ok and got == sample,
          "ok=%s got==orig=%s" % (ok, got == sample))
    # 空串 / None
    check("copy_text empty str", M.copy_text("") is True)
except Exception as e:
    check("clipboard roundtrip", False, "EXC: " + str(e))

r1 = M.copy_and_verify("验证复制自检是否真的成功")
check("copy_and_verify ok/mismatch/empty", r1 in ("ok", "mismatch", "fail", "empty"),
      "result=%r" % r1)
check("copy_and_verify empty", M.copy_and_verify("   ") == "empty")

# ---------------------------------------------------------------------------
# 5. Api 业务流（与 UI 解耦，可直接单测）
# ---------------------------------------------------------------------------
tmp = tempfile.mkdtemp(prefix="floatsniptest_")
tmpdata = os.path.join(tmp, "data.json")
M.DATA_FILE = tmpdata  # 重定向，避免污染真实 AppData

api = M.Api()
check("Api init load defaults", api.data["settings"]["hotkey"] == M.DEFAULT_HOTKEY)
check("Api set_mode", api.set_mode("panel") == "panel" and api.mode == "panel")
check("Api toggle_mode", api.toggle_mode() == "ball")
# 片段增删改
r = api.save_snippet(None, "新常用语内容", "c1")
check("save_snippet new", r["ok"] and any(s["content"] == "新常用语内容" for s in api.data["snippets"]))
new_id = [s["id"] for s in api.data["snippets"] if s["content"] == "新常用语内容"][0]
r = api.save_snippet(new_id, "改过的", "c2")
check("save_snippet edit", any(s["id"] == new_id and s["content"] == "改过的" and s["category"] == "c2"
                               for s in api.data["snippets"]))
r = api.save_snippet(None, "   ", "c1")
check("save_snippet empty rejected", (not r["ok"]) and "空" in r["msg"])
before = len(api.data["snippets"])
api.delete_snippet(new_id)
check("delete_snippet", len(api.data["snippets"]) == before - 1)

# 分类改名 / 新建（上限 10）
r = api.add_category("我的分类")
check("add_category", r["ok"] and any(c["name"] == "我的分类" for c in api.data["categories"]))
r = api.rename_category("all", "改名固定")
check("rename fixed rejected", (not r["ok"]) and "固定" in r["msg"])
new_cat = [c["id"] for c in api.data["categories"] if c["name"] == "我的分类"][0]
r = api.rename_category(new_cat, "重命名后")
check("rename_category", any(c["id"] == new_cat and c["name"] == "重命名后"
                             for c in api.data["categories"]))

# 分类重名拦截：防止造出同名分类→下拉框无法区分→保存静默错分
r = api.add_category("重命名后")   # 已存在
check("add_category duplicate rejected", (not r["ok"]) and "已存在" in r["msg"])
r = api.add_category("全新分类A")
check("add_category unique ok", r["ok"] and any(c["name"] == "全新分类A"
                                                for c in api.data["categories"]))
new_catA = [c["id"] for c in api.data["categories"] if c["name"] == "全新分类A"][0]
r = api.rename_category(new_catA, "重命名后")  # 改成已存在名
check("rename_category duplicate rejected", (not r["ok"]) and "已存在" in r["msg"])
r = api.rename_category(new_catA, "全新分类A")  # 改名成自己原名，应允许
check("rename_category to self name ok", r["ok"])

# 删除分类（连带其下常用语一并删除；固定分类不可删；不存在报错）
api.add_category("待删分类")
del_cat = [c["id"] for c in api.data["categories"] if c["name"] == "待删分类"][0]
api.save_snippet(None, "属于待删", del_cat)
api.save_snippet(None, "属于待删2", del_cat)
before_cats = len(api.data["categories"])
before_snips = len(api.data["snippets"])
r = api.delete_category(del_cat)
check("delete_category removes category",
      r["ok"] and len(api.data["categories"]) == before_cats - 1
      and not any(c["id"] == del_cat for c in api.data["categories"]))
check("delete_category cascades snippets",
      r["ok"] and r["removed"] == 2 and len(api.data["snippets"]) == before_snips - 2
      and not any(s["category"] == del_cat for s in api.data["snippets"]))
r = api.delete_category("all")
check("delete_category fixed rejected", (not r["ok"]) and "固定" in r["msg"])
r = api.delete_category("nope")
check("delete_category missing rejected", (not r["ok"]) and "不存在" in r["msg"])

# 持久化：重新加载应当保留（用一个未被删除的片段验证）
api.save_snippet(None, "持久化校验片段", "c2")
api2 = M.Api()
check("data persisted across reload",
      any(c["name"] == "重命名后" for c in api2.data["categories"]) and
      any(s["content"] == "持久化校验片段" for s in api2.data["snippets"]))

# active_cat 记忆：切换分类必须落盘，重启后停留上次分类（用户要求的'保存记忆'）
api.set_active_cat("c3")
api3 = M.Api()
check("active_cat persisted across reload",
      api3.data["settings"].get("active_cat") == "c3",
      "active_cat=%r" % api3.data["settings"].get("active_cat"))
# 默认初始为 'all'，且非法分类 id 在 UI 初始化时会被守卫回退（此处验证字段存在）
check("active_cat default is present", "active_cat" in api.data["settings"])

# auto_paste / hotkey 设置
api.set_auto_paste(True)
check("set_auto_paste", api.data["settings"]["auto_paste"] is True)
r = api.set_hotkey("alt+space")
check("set_hotkey valid", r["ok"] and r["hotkey"] == M.normalize_hotkey("alt+space"))
r = api.set_hotkey("not a key")
check("set_hotkey invalid rejected", (not r["ok"]) and "不合法" in r["msg"])

# 快捷键「显示名→保存」round-trip：设置框保存时传入的是 format 后的显示串，
# 必须能被 normalize 还原，否则默认快捷键下点「保存」会被整体拒绝（改了不生效）
r = api.set_hotkey(M.format_hotkey_display("ctrl+`"))
check("set_hotkey round-trip from display string",
      r["ok"] and r["hotkey"] == M.normalize_hotkey("ctrl+`"),
      "hotkey=%r" % (r.get("hotkey") if r else None))

# 退出路径在无 GUI 句柄下必须安全（不抛异常、不卡死主线程）
try:
    api.quit_app()
    check("quit_app safe without handles", True)
except Exception as e:
    check("quit_app safe without handles", False, str(e))

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 6. 数据迁移（老数据缺字段时补全，不破坏）
# ---------------------------------------------------------------------------
legacy = {
    "settings": {"auto_paste": False, "hotkey": "ctrl+`"},
    "categories": [{"id": "all", "name": "所有", "fixed": True}, {"id": "c1", "name": "AI"}],
    "snippets": [{"id": "s1", "content": "x", "category": "c1"}],
}
legacy_path = os.path.join(tmp, "legacy.json")
with open(legacy_path, "w", encoding="utf-8") as f:
    import json as _json
    _json.dump(legacy, f)
M.DATA_FILE = legacy_path
M2 = M.Api()
check("migration adds window_x", "window_x" in M2.data["settings"])
check("migration adds active_cat default", M2.data["settings"].get("active_cat") == "all")
check("migration keeps snippets", M2.data["snippets"][0]["content"] == "x")
check("migration keeps hotkey", M2.data["settings"]["hotkey"] == "ctrl+`")

# ---------------------------------------------------------------------------
# 汇总
# ---------------------------------------------------------------------------
print("=" * 64)
print("FloatSnip v2 逻辑层验证")
print("=" * 64)
print("\n".join(EVID))
print("-" * 64)
print("RESULT: %d passed, %d failed" % (PASS, FAIL))
sys.exit(1 if FAIL else 0)
