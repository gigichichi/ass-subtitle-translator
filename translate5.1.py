import requests
import re
from pathlib import Path

# ========== 配置 ==========
BASE_URL = "https://api.deepseek.com/v1"
MODEL = "deepseek-v4-flash"
# ==========================


def load_api_key():
    """从 api_key.txt 或环境变量读取 API key"""
    key_file = Path(__file__).parent / "api_key.txt"
    if key_file.exists():
        return key_file.read_text(encoding='utf-8').strip()
    import os
    return os.environ.get("DEEPSEEK_API_KEY", "xxxxx")


API_KEY = load_api_key()

# ── 行号标记格式 ──
LINE_MARKER_RE = re.compile(r'^\[L\d{4}\]')


def add_line_markers(lines):
    """给每行添加行号前缀 [L0001]"""
    return [f"[L{i+1:04d}]{line}" for i, line in enumerate(lines)]


def strip_line_markers(lines):
    """去掉行号前缀，恢复纯译文"""
    return [LINE_MARKER_RE.sub('', line, count=1) for line in lines]


def validate_line_counts(original, translated, marker_prefix=True):
    """
    验证翻译后的行数是否与原文一致。
    返回 (is_valid, details)
    """
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


def build_system_prompt(glossary):
    """构建极其严格的 system prompt"""
    return f"""你是专业字幕翻译助手。以下规则必须绝对遵守，任何违反都视为任务失败。

══════════════════════════════════════
【术语表】
{glossary}
══════════════════════════════════════

【规则 1 · 行号标记 · 最高优先级】
每条输入的开头都有一个 [L0001] 格式的行号标记。
你必须在对应翻译输出的行首**原封不动**地保留该标记。
例如输入 "[L0003]Hello world" → 输出 "[L0003]你好世界"

【规则 2 · 行数一致 · 最高优先级】
输入有多少行，输出就**必须**有多少行。
禁止合并多行为一行。
禁止将一行拆分为多行。
一行入 → 一行出。不可更改。

【规则 3 · \\N 保留】
\\N 是字幕软换行标记，必须原样保留在翻译文本中。
例如 "It'll take more than\\Nshowering them with weak magic"
→ "[L0001]想用同属性的弱魔法\\N把它们轰掉可没那么简单"
\\N 的数量和位置应与原文对应。

【规则 4 · 纯翻译输出】
只输出带行号标记的翻译结果。
不要添加任何解释、注释、英文原文、Markdown 格式或空行。

【翻译风格】
- 翻译成自然流畅的简体中文
- 保留原文语气和语体风格
- 参照术语表确保专有名词翻译一致"""


def translate_batch(batch_lines, glossary, batch_num, retry_count=0):
    """
    翻译一批行，失败时自动重试。
    batch_lines: 已经带行号标记的行列表
    返回: 翻译后的行列表（已去除行号标记）
    """
    max_retries = 3
    batch_text = "\n".join(batch_lines)

    for attempt in range(max_retries + 1):
        # 重试时降低 temperature 使输出更稳定
        temperature = max(0.1, 0.3 - attempt * 0.1)

        system_prompt = build_system_prompt(glossary)

        # 重试时在 user prompt 中追加更严厉的警告
        user_text = batch_text
        if attempt > 0:
            user_text = (
                f"⚠️ 上一次翻译失败！原因：行数不匹配。\n"
                f"请严格确保输出恰好 {len(batch_lines)} 行，每行以对应的 [LXXXX] 开头。\n\n"
                f"{batch_text}"
            )

        try:
            response = requests.post(
                f"{BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {API_KEY}"},
                json={
                    "model": MODEL,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_text}
                    ],
                    "max_tokens": 8000,
                    "temperature": temperature
                },
                timeout=120
            )

            raw = response.json()['choices'][0]['message']['content'].strip()
            translated_lines = raw.split("\n")

            # 过滤可能的空行
            translated_lines = [l for l in translated_lines if l.strip()]

            is_valid, msg = validate_line_counts(batch_lines, translated_lines, marker_prefix=True)

            if is_valid:
                if attempt > 0:
                    print(f"  ✅ 第 {attempt + 1} 次重试成功")
                return strip_line_markers(translated_lines), True

            # 失败处理
            if attempt < max_retries:
                print(f"  ⚠️ 第 {attempt + 1} 次失败：{msg}，正在重试...")
            else:
                print(f"  ❌ 重试 {max_retries} 次后仍失败：{msg}")

                # 最后手段：尝试用无标记版本重新翻译（放弃标记验证，仅检查行数）
                print(f"  🔄 尝试最终备用方案（无标记模式）...")
                fallback_result = translate_batch_fallback(batch_lines, glossary)
                if fallback_result:
                    return fallback_result, True
                print(f"  ☠️ 最终备用方案也失败，保留原文")
                return [LINE_MARKER_RE.sub('', l, count=1) for l in batch_lines], False

        except Exception as e:
            if attempt < max_retries:
                print(f"  ⚠️ 请求异常：{e}，正在重试...")
            else:
                print(f"  ❌ 请求失败：{e}")
                return [LINE_MARKER_RE.sub('', l, count=1) for l in batch_lines], False

    return [LINE_MARKER_RE.sub('', l, count=1) for l in batch_lines], False


def translate_batch_fallback(batch_lines, glossary):
    """
    最终备用方案：去掉行号标记，用极简 prompt，仅依赖行数检查。
    """
    # 先去掉标记
    plain_lines = [LINE_MARKER_RE.sub('', l, count=1) for l in batch_lines]
    plain_text = "\n".join(plain_lines)

    system_prompt = f"""你是专业字幕翻译助手。
参照术语表翻译成简体中文。
{glossary}

绝对规则：
- 输入是 {len(plain_lines)} 行字幕，输出必须恰好 {len(plain_lines)} 行
- 一行入一行出，不合并不拆分
- \\N 原样保留
- 仅输出翻译结果，无任何额外内容"""

    try:
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {API_KEY}"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": plain_text}
                ],
                "max_tokens": 8000,
                "temperature": 0.1
            },
            timeout=120
        )

        raw = response.json()['choices'][0]['message']['content'].strip()
        translated_lines = raw.split("\n")
        translated_lines = [l for l in translated_lines if l.strip()]

        if len(translated_lines) == len(plain_lines):
            print(f"  ✅ 备用方案成功")
            return translated_lines

        print(f"  备用方案行数：期望 {len(plain_lines)}，实际 {len(translated_lines)}")
    except Exception as e:
        print(f"  备用方案异常：{e}")

    return None


# ========== 主程序 ==========
def main():
    current_dir = Path(__file__).parent

    # 1. 读取术语表
    glossary_file = current_dir / "术语表.csv"
    if glossary_file.exists():
        glossary = glossary_file.read_text(encoding='utf-8')
        print(f"✓ 术语表已加载：{len(glossary)} 字符")
    else:
        glossary = ""
        print("⚠️  未找到术语表.csv")

    # 2. 查找 txt 文件
    txt_files = list(current_dir.glob("*_export.txt"))
    # 排除已翻译的文件
    txt_files = [f for f in txt_files if "_translated" not in f.name]

    if not txt_files:
        print("❌ 未找到 *_export.txt 文件")
        input("按回车键退出...")
        return

    # 3. 选择文件
    if len(txt_files) > 1:
        print("\n找到多个文件：")
        for i, f in enumerate(txt_files, 1):
            print(f"  {i}. {f.name}")
        choice = int(input("\n请输入文件编号: ")) - 1
        input_file = txt_files[choice]
    else:
        input_file = txt_files[0]

    print(f"\n【开始处理】{input_file.name}")

    # 4. 读取原文
    original_lines = input_file.read_text(encoding='utf-8').splitlines(keepends=False)
    # 去掉可能的尾随空行
    while original_lines and not original_lines[-1].strip():
        original_lines.pop()

    print(f"原文共 {len(original_lines)} 行")

    # 5. 添加行号标记
    marked_lines = add_line_markers(original_lines)

    # 6. 分批翻译
    BATCH_SIZE = 40
    all_results = []
    failed_batches = []
    total_batches = (len(marked_lines) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(marked_lines), BATCH_SIZE):
        batch_num = i // BATCH_SIZE + 1
        batch = marked_lines[i:i + BATCH_SIZE]
        print(f"\n【批次 {batch_num}/{total_batches}】行 {i+1}-{i+len(batch)}")

        translated, success = translate_batch(batch, glossary, batch_num)

        if len(translated) != len(batch):
            print(f"  ⚠️ 严重：行数仍不匹配！原文 {len(batch)} → 译文 {len(translated)}")
            # 补齐或截断以维持对齐（宁可截断也不破坏后续对齐）
            if len(translated) > len(batch):
                translated = translated[:len(batch)]
            else:
                # 缺少的行用原文填充
                plain_batch = [LINE_MARKER_RE.sub('', l, count=1) for l in batch]
                while len(translated) < len(batch):
                    translated.append(plain_batch[len(translated)])
            failed_batches.append(batch_num)

        all_results.extend(translated)

    # 7. 保存
    output_file = input_file.with_name(input_file.stem + "_translated.txt")
    output_file.write_text("\n".join(all_results), encoding='utf-8')

    print(f"\n{'='*50}")
    print(f"✓ 翻译完成！")
    print(f"  输出文件：{output_file.name}")
    print(f"  原文行数：{len(original_lines)}")
    print(f"  译文行数：{len(all_results)}")
    if failed_batches:
        print(f"  ⚠️ 以下批次在重试后仍有问题：{failed_batches}")
        print(f"  （已通过补齐/截断保证对齐，但建议人工检查这些批次）")
    else:
        print(f"  ✅ 所有批次行数完全匹配")
    print(f"{'='*50}")

    input("\n按回车键退出...")


if __name__ == "__main__":
    main()
