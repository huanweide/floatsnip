# -*- coding: utf-8 -*-
"""FloatSnip 逻辑层 pytest 测试（真实导入 main.py，不 mock tkinter）。

为什么重写（旧版 test_logic.py 的问题）：
  - 旧版把 ~60 条断言写成模块顶层的 check(...) 调用，**import 阶段就执行**，
    顺带真的往系统剪贴板写内容、真的建 Api 落盘；
  - pytest 只能收集到 1 个 test，CI 永远显示 "1 passed"，任何一条失败都要从一大段
    打印里人肉定位，也无法用 `-k` 单独重跑某一条。

新版：每条断言都是独立的 test / parametrize 用例；唯一有外部副作用的操作
（读写系统剪贴板）集中在 test_clipboard_* 里，环境不允许时 skip 而不是失败。
覆盖：热键规范化 / 显示名 / Win32 vk 解析 / 剪贴板编解码 / Api 业务流 / 数据迁移。
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import main as M


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def api(tmp_path, monkeypatch):
    """每个用例一份独立 data.json，绝不碰用户真实的 AppData 数据。"""
    monkeypatch.setattr(M, "DATA_FILE", str(tmp_path / "data.json"))
    return M.Api()


# ---------------------------------------------------------------------------
# 1. 热键规范化
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expr,expect_valid", [
    # 合法：必须带修饰键
    ("ctrl+`", True),
    ("ctrl+shift+alt+k", True),
    ("win+k", True),
    ("alt+space", True),
    ("ctrl+k", True),
    ("ctrl+f12", True),
    ("ctrl+shift+/", True),
    ("CTRL+K", True),                 # 大小写
    ("  ctrl + k  ", True),           # 空格
    ("ctrl+escape", True),            # 别名
    ("ctrl+return", True),            # 别名
    # 非法：没有修饰键（裸键）
    ("f12", False),
    ("k", False),
    ("space", False),
    ("esc", False),
    ("a", False),
    # 非法：其它
    ("ctrl+shift", False),            # 只有修饰键没有主键
    ("ctrl+ctrl", False),             # 重复修饰没有主键
    ("zzz", False),                   # 非法主键
    ("", False),
    ("ctrl+é", False),                # 非法字符
    ("ctrl+k+j", False),              # 两个主键
    ("ctrl++", False),                # '+' 不是可用主键
    (None, False),
    (123, False),
])
def test_normalize_hotkey(expr, expect_valid):
    assert (M.normalize_hotkey(expr) is not None) is expect_valid


def test_bare_key_hotkey_is_rejected():
    """事故回归：裸键热键会让用户每敲一次该键就弹出面板，必须拒绝。

    旧版本允许把 k / 空格 / F12 这类单键设成全局热键；RegisterHotKey 注册成功后，
    用户在任何窗口里敲这个键都会唤起面板，等于这台电脑没法正常打字。
    """
    for expr in ("k", "a", "z", "1", "0", "space", "enter", "esc", "tab", "f12"):
        assert M.normalize_hotkey(expr) is None, "裸键 %r 不应被接受" % expr


def test_ui_recorder_rejects_bare_key():
    """设置框的按键录制路径无法在无显示器环境实例化，改断言源码里确实有拦截。

    没有这个拦截时：用户在设置里单击快捷键框后只按一个 k（不按修饰键），
    旧代码就会把 k 当成热键写入，保存后每次打字都弹面板。
    """
    with open(os.path.join(HERE, "main.py"), "r", encoding="utf-8") as f:
        src = f.read()
    # 文件里有多个 _on_key（不同控件），取设置框那个（操作 hotkey_var 的）
    body = ""
    pos = 0
    while True:
        i = src.find("def _on_key(", pos)
        if i < 0:
            break
        chunk = src[i:i + 2000]
        if "hotkey_var" in chunk:
            body = chunk
            break
        pos = i + 1
    assert body, "没找到设置框的按键录制函数 _on_key"
    hint = "请按住 Ctrl/Alt/Shift/Win 再按主键"
    assert hint in body, "按键录制函数里必须有裸键提示"
    assert "if not mods:" in body, "按键录制函数里必须有裸键分支"
    assert body.index("if not mods:") < body.index(hint), "裸键拦截必须写在写入 hotkey_var 之前"


def test_hotkey_has_modifier():
    assert M.hotkey_has_modifier("ctrl+k") is True
    assert M.hotkey_has_modifier("win+k") is True
    assert M.hotkey_has_modifier("k") is False
    assert M.hotkey_has_modifier("") is False
    assert M.hotkey_has_modifier(None) is False


def test_set_hotkey_rejects_bare_key_with_clear_message(api):
    r = api.set_hotkey("k")
    assert r["ok"] is False
    assert "必须包含" in r["msg"], "提示要点明缺修饰键，而不是笼统说格式不合法"


def test_set_hotkey_invalid_gives_format_message(api):
    r = api.set_hotkey("ctrl+é")
    assert r["ok"] is False
    assert "不合法" in r["msg"]


def test_set_hotkey_roundtrip_from_display_string(api):
    """设置框保存时传的是 format 后的显示串，必须能被 normalize 还原。"""
    r = api.set_hotkey(M.format_hotkey_display("ctrl+`"))
    assert r["ok"] is True
    assert r["hotkey"] == M.normalize_hotkey("ctrl+`")


def test_default_hotkey_is_registerable():
    spec = M.normalize_hotkey(M.DEFAULT_HOTKEY)
    mods, vk = M._spec_to_mod_vk(spec)
    assert spec is not None
    assert mods != 0, "默认热键必须带修饰键"
    assert isinstance(vk, int) and vk > 0


# ---------------------------------------------------------------------------
# 2. 显示名
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("expr,expect", [
    ("ctrl+`", "Ctrl+`"),
    ("win+k", "Win+K"),
    ("ctrl+shift+alt+k", "Ctrl+Shift+Alt+K"),
    ("ctrl+escape", "Ctrl+Esc"),
    ("ctrl+f12", "Ctrl+F12"),
])
def test_format_hotkey_display(expr, expect):
    assert M.format_hotkey_display(expr) == expect


def test_format_hotkey_display_falls_back_for_invalid():
    assert M.format_hotkey_display("k") == "k"
    assert M.format_hotkey_display(None) == ""


# ---------------------------------------------------------------------------
# 3. Win32 vk 解析 / 冲突预检
# ---------------------------------------------------------------------------
def test_spec_to_mod_vk_ctrl():
    mods, vk = M._spec_to_mod_vk("<ctrl>+`")
    assert mods == 2 and isinstance(vk, int) and vk > 0


def test_spec_to_mod_vk_cmd():
    mods, vk = M._spec_to_mod_vk("<cmd>+k")
    assert mods == 8 and vk > 0


def test_spec_to_mod_vk_alt_shift():
    mods, vk = M._spec_to_mod_vk("<alt>+<shift>+x")
    assert mods == (1 | 4) and vk > 0


def test_spec_to_mod_vk_none():
    assert M._spec_to_mod_vk(None) == (0, None)


def test_hotkey_is_available_returns_bool():
    avail = M.hotkey_is_available("<ctrl>+`")
    assert isinstance(avail, bool)


# ---------------------------------------------------------------------------
# 4. 剪贴板编解码（UTF-16 + GlobalAlloc 64 位安全）
# ---------------------------------------------------------------------------
def test_copy_empty_string_is_true():
    assert M.copy_text("") is True


def test_copy_text_none_is_true():
    assert M.copy_text(None) is True


def test_clipboard_roundtrip():
    """真实的写→读回自检。环境不支持剪贴板时 skip（不是失败）。"""
    sample = "复制自检 ✓ 中文 + emoji 🚀 + 换行\n第二行"
    if not M.copy_text(sample):
        pytest.skip("当前环境无法访问系统剪贴板")
    assert M.read_clipboard() == sample


def test_copy_and_verify_empty():
    assert M.copy_and_verify("   ") == "empty"


def test_copy_and_verify_result_is_known_enum():
    assert M.copy_and_verify("验证复制自检是否真的成功") in ("ok", "mismatch", "fail", "empty")


# ---------------------------------------------------------------------------
# 5. Api 业务流
# ---------------------------------------------------------------------------
def test_api_init_defaults(api):
    assert api.data["settings"]["hotkey"] == M.DEFAULT_HOTKEY
    assert api.data["settings"]["active_cat"] == "all"


def test_set_mode_and_toggle(api):
    assert api.set_mode("panel") == "panel"
    assert api.mode == "panel"
    assert api.toggle_mode() == "ball"


def test_save_snippet_new_then_edit(api):
    r = api.save_snippet(None, "新常用语内容", "c1")
    assert r["ok"] is True
    sid = [s["id"] for s in api.data["snippets"] if s["content"] == "新常用语内容"][0]
    r = api.save_snippet(sid, "改过的", "c2")
    assert r["ok"] is True
    hit = [s for s in api.data["snippets"] if s["id"] == sid][0]
    assert hit["content"] == "改过的" and hit["category"] == "c2"


def test_save_snippet_empty_rejected(api):
    r = api.save_snippet(None, "   ", "c1")
    assert r["ok"] is False and "空" in r["msg"]


def test_save_snippet_length_cap(api):
    """README 承诺的软上限 10000 字：超限必须明确拒绝，不能静默截断。"""
    r = api.save_snippet(None, "x" * (M.MAX_SNIPPET_LEN + 1), "c1")
    assert r["ok"] is False and "过长" in r["msg"]
    assert not any(len(s["content"]) > M.MAX_SNIPPET_LEN for s in api.data["snippets"])


def test_save_snippet_at_limit_ok(api):
    r = api.save_snippet(None, "x" * M.MAX_SNIPPET_LEN, "c1")
    assert r["ok"] is True


def test_delete_snippet(api):
    r = api.save_snippet(None, "待删除", "c1")
    assert r["ok"] and "state" in r
    sid = [s["id"] for s in api.data["snippets"] if s["content"] == "待删除"][0]
    before = len(api.data["snippets"])
    api.delete_snippet(sid)
    assert len(api.data["snippets"]) == before - 1


def test_add_category_and_rename(api):
    r = api.add_category("我的分类")
    assert r["ok"] and any(c["name"] == "我的分类" for c in api.data["categories"])
    cid = [c["id"] for c in api.data["categories"] if c["name"] == "我的分类"][0]
    assert api.rename_category(cid, "重命名后")["ok"] is True


def test_rename_fixed_category_rejected(api):
    r = api.rename_category("all", "改名固定")
    assert r["ok"] is False and "固定" in r["msg"]


def test_add_category_duplicate_rejected(api):
    api.add_category("重名分类")
    r = api.add_category("重名分类")
    assert r["ok"] is False and "已存在" in r["msg"]


def test_rename_category_duplicate_rejected(api):
    api.add_category("甲")
    api.add_category("乙")
    a = [c["id"] for c in api.data["categories"] if c["name"] == "甲"][0]
    r = api.rename_category(a, "乙")
    assert r["ok"] is False and "已存在" in r["msg"]


def test_rename_category_to_self_name_ok(api):
    api.add_category("原名")
    cid = [c["id"] for c in api.data["categories"] if c["name"] == "原名"][0]
    assert api.rename_category(cid, "原名")["ok"] is True


def test_delete_category_cascades_its_snippets(api):
    api.add_category("待删分类")
    cid = [c["id"] for c in api.data["categories"] if c["name"] == "待删分类"][0]
    api.save_snippet(None, "属于待删", cid)
    api.save_snippet(None, "属于待删2", cid)
    before_cats = len(api.data["categories"])
    before_snips = len(api.data["snippets"])
    r = api.delete_category(cid)
    assert r["ok"] is True and r["removed"] == 2
    assert len(api.data["categories"]) == before_cats - 1
    assert len(api.data["snippets"]) == before_snips - 2
    assert not any(s["category"] == cid for s in api.data["snippets"])


def test_delete_category_fixed_rejected(api):
    r = api.delete_category("all")
    assert r["ok"] is False and "固定" in r["msg"]


def test_delete_category_missing_rejected(api):
    r = api.delete_category("nope")
    assert r["ok"] is False and "不存在" in r["msg"]


def test_data_persists_across_reload(api):
    api.add_category("持久化分类")
    api.save_snippet(None, "持久化校验片段", "c2")
    again = M.Api()
    assert any(c["name"] == "持久化分类" for c in again.data["categories"])
    assert any(s["content"] == "持久化校验片段" for s in again.data["snippets"])


def test_active_cat_persists_across_reload(api):
    api.set_active_cat("c3")
    again = M.Api()
    assert again.data["settings"].get("active_cat") == "c3"


def test_set_auto_paste(api):
    api.set_auto_paste(True)
    assert api.data["settings"]["auto_paste"] is True


def test_export_backup_excludes_sensitive(api, tmp_path):
    api.save_snippet(None, "普通常用语", "c1", sensitive=False)
    api.save_snippet(None, "敏感口令123", "c1", sensitive=True)
    out = tmp_path / "backup.json"
    ok, err = api.export_backup(str(out))
    assert ok, err
    with open(str(out), "r", encoding="utf-8") as f:
        exp = json.load(f)
    assert [s for s in exp.get("snippets", []) if s.get("sensitive")] == []
    assert any(s["content"] == "普通常用语" for s in exp.get("snippets", []))


def test_quit_app_safe_without_handles(api):
    api.quit_app()   # 无 GUI 句柄时不能抛异常、不能卡死


# ---------------------------------------------------------------------------
# 6. 数据迁移
# ---------------------------------------------------------------------------
def test_migration_adds_missing_fields(tmp_path, monkeypatch):
    legacy = {
        "settings": {"auto_paste": False, "hotkey": "ctrl+`"},
        "categories": [{"id": "all", "name": "所有", "fixed": True},
                       {"id": "c1", "name": "AI"}],
        "snippets": [{"id": "s1", "content": "x", "category": "c1"}],
    }
    p = tmp_path / "legacy.json"
    p.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(M, "DATA_FILE", str(p))
    data = M.load_data()
    assert "window_x" in data["settings"]
    assert data["settings"].get("active_cat") == "all"
    assert data["snippets"][0]["content"] == "x"
    assert data["settings"]["hotkey"] == "ctrl+`"


def test_migration_resets_bare_key_hotkey(tmp_path, monkeypatch):
    """事故回归：老版本可以把裸键写进 data.json，升级后必须回退默认热键。

    否则用户升级完一开机，每敲一次那个键面板就弹一次。
    """
    legacy = {
        "settings": {"auto_paste": False, "hotkey": "k"},
        "categories": [{"id": "all", "name": "所有", "fixed": True}],
        "snippets": [],
    }
    p = tmp_path / "legacy_bare.json"
    p.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(M, "DATA_FILE", str(p))
    data = M.load_data()
    assert data["settings"]["hotkey"] == M.DEFAULT_HOTKEY


def test_load_data_falls_back_to_defaults_on_corrupt_file(tmp_path, monkeypatch):
    p = tmp_path / "broken.json"
    p.write_text("{ this is not json", encoding="utf-8")
    monkeypatch.setattr(M, "DATA_FILE", str(p))
    data = M.load_data()
    assert data["settings"]["hotkey"] == M.DEFAULT_HOTKEY
    assert data["categories"][0]["id"] == "all"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
