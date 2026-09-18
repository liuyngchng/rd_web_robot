# RPA Recorder

录制浏览器操作并一键回放的轻量工具。基于 **Playwright codegen** 引擎，跨平台（Windows / Linux / macOS），用户无需安装 Python 环境。

## 功能

- 🔴 **录制**：打开浏览器，记录用户所有点击、输入、跳转等操作
- ▶️ **执行**：一键复刻录制的操作流程
- 📋 **历史管理**：录制记录自动保存，可随时回放或删除

## 用户使用方式

1. 解压 zip
2. 双击 `rd-rpa.exe`（Linux/macOS 为 `./rd-rpa`）
3. 首次运行自动下载浏览器内核（~170MB，仅一次）
4. 输入 URL → 点「录制」→ 正常操作浏览器 → 关闭浏览器窗口结束录制
5. 点「执行」→ 自动回放

## 开发者使用

### 环境要求

- Python 3.9+
- Playwright（`pip install playwright`）
- 浏览器内核（`python -m playwright install chromium`）

### 运行

```bash
python main.py
```

### 打包为可执行文件

```bash
python build.py           # 打包当前平台
python build.py --clean   # 清理后重新打包
```

产物在 `dist/` 目录。

### 离线分发

若目标机器无网络（无法首次下载浏览器），需提前准备浏览器内核：

1. 本机运行 `python -m playwright install chromium`
2. 打包时把 `%LOCALAPPDATA%\ms-playwright`（Windows）或 `~/.cache/ms-playwright`（Linux）目录连同 exe 一起分发
3. 设置环境变量 `PLAYWRIGHT_BROWSERS_PATH` 指向该目录

## 架构

```
main.py          → GUI（tkinter）+ 业务逻辑
  ├─ Recorder    → 调用 playwright codegen 录制
  ├─ Player      → 执行录制的脚本
  └─ recordings/ → 脚本 + index.json 索引
```

录制引擎复用 Playwright 官方 `codegen`，稳定性和选择器策略均有保障。

## 目录结构

```
rd_rpa/
├── main.py           # 主程序（GUI + 逻辑）
├── build.py          # 打包脚本
├── recordings/       # 录制产物（运行时生成）
└── README.md
```
