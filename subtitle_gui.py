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
BATCH_SIZE = 40

# ── 行号标记：强制 AI 保持行数一致 ──
LINE_MARKER_RE = re.compile(r'^\[L\d{4}\]')


def add_line_markers(lines: list[str]) -> list[str]:
    """给每行添加行号前缀 [L0001]"""
    return [f"[L{i+1:04d}]{line}" for i, line in enumerate(lines)]


def strip_line_markers(lines: list[str]) -> list[str]:
    """去掉行号前缀"""
    return [LINE_MARKER_RE.sub('', line, count=1) for line in lines]


def validate_line_counts(
    original: list[str], translated: list[str], marker_prefix: bool = True
) -> tuple[bool, str]:
    """验证翻译后行数是否与原文一致"""
    if len(original) != len(translated):
        return False, f"行数不匹配：原文 {len(original)} 行 → 译文 {len(translated)} 行"
    if marker_prefix:
        missing = []
        for i in range(len(original)):
            expected = f"[L{i+1:04d}]"
            if not translated[i].startswith(expected):
                missing.append(i + 1)
        if missing:
            return False, f"缺少行号标记：行 {missing[:10]}{'...' if len(missing) > 10 else ''}"
    return True, "OK"

# ---------- 本地 API Key 文件（同目录 api_key.txt，第一行有效内容）----------
API_KEY_FILENAME = "api_key.txt"

# ---------- 双主题配色 ----------
# 全局可变颜色变量 — switch_theme() 切换时批量更新
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
BANNER_BG = "#fce7f3"

THEME_DATA = {
    # ── 经典粉：淡雅，面板纯白 ──
    "🌸 经典粉": {
        "BG_APP": "#fff5fb", "BG_PANEL": "#ffffff", "BG_PANEL_SOFT": "#fff0f7",
        "BORDER_SOFT": "#fbcfe8", "ACCENT_PINK": "#f472b6", "ACCENT_PINK_HOVER": "#ec4899",
        "ACCENT_LILAC": "#ddd6fe", "TEXT_ROSE": "#9f1239", "TEXT_ROSE_SOFT": "#be185d",
        "TEXT_MUTED": "#a8557c", "BANNER_BG": "#fce7f3",
    },
    # ── 甜蜜糖果：浓郁粉嫩，Material Design Pink，整体泛粉 ──
    "🍬 甜蜜糖果": {
        "BG_APP": "#fce4ec",          # ← 明显粉底（经典是几乎白的 #fff5fb）
        "BG_PANEL": "#fff0f5",        # ← 淡紫粉面板（经典是纯白 #ffffff）
        "BG_PANEL_SOFT": "#fce4ec",   # ← 输入区与底色统一
        "BORDER_SOFT": "#f48fb1",     # ← 清晰可见的粉边框
        "ACCENT_PINK": "#e91e63",     # ← 亮粉按钮！（经典是淡粉 #f472b6）
        "ACCENT_PINK_HOVER": "#c2185b",
        "ACCENT_LILAC": "#e1bee7",    # ← 浅紫
        "TEXT_ROSE": "#880e4f",       # ← 深玫红文字
        "TEXT_ROSE_SOFT": "#ad1457",
        "TEXT_MUTED": "#d81b60",      # ← 深粉灰色
        "BANNER_BG": "#f8bbd0",       # ← 婴儿粉 Banner
    },
}

FONT_UI = ("Microsoft YaHei UI", 10)
FONT_UI_SM = ("Microsoft YaHei UI", 9)
FONT_TITLE = ("Microsoft YaHei UI", 13, "bold")
FONT_SUB = ("Microsoft YaHei UI", 9)


def switch_theme(theme_name: str):
    """切换全局配色变量"""
    global BG_APP, BG_PANEL, BG_PANEL_SOFT, BORDER_SOFT, BANNER_BG
    global ACCENT_PINK, ACCENT_PINK_HOVER, ACCENT_LILAC
    global TEXT_ROSE, TEXT_ROSE_SOFT, TEXT_MUTED
    t = THEME_DATA.get(theme_name, THEME_DATA["🌸 经典粉"])
    BG_APP = t["BG_APP"]; BG_PANEL = t["BG_PANEL"]; BG_PANEL_SOFT = t["BG_PANEL_SOFT"]
    BORDER_SOFT = t["BORDER_SOFT"]; ACCENT_PINK = t["ACCENT_PINK"]; ACCENT_PINK_HOVER = t["ACCENT_PINK_HOVER"]
    ACCENT_LILAC = t["ACCENT_LILAC"]; TEXT_ROSE = t["TEXT_ROSE"]; TEXT_ROSE_SOFT = t["TEXT_ROSE_SOFT"]
    TEXT_MUTED = t["TEXT_MUTED"]; BANNER_BG = t.get("BANNER_BG", "#fce7f3")


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
    line_count: int,
    temperature: float = 0.3,
    retry_prompt: bool = False,
) -> str:
    """单次翻译请求（无标记，纯文本）"""
    extra = ""
    if retry_prompt:
        extra = f"\n\n⚠️ 特别注意：上轮翻译行数不匹配。输入是 {line_count} 行，你的输出也必须恰好 {line_count} 行。这是硬性要求。"

    messages = [
        {
            "role": "system",
            "content": f"""你是专业字幕翻译助手。

【术语表】
{glossary}

【翻译规则】
- 输入是一组按行分隔的字幕文本，每行是一条独立字幕
- 你必须逐行翻译：输入有多少行，输出就必须恰好多少行
- 绝对禁止合并多行或拆分单行
- \\N 是字幕的软换行标记，必须原样保留在翻译中
- 只输出翻译结果，不要包含原文、序号、解释或任何额外内容
- 翻译成自然流畅的简体中文，保留原文语气""",
        },
        {"role": "user", "content": text + extra},
    ]
    response = requests.post(
        f"{base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "max_tokens": 8000,
            "temperature": temperature,
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
    """读取 *_export.txt，翻译后写入 *_export_translated.txt，返回译文路径。
    纯文本模式：不加行号标记，仅校验行数。"""
    p = Path(export_path)
    original_lines = p.read_text(encoding="utf-8").splitlines(keepends=False)
    while original_lines and not original_lines[-1].strip():
        original_lines.pop()

    results: list[str] = []
    total_batches = (len(original_lines) + batch_size - 1) // batch_size

    for i in range(0, len(original_lines), batch_size):
        batch_num = i // batch_size + 1
        batch = original_lines[i : i + batch_size]
        batch_line_count = len(batch)
        log(f"  翻译批次 {batch_num}/{total_batches} (行 {i+1}-{i+batch_line_count}) …")

        batch_text = "\n".join(batch)
        translated_lines = None

        for attempt in range(2):  # 最多1次重试
            temperature = 0.2 if attempt == 0 else 0.1
            is_retry = attempt > 0

            try:
                translated = translate_batch(
                    batch_text, glossary, api_key, base_url, model,
                    line_count=batch_line_count,
                    temperature=temperature,
                    retry_prompt=is_retry,
                )
                translated_lines = translated.split("\n")
                translated_lines = [l for l in translated_lines if l.strip()]

                if len(translated_lines) == batch_line_count:
                    if is_retry:
                        log(f"    ✅ 重试成功")
                    break

                if not is_retry:
                    log(f"    ⚠ 行数不匹配：原文 {batch_line_count} → 译文 {len(translated_lines)}，重试中…")
                else:
                    log(f"    ⚠ 重试后仍不匹配：原文 {batch_line_count} → 译文 {len(translated_lines)}，强制对齐")

            except Exception as e:
                if not is_retry:
                    log(f"    ⚠ 请求异常：{e}，重试中…")
                else:
                    log(f"    ❌ 请求失败：{e}，保留原文")
                    translated_lines = list(batch)

        if translated_lines is None:
            translated_lines = list(batch)

        # 兜底对齐
        if len(translated_lines) != batch_line_count:
            if len(translated_lines) > batch_line_count:
                translated_lines = translated_lines[:batch_line_count]
            else:
                while len(translated_lines) < batch_line_count:
                    translated_lines.append(batch[len(translated_lines)])

        results.extend(translated_lines)

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


# ═══════════════════════════════════════════════════════════
# 行号文本组件：行号栏 + 文本区，滚动同步
# ═══════════════════════════════════════════════════════════
class LineNumberedText(tk.Frame):
    """带行号栏的文本区域。

    【重要说明】此处的「行」指 txt 文件中的逻辑行（即 ASS 的一条 Dialogue），
    不是视觉上文字换行后的行。txt 中一个逻辑行可能包含 \\N（ASS 软换行标记），
    在文本区会显示为 \\N 字符，但它仍在同一个逻辑行内，对应行号栏的一个编号。

    行号栏与文本区使用相同字体和 nowrap 模式，保证逐行对齐。
    点击行号栏或文本区任意位置 → 高亮当前逻辑行 + 触发回调。
    """

    # 统一字体（行号栏和文本区共用，保证行高一致）
    # 中文字体 + 等宽回退，确保中英文行高完全一致
    LINE_FONT = ("Microsoft YaHei UI", 10)

    def __init__(self, master, editable=False, on_line_select=None, **kw):
        super().__init__(master, **kw)
        self.configure(bg=BG_PANEL)
        self._editable = editable
        self._on_line_select = on_line_select

        # ── 共享配置：行号栏和文本区必须参数一致才能对齐 ──
        _common = dict(
            font=self.LINE_FONT,
            padx=6, pady=4,
            spacing1=2,   # 行上方额外间距（让行与行之间更清晰）
            spacing2=0,
            spacing3=0,
            borderwidth=0,
            highlightthickness=0,
            wrap=tk.NONE,
            relief=tk.FLAT,
        )

        # ── 行号栏（只读）──
        self.gutter = tk.Text(
            self, width=5,
            bg="#fdf2f8", fg=TEXT_MUTED,
            state=tk.DISABLED,
            cursor="arrow",
            takefocus=False,
            **_common,
        )
        self.gutter.pack(side=tk.LEFT, fill=tk.Y)

        # ── 主文本区 ──
        self.text = tk.Text(
            self,
            bg="#ffffff", fg=TEXT_ROSE,
            undo=True,
            insertbackground=TEXT_ROSE,
            **_common,
        )
        if not editable:
            self.text.config(state=tk.DISABLED)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # ── 垂直滚动条 ──
        self.v_scrollbar = tk.Scrollbar(self)
        self.v_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        def yview_both(*args):
            self.text.yview(*args)
            self.gutter.yview(*args)

        self.v_scrollbar.config(command=yview_both)

        # 关键：text.see() / 程序化滚动时也要同步行号栏
        def on_text_scroll(*args):
            self.v_scrollbar.set(*args)
            self.gutter.yview_moveto(args[0])

        self.text.config(yscrollcommand=on_text_scroll)

        # ── 水平滚动条 ──
        self.h_scrollbar = tk.Scrollbar(self, orient=tk.HORIZONTAL)
        self.h_scrollbar.pack(side=tk.BOTTOM, fill=tk.X)

        def xview_both(*args):
            self.text.xview(*args)
            self.gutter.xview(*args)

        self.h_scrollbar.config(command=xview_both)
        self.text.config(xscrollcommand=self.h_scrollbar.set)

        # ── 鼠标滚轮（垂直）──
        self.text.bind("<MouseWheel>", self._on_mousewheel)
        self.gutter.bind("<MouseWheel>", self._on_mousewheel)

        # Shift + 滚轮 → 水平滚动
        self.text.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.gutter.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)

        # ── 标签 ──
        self.text.tag_config("soft_break", background="#e0f2fe", foreground="#0369a1")
        self.text.tag_config("current_line", background="#fce7f3")

        # ── 点击知行号 ──
        self.text.bind("<Button-1>", self._on_click)
        self.gutter.bind("<Button-1>", self._on_click)

    def _on_mousewheel(self, event):
        delta = int(-1 * (event.delta / 120))
        self.text.yview_scroll(delta, "units")
        self.gutter.yview_scroll(delta, "units")
        return "break"

    def _on_shift_mousewheel(self, event):
        delta = int(-1 * (event.delta / 120))
        self.text.xview_scroll(delta, "units")
        self.gutter.xview_scroll(delta, "units")
        return "break"

    def _on_click(self, event):
        """点击时高亮当前行并通知外部"""
        widget = event.widget
        if widget == self.gutter:
            # 从行号栏点击，计算对应的文本行
            idx = self.gutter.index(f"@{event.x},{event.y}")
            line_num = int(idx.split(".")[0])
        else:
            idx = self.text.index(f"@{event.x},{event.y}")
            line_num = int(idx.split(".")[0])

        self._highlight_line(line_num)
        if self._on_line_select:
            self._on_line_select(line_num)

    def _highlight_line(self, line_num):
        """高亮指定逻辑行（清除旧高亮）"""
        self.text.tag_remove("current_line", "1.0", tk.END)
        start = f"{line_num}.0"
        end = f"{line_num}.end"
        self.text.tag_add("current_line", start, end)
        self.text.see(start)

    def set_content(self, lines: list[str]):
        """设置文本内容，自动更新行号栏并高亮 \\N"""
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        for line in lines:
            self.text.insert(tk.END, line + "\n")
        self.text.delete("end-1c", tk.END)

        self._highlight_soft_breaks()

        if not self._editable:
            self.text.config(state=tk.DISABLED)

        self._update_gutter()

    def _highlight_soft_breaks(self):
        """高亮所有 \\N 标记"""
        self.text.tag_remove("soft_break", "1.0", tk.END)
        content = self.text.get("1.0", tk.END)
        for match in re.finditer(r"\\N", content):
            start_idx = match.start()
            start = f"1.0+{start_idx}c"
            end = f"1.0+{start_idx+2}c"
            self.text.tag_add("soft_break", start, end)

    def _update_gutter(self):
        """根据主文本区的行数更新行号栏"""
        line_count = self.text.index("end-1c").split(".")[0]
        try:
            line_count = int(line_count)
        except ValueError:
            line_count = 0

        self.gutter.config(state=tk.NORMAL)
        self.gutter.delete("1.0", tk.END)
        gutter_lines = "\n".join(
            f"{i+1:>4} " for i in range(max(line_count, 1))
        )
        self.gutter.insert("1.0", gutter_lines)
        self.gutter.config(state=tk.DISABLED)

    def get_content(self) -> list[str]:
        """获取文本内容（按逻辑行分割的列表）"""
        text = self.text.get("1.0", "end-1c")
        if not text.strip():
            return []
        return text.split("\n")

    @property
    def line_count(self):
        try:
            return int(self.text.index("end-1c").split(".")[0])
        except ValueError:
            return 0


# ═══════════════════════════════════════════════════════════
# 校对窗口：原文/译文左右对照，译文可编辑
# ═══════════════════════════════════════════════════════════
class ReviewWindow(tk.Toplevel):
    """字幕翻译校对窗口。

    左侧：原文（只读，带行号）
    右侧：译文（可编辑，带行号）
    底部：状态栏 + 操作按钮
    """

    def __init__(
        self,
        master,
        export_path: str = "",
        trans_path: str = "",
        ass_path: str = "",
        on_import=None,
    ):
        super().__init__(master)
        self.title("校对窗口")
        self.geometry("1280x750")
        self.minsize(980, 500)
        self.configure(bg=BG_APP)

        self._export_path = export_path
        self._trans_path = trans_path
        self._ass_path = ass_path
        self._on_import = on_import
        self._modified = False
        self._has_ass = bool(ass_path and Path(ass_path).exists())
        self._last_export_dir = str(Path(export_path).parent) if export_path else ""
        self._last_trans_dir = str(Path(trans_path).parent) if trans_path else ""

        # ── 顶部说明栏 ──
        info_bar = tk.Frame(self, bg="#fef3c7", highlightthickness=1, highlightbackground="#fcd34d")
        info_bar.pack(fill=tk.X, padx=8, pady=(8, 0))
        tk.Label(
            info_bar,
            text=(
                "【校对说明】行号遵循 txt 文件的「逻辑行」，不是视觉行。"
                "一行 = ASS 的一条 Dialogue。\\N（高亮显示）是行内软换行标记，不是真正的行分隔符。"
                "右键译文区可拆分/合并/插入/删除行。"
            ),
            font=("Microsoft YaHei UI", 9),
            fg="#92400e",
            bg="#fef3c7",
            justify=tk.LEFT,
        ).pack(padx=10, pady=6)

        # ── 顶部：文件选择栏（左右独立）──
        file_bar = tk.Frame(self, bg=BG_PANEL, highlightthickness=1, highlightbackground=BORDER_SOFT)
        file_bar.pack(fill=tk.X, padx=8, pady=(4, 0))
        file_bar.columnconfigure(0, weight=1)
        file_bar.columnconfigure(1, weight=1)

        # 左侧：原文文件选择
        left_file = tk.Frame(file_bar, bg=BG_PANEL)
        left_file.grid(row=0, column=0, sticky=tk.EW, padx=(8, 4), pady=6)
        tk.Label(left_file, text="原文：", font=FONT_UI_SM, fg="#0369a1", bg=BG_PANEL).pack(side=tk.LEFT)
        self.var_export_label = tk.StringVar(value=Path(export_path).name if export_path else "（未选择）")
        tk.Label(
            left_file, textvariable=self.var_export_label,
            font=("Consolas", 9), fg=TEXT_MUTED, bg=BG_PANEL,
        ).pack(side=tk.LEFT, padx=(4, 6))
        tk.Button(
            left_file, text="📂 浏览…", font=FONT_UI_SM,
            command=self._open_export, relief=tk.FLAT,
            bg="#e0f2fe", fg="#0369a1", cursor="hand2", padx=8, pady=2,
        ).pack(side=tk.LEFT)

        # 右侧：译文文件选择
        right_file = tk.Frame(file_bar, bg=BG_PANEL)
        right_file.grid(row=0, column=1, sticky=tk.EW, padx=(4, 8), pady=6)
        tk.Label(right_file, text="译文：", font=FONT_UI_SM, fg=TEXT_ROSE, bg=BG_PANEL).pack(side=tk.LEFT)
        self.var_trans_label = tk.StringVar(value=Path(trans_path).name if trans_path else "（未选择）")
        tk.Label(
            right_file, textvariable=self.var_trans_label,
            font=("Consolas", 9), fg=TEXT_MUTED, bg=BG_PANEL,
        ).pack(side=tk.LEFT, padx=(4, 6))
        tk.Button(
            right_file, text="📂 浏览…", font=FONT_UI_SM,
            command=self._open_trans, relief=tk.FLAT,
            bg="#fce7f3", fg=TEXT_ROSE, cursor="hand2", padx=8, pady=2,
        ).pack(side=tk.LEFT)

        # ── 工具栏 ──
        toolbar = tk.Frame(self, bg=BG_PANEL, highlightthickness=1, highlightbackground=BORDER_SOFT)
        toolbar.pack(fill=tk.X, padx=8, pady=(4, 0))

        tools = [
            ("✂ 拆分行", "在译文光标处将一行拆为两行（插入 \\N 作为分隔）", self._split_line),
            ("▲ 向上合并", "将译文当前行合并到上一行末尾", self._merge_up),
            ("▼ 向下合并", "将译文当前行合并到下一行开头", self._merge_down),
            ("＋ 插入行", "在译文当前行之后插入空行", self._insert_line),
            ("✕ 删除行", "删除译文当前行", self._delete_line),
        ]
        for text, tooltip, cmd in tools:
            btn = tk.Button(
                toolbar,
                text=text,
                font=FONT_UI_SM,
                command=cmd,
                relief=tk.FLAT,
                bg="#fce7f3",
                fg=TEXT_ROSE,
                activebackground="#fbcfe8",
                activeforeground=TEXT_ROSE,
                cursor="hand2",
                padx=8,
                pady=4,
            )
            btn.pack(side=tk.LEFT, padx=3, pady=4)

        # 分隔
        tk.Frame(toolbar, width=2, bg=BORDER_SOFT).pack(side=tk.LEFT, fill=tk.Y, padx=8, pady=4)

        self.btn_save = tk.Button(
            toolbar,
            text="💾 保存修改",
            font=("Microsoft YaHei UI", 9, "bold"),
            command=self._save,
            relief=tk.FLAT,
            bg=ACCENT_PINK,
            fg="#ffffff",
            activebackground=ACCENT_PINK_HOVER,
            activeforeground="#ffffff",
            cursor="hand2",
            padx=12,
            pady=4,
        )
        self.btn_save.pack(side=tk.LEFT, padx=3, pady=4)

        self.btn_import = tk.Button(
            toolbar,
            text="📥 导入 ASS",
            font=("Microsoft YaHei UI", 9, "bold"),
            command=self._do_import,
            relief=tk.FLAT,
            bg="#a78bfa",
            fg="#ffffff",
            activebackground="#8b5cf6",
            activeforeground="#ffffff",
            cursor="hand2",
            padx=12,
            pady=4,
        )
        self.btn_import.pack(side=tk.LEFT, padx=3, pady=4)
        if not self._has_ass:
            self.btn_import.pack_forget()  # 无 ASS 时隐藏导入按钮

        # ── 主区域：左右对照 ──
        paned = tk.PanedWindow(self, orient=tk.HORIZONTAL, bg=BORDER_SOFT, sashwidth=4)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=(4, 8))

        # 左侧：原文
        left_frame = tk.Frame(paned, bg=BG_PANEL)
        tk.Label(
            left_frame,
            text="原文 (English) — 只读",
            font=("Microsoft YaHei UI", 9, "bold"),
            fg="#0369a1",
            bg="#e0f2fe",
        ).pack(fill=tk.X, padx=0, pady=0)
        self._left_view = LineNumberedText(
            left_frame, editable=False, on_line_select=self._on_left_select,
        )
        self._left_view.pack(fill=tk.BOTH, expand=True)
        paned.add(left_frame, stretch="always")

        # 右侧：译文
        right_frame = tk.Frame(paned, bg=BG_PANEL)
        tk.Label(
            right_frame,
            text="译文 (中文) — 可编辑",
            font=("Microsoft YaHei UI", 9, "bold"),
            fg=TEXT_ROSE,
            bg="#fce7f3",
        ).pack(fill=tk.X, padx=0, pady=0)
        self._right_view = LineNumberedText(
            right_frame, editable=True, on_line_select=self._on_right_select,
        )
        self._right_view.pack(fill=tk.BOTH, expand=True)
        paned.add(right_frame, stretch="always")

        # ── 右键菜单（仅译文） ──
        self._context_menu = tk.Menu(self, tearoff=0)
        self._context_menu.add_command(label="✂ 在光标处拆分行", command=self._split_line)
        self._context_menu.add_command(label="▲ 向上合并", command=self._merge_up)
        self._context_menu.add_command(label="▼ 向下合并", command=self._merge_down)
        self._context_menu.add_separator()
        self._context_menu.add_command(label="＋ 插入空行", command=self._insert_line)
        self._context_menu.add_command(label="✕ 删除此行", command=self._delete_line)
        self._right_view.text.bind("<Button-3>", self._show_context_menu)
        self._right_view.text.bind("<Button-2>", self._show_context_menu)

        # 文本修改标记
        self._right_view.text.bind("<<Modified>>", self._on_text_modified)
        self._right_view.text.edit_modified(False)

        # ── 底部状态栏 ──
        status_bar = tk.Frame(self, bg=BG_PANEL, highlightthickness=1, highlightbackground=BORDER_SOFT)
        status_bar.pack(fill=tk.X, padx=8, pady=(0, 8))

        self.var_line_status = tk.StringVar(value="加载中…")
        tk.Label(
            status_bar,
            textvariable=self.var_line_status,
            font=("Consolas", 10, "bold"),
            fg=TEXT_ROSE,
            bg=BG_PANEL,
        ).pack(side=tk.LEFT, padx=12, pady=6)

        self.var_cur_line = tk.StringVar(value="点击行号或文本定位当前行")
        tk.Label(
            status_bar,
            textvariable=self.var_cur_line,
            font=FONT_UI,
            fg="#0369a1",
            bg=BG_PANEL,
        ).pack(side=tk.LEFT, padx=(0, 12), pady=6)

        self.var_save_status = tk.StringVar(value="")
        tk.Label(
            status_bar,
            textvariable=self.var_save_status,
            font=FONT_UI_SM,
            fg=TEXT_MUTED,
            bg=BG_PANEL,
        ).pack(side=tk.RIGHT, padx=12, pady=6)

        # ── 加载内容 ──
        self._load_files()

        # ── 键盘快捷键 ──
        self.bind("<Control-s>", lambda e: self._save())
        self.bind("<Control-S>", lambda e: self._save())

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 文件加载 ──
    # ── 文件加载（独立）──
    def _load_export(self):
        """加载原文文件"""
        if not self._export_path:
            self._left_view.set_content([])
            self.var_export_label.set("（未选择）")
            return
        try:
            lines = Path(self._export_path).read_text(encoding="utf-8").splitlines(keepends=False)
            while lines and not lines[-1].strip():
                lines.pop()
            self._left_view.set_content(lines)
            self.var_export_label.set(Path(self._export_path).name)
            self._update_title()
        except OSError:
            self._left_view.set_content(["(无法读取原文)"])
            self.var_export_label.set("读取失败")

    def _load_trans(self):
        """加载译文文件"""
        if not self._trans_path:
            self._right_view.set_content([])
            self.var_trans_label.set("（未选择）")
            return
        try:
            lines = Path(self._trans_path).read_text(encoding="utf-8").splitlines(keepends=False)
            while lines and not lines[-1].strip():
                lines.pop()
            self._right_view.set_content(lines)
            self.var_trans_label.set(Path(self._trans_path).name)
            self._update_title()
        except OSError:
            self._right_view.set_content(["(无法读取译文)"])
            self.var_trans_label.set("读取失败")

    def _load_files(self):
        """加载原文和译文（兼容旧调用）"""
        self._load_export()
        self._load_trans()
        self._update_status()

    def _update_title(self):
        """根据已加载的文件更新窗口标题"""
        parts = []
        if self._export_path:
            parts.append(Path(self._export_path).name)
        if self._trans_path:
            parts.append(Path(self._trans_path).name)
        if parts:
            self.title(f"校对窗口 — {' ↔ '.join(parts)}")
        else:
            self.title("校对窗口")

    def _open_export(self):
        """浏览并打开原文文件"""
        initial = self._last_export_dir or self._last_trans_dir or str(Path(__file__).parent)
        path = filedialog.askopenfilename(
            title="选择原文 TXT 文件",
            initialdir=initial,
            filetypes=[("TXT 文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self._last_export_dir = str(Path(path).parent)
        self._export_path = path
        self._load_export()
        self._try_find_ass()
        self._update_status()

    def _open_trans(self):
        """浏览并打开译文文件"""
        initial = self._last_trans_dir or self._last_export_dir or str(Path(__file__).parent)
        path = filedialog.askopenfilename(
            title="选择译文 TXT 文件",
            initialdir=initial,
            filetypes=[("TXT 文件", "*.txt"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self._last_trans_dir = str(Path(path).parent)
        self._trans_path = path
        self._load_trans()
        self._update_status()

    def _try_find_ass(self):
        """根据原文路径尝试找到对应的 ASS 文件"""
        if not self._export_path or self._has_ass:
            return
        p = Path(self._export_path)
        stem = p.stem
        for suffix in ("_export",):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        candidates = list(p.parent.glob(f"{stem}*.ass"))
        if not candidates:
            stem2 = re.sub(r'\[.*?\]', '', stem).rstrip('_')
            candidates = list(p.parent.glob(f"{stem2}*.ass"))
        if candidates:
            self._ass_path = str(candidates[0])
            self._has_ass = True
            self.btn_import.pack(side=tk.LEFT, padx=3, pady=4)  # 显示导入按钮

    # ── 状态更新 ──
    def _update_status(self):
        orig = self._left_view.line_count
        trans = self._right_view.line_count
        if orig == trans:
            self.var_line_status.set(f"✅ 原文 {orig} 行  |  译文 {trans} 行  |  行数一致")
        else:
            diff = trans - orig
            sign = "+" if diff > 0 else ""
            self.var_line_status.set(
                f"⚠️ 原文 {orig} 行  |  译文 {trans} 行  |  差异 {sign}{diff} 行 — 请修正后保存！"
            )
        save_text = "已修改未保存" if self._modified else ""
        self.var_save_status.set(save_text)

    # ── 行选中回调 ──
    def _on_left_select(self, line_num):
        """原文侧点击某行时同步显示行号"""
        self.var_cur_line.set(f"原文第 {line_num} 行 — 点击行号栏或文本区定位")
        # 同步高亮译文对应行
        self._right_view._highlight_line(line_num)

    def _on_right_select(self, line_num):
        """译文侧点击某行时同步显示行号"""
        self.var_cur_line.set(f"译文第 {line_num} 行 — 右键可拆分/合并/增删")
        # 同步高亮原文对应行
        self._left_view._highlight_line(line_num)

    # ── 编辑操作 ──
    def _get_cursor_line(self):
        """获取译文中光标所在行号（1-based）"""
        return int(self._right_view.text.index(tk.INSERT).split(".")[0])

    def _split_line(self):
        """在光标位置将一行拆分为两行"""
        text_widget = self._right_view.text
        try:
            cursor_idx = text_widget.index(tk.INSERT)
            line_num = int(cursor_idx.split(".")[0])
            col = int(cursor_idx.split(".")[1])

            line_start = f"{line_num}.0"
            line_end = f"{line_num}.end"
            full_line = text_widget.get(line_start, line_end)

            if col <= 0 or col >= len(full_line):
                messagebox.showinfo("提示", "光标需在行中间位置才能拆分，不能在行首或行尾。")
                return

            part1 = full_line[:col]
            part2 = full_line[col:]

            text_widget.config(state=tk.NORMAL)
            text_widget.delete(line_start, line_end)
            text_widget.insert(line_start, part1 + "\n" + part2)
            text_widget.edit_modified(True)
            self._right_view._update_gutter()
            self._highlight_all_soft_breaks()
            self._modified = True
            self._update_status()
        except Exception as e:
            messagebox.showerror("错误", f"拆分失败：{e}")

    def _merge_up(self):
        """将当前行合并到上一行"""
        text_widget = self._right_view.text
        try:
            line_num = self._get_cursor_line()
            if line_num <= 1:
                messagebox.showinfo("提示", "已是第一行，无法向上合并。")
                return

            prev_line_text = text_widget.get(f"{line_num-1}.0", f"{line_num-1}.end")
            curr_line_text = text_widget.get(f"{line_num}.0", f"{line_num}.end")

            text_widget.config(state=tk.NORMAL)
            text_widget.delete(f"{line_num-1}.0", f"{line_num}.end")
            merged = prev_line_text + r"\N" + curr_line_text
            text_widget.insert(f"{line_num-1}.0", merged)
            text_widget.edit_modified(True)
            self._right_view._update_gutter()
            self._highlight_all_soft_breaks()
            self._modified = True
            self._update_status()
        except Exception as e:
            messagebox.showerror("错误", f"合并失败：{e}")

    def _merge_down(self):
        """将当前行合并到下一行"""
        text_widget = self._right_view.text
        try:
            line_num = self._get_cursor_line()
            last_line = int(text_widget.index("end-1c").split(".")[0])
            if line_num >= last_line:
                messagebox.showinfo("提示", "已是最后一行，无法向下合并。")
                return

            curr_line_text = text_widget.get(f"{line_num}.0", f"{line_num}.end")
            next_line_text = text_widget.get(f"{line_num+1}.0", f"{line_num+1}.end")

            text_widget.config(state=tk.NORMAL)
            text_widget.delete(f"{line_num}.0", f"{line_num+1}.end")
            merged = curr_line_text + r"\N" + next_line_text
            text_widget.insert(f"{line_num}.0", merged)
            text_widget.edit_modified(True)
            self._right_view._update_gutter()
            self._highlight_all_soft_breaks()
            self._modified = True
            self._update_status()
        except Exception as e:
            messagebox.showerror("错误", f"合并失败：{e}")

    def _insert_line(self):
        """在当前行之后插入空行"""
        text_widget = self._right_view.text
        try:
            line_num = self._get_cursor_line()
            last_line = int(text_widget.index("end-1c").split(".")[0])

            text_widget.config(state=tk.NORMAL)
            if line_num >= last_line:
                text_widget.insert(tk.END, "\n")
            else:
                text_widget.insert(f"{line_num}.end", "\n")
            text_widget.edit_modified(True)
            self._right_view._update_gutter()
            self._modified = True
            self._update_status()
        except Exception as e:
            messagebox.showerror("错误", f"插入失败：{e}")

    def _delete_line(self):
        """删除当前行"""
        text_widget = self._right_view.text
        try:
            line_num = self._get_cursor_line()
            last_line = int(text_widget.index("end-1c").split(".")[0])
            if last_line <= 1:
                messagebox.showinfo("提示", "至少保留一行。")
                return

            text_widget.config(state=tk.NORMAL)
            if line_num >= last_line:
                text_widget.delete(f"{line_num-1}.end", f"{line_num}.end")
            else:
                text_widget.delete(f"{line_num}.0", f"{line_num+1}.0")
            text_widget.edit_modified(True)
            self._right_view._update_gutter()
            self._modified = True
            self._update_status()
        except Exception as e:
            messagebox.showerror("错误", f"删除失败：{e}")

    def _highlight_all_soft_breaks(self):
        """重新高亮所有 \\N"""
        self._right_view.text.tag_remove("soft_break", "1.0", tk.END)
        self._right_view._highlight_soft_breaks()

    # ── 右键菜单 ──
    def _show_context_menu(self, event):
        self._context_menu.tk_popup(event.x_root, event.y_root)

    def _on_text_modified(self, event=None):
        if self._right_view.text.edit_modified():
            self._modified = True
            self._update_status()
            self._right_view.text.edit_modified(False)

    # ── 保存 ──
    def _save(self):
        """保存译文到 translated.txt"""
        try:
            lines = self._right_view.get_content()
            Path(self._trans_path).write_text("\n".join(lines), encoding="utf-8")
            self._modified = False
            self._trans_count = len(lines)
            self._update_status()
            self.var_save_status.set("✅ 已保存")
            self.after(3000, lambda: self.var_save_status.set(""))
        except OSError as e:
            messagebox.showerror("保存失败", str(e))

    # ── 导入 ──
    def _do_import(self):
        """先保存，再执行导入"""
        if not self._has_ass:
            messagebox.showinfo("提示", "此校对窗口未关联 ASS 文件，无法导入。\n请使用「保存修改」将译文保存到 txt 文件后，在主界面用导入功能。")
            return
        if self._modified:
            if not messagebox.askyesno("未保存", "译文有修改尚未保存，是否先保存再导入？"):
                return
            self._save()

        out_ass = import_txt_to_ass(self._ass_path, self._trans_path)
        if out_ass:
            messagebox.showinfo("导入成功", f"已生成：\n{out_ass}")
            if self._on_import:
                self._on_import(f"✓ 导入完成：{out_ass}")
        else:
            messagebox.showerror("导入失败", "无法将译文写回 ASS 文件。")

    # ── 关闭 ──
    def _on_close(self):
        if self._modified:
            if messagebox.askyesno("未保存", "译文有修改尚未保存，是否保存后关闭？"):
                self._save()
        self.destroy()


class SubtitleApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("✦ 字幕工坊 · 导出 / 翻译 / 写回")
        self.root.minsize(980, 620)
        self.root.geometry("1040x680")
        self.root.configure(bg=BG_APP)

        self._script_dir = Path(__file__).resolve().parent
        self._busy = False
        self._selected_paths: list[str] = []
        self._pending_review: list[dict] = []  # 待校对的文件列表
        self._last_directory: str = str(self._script_dir)  # 上次浏览的目录

        outer = tk.Frame(self.root, bg=BG_APP)
        outer.pack(fill=tk.BOTH, expand=True, padx=16, pady=14)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        banner = tk.Frame(outer, bg=BANNER_BG, highlightthickness=0, highlightbackground=BORDER_SOFT)
        banner.grid(row=0, column=0, sticky=tk.EW, pady=(0, 12))
        self._banner = banner
        tk.Label(
            banner,
            text="✦ 字幕工坊 ✦",
            font=FONT_TITLE,
            fg=TEXT_ROSE,
            bg=BANNER_BG,
        ).pack(side=tk.LEFT, padx=16, pady=10)
        self._banner_sub = tk.Label(
            banner,
            text="横版工作台 · 左侧填好密钥与术语 · 右侧选文件看日志 · 选好后点「确定」才开始",
            font=FONT_SUB,
            fg=TEXT_MUTED,
            bg=BANNER_BG,
        )
        self._banner_sub.pack(side=tk.LEFT, padx=(0, 12), pady=10)

        # 主题切换按钮
        self._theme_name = tk.StringVar(value="🌸 经典粉")
        self._btn_theme = tk.Button(
            banner,
            textvariable=self._theme_name,
            font=("Microsoft YaHei UI", 8),
            command=self._toggle_theme,
            relief=tk.FLAT,
            bg=ACCENT_LILAC,
            fg=TEXT_ROSE,
            activebackground=ACCENT_PINK,
            activeforeground="#ffffff",
            cursor="hand2",
            padx=10,
            pady=2,
            borderwidth=0,
        )
        self._btn_theme.pack(side=tk.RIGHT, padx=12, pady=10)

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

        # ── 独立校对入口 ──
        tk.Frame(left, height=1, bg=BORDER_SOFT).pack(fill=tk.X, pady=(12, 10))

        tk.Label(
            left,
            text="直接校对 TXT（不经过翻译流程）",
            font=FONT_UI_SM,
            fg=TEXT_MUTED,
            bg=BG_PANEL,
        ).pack(anchor=tk.W)

        self.btn_review_txt = tk.Button(
            left,
            text="📝 打开 TXT 校对 …",
            font=FONT_UI,
            command=self._on_review_txt_click,
            relief=tk.FLAT,
            bg="#e0f2fe",
            fg="#0369a1",
            activebackground="#bae6fd",
            activeforeground="#0369a1",
            cursor="hand2",
            padx=12,
            pady=8,
        )
        self.btn_review_txt.pack(fill=tk.X, pady=(4, 0))

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

        # ── 操作按钮栏（翻译完成后显示）──
        self.action_bar = tk.Frame(log_wrap, bg=BG_PANEL)
        self.action_bar.grid(row=2, column=0, sticky=tk.EW, pady=(8, 0))
        self.action_bar.columnconfigure(0, weight=1)

        self.btn_review = tk.Button(
            self.action_bar,
            text="🔍 校对译文",
            font=("Microsoft YaHei UI", 10, "bold"),
            command=self._on_review_click,
            relief=tk.FLAT,
            bg=ACCENT_PINK,
            fg="#ffffff",
            activebackground=ACCENT_PINK_HOVER,
            activeforeground="#ffffff",
            cursor="hand2",
            padx=16,
            pady=6,
        )
        self.btn_review.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_import_all = tk.Button(
            self.action_bar,
            text="📥 跳过校对，直接导入",
            font=FONT_UI,
            command=self._on_import_all_click,
            relief=tk.FLAT,
            bg="#fbcfe8",
            fg=TEXT_ROSE,
            activebackground="#f9a8d4",
            activeforeground=TEXT_ROSE,
            cursor="hand2",
            padx=12,
            pady=6,
        )
        self.btn_import_all.pack(side=tk.LEFT)

        self.action_bar.grid_remove()  # 初始隐藏

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

    # ── 主题切换 ──
    def _toggle_theme(self):
        """切换主题并刷新所有控件颜色"""
        current = self._theme_name.get()
        new = "🍬 甜蜜糖果" if current == "🌸 经典粉" else "🌸 经典粉"
        self._theme_name.set(new)
        switch_theme(new)
        self._refresh_theme_colors()

    def _refresh_theme_colors(self):
        """遍历主窗口控件树，刷新所有控件颜色以匹配新主题"""
        root = self.root
        root.configure(bg=BG_APP)
        color_map = self._theme_color_map()

        def replace_color(cur_val: str) -> str | None:
            """如果当前颜色匹配旧主题中某项，返回新颜色，否则 None"""
            if not cur_val:
                return None
            cur = str(cur_val).lower().strip()
            for old_hex, new_hex in color_map.items():
                if old_hex.lower() in cur:
                    return new_hex
            return None

        def walk(w, depth=0):
            try:
                cls = w.winfo_class()
                if cls in ("Frame", "Labelframe"):
                    new_bg = replace_color(w.cget("bg"))
                    if new_bg:
                        w.configure(bg=new_bg)
                    new_hl = replace_color(w.cget("highlightbackground"))
                    if new_hl:
                        w.configure(highlightbackground=new_hl)

                elif cls == "Label":
                    new_bg = replace_color(w.cget("bg"))
                    new_fg = replace_color(w.cget("fg"))
                    if new_bg: w.configure(bg=new_bg)
                    if new_fg: w.configure(fg=new_fg)

                elif cls == "Button":
                    new_bg = replace_color(w.cget("bg"))
                    new_fg = replace_color(w.cget("fg"))
                    new_abg = replace_color(w.cget("activebackground"))
                    new_afg = replace_color(w.cget("activeforeground"))
                    if new_bg: w.configure(bg=new_bg)
                    if new_fg: w.configure(fg=new_fg)
                    if new_abg: w.configure(activebackground=new_abg)
                    if new_afg: w.configure(activeforeground=new_afg)

                elif cls == "Text":
                    new_bg = replace_color(w.cget("bg"))
                    new_fg = replace_color(w.cget("fg"))
                    if new_bg: w.configure(bg=new_bg)
                    if new_fg: w.configure(fg=new_fg)
                    new_ins = replace_color(w.cget("insertbackground"))
                    if new_ins: w.configure(insertbackground=new_ins)

                elif cls == "Entry":
                    new_bg = replace_color(w.cget("bg"))
                    new_fg = replace_color(w.cget("fg"))
                    if new_bg: w.configure(bg=new_bg)
                    if new_fg: w.configure(fg=new_fg)
                    new_ins = replace_color(w.cget("insertbackground"))
                    if new_ins: w.configure(insertbackground=new_ins)
            except Exception:
                pass
            for child in w.winfo_children():
                walk(child, depth + 1)

        walk(root)

        # 显式刷新特定控件
        self._banner.configure(bg=BANNER_BG)
        try:
            self._banner_sub.configure(bg=BANNER_BG, fg=TEXT_MUTED)
        except Exception:
            pass
        try:
            self._btn_theme.configure(
                bg=ACCENT_LILAC, fg=TEXT_ROSE,
                activebackground=ACCENT_PINK, activeforeground="#ffffff",
            )
        except Exception:
            pass
        try:
            self.log_widget.configure(bg=BG_PANEL_SOFT)
        except Exception:
            pass

    @staticmethod
    def _theme_color_map() -> dict[str, str]:
        """返回旧主题颜色 → 新主题颜色的映射"""
        classic = THEME_DATA["🌸 经典粉"]
        sweet = THEME_DATA["🍬 甜蜜糖果"]
        # 当前主题是哪套？BG_APP 的值指示
        if BG_APP == classic["BG_APP"]:
            old, new = sweet, classic
        else:
            old, new = classic, sweet
        return {old[k]: new[k] for k in old if old[k] != new[k]}

    def _on_select_ass(self) -> None:
        if self._busy:
            return
        paths = filedialog.askopenfilenames(
            title="选择 ASS 字幕文件",
            initialdir=self._last_directory,
            filetypes=[("ASS 字幕", "*.ass"), ("所有文件", "*.*")],
        )
        if not paths:
            return
        self._selected_paths = list(paths)
        self._last_directory = str(Path(paths[0]).parent)
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
        self.action_bar.grid_remove()

        def worker() -> None:
            self.set_busy(True)
            self._pending_review.clear()
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
                        self.log("❌ 翻译失败，跳过。")
                        continue
                    self.log(f"   → {trans_path}")

                    # 加入待校对列表，暂不自动导入
                    self._pending_review.append({
                        "ass_path": ass_path,
                        "export_path": export_path,
                        "trans_path": trans_path,
                    })

                if self._pending_review:
                    self.log(f"\n{'─'*40}")
                    self.log(f"共 {len(self._pending_review)} 个文件翻译完成。")
                    self.log(f"请点击下方「校对译文」逐文件校对，或「跳过校对，直接导入」。")
                    self.root.after(0, self._show_review_actions)
                    self.set_status("翻译完成 · 请校对译文或直接导入")
                else:
                    self.set_status("没有文件被成功翻译")
            except Exception as e:
                self.log(f"❌ 未捕获错误：{e}")
                self.set_status("出错")
                self.root.after(0, lambda: messagebox.showerror("错误", str(e)))
            finally:
                self.set_busy(False)

        threading.Thread(target=worker, daemon=True).start()

    # ── 校对/导入操作 ──
    def _show_review_actions(self):
        self.action_bar.grid()

    def _hide_review_actions(self):
        self.action_bar.grid_remove()

    def _on_review_click(self):
        """打开校对窗口，逐文件校对"""
        if not self._pending_review:
            messagebox.showinfo("提示", "没有待校对的文件。")
            return
        # 取第一个待校对文件
        item = self._pending_review.pop(0)
        ReviewWindow(
            self.root,
            export_path=item["export_path"],
            trans_path=item["trans_path"],
            ass_path=item["ass_path"],
            on_import=lambda msg: self.log(msg),
        )
        if not self._pending_review:
            self._hide_review_actions()

    def _on_import_all_click(self):
        """跳过校对，直接导入所有待处理的文件"""
        if not self._pending_review:
            messagebox.showinfo("提示", "没有待导入的文件。")
            return

        count = 0
        for item in self._pending_review:
            out_ass = import_txt_to_ass(item["ass_path"], item["trans_path"])
            if out_ass:
                self.log(f"✓ 导入完成：{out_ass}")
                count += 1
            else:
                self.log(f"❌ 导入失败：{item['ass_path']}")

        self.log(f"\n导入完毕：{count}/{len(self._pending_review)} 个文件成功。")
        self._pending_review.clear()
        self._hide_review_actions()
        self.set_status("导入完成 · 可继续选择文件后再次确定")

    def _on_review_txt_click(self):
        """独立入口：打开空白校对窗口，在窗口内分别浏览原文和译文"""
        ReviewWindow(self.root, on_import=lambda msg: self.log(msg))
        self.log("📝 已打开校对窗口，请在窗口内分别选择原文和译文文件")

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    SubtitleApp().run()


if __name__ == "__main__":
    main()
