#!/usr/bin/env python3
"""RPA Recorder — 录制浏览器操作并回放。基于 Playwright codegen 引擎。"""

import json
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Optional

# ── 路径配置 ──────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = BASE_DIR / "recordings"
RECORDINGS_DIR.mkdir(exist_ok=True)
INDEX_FILE = RECORDINGS_DIR / "index.json"


def load_index() -> list[dict]:
    if not INDEX_FILE.exists():
        return []
    try:
        return json.loads(INDEX_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_index(entries: list[dict]) -> None:
    INDEX_FILE.write_text(json.dumps(entries, ensure_ascii=False, indent=2), "utf-8")


# ── 录制 / 回放逻辑 ────────────────────────────────────────

class Recorder:
    """封装 Playwright codegen 子进程管理"""

    def __init__(self, url: str, output_path: Path):
        self.url = url
        self.output_path = output_path
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        cmd = [
            sys.executable, "-m", "playwright", "codegen",
            "--target", "python",
            "--output", str(self.output_path),
            "--browser", "chromium",
            self.url,
        ]
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None


class Player:
    """封装回放：直接跑 codegen 生成的 Python 脚本"""

    def __init__(self, script_path: Path):
        self.script_path = script_path
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        cmd = [sys.executable, str(self.script_path)]
        self.process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def wait(self) -> int:
        if self.process:
            return self.process.wait()
        return -1

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stop(self):
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None


# ── GUI ────────────────────────────────────────────────────

COLORS = {
    "bg": "#1e1e2e",
    "fg": "#cdd6f4",
    "accent": "#cba6f7",
    "accent_hover": "#b4befe",
    "record": "#f38ba8",
    "play": "#a6e3a1",
    "btn_bg": "#313244",
    "btn_hover": "#45475a",
    "entry_bg": "#313244",
    "list_bg": "#181825",
    "list_fg": "#cdd6f4",
    "list_select": "#45475a",
    "status_idle": "#a6adc8",
    "status_recording": "#f38ba8",
    "status_playing": "#a6e3a1",
    "border": "#45475a",
}

FONT_LARGE = ("Segoe UI", 16, "bold")
FONT_NORMAL = ("Segoe UI", 11)
FONT_SMALL = ("Segoe UI", 9)
FONT_MONO = ("Consolas", 10)


class RPARecorderApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("RPA Recorder")
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

        self.build_ui()
        self.refresh_list()
        self.check_subprocess_periodic()

    def center_window(self):
        """窗口居中"""
        self.root.update_idletasks()
        w = 560
        h = 500
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
            header, text=" RPARecorder", font=FONT_LARGE,
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
            btn_frame, "  录制 (Record)  ", self.on_record, COLORS["record"], "black",
        )
        self.record_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6), ipady=12)

        self.play_btn = self._make_btn(
            btn_frame, "  执行 (Replay)  ", self.on_replay, COLORS["play"], "black",
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
            font=FONT_SMALL, bg=COLORS["btn_bg"], fg=COLORS["fg"],
            activebackground=COLORS["btn_hover"], activeforeground=COLORS["fg"],
            relief="flat", padx=10, cursor="hand2",
            highlightthickness=1, highlightbackground=COLORS["border"],
        )
        self.delete_btn.pack(side=tk.RIGHT)

        list_container = tk.Frame(self.root, bg=COLORS["border"])
        list_container.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))

        columns = ("name", "steps", "url", "path")
        self.tree = ttk.Treeview(
            list_container, columns=columns, show="headings",
            selectmode="browse", height=8,
        )
        self.tree.heading("name", text="名称")
        self.tree.heading("steps", text="步数")
        self.tree.heading("url", text="URL")
        self.tree.heading("path", text="文件")
        self.tree.column("name", width=130, minwidth=80)
        self.tree.column("steps", width=50, minwidth=40, anchor="center")
        self.tree.column("url", width=200, minwidth=100)
        self.tree.column("path", width=0, minwidth=0, stretch=False)
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
            background=COLORS["btn_bg"],
            foreground=COLORS["fg"],
            font=FONT_SMALL,
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["list_select"])],
            foreground=[("selected", COLORS["fg"])],
        )

    def _make_btn(self, parent, text, command, color, text_color):
        btn = tk.Button(
            parent, text=text, command=command,
            font=FONT_NORMAL, bg=color, fg=text_color,
            activebackground=color, activeforeground=text_color,
            relief="flat", cursor="hand2",
            borderwidth=0, highlightthickness=0,
        )
        return btn

    # ── 核心操作 ────────────────────────────────────────

    def on_record(self):
        if self.recorder and self.recorder.running:
            self._stop_recording()
            return

        url = self.url_var.get().strip()
        if not url:
            messagebox.showwarning("提示", "请输入 URL")
            return
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.url_var.set(url)

        self._start_recording(url)

    def _start_recording(self, url: str):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_name = f"rec_{ts}.py"
        script_path = RECORDINGS_DIR / script_name

        self.recorder = Recorder(url, script_path)
        # 同步启动（exec 很快，避免与周期性检查产生竞态）
        self.recorder.start()

        # 后台等待 codegen 退出
        def wait():
            if self.recorder.process:
                self.recorder.process.wait()
                self.recorder.process = None
            self.root.after(0, self._on_recording_finished, script_path)

        threading.Thread(target=wait, daemon=True).start()

        self.set_status("recording", f"正在录制 → {url}")
        self.record_btn.config(text="  停止录制 (Stop)  ", bg=COLORS["status_idle"], fg="black")

    def _stop_recording(self):
        if self.recorder:
            self.recorder.stop()
        self.set_status("idle", "就绪")
        self.record_btn.config(text="  录制 (Record)  ", bg=COLORS["record"], fg="black")

    def _on_recording_finished(self, script_path: Path):
        if self.recorder is None:
            return  # 防止线程回调与周期性检查双重触发
        self.recorder = None
        self.record_btn.config(text="  录制 (Record)  ", bg=COLORS["record"], fg="black")
        if script_path.exists() and script_path.stat().st_size > 0:
            script_content = script_path.read_text("utf-8")
            # 估算步数（统计 page./browser. 调用行数）
            step_count = sum(
                1 for line in script_content.splitlines()
                if line.strip().startswith(("page.", "browser.", "context."))
            )
            url = self.url_var.get().strip()
            entry = {
                "name": script_path.name,
                "steps": step_count,
                "url": url,
                "path": str(script_path),
                "created_at": datetime.now().isoformat(),
            }
            self.recordings.insert(0, entry)
            save_index(self.recordings)
            self.set_status("idle", f"录制完成 — {step_count} 步")
        else:
            self.set_status("idle", "录制已取消（未生成记录）")
        self.recorder = None
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

        self._start_replay(script_path)

    def _start_replay(self, script_path: Path):
        self.player = Player(script_path)

        def run():
            self.player.start()
            if self.player.process:
                self.player.process.wait()
                self.player.process = None
            self.root.after(0, self._on_replay_finished)

        threading.Thread(target=run, daemon=True).start()

        self.set_status("playing", f"正在回放 → {script_path.name}")
        self.play_btn.config(text="  停止回放 (Stop)  ", bg=COLORS["status_idle"], fg="black")

    def _stop_replay(self):
        if self.player:
            self.player.stop()
        self.set_status("idle", "就绪")
        self.play_btn.config(text="  执行 (Replay)  ", bg=COLORS["play"], fg="black")

    def _on_replay_finished(self):
        if self.player is None:
            return  # 防止双重触发
        self.player = None
        self.play_btn.config(text="  执行 (Replay)  ", bg=COLORS["play"], fg="black")
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
            # 检查文件是否存在
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
            self._on_recording_finished(self.recorder.output_path)

        if self.player and self.player.running:
            pass  # 仍在回放中
        elif self.player and not self.player.running:
            self._on_replay_finished()

        self._monitor_after_id = self.root.after(2000, self.check_subprocess_periodic)

    def on_close(self):
        """窗口关闭时清理"""
        if self.recorder and self.recorder.running:
            self.recorder.stop()
        if self.player and self.player.running:
            self.player.stop()
        if self._monitor_after_id:
            self.root.after_cancel(self._monitor_after_id)
        self.root.destroy()


# ── 入口 ──────────────────────────────────────────────────

def main():
    root = tk.Tk()
    app = RPARecorderApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()