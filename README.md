<!-- badges -->
[![License](https://img.shields.io/github/license/huanweide/floatsnip)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%2010%2F11-blue)](https://www.microsoft.com/windows)
[![Python](https://img.shields.io/badge/Python-3.x-3776AB)](https://www.python.org)
[![Release](https://img.shields.io/github/v/release/huanweide/floatsnip)](releases)
<!-- /badges -->

# FloatSnip · 桌面悬浮球快贴工具

> 一个随时浮在桌面的小圆球：常用的文字「就在指尖」，点一下就复制，绝不打断心流。免费、开源、单文件、免安装、纯本地。

复制粘贴是日常最高频、也最打断心流的操作之一——写代码要反复找 prompt、发话术要来回切换窗口、账号命令模板天天复制。FloatSnip 想做的很简单：让常用文字常驻桌面，零延迟拖到顺手位置，点开就看到，点一下就复制，完了。

## 功能特性

| 功能 | 说明 |
|------|------|
| 真正的悬浮球（无白边） | 通过 Win32 `SetWindowRgn` 把窗口裁成圆形，浮在桌面、无白边、不是方形白块 |
| 丝滑拖动 | 原生鼠标事件 + `geometry()` 直接移动，单进程零延迟、跟手 |
| 快捷键召唤（可自定义） | 默认 `Ctrl + \`` 唤起/收起；设置里点一下快捷键框、按下组合键即更换并记住 |
| 列表即首页 | 展开即见全部常用语，可滚动；点任意一条自动复制并亮绿色「已复制」确认 |
| 分类标签 | 预置「所有 / AI / 平常常用 / 工作 / 学习 / 生活」，可改名、新建（最多 10 个） |
| 随手编辑 | 底部「＋ 新建常用语」随时加；每条带编辑、删除；支持中文输入法，软上限 10000 字 |
| 复制自检 | 复制后读回剪贴板自检：成功亮绿、失败红色提示，确保「真复制了」 |
| 纯本地 · 零账户 | 全部内容存本机 `AppData\Local\FloatSnip\data.json`，可改可同步、不上传任何服务器 |
| 可选自动粘贴 | 设置开启后，复制完自动向刚才的窗口粘贴（实验性） |
| 高分屏清晰 | 启用 Windows DPI 感知，125%/150% 缩放下不再发虚 |
| 系统托盘常驻 | 左键唤起浮球、右键菜单（显示 / 设置 / 退出），退出时清理图标 |
| 开机自启（默认关闭） | 见下方「手动启动」说明；可在设置里开启 |

## 快速开始

1. 前往 [Releases](releases) 下载最新 `FloatSnip.exe`。
2. 双击运行（无需安装），桌面上出现一个小圆球。
3. **按住拖动**到顺手的位置；**单击圆球**（或按 `Ctrl + \``）展开面板。
4. 点面板里的任意常用语 → 显示「已复制」，去目标处 `Ctrl + V` 即可。
5. 点「＋ 新建常用语」添加你自己的内容；点条目的编辑图标可修改、删除图标可删除。

> 数据文件位置：`%AppData%\Local\FloatSnip\data.json`（可直接备份或编辑）。

## 手动启动（重要：开机自启已关闭）

当前版本**默认不会**在系统开机时自动启动。请选择以下任一方式手动启动：

- **直接运行**：双击 `FloatSnip.exe` 即可。
- **放入启动文件夹（实现自启）**：把 `FloatSnip.exe` 的快捷方式放进启动文件夹。
  按 `Win + R` 输入 `shell:startup` 打开该文件夹，将快捷方式拖入即可。
- **设置内开启**：运行后在面板设置里勾选「开机自启」，下次开机自动出现（写入注册表
  `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\FloatSnip`）。

退出方式：右键系统托盘图标 → 「退出」，或面板标题栏菜单关闭。每个无边框窗口都提供至少两种关闭路径，不会留下「关不掉」的窗口。

## 从源码运行与打包

环境要求：Windows 10/11、Python 3.x。

```bash
# 1. 直接运行源码
python main.py

# 2. 打包为单文件 exe（需先 pip install pyinstaller）
pyinstaller FloatSnip.spec
# 产物：dist/FloatSnip.exe
```

`FloatSnip.spec` 已预置好 PyInstaller 配置（`console=False`、`upx=True`、单文件、无控制台窗口），
目标平台 Windows 10/11。

## 配置说明

所有配置保存在本机 JSON，路径：`%AppData%\Local\FloatSnip\data.json`。

| 配置项 | 含义 | 默认值 |
|--------|------|--------|
| `auto_paste` | 复制后自动粘贴 | 关闭 |
| `hotkey` | 唤起见/收起的全局快捷键 | `ctrl+\`` |
| `autostart` | 开机自启 | 关闭 |
| `active_cat` | 记忆上次选中的分类 | `all` |
| `window_x` / `window_y` | 浮球位置（自动记忆） | 自动 |

分类管理与快捷键修改均在面板「设置」（齿轮）里完成，改完立即生效并持久化。

## 工作原理

```
浮球窗口 ──Win32 SetWindowRgn/CreateEllipticRgn──▶ 圆形裁剪（去白边）
   │
   ├─ 拖动 ──tkinter 鼠标事件 + geometry()──▶ 零延迟跟手移动
   ├─ 全局热键 ──Win32 RegisterHotKey──▶ 唤起/收起（零全局钩子，已告别 pynput）
   ├─ 复制 ──ctypes 写剪贴板 + 读回自检──▶ 绿/红反馈
   └─ 数据 ──本地 JSON（data.json）──▶ 纯本地、零上传
```

- UI 用 Python 标准库 `tkinter` 构建，零额外 GUI 框架依赖（体积小、启动快）。
- 圆形窗口：Win32 `SetWindowRgn` + `CreateEllipticRgn` 裁剪，彻底消除白边。
- 拖动：原生事件 + `geometry()` 直接移动（单进程、丝滑跟手）。
- 全局热键：`RegisterHotKey`（零钩子依赖）；剪贴板：ctypes；存储：本地 JSON。
- 打包：PyInstaller 单文件 exe。

## 目录结构

```
floatsnip/
├── main.py          # 全部源码（单文件，含浮球/面板/设置/托盘/自启逻辑）
├── test_logic.py    # 逻辑自测
├── FloatSnip.spec   # PyInstaller 打包配置
├── LICENSE          # MIT
└── README.md
```

## 许可证

MIT —— 完全免费，欢迎 Star 与 PR。
