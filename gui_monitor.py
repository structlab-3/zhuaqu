"""
监控 GUI：
- 可选配置文件/输出文件
- 关键词输入（逗号分隔），可覆盖配置中的 queries（search_engine/http_html_search/browser_search）
- 实时日志，中文界面，进度条显示 Cycle 进度
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk, filedialog, messagebox
import sys

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = BASE_DIR / "config.search_engine.sample.json"
DEFAULT_OUTPUT = BASE_DIR / "drafts_output.json"


class MonitorGUI(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("监控运行")
        self.geometry("820x640")

        self.config_path = tk.StringVar(value=str(DEFAULT_CONFIG))
        self.output_path = tk.StringVar(value=str(DEFAULT_OUTPUT))
        self.running = False
        self.query_text = tk.StringVar(value="论文辅导")
        self.site_var = tk.StringVar(value="zhihu")
        self.status_text = tk.StringVar(value="就绪")
        self.progress_value = tk.IntVar(value=0)
        self.progress_max = tk.IntVar(value=1)

        self._build_ui()

    def _build_ui(self) -> None:
        frm = ttk.Frame(self, padding=10)
        frm.pack(fill="both", expand=True)

        # 配置文件
        ttk.Label(frm, text="配置文件:").grid(row=0, column=0, sticky="w")
        entry_cfg = ttk.Entry(frm, textvariable=self.config_path, width=70)
        entry_cfg.grid(row=0, column=1, sticky="ew", padx=5)
        ttk.Button(frm, text="浏览", command=self.browse_config).grid(row=0, column=2, sticky="w")

        # 输出
        ttk.Label(frm, text="输出 JSON:").grid(row=1, column=0, sticky="w", pady=(5, 0))
        entry_out = ttk.Entry(frm, textvariable=self.output_path, width=70)
        entry_out.grid(row=1, column=1, sticky="ew", padx=5, pady=(5, 0))
        ttk.Button(frm, text="浏览", command=self.browse_output).grid(row=1, column=2, sticky="w", pady=(5, 0))

        # 关键词
        ttk.Label(frm, text="关键词(逗号分隔):").grid(row=2, column=0, sticky="w", pady=(5, 0))
        entry_q = ttk.Entry(frm, textvariable=self.query_text, width=70)
        entry_q.grid(row=2, column=1, sticky="ew", padx=5, pady=(5, 0))
        ttk.Label(frm, text="站点:").grid(row=3, column=0, sticky="w", pady=(5, 0))
        site_cb = ttk.Combobox(frm, textvariable=self.site_var, state="readonly", values=("zhihu", "csdn", "tieba", "reddit", "duckduckgo"), width=15)
        site_cb.grid(row=3, column=1, sticky="w", padx=5, pady=(5, 0))

        # 按钮 + 状态 + 进度
        btn_frame = ttk.Frame(frm)
        btn_frame.grid(row=4, column=0, columnspan=3, sticky="we", pady=(10, 5))
        self.btn_run = ttk.Button(btn_frame, text="开始运行", command=self.start_run)
        self.btn_run.pack(side="left", padx=(0, 6))
        self.btn_load = ttk.Button(btn_frame, text="重新加载输出", command=self.load_output)
        self.btn_load.pack(side="left", padx=(0, 6))
        self.status_label = ttk.Label(btn_frame, textvariable=self.status_text)
        self.status_label.pack(side="left", padx=(10, 6))
        self.progress = ttk.Progressbar(btn_frame, variable=self.progress_value, maximum=1, length=200, mode="determinate")
        self.progress.pack(side="left", padx=(0, 6), fill="x", expand=True)

        # 日志
        ttk.Label(frm, text="日志:").grid(row=5, column=0, sticky="w", pady=(5, 0))
        self.log_text = tk.Text(frm, height=10, wrap="word", bg="#0f172a", fg="#e5e7eb", insertbackground="#e5e7eb")
        self.log_text.grid(row=6, column=0, columnspan=3, sticky="nsew")

        # 草稿
        ttk.Label(frm, text="匹配草稿:").grid(row=7, column=0, sticky="w", pady=(5, 0))
        self.results_text = tk.Text(frm, height=12, wrap="word")
        self.results_text.grid(row=8, column=0, columnspan=3, sticky="nsew")

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(6, weight=1)
        frm.rowconfigure(8, weight=1)

    def browse_config(self) -> None:
        path = filedialog.askopenfilename(
            title="选择配置 JSON", initialdir=str(BASE_DIR), filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if path:
            self.config_path.set(path)

    def browse_output(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择输出 JSON",
            initialdir=str(BASE_DIR),
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self.output_path.set(path)

    def append_log(self, text: str) -> None:
        self.log_text.insert("end", text)
        self.log_text.see("end")

    def set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        self.btn_run.config(state=state)
        if not running:
            self.status_text.set("就绪")
            self.progress_value.set(0)

    def start_run(self) -> None:
        if self.running:
            return
        cfg_path = Path(self.config_path.get())
        out = self.output_path.get()
        if not cfg_path.exists():
            messagebox.showerror("错误", f"未找到配置文件: {cfg_path}")
            return

        # 读取配置
        temp_cfg_path = BASE_DIR / "_tmp_gui_config.json"
        try:
            cfg_data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:
            messagebox.showerror("错误", f"读取配置失败: {e}")
            return

        # 覆盖关键词和站点
        q_text = self.query_text.get().strip()
        source_type = cfg_data.get("source", {}).get("type")
        if q_text and source_type in ("search_engine", "http_html_search", "browser_search"):
            keywords = [x.strip() for x in q_text.split(",") if x.strip()]
            cfg_data.setdefault("source", {})["queries"] = keywords
            cfg_data["source"]["site"] = self.site_var.get()
            # 自动设置 engine：duckduckgo 走非浏览器，其他站点走浏览器
            if cfg_data["source"]["site"] == "duckduckgo":
                cfg_data["source"]["engine"] = "duckduckgo"
            else:
                cfg_data["source"]["engine"] = "browser"
            temp_cfg_path.write_text(json.dumps(cfg_data, ensure_ascii=False, indent=2), encoding="utf-8")
            cfg_to_use = str(temp_cfg_path)
        else:
            cfg_to_use = str(cfg_path)

        # 进度初始化
        self.progress_value.set(0)
        self.progress_max.set(cfg_data.get("max_cycles", 1))
        self.progress.config(maximum=self.progress_max.get())
        self.status_text.set("运行中...")

        def worker():
            self.set_running(True)
            cmd = [sys.executable, str(BASE_DIR / "monitor_main.py"), "--config", cfg_to_use, "--output", out]
            self.append_log(f"\n$ {' '.join(cmd)}\n")
            try:
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    env=env,
                )
                assert proc.stdout is not None
                for line in proc.stdout:
                    self.append_log(line)
                    if "Cycle " in line and "events=" in line:
                        try:
                            parts = line.strip().split()
                            for p in parts:
                                if p.startswith("Cycle"):
                                    cycle_num = int(p.replace("Cycle", "").replace(":", ""))
                                    self.progress_value.set(min(cycle_num, self.progress_max.get()))
                                    break
                        except Exception:
                            pass
                proc.wait()
                self.append_log(f"[DONE] exit {proc.returncode}\n")
            except Exception as e:
                self.append_log(f"[ERROR] {e}\n")
            finally:
                # ensure UI reset
                self.set_running(False)
                # 填满进度条
                self.progress_value.set(self.progress_max.get())
                self.status_text.set("完成")
                # reload output
                try:
                    self.load_output()
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def load_output(self) -> None:
        out = Path(self.output_path.get())
        if not out.exists():
            messagebox.showwarning("提示", f"未找到输出文件: {out}")
            return
        try:
            data = json.loads(out.read_text(encoding="utf-8"))
        except Exception as e:
            messagebox.showerror("错误", f"读取输出失败: {e}")
            return
        drafts = data.get("drafts", [])
        events = data.get("events", [])
        lines = [f"事件数量: {len(events)}", "==== 事件列表 ===="]
        for e in events:
            lines.append(f"- {e.get('title','')} | {e.get('url','')}")
        lines.append("\n草稿数量: {0}".format(len(drafts)))
        lines.append("==== 草稿列表 ====")
        for d in drafts:
            lines.append(f"- [{d.get('rule_id','')}] {d.get('draft_text','')}")
        self.results_text.delete("1.0", "end")
        self.results_text.insert("end", "\n".join(lines))


def main():
    app = MonitorGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
