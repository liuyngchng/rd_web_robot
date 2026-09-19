#!/usr/bin/env python3
"""打包脚本：把 rd_web_robot 打成自包含可执行文件。

用法：
    python build.py          # 打包当前平台
    python build.py --clean  # 清理构建产物后重新打包
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Windows 控制台默认 GBK，emoji 会导致 UnicodeEncodeError；统一用 ASCII 标记
OK = "[OK]"
FAIL = "[FAIL]"


def ensure_deps():
    """确保 PyInstaller 已安装"""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[build] 安装 PyInstaller ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("[build] PyInstaller 安装完成")


def find_playwright_driver_dir() -> Path:
    """定位 Playwright 自带的 driver 目录"""
    import playwright

    return Path(playwright.__file__).resolve().parent / "driver"


def clean():
    """清理构建产物"""
    for name in ["build", "dist", "rd_web_robot.spec"]:
        p = BASE_DIR / name
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
            print(f"[build] 已删除 {name}/")
        elif p.is_file():
            p.unlink()
            print(f"[build] 已删除 {name}")


def build():
    ensure_deps()
    print("[build] 开始打包 ...")

    driver_dir = find_playwright_driver_dir()
    if not driver_dir.exists():
        print(f"[build] {FAIL} 未找到 Playwright driver 目录，请先 pip install playwright")
        sys.exit(1)

    # Playwright 官方 hook 已通过 collect_data_files 自动打包 driver 目录，
    # 无需手动 --add-data

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "rd_web_robot",
        "--windowed",
        "--onefile",
        "--clean",
        "--noconfirm",
        "--hidden-import", "tkinter",
        "--hidden-import", "playwright",
        "--hidden-import", "playwright.sync_api",
        "--exclude-module", "pytest",
        "--exclude-module", "numpy",
        "--exclude-module", "PIL",
        "main.py",
    ]

    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print(f"[build] {FAIL} 打包失败")
        sys.exit(1)

    exe_name = "rd_web_robot.exe" if sys.platform == "win32" else "rd_web_robot"
    exe_path = BASE_DIR / "dist" / exe_name
    if not exe_path.exists():
        print(f"[build] {FAIL} 未找到产物")
        sys.exit(1)

    print(f"[build] {OK} 打包完成：{exe_path}")
    print(f"[build] 产物大小：{exe_path.stat().st_size / 1024 / 1024:.1f} MB")
    print()
    print("[build] 提示：")
    print("  - 首次运行时程序会引导下载 Chromium 浏览器（~170MB）")
    print("  - 如需离线分发，请在本机先运行一次安装浏览器：")
    print("      python -m playwright install chromium")
    print("    然后把 %LOCALAPPDATA%\\ms-playwright 目录一起打包进 zip")
    print()


def main():
    parser = argparse.ArgumentParser(description="打包 rd_web_robot")
    parser.add_argument("--clean", action="store_true", help="清理后重新打包")
    args = parser.parse_args()

    if args.clean:
        clean()
    build()


if __name__ == "__main__":
    main()
