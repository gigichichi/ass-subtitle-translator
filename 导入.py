import os
import re
import glob

def replace_first_plain(text, replacement):
    """将 text 中的第一个非样式标签的纯文本替换为 replacement，保留样式标签"""
    replaced = False
    def repl(m):
        nonlocal replaced
        if replaced or m.group(0).startswith('{'):
            return m.group(0)
        replaced = True
        return replacement
    return re.sub(r'(\{[^}]*\}|[^{]+)', repl, text)

def process_ass_with_export(ass_path, export_path, output_path=None):
    """使用 export_path 中的行替换 ass_path 中的 Dialogue 文本，输出到 output_path"""
    if output_path is None:
        output_path = os.path.splitext(ass_path)[0] + "_output.ass"
    
    try:
        # 读取 ASS 文件
        with open(ass_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 读取导出的文本（每行是一个对话的纯文本）
        with open(export_path, 'r', encoding='utf-8') as ef:
            export_lines = [line.rstrip('\n') for line in ef]
        
        idx = 0
        with open(output_path, 'w', encoding='utf-8') as out:
            for line in lines:
                if line.startswith('Dialogue:'):
                    parts = line.split(',', 9)
                    if len(parts) >= 10 and idx < len(export_lines):
                        orig_text = parts[9]
                        # 将 export 行中的换行符转换为 ASS 的 \N
                        new_plain = export_lines[idx].replace('\n', r'\N')
                        # 替换第一个纯文本区域，保留样式标签
                        new_text = replace_first_plain(orig_text, new_plain)
                        parts[9] = new_text + '\n'
                        line = ','.join(parts)
                        idx += 1
                out.write(line)
        
        print(f"成功处理：{os.path.basename(ass_path)} -> {os.path.basename(output_path)} (使用了 {os.path.basename(export_path)})")
        return True
    
    except Exception as e:
        print(f"处理 {os.path.basename(ass_path)} 时出错：{e}")
        return False

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ass_files = glob.glob(os.path.join(script_dir, "*.ass"))
    
    if not ass_files:
        print("当前目录下没有找到 .ass 文件")
        return
    
    processed_count = 0
    for ass_path in ass_files:
        base_name = os.path.splitext(ass_path)[0]
        # 自动匹配同名的 _export_translate.txt 文件
        export_path = base_name + "_export_translated.txt"
        
        if not os.path.exists(export_path):
            print(f"警告：未找到 {os.path.basename(ass_path)} 对应的导出文件 {os.path.basename(export_path)}，跳过")
            continue
        
        print(f"处理：{os.path.basename(ass_path)} <-> {os.path.basename(export_path)}")
        if process_ass_with_export(ass_path, export_path):
            processed_count += 1
    
    print(f"\n处理完成！共处理 {processed_count} 个文件，跳过 {len(ass_files) - processed_count} 个（缺少导出文件）")

if __name__ == "__main__":
    main()