#!/usr/bin/env python3
"""打包脚本：把 RPA Recorder 打成自包含可执行文件。

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


def ensure_deps():
    """确保 PyInstaller 已安装"""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[build] 安装 PyInstaller ...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
        print("[build] PyInstaller 安装完成")


def clean():
    """清理构建产物"""
    for name in ["build", "dist", "rd_rpa.spec"]:
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

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "rd-rpa",
        "--windowed",                    # GUI 程序，不弹控制台
        "--onefile",                     # 单文件 exe
        "--clean",
        "--noconfirm",
        # 显式引入 tkinter（PyInstaller 有时检测不到）
        "--hidden-import", "tkinter",
        "--hidden-import", "playwright",
        "--hidden-import", "playwright.sync_api",
        "--hidden-import", "playwright._impl._driver",
        # 排除不必要的大依赖
        "--exclude-module", "pytest",
        "--exclude-module", "numpy",
        "--exclude-module", "PIL",
        "main.py",
    ]

    result = subprocess.run(cmd, cwd=BASE_DIR)
    if result.returncode != 0:
        print("[build] ❌ 打包失败")
        sys.exit(1)

    exe_name = "rd-rpa.exe" if sys.platform == "win32" else "rd-rpa"
    exe_path = BASE_DIR / "dist" / exe_name
    if not exe_path.exists():
        print("[build] ❌ 未找到产物")
        sys.exit(1)

    print(f"[build] ✅ 打包完成：{exe_path}")
    print(f"[build] 产物大小：{exe_path.stat().st_size / 1024 / 1024:.1f} MB")
    print()
    print("[build] 提示：")
    print("  - 首次运行时程序会自动下载 Chromium 浏览器（~170MB）")
    print("  - 如需离线分发，请在本机先运行一次安装浏览器：")
    print("      python -m playwright install chromium")
    print("    然后把 %LOCALAPPDATA%\\ms-playwright 目录一起打包进 zip")
    print()


def main():
    parser = argparse.ArgumentParser(description="打包 RPA Recorder")
    parser.add_argument("--clean", action="store_true", help="清理后重新打包")
    args = parser.parse_args()

    if args.clean:
        clean()
    build()


if __name__ == "__main__":
    main()
