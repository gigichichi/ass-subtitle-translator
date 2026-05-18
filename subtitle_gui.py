# -*- coding: utf-8 -*-
"""
字幕处理：选择 ASS → 点击「确定」→ 导出纯文本 → DeepSeek 翻译 → 写回生成 *_output.ass
"""
from __future__ import annotations

import os
import re
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

import requests

# ---------- 与原版脚本一致的可调默认 ----------
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-flash"
BATCH_SIZE = 50

# ---------- 本地 API Key 文件（同目录 api_key.txt，第一行有效内容）----------
API_KEY_FILENAME = "api_key.txt"

# ---------- 少女梦幻风配色（横版布局）----------
BG_APP = "#fff5fb"
BG_PANEL = "#ffffff"
BG_PANEL_SOFT = "#fff0f7"
BORDER_SOFT = "#fbcfe8"
ACCENT_PINK = "#f472b6"
ACCENT_PINK_HOVER = "#ec4899"
ACCENT_LILAC = "#ddd6fe"
TEXT_ROSE = "#9f1239"
TEXT_ROSE_SOFT = "#be185d"
TEXT_MUTED = "#a8557c"
FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_SM = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")
FONT_SUB = ("Microsoft YaHei UI", 9)


def load_api_key_from_file(script_dir: Path) -> str:
    """读取同目录 api_key.txt：跳过空行与 # 注释，返回第一条有效行。"""
    p = script_dir / API_KEY_FILENAME
    if not p.is_file():
        return ""
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return ""
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        return s
    return ""


def replace_first_plain(text: str, replacement: str) -> str:
    """将 text 中第一个非样式标签的纯文本替换为 replacement，保留样式标签"""
    replaced = False

    def repl(m: re.Match[str]) -> str:
        nonlocal replaced
        if replaced or m.group(0).startswith("{"):
            return m.group(0)
        replaced = True
        return replacement

    return re.sub(r"(\{[^}]*\}|[^{]+)", repl, text)


def export_ass_to_txt(ass_path: str) -> str | None:
    """从 ASS 导出每句纯文本到同目录 stem_export.txt，返回导出文件路径；失败返回 None。"""
    output_file = os.path.splitext(ass_path)[0] + "_export.txt"
    try:
        with open(ass_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        extracted: list[str] = []
        for line in lines:
            if line.startswith("Dialogue:"):
                parts = line.split(",", 9)
                if len(parts) >= 10:
                    text = parts[9].rstrip("\n")
                    plain = re.sub(r"\{[^}]*\}", "", text)
                    extracted.append(plain)
        if not extracted:
            return None
        with open(output_file, "w", encoding="utf-8") as out:
            out.write("\n".join(extracted))
        return output_file
    except OSError:
        return None


def translate_batch(
    text: str,
    glossary: str,
    api_key: str,
    base_url: str,
    model: str,
) -> str:
    messages = [
        {
            "role": "system",
            "content": f"""你是专业字幕翻译助手。

【术语表】
{glossary}

【翻译规则】
- 真实换行符（\\n）才是"一行"，\\N 是ASS字幕格式的内部换行标记，不是真正的换行
- 每个真实行单独翻译，保持行数一致
- 直接输出翻译结果，不要包含原文
- 不要添加序号、解释或Markdown格式
- 保留每行开头和结尾的空白字符""",
        },
        {"role": "user", "content": text},
    ]
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "max_tokens": 8000,
            "temperature": 0.3,
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()


def translate_export_file(
    export_path: str,
    glossary: str,
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int,
    log,
) -> str | None:
    """读取 *_export.txt，翻译后写入 *_export_translated.txt，返回译文路径。"""
    p = Path(export_path)
    lines = p.read_text(encoding="utf-8").splitlines(keepends=False)
    results: list[str] = []
    total_batches = (len(lines) + batch_size - 1) // batch_size

    for i in range(0, len(lines), batch_size):
        batch_num = i // batch_size + 1
        log(f"  翻译批次 {batch_num}/{total_batches} …")
        batch = lines[i : i + batch_size]
        batch_text = "\n".join(batch)
        try:
            translated = translate_batch(batch_text, glossary, api_key, base_url, model)
            translated_lines = translated.split("\n")
            if len(translated_lines) != len(batch):
                log(
                    f"  ⚠ 第{batch_num}批行数不一致：原文 {len(batch)} 行，译文 {len(translated_lines)} 行"
                )
            results.extend(translated_lines)
        except Exception as e:
            log(f"  ❌ 第{batch_num}批失败：{e}，该批保留原文")
            results.extend(batch)

    out_path = p.with_name(p.stem + "_translated.txt")
    out_path.write_text("\n".join(results), encoding="utf-8")
    return str(out_path)


def import_txt_to_ass(ass_path: str, export_translated_path: str) -> str | None:
    """用译文替换 Dialogue 中首段纯文本，生成 stem_output.ass。"""
    output_path = os.path.splitext(ass_path)[0] + "_output.ass"
    try:
        with open(ass_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        with open(export_translated_path, "r", encoding="utf-8") as ef:
            export_lines = [line.rstrip("\n") for line in ef]
        idx = 0
        with open(output_path, "w", encoding="utf-8") as out:
            for line in lines:
                if line.startswith("Dialogue:"):
                    parts = line.split(",", 9)
                    if len(parts) >= 10 and idx < len(export_lines):
                        orig_text = parts[9]
                        new_plain = export_lines[idx].replace("\n", r"\N")
                        new_text = replace_first_plain(orig_text, new_plain)
                        parts[9] = new_text + "\n"
                        line = ",".join(parts)
                        idx += 1
                out.write(line)
        return output_path
    except OSError:
        return None


class SubtitleApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("✦ 字幕小梦工坊 · 导出 / 翻译 / 写回")
        self.root.minsize(980, 520)
        self.root.geometry("1040x560")
        self.root.configure(bg=BG_APP)

        self._script_dir = Path(__file__).resolve().parent
        self._busy = False
        self._selected_paths: list[str] = []

        outer = tk.Frame(self.root, bg=BG_APP)
        outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        banner = tk.Frame(outer, bg="#fce7f3", highlightthickness=1, highlightbackground=BORDER_SOFT)
        banner.grid(row=0, column=0, sticky=tk.EW, pady=(0, 12))
        tk.Label(
            banner,
            text="✦ 字幕小梦工坊 ✦",
            font=FONT_TITLE,
            fg=TEXT_ROSE,
            bg="#fce7f3",
        ).pack(side=tk.LEFT, padx=16, pady=10)
        tk.Label(
            banner,
            text="横版工作台 · 左侧填好密钥与术语 · 右侧选文件看日志 · 选好后点「确定」才开始",
            font=FONT_SUB,
            fg=TEXT_MUTED,
            bg="#fce7f3",
        ).pack(side=tk.LEFT, padx=(0, 12), pady=10)

        main = tk.Frame(outer, bg=BG_APP)
        main.grid(row=1, column=0, sticky=tk.NSEW)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        # ---------- 左侧：设置区（竖条）----------
        left = tk.Frame(
            main,
            bg=BG_PANEL,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
            padx=14,
            pady=14,
        )
        left.grid(row=0, column=0, sticky=tk.NSEW, padx=(0, 12))
        left.configure(width=320)
        left.grid_propagate(False)

        tk.Label(left, text="API 与模型", font=FONT_TITLE, fg=TEXT_ROSE, bg=BG_PANEL).pack(anchor=tk.W)

        tk.Label(left, text="API Key（也可写入同目录 api_key.txt）", font=FONT_UI_SM, fg=TEXT_MUTED, bg=BG_PANEL).pack(
            anchor=tk.W, pady=(10, 2)
        )
        self.var_api_key = tk.StringVar(value=load_api_key_from_file(self._script_dir))
        self.ent_api_key = tk.Entry(
            left,
            textvariable=self.var_api_key,
            font=FONT_UI,
            show="*",
            relief=tk.FLAT,
            bg=BG_PANEL_SOFT,
            fg=TEXT_ROSE,
            insertbackground=TEXT_ROSE,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
            highlightcolor=ACCENT_PINK,
        )
        self.ent_api_key.pack(fill=tk.X, pady=(0, 6))

        tk.Label(left, text="API 地址", font=FONT_UI_SM, fg=TEXT_MUTED, bg=BG_PANEL).pack(anchor=tk.W)
        self.var_base_url = tk.StringVar(value=DEFAULT_BASE_URL)
        self.ent_base_url = tk.Entry(
            left,
            textvariable=self.var_base_url,
            font=FONT_UI,
            relief=tk.FLAT,
            bg=BG_PANEL_SOFT,
            fg=TEXT_ROSE,
            insertbackground=TEXT_ROSE,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
            highlightcolor=ACCENT_PINK,
        )
        self.ent_base_url.pack(fill=tk.X, pady=(2, 8))

        tk.Label(left, text="模型", font=FONT_UI_SM, fg=TEXT_MUTED, bg=BG_PANEL).pack(anchor=tk.W)
        self.var_model = tk.StringVar(value=DEFAULT_MODEL)
        self.ent_model = tk.Entry(
            left,
            textvariable=self.var_model,
            font=FONT_UI,
            relief=tk.FLAT,
            bg=BG_PANEL_SOFT,
            fg=TEXT_ROSE,
            insertbackground=TEXT_ROSE,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
            highlightcolor=ACCENT_PINK,
        )
        self.ent_model.pack(fill=tk.X, pady=(2, 12))

        tk.Label(left, text="术语表", font=FONT_UI_SM, fg=TEXT_MUTED, bg=BG_PANEL).pack(anchor=tk.W)
        gloss_row = tk.Frame(left, bg=BG_PANEL)
        gloss_row.pack(fill=tk.X, pady=(2, 0))
        self.var_glossary_path = tk.StringVar()
        self.ent_glossary = tk.Entry(
            gloss_row,
            textvariable=self.var_glossary_path,
            font=FONT_UI_SM,
            relief=tk.FLAT,
            bg=BG_PANEL_SOFT,
            fg=TEXT_ROSE,
            insertbackground=TEXT_ROSE,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
        )
        self.ent_glossary.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn_gloss_browse = tk.Button(
            gloss_row,
            text="浏览",
            font=FONT_UI_SM,
            command=self._browse_glossary,
            relief=tk.FLAT,
            bg=ACCENT_LILAC,
            fg=TEXT_ROSE,
            activebackground="#c4b5fd",
            activeforeground=TEXT_ROSE,
            cursor="hand2",
            padx=10,
            pady=4,
        )
        self.btn_gloss_browse.pack(side=tk.LEFT, padx=(6, 0))
        self.btn_gloss_default = tk.Button(
            gloss_row,
            text="默认",
            font=FONT_UI_SM,
            command=self._use_default_glossary,
            relief=tk.FLAT,
            bg=ACCENT_LILAC,
            fg=TEXT_ROSE,
            activebackground="#c4b5fd",
            activeforeground=TEXT_ROSE,
            cursor="hand2",
            padx=8,
            pady=4,
        )
        self.btn_gloss_default.pack(side=tk.LEFT, padx=(6, 0))

        tk.Frame(left, height=1, bg=BORDER_SOFT).pack(fill=tk.X, pady=16)

        tk.Label(left, text="字幕文件", font=FONT_TITLE, fg=TEXT_ROSE, bg=BG_PANEL).pack(anchor=tk.W)
        tk.Label(
            left,
            text="可多选 ASS，再点「确定」开始处理",
            font=FONT_UI_SM,
            fg=TEXT_MUTED,
            bg=BG_PANEL,
            wraplength=280,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(4, 10))

        btn_row = tk.Frame(left, bg=BG_PANEL)
        btn_row.pack(fill=tk.X)
        self.btn_select = tk.Button(
            btn_row,
            text="选择 ASS…",
            font=FONT_UI,
            command=self._on_select_ass,
            relief=tk.FLAT,
            bg="#fbcfe8",
            fg=TEXT_ROSE,
            activebackground="#f9a8d4",
            activeforeground=TEXT_ROSE,
            cursor="hand2",
            padx=12,
            pady=8,
        )
        self.btn_select.pack(side=tk.LEFT)
        self.btn_confirm = tk.Button(
            btn_row,
            text="确定 ✧",
            font=("Microsoft YaHei UI", 10, "bold"),
            command=self._on_confirm_run,
            relief=tk.FLAT,
            bg=ACCENT_PINK,
            fg="#ffffff",
            activebackground=ACCENT_PINK_HOVER,
            activeforeground="#fff7fb",
            cursor="hand2",
            padx=18,
            pady=8,
        )
        self.btn_confirm.pack(side=tk.LEFT, padx=(10, 0))
        self.btn_confirm.configure(state=tk.DISABLED)

        self.var_status = tk.StringVar(value="就绪 · 请先选择 ASS 文件")
        tk.Label(
            left,
            textvariable=self.var_status,
            font=FONT_UI_SM,
            fg=TEXT_ROSE_SOFT,
            bg=BG_PANEL,
            wraplength=280,
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(14, 0))

        # ---------- 右侧：预览 + 日志（横版主区域）----------
        right = tk.Frame(main, bg=BG_APP)
        right.grid(row=0, column=1, sticky=tk.NSEW)
        right.rowconfigure(1, weight=1)
        right.columnconfigure(0, weight=1)

        preview_wrap = tk.Frame(
            right,
            bg=BG_PANEL,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
            padx=10,
            pady=10,
        )
        preview_wrap.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))
        preview_wrap.columnconfigure(0, weight=1)

        tk.Label(preview_wrap, text="当前选中的文件", font=FONT_UI, fg=TEXT_ROSE, bg=BG_PANEL).grid(
            row=0, column=0, sticky=tk.W
        )
        self._file_preview = tk.Text(
            preview_wrap,
            height=5,
            wrap=tk.WORD,
            font=FONT_UI_SM,
            fg=TEXT_ROSE,
            bg=BG_PANEL_SOFT,
            relief=tk.FLAT,
            padx=8,
            pady=6,
            state=tk.DISABLED,
            cursor="arrow",
            highlightthickness=0,
        )
        self._file_preview.grid(row=1, column=0, sticky=tk.EW, pady=(6, 0))

        log_wrap = tk.Frame(
            right,
            bg=BG_PANEL,
            highlightthickness=1,
            highlightbackground=BORDER_SOFT,
            padx=10,
            pady=10,
        )
        log_wrap.grid(row=1, column=0, sticky=tk.NSEW)
        log_wrap.rowconfigure(1, weight=1)
        log_wrap.columnconfigure(0, weight=1)

        tk.Label(log_wrap, text="运行日志", font=FONT_UI, fg=TEXT_ROSE, bg=BG_PANEL).grid(row=0, column=0, sticky=tk.W)
        self.log_widget = scrolledtext.ScrolledText(
            log_wrap,
            height=12,
            wrap=tk.WORD,
            font=("Consolas", 9),
            fg=TEXT_ROSE,
            bg="#fffafd",
            insertbackground=TEXT_ROSE,
            relief=tk.FLAT,
            padx=8,
            pady=6,
            state=tk.DISABLED,
            highlightthickness=0,
        )
        self.log_widget.grid(row=1, column=0, sticky=tk.NSEW, pady=(6, 0))

        self._use_default_glossary()
        self._refresh_file_preview()

    def _refresh_file_preview(self) -> None:
        self._file_preview.configure(state=tk.NORMAL)
        self._file_preview.delete("1.0", tk.END)
        if not self._selected_paths:
            self._file_preview.insert(tk.END, "（尚未选择文件）")
        else:
            for p in self._selected_paths:
                self._file_preview.insert(tk.END, p + "\n")
        self._file_preview.configure(state=tk.DISABLED)

        if self._selected_paths:
            self.btn_confirm.configure(state=tk.NORMAL)
            self.var_status.set(f"已选择 {len(self._selected_paths)} 个文件，点击「确定」开始")
        else:
            self.btn_confirm.configure(state=tk.DISABLED)
            self.var_status.set("就绪 · 请先选择 ASS 文件")

    def _use_default_glossary(self) -> None:
        default = self._script_dir / "术语表.csv"
        if default.exists():
            self.var_glossary_path.set(str(default))
        else:
            self.var_glossary_path.set("")

    def _browse_glossary(self) -> None:
        path = filedialog.askopenfilename(
            title="选择术语表",
            filetypes=[("CSV", "*.csv"), ("所有文件", "*.*")],
        )
        if path:
            self.var_glossary_path.set(path)

    def _on_select_ass(self) -> None:
        if self._busy:
            return
        paths = filedialog.askopenfilenames(
            title="选择 ASS 字幕文件",
            filetypes=[("ASS 字幕", "*.ass"), ("所有文件", "*.*")],
        )
        if not paths:
            return
        self._selected_paths = list(paths)
        self._refresh_file_preview()

    def _append_log(self, s: str) -> None:
        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.insert(tk.END, s + "\n")
        self.log_widget.see(tk.END)
        self.log_widget.configure(state=tk.DISABLED)

    def log(self, s: str) -> None:
        self.root.after(0, lambda: self._append_log(s))

    def set_status(self, s: str) -> None:
        self.root.after(0, lambda: self.var_status.set(s))

    def set_busy(self, busy: bool) -> None:
        def _apply() -> None:
            self._busy = busy
            st = tk.DISABLED if busy else tk.NORMAL
            self.btn_select.configure(state=st)
            self.btn_gloss_browse.configure(state=st)
            self.btn_gloss_default.configure(state=st)
            self.ent_api_key.configure(state=st)
            self.ent_base_url.configure(state=st)
            self.ent_model.configure(state=st)
            self.ent_glossary.configure(state=st)
            if busy:
                self.btn_confirm.configure(state=tk.DISABLED)
            else:
                self.btn_confirm.configure(
                    state=tk.NORMAL if self._selected_paths else tk.DISABLED
                )

        self.root.after(0, _apply)

    def _on_confirm_run(self) -> None:
        if self._busy:
            return
        paths = list(self._selected_paths)
        if not paths:
            messagebox.showinfo("提示", "请先选择要处理的 ASS 字幕。")
            return
        api_key = self.var_api_key.get().strip()
        if not api_key:
            messagebox.showwarning("提示", "请填写 API Key，或在同目录放置 api_key.txt。")
            return
        base_url = self.var_base_url.get().strip() or DEFAULT_BASE_URL
        model = self.var_model.get().strip() or DEFAULT_MODEL
        gloss_path = self.var_glossary_path.get().strip()
        glossary = ""
        if gloss_path and Path(gloss_path).is_file():
            try:
                glossary = Path(gloss_path).read_text(encoding="utf-8")
            except OSError as e:
                messagebox.showerror("错误", f"无法读取术语表：{e}")
                return

        self.log_widget.configure(state=tk.NORMAL)
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.configure(state=tk.DISABLED)

        def worker() -> None:
            self.set_busy(True)
            try:
                for n, ass_path in enumerate(paths, 1):
                    self.set_status(f"处理中 ({n}/{len(paths)})：{Path(ass_path).name}")
                    self.log(f"======== 文件 {n}/{len(paths)}：{ass_path} ========")
                    self.log("① 导出纯文本 …")
                    export_path = export_ass_to_txt(ass_path)
                    if not export_path:
                        self.log("❌ 导出失败或未找到 Dialogue 行，跳过。")
                        continue
                    self.log(f"   → {export_path}")

                    self.log("② 调用 API 翻译 …")
                    trans_path = translate_export_file(
                        export_path,
                        glossary,
                        api_key,
                        base_url,
                        model,
                        BATCH_SIZE,
                        self.log,
                    )
                    if not trans_path:
                        self.log("❌ 翻译失败，跳过导入。")
                        continue
                    self.log(f"   → {trans_path}")

                    self.log("③ 导入写回 ASS …")
                    out_ass = import_txt_to_ass(ass_path, trans_path)
                    if not out_ass:
                        self.log("❌ 导入失败。")
                    else:
                        self.log(f"✓ 完成：{out_ass}")

                self.set_status("全部完成 · 可继续选择文件后再次确定")
            except Exception as e:
                self.log(f"❌ 未捕获错误：{e}")
                self.set_status("出错")
                self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
            finally:
                self.set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    SubtitleApp().run()


if __name__ == "__main__":
    main()
