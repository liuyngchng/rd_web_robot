# rd_web_robot

录制浏览器操作并一键回放的轻量工具。基于 **Playwright** 引擎，跨平台（Windows / Linux / macOS），用户无需安装 Python 环境。

## 功能

- 🔴 **录制**：打开浏览器，记录用户所有点击、输入、跳转等操作
- ▶️ **执行**：一键复刻录制的操作流程
- 📋 **历史管理**：录制记录自动保存，可随时回放或删除

## 用户使用方式

1. 解压 zip
2. 双击 `rd_web_robot.exe`（Linux/macOS 为 `./rd_web_robot`）
3. 首次运行会提示下载浏览器内核（~170MB，仅一次）
4. 输入 URL → 点「录制」→ 正常操作浏览器 → 关闭浏览器窗口结束录制
5. 点「执行」→ 自动回放

## 开发者使用

### 环境要求

- Python 3.9+
- 依赖安装：`pip install -r requirements.txt`
- 浏览器内核（`python -m playwright install chromium`）

### 运行

```bash
python main.py
```

### 打包为可执行文件

在**当前平台**打包本平台的可执行文件。跨平台打包需要分别在对应系统上执行。

```bash
python build.py           # 打包当前平台
python build.py --clean   # 清理后重新打包
```

| 打包平台 | 产物 |
|----------|------|
| Windows | `dist/rd_web_robot.exe` |
| Linux | `dist/rd_web_robot` |
| macOS | `dist/rd_web_robot` |

Windows 产物约 48MB，Linux/macOS 类似。

### 离线分发

若目标机器无网络（无法首次下载浏览器），需提前准备浏览器内核：

1. 本机运行 `python -m playwright install chromium`
2. 把浏览器目录连同可执行文件一起分发：

| 平台 | 浏览器目录 |
|------|-----------|
| Windows | `%LOCALAPPDATA%\ms-playwright` |
| Linux | `~/.cache/ms-playwright` |
| macOS | `~/Library/Caches/ms-playwright` |

3. 设置环境变量 `PLAYWRIGHT_BROWSERS_PATH` 指向该目录

或者把浏览器目录直接放在 `rd_web_robot` 同目录下的 `.local-browsers` 目录中（不需要设环境变量，程序会自动检测 `PLAYWRIGHT_BROWSERS_PATH` 未配置时的默认路径）。

## 架构

```
main.py            → GUI（tkinter）+ 业务逻辑
  ├─ Recorder      → 调用 Playwright 内建 node + cli.js（codegen）录制
  ├─ Player        → 在后台线程中 exec 录制的 Python 脚本回放
  └─ recordings/   → 脚本 + index.json 索引
```

录制引擎走 Playwright 自带的 Node.js + CLI（`playwright/driver/` 目录），不依赖系统 Python 或 Node，稳定性和选择器策略均有保障。打包时通过 Playwright 官方 PyInstaller hook 自动打入 exe。

## 目录结构

```
rd_web_robot/
├── main.py           # 主程序（GUI + 逻辑）
├── build.py          # 打包脚本
├── recordings/       # 录制产物（运行时生成）
├── logs/             # 运行日志（运行时生成）
└── README.md
```

## 问题排查

程序运行日志在 `logs/rpa.log`，遇到异常时可查看该文件获取完整堆栈信息。日志文件最大 2MB，保留最近 3 个历史文件。