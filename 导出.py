import os
import re
import glob

def process_ass_file(file_path):
    """处理单个 ASS 文件，提取对话行并去除样式标签，输出到同名的 _export.txt 文件"""
    output_file = os.path.splitext(file_path)[0] + "_export.txt"
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        extracted_lines = []
        for line in lines:
            if line.startswith('Dialogue:'):
                parts = line.split(',', 9)
                if len(parts) >= 10:
                    text = parts[9].rstrip('\n')
                    # 移除花括号内的样式标签，如 {\fnArial\b1}
                    plain = re.sub(r'\{[^}]*\}', '', text)
                    extracted_lines.append(plain)
        
        if extracted_lines:
            with open(output_file, 'w', encoding='utf-8') as out:
                out.write('\n'.join(extracted_lines))
            print(f"成功处理：{os.path.basename(file_path)} -> {os.path.basename(output_file)}")
        else:
            print(f"警告：{os.path.basename(file_path)} 中没有找到 Dialogue 行")
    
    except Exception as e:
        print(f"处理文件 {os.path.basename(file_path)} 时出错：{e}")

def main():
    # 获取脚本所在目录（与 .bat 和 .ass 文件同目录）
    script_dir = os.path.dirname(os.path.abspath(__file__))
    ass_files = glob.glob(os.path.join(script_dir, "*.ass"))
    
    if not ass_files:
        print("当前目录下没有找到 .ass 文件")
        return
    
    print(f"找到 {len(ass_files)} 个 ASS 文件，开始处理...")
    for ass_file in ass_files:
        process_ass_file(ass_file)
    print("全部处理完毕")

if __name__ == "__main__":
    main()