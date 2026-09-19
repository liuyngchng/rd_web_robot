#!/usr/bin/env python3
"""rd_web_robot — 录制浏览器操作并回放。基于 Playwright 引擎。"""

import json
import logging
import os
import platform
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

# ── 平台检测 ──────────────────────────────────────────────
IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"
IS_MAC = platform.system() == "Darwin"

# ── 路径配置 ──────────────────────────────────────────────
# PyInstaller onefile 和开发模式兼容
if getattr(sys, "frozen", False):
    # 打包模式：exe 所在目录（用户解压的目录）
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)
INDEX_FILE = RECORDINGS_DIR / "index.json"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "rpa.log"


def _default_browsers_dir() -> Path:
    """Chromium 浏览器内核的默认安装目录（playwright install 的默认落点）"""
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "ms-playwright"
    elif IS_MAC:
        return Path.home() / "Library" / "Caches" / "ms-playwright"
    else:
        return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "ms-playwright"


# 关键：必须在首次 import playwright / launch 浏览器之前设置，
# 否则 frozen 环境下 playwright 会回退到 _MEIPASS 临时目录里的
# driver/package/.local-browsers 去找 chromium（找不到）。
if not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_default_browsers_dir())


# ── 日志 ──────────────────────────────────────────────────
def setup_logging() -> logging.Logger:
    logger = logging.getLogger("rpa")
    if logger.handlers:  # 避免重复初始化
        return logger
    logger.setLevel(logging.DEBUG)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    logger.addHandler(handler)
    return logger


log = setup_logging()


def _log_uncaught(exc_type, exc_value, exc_tb):
    """未捕获异常兜底：写日志 + 走默认处理"""
    log.error("未捕获异常", exc_info=(exc_type, exc_value, exc_tb))
    sys.__excepthook__(exc_type, exc_value, exc_tb)


sys.excepthook = _log_uncaught


def _find_playwright_driver_dir() -> Path:
    """定位 Playwright 自带的 driver 目录（含 node.exe + cli.js）"""
    import playwright

    return Path(playwright.__file__).resolve().parent / "driver"


def _find_node_exe() -> Path:
    driver_dir = _find_playwright_driver_dir()
    node_name = "node.exe" if IS_WINDOWS else "node"
    node_path = driver_dir / node_name
    if not node_path.exists():
        raise FileNotFoundError(f"未找到 Playwright 内建 Node.js: {node_path}")
    log.debug("NODE_EXE=%s", node_path)
    return node_path


def _find_cli_js() -> Path:
    cli = _find_playwright_driver_dir() / "package" / "cli.js"
    if not cli.exists():
        raise FileNotFoundError(f"未找到 Playwright CLI: {cli}")
    log.debug("CLI_JS=%s", cli)
    return cli


NODE_EXE = _find_node_exe()
CLI_JS = _find_cli_js()


def get_chromium_browsers_dir() -> Path:
    """Chromium 浏览器内核安装目录（含 PLAYWRIGHT_BROWSERS_PATH 覆盖）"""
    env_path = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if env_path:
        return Path(env_path)
    return _default_browsers_dir()


def is_chromium_installed() -> bool:
    """检测 Chromium 浏览器是否已安装"""
    browsers_dir = get_chromium_browsers_dir()
    if not browsers_dir.exists():
        return False
    chrome_exe_name = "chrome.exe" if IS_WINDOWS else "chrome"
    for item in browsers_dir.glob("chromium-*"):
        if item.is_dir():
            # 子目录名可能是 chrome-win / chrome-win64，递归查找 exe
            for exe in item.rglob(chrome_exe_name):
                return True
    return False


def install_chromium() -> subprocess.CompletedProcess:
    """通过 Playwright 内建 node CLI 安装 Chromium"""
    popen_kwargs: dict = {"capture_output": True, "text": True, "timeout": 300}
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return subprocess.run(
        [str(NODE_EXE), str(CLI_JS), "install", "chromium"],
        **popen_kwargs,
    )


# ── 录制历史管理 ──────────────────────────────────────────


def load_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_index(entries: list[dict]) -> None:
    INDEX_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")


# ── 录制 ──────────────────────────────────────────────────


class Recorder:
    """调用 Playwright 内建 node CLI 的 codegen 命令录制"""

    def __init__(self, url: str, output_path: Path):
        self.url = url
        self.output_path = output_path
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        cmd = [
            str(NODE_EXE),
            str(CLI_JS),
            "codegen",
            "--target", "python",
            "--output", str(self.output_path),
            "--browser", "chromium",
            "--ignore-https-errors",
            self.url,
        ]
        log.info("录制启动: %s", " ".join(cmd))
        popen_kwargs: dict = {
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.PIPE,
        }
        if IS_WINDOWS:
            # 防止 GUI 程序（--windowed）起子进程时弹出控制台窗口
            popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        self.process = subprocess.Popen(cmd, **popen_kwargs)

    def stop(self):
        """通知子进程退出；不阻塞主线程"""
        if self.process:
            self.process.terminate()
            self.process = None
            # process.wait() 由后台线程负责

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None


# ── 回放 ──────────────────────────────────────────────────


class Player:
    """在后台线程中 exec 生成的 Python 脚本；停止时杀死 Chromium 子进程"""

    def __init__(self, script_path: Path):
        self.script_path = script_path
        self._thread: Optional[threading.Thread] = None
        self._stopped_by_user = False
        self._error: Optional[str] = None

    def start(self):
        script_content = self.script_path.read_text("utf-8")
        self._stopped_by_user = False
        self._error = None
        log.info("回放启动: %s (%d 字节)", self.script_path, len(script_content))

        def _run():
            try:
                namespace: dict = {"__name__": "__main__", "__file__": str(self.script_path)}
                exec(compile(script_content, str(self.script_path), "exec"), namespace)
                log.info("回放完成: %s", self.script_path)
            except Exception:
                self._error = traceback.format_exc()
                log.error("回放异常:\n%s", self._error)

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def stop(self):
        """杀死 Chromium 子进程以中断回放"""
        self._stopped_by_user = True
        self._kill_chromium_children()

    @staticmethod
    def _kill_chromium_children():
        """终止当前进程树下的 chromium/chrome 子进程"""
        try:
            popen_kwargs: dict = {"capture_output": True}
            if IS_WINDOWS:
                popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            if IS_WINDOWS:
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe", "/T"], **popen_kwargs)
            else:
                subprocess.run(["pkill", "-f", "chromium"], **popen_kwargs)
        except Exception:
            pass  # 尽力而为，失败也不阻塞

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def error(self) -> Optional[str]:
        return self._error

    @property
    def stopped_by_user(self) -> bool:
        return self._stopped_by_user


# ── GUI ────────────────────────────────────────────────────

COLORS = {
    "bg": "#f5f7fa",
    "fg": "#333333",
    "accent": "#4b6cb7",
    "accent_hover": "#3a5a9e",
    "record": "#c62828",
    "play": "#2e7d32",
    "stop": "#ff4d4d",
    "btn_bg": "#4b6cb7",
    "btn_hover": "#3a5a9e",
    "btn_fg": "#ffffff",
    "entry_bg": "#ffffff",
    "list_bg": "#ffffff",
    "list_fg": "#333333",
    "list_select": "#e8ecf2",
    "status_idle": "#888888",
    "status_recording": "#c62828",
    "status_playing": "#2e7d32",
    "border": "#e0e0e0",
    "heading_bg": "#f8f9fb",
    "heading_fg": "#5f6368",
}

FONT_LARGE = ("Segoe UI", 16, "bold")
FONT_NORMAL = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 10)


class RDWebRobotApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("rd_web_robot")
        self.root.geometry("560x500")
        self.root.minsize(480, 400)
        self.root.configure(bg=COLORS["bg"])
        self.root.resizable(True, True)
        self.center_window()

        self.recorder: Optional[Recorder] = None
        self.player: Optional[Player] = None
        self.recordings: list[dict] = load_index()
        self.url_var = tk.StringVar(value="https://")
        self.status_var = tk.StringVar(value="就绪")
        self._monitor_after_id: Optional[str] = None
        self._recording_url: str = ""  # 录制启动时的 URL，避免录制结束后读到被修改的输入框

        self.build_ui()
        self.refresh_list()
        self.check_subprocess_periodic()
        # 首次运行检查浏览器安装
        self.root.after(500, self._check_browser_on_startup)

    def center_window(self):
        """窗口居中"""
        self.root.update_idletasks()
        w, h = 560, 500
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    # ── UI 构建 ────────────────────────────────────────

    def build_ui(self):
        # 顶部标题栏
        header = tk.Frame(self.root, bg=COLORS["bg"])
        header.pack(fill=tk.X, padx=16, pady=(16, 8))
        tk.Label(
            header, text=" rd_web_robot", font=FONT_LARGE,
            bg=COLORS["bg"], fg=COLORS["accent"],
        ).pack(side=tk.LEFT)

        # URL 输入行
        url_frame = tk.Frame(self.root, bg=COLORS["bg"])
        url_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(
            url_frame, text="URL", font=FONT_SMALL,
            bg=COLORS["bg"], fg=COLORS["fg"],
        ).pack(side=tk.LEFT, padx=(0, 6))
        self.url_entry = tk.Entry(
            url_frame, textvariable=self.url_var, font=FONT_MONO,
            bg=COLORS["entry_bg"], fg=COLORS["fg"],
            insertbackground=COLORS["fg"], relief="flat", borderwidth=0,
            highlightthickness=1, highlightcolor=COLORS["accent"],
            highlightbackground=COLORS["border"],
        )
        self.url_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

        # 两个大按钮
        btn_frame = tk.Frame(self.root, bg=COLORS["bg"])
        btn_frame.pack(fill=tk.X, padx=16, pady=12)

        self.record_btn = self._make_btn(
            btn_frame, "  录制 (Record)  ", self.on_record, COLORS["record"], COLORS["btn_fg"],
        )
        self.record_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=12)

        self.play_btn = self._make_btn(
            btn_frame, "  执行 (Replay)  ", self.on_replay, COLORS["play"], COLORS["btn_fg"],
        )
        self.play_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0), ipady=12)

        # 状态栏
        status_frame = tk.Frame(self.root, bg=COLORS["bg"])
        status_frame.pack(fill=tk.X, padx=16, pady=(0, 8))
        tk.Label(
            status_frame, text="状态：", font=FONT_SMALL,
            bg=COLORS["bg"], fg=COLORS["status_idle"],
        ).pack(side=tk.LEFT)
        self.status_label = tk.Label(
            status_frame, textvariable=self.status_var,
            font=FONT_SMALL, bg=COLORS["bg"], fg=COLORS["status_idle"],
        )
        self.status_label.pack(side=tk.LEFT)

        # 录制历史列表
        list_header = tk.Frame(self.root, bg=COLORS["bg"])
        list_header.pack(fill=tk.X, padx=16, pady=(4, 4))
        tk.Label(
            list_header, text="📋 录制历史", font=FONT_NORMAL,
            bg=COLORS["bg"], fg=COLORS["fg"],
        ).pack(side=tk.LEFT)
        self.delete_btn = tk.Button(
            list_header, text="删除选中", command=self.on_delete,
            font=FONT_SMALL, bg=COLORS["bg"], fg="#c62828",
            activebackground="#ffebee", activeforeground="#c62828",
            relief="flat", padx=10, cursor="hand2",
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        self.delete_btn.pack(side=tk.RIGHT)

        list_container = tk.Frame(self.root, bg=COLORS["border"])
        list_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        columns = ("name", "steps", "url", "_idx")
        self.tree = ttk.Treeview(
            list_container, columns=columns, show="headings",
            selectmode="browse", height=8,
        )
        self.tree.heading("name", text="名称")
        self.tree.heading("steps", text="步数")
        self.tree.heading("url", text="URL")
        self.tree.heading("_idx", text="")
        self.tree.column("name", width=130, minwidth=80)
        self.tree.column("steps", width=50, minwidth=40, anchor="center")
        self.tree.column("url", width=200, minwidth=100)
        self.tree.column("_idx", width=0, minwidth=0, stretch=False)
        self.tree.bind("<Double-1>", lambda e: self.on_replay())

        scrollbar = ttk.Scrollbar(list_container, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # 样式
        style = ttk.Style()
        style.theme_use("default")
        style.configure(
            "Treeview",
            background=COLORS["list_bg"],
            foreground=COLORS["list_fg"],
            fieldbackground=COLORS["list_bg"],
            rowheight=28,
            font=FONT_SMALL,
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["heading_bg"],
            foreground=COLORS["heading_fg"],
            font=FONT_SMALL,
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["list_select"])],
            foreground=[("selected", COLORS["fg"])],
        )

    def _make_btn(self, parent, text, command, color, text_color):
        # 自动推导 hover 色：加深 10%
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
        darken = lambda c: max(0, int(c * 0.9))
        hover_color = f"#{darken(r):02x}{darken(g):02x}{darken(b):02x}"
        btn = tk.Button(
            parent, text=text, command=command,
            font=FONT_NORMAL, bg=color, fg=text_color,
            activebackground=hover_color, activeforeground=text_color,
            relief="flat", cursor="hand2",
            borderwidth=0, highlightthickness=0,
        )
        return btn

    # ── 浏览器安装检测 ──────────────────────────────

    def _check_browser_on_startup(self):
        """启动后检测浏览器，未安装则提示安装"""
        installed = is_chromium_installed()
        log.debug("Chromium 检测: installed=%s dir=%s", installed, get_chromium_browsers_dir())
        if not installed:
            if messagebox.askyesno(
                "浏览器未安装",
                "未检测到 Chromium 浏览器内核，需要下载（~170MB，仅一次）。\n\n是否现在下载？"
            ):
                self._install_browser()
            else:
                log.warning("用户跳过浏览器安装")
                messagebox.showwarning("提示", "未安装浏览器，录制和回放功能将无法使用。")

    def _install_browser(self):
        """后台下载浏览器"""
        self.set_status("recording", "正在下载 Chromium 浏览器...")
        log.info("开始安装 Chromium ...")

        def _do_install():
            try:
                result = install_chromium()
                if result.returncode == 0:
                    log.info("Chromium 安装完成")
                    self.root.after(0, lambda: self.set_status("idle", "浏览器安装完成"))
                else:
                    err = result.stderr.strip()[-300:] if result.stderr else "未知错误"
                    log.error("Chromium 安装失败: code=%d stderr=%s", result.returncode, err)
                    self.root.after(0, lambda: messagebox.showerror(
                        "安装失败",
                        f"Chromium 安装失败 (code={result.returncode})\n\n{err}"
                    ))
                    self.root.after(0, lambda: self.set_status("idle", "就绪"))
            except subprocess.TimeoutExpired:
                log.error("Chromium 安装超时")
                self.root.after(0, lambda: messagebox.showerror(
                    "安装超时", "Chromium 下载超时，请检查网络后重试。"
                ))
                self.root.after(0, lambda: self.set_status("idle", "就绪"))
            except Exception as e:
                log.error("Chromium 安装异常: %s", e)
                self.root.after(0, lambda: messagebox.showerror("安装异常", str(e)))
                self.root.after(0, lambda: self.set_status("idle", "就绪"))

        threading.Thread(target=_do_install, daemon=True).start()

    # ── 核心操作 ────────────────────────────────────────

    def on_record(self):
        if self.recorder and self.recorder.running:
            self._stop_recording()
            return

        url = self.url_var.get().strip()
        if not url or url == "https://":
            messagebox.showwarning("提示", "请输入有效的 URL")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.url_var.set(url)

        if not is_chromium_installed():
            messagebox.showwarning("提示", "请先安装 Chromium 浏览器")
            return

        self._start_recording(url)

    def _start_recording(self, url: str):
        self._recording_url = url  # 锁死录制启动时的 URL
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_name = f"rec_{ts}.py"
        script_path = RECORDINGS_DIR / script_name

        self.recorder = Recorder(url, script_path)
        self.recorder.start()

        if self.recorder.process is None:
            messagebox.showerror("错误", "录制进程启动失败，请确认 Playwright 环境正常")
            return

        # 后台等待 codegen 退出（先捕获 Popen 引用防止 stop() 并发置 None）
        recording_url = url  # 闭包里锁死 URL，防止 start 新录制时覆盖
        process = self.recorder.process

        def wait():
            if process:
                stderr_output = process.communicate()[1]
                exit_code = process.returncode
                if exit_code != 0 and stderr_output:
                    err_text = stderr_output.decode("utf-8", errors="replace").strip()
                    log.error("录制异常退出: code=%d stderr=%s", exit_code, err_text[-500:])
                    self.root.after(0, lambda: messagebox.showerror(
                        "录制错误", f"录制异常退出 (code={exit_code})\n\n{err_text[-500:]}"
                    ))
            self.root.after(0, self._on_recording_finished, script_path, recording_url)

        threading.Thread(target=wait, daemon=True).start()

        self.set_status("recording", f"正在录制 → {url}")
        self.record_btn.config(text="  停止录制 (Stop)  ", bg=COLORS["stop"], fg=COLORS["btn_fg"])

    def _stop_recording(self):
        if self.recorder:
            self.recorder.stop()
        self.set_status("idle", "就绪")
        self.record_btn.config(text="  录制 (Record)  ", bg=COLORS["record"], fg=COLORS["btn_fg"])

    def _on_recording_finished(self, script_path: Path, recording_url: str = ""):
        """录制子进程退出后的回调（由后台线程或周期性检查触发）"""
        if self.recorder is None:
            return
        self.recorder = None
        self.record_btn.config(text="  录制 (Record)  ", bg=COLORS["record"], fg=COLORS["btn_fg"])

        if script_path.exists() and script_path.stat().st_size > 0:
            script_content = script_path.read_text("utf-8")
            step_count = sum(
                1 for line in script_content.splitlines()
                if line.strip().startswith(("page.", "browser.", "context."))
            )
            entry = {
                "name": script_path.name,
                "steps": step_count,
                "url": recording_url or self._recording_url,
                "path": str(script_path),
                "created_at": datetime.now().isoformat(),
            }
            self.recordings.insert(0, entry)
            save_index(self.recordings)
            self.set_status("idle", f"录制完成 — {step_count} 步")
            log.info("录制完成: %s (%d 步, %d 字节)", script_path.name, step_count, len(script_content))
        else:
            self.set_status("idle", "录制已取消（未生成记录）")
            log.warning("录制已取消，脚本未生成或为空: %s", script_path)
        self.root.after(0, self.refresh_list)

    def on_replay(self):
        if self.player and self.player.running:
            self._stop_replay()
            return

        # 先看是否有选中项
        selection = self.tree.selection()
        if selection:
            idx = int(self.tree.item(selection[0], "values")[-1])
            entry = self.recordings[idx]
        elif self.recordings:
            entry = self.recordings[0]
        else:
            messagebox.showwarning("提示", "没有可执行的录制记录，请先录制")
            return

        script_path = Path(entry["path"])
        if not script_path.exists():
            messagebox.showerror("错误", f"脚本文件不存在：\n{script_path}")
            return

        if not is_chromium_installed():
            messagebox.showwarning("提示", "请先安装 Chromium 浏览器")
            return

        self._start_replay(script_path)

    def _start_replay(self, script_path: Path):
        self.player = Player(script_path)
        self.player.start()

        self.set_status("playing", f"正在回放 → {script_path.name}")
        self.play_btn.config(text="  停止回放 (Stop)  ", bg=COLORS["stop"], fg=COLORS["btn_fg"])

    def _stop_replay(self):
        if self.player:
            self.player.stop()
        self.set_status("idle", "就绪")
        self.play_btn.config(text="  执行 (Replay)  ", bg=COLORS["play"], fg=COLORS["btn_fg"])

    def _on_replay_finished(self):
        """回放完成后的回调（由周期性检查触发）"""
        if self.player is None:
            return

        error = self.player.error
        stopped = self.player.stopped_by_user

        self.player = None
        self.play_btn.config(text="  执行 (Replay)  ", bg=COLORS["play"], fg=COLORS["btn_fg"])

        if stopped:
            self.set_status("idle", "回放已停止")
            log.info("回放被用户停止")
        elif error:
            self.set_status("idle", "回放异常")
            log.error("回放失败，详情见上方错误日志")
            messagebox.showerror("回放错误", f"回放过程中发生错误：\n\n{error[-800:]}")
        else:
            self.set_status("idle", "回放完成")

    def on_delete(self):
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("提示", "请先选中要删除的记录")
            return
        idx = int(self.tree.item(selection[0], "values")[-1])
        entry = self.recordings[idx]
        if not messagebox.askyesno("确认", f"删除 {entry['name']}？"):
            return
        script_path = Path(entry["path"])
        if script_path.exists():
            script_path.unlink()
        self.recordings.pop(idx)
        save_index(self.recordings)
        self.refresh_list()

    def refresh_list(self):
        for item in self.tree.get_children():
            self.tree.delete(item)
        for i, entry in enumerate(self.recordings):
            if not Path(entry["path"]).exists():
                continue
            self.tree.insert(
                "", tk.END,
                values=(entry["name"], entry["steps"], entry["url"], i),
            )

    # ── 状态管理 ────────────────────────────────────────

    def set_status(self, state: str, message: str):
        self.status_var.set(message)
        color_map = {
            "idle": COLORS["status_idle"],
            "recording": COLORS["status_recording"],
            "playing": COLORS["status_playing"],
        }
        self.status_label.config(fg=color_map.get(state, COLORS["status_idle"]))

    def check_subprocess_periodic(self):
        """周期性检查子进程状态（兜底：用户直接关浏览器窗口而不是自己点停止）"""
        if self.recorder and self.recorder.running:
            pass  # 仍在录制中
        elif self.recorder and not self.recorder.running:
            # 用户通过关闭浏览器退出 codegen，而不是点停止按钮
            recorder = self.recorder  # 捕获引用，防止回调竞态
            recorder.process = None
            self._on_recording_finished(recorder.output_path, recorder.url)

        if self.player and self.player.running:
            pass  # 仍在回放中
        elif self.player and not self.player.running:
            self._on_replay_finished()

        self._monitor_after_id = self.root.after(2000, self.check_subprocess_periodic)

    def on_close(self):
        """窗口关闭时清理"""
        log.info("用户关闭窗口，开始清理 ...")
        if self.recorder and self.recorder.running:
            self.recorder.stop()
        if self.player and self.player.running:
            self.player.stop()
        if self._monitor_after_id:
            self.root.after_cancel(self._monitor_after_id)
        self.root.destroy()


# ── 入口 ──────────────────────────────────────────────────


def main():
    log.info("[rd_web_robot] 启动")
    log.info("frozen=%s BASE_DIR=%s", getattr(sys, "frozen", False), BASE_DIR)
    log.info("BROWSERS_PATH=%s", os.environ.get("PLAYWRIGHT_BROWSERS_PATH"))
    root = tk.Tk()
    app = RDWebRobotApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
    log.info("[rd_web_robot] 退出")


if __name__ == "__main__":
    main()