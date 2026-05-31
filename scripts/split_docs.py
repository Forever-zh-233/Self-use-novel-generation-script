# -*- coding: utf-8 -*-
"""
分片脚本 - 将约束文档拆分成独立的chunk文件
用法: python split_docs.py
输入: 工作台根目录下的约束文档
输出: 工作台 chunks/ 目录下的所有 chunk 文件 + index.json
"""

import os
import re
import json

# 配置。默认取脚本上级目录，也可用 NOVEL_WORKSPACE 覆盖。
BASE_DIR = os.path.abspath(os.environ.get("NOVEL_WORKSPACE") or os.path.join(os.path.dirname(__file__), ".."))
CHUNKS_DIR = os.path.join(BASE_DIR, "chunks")
SOURCE_DOCS = {
    "风格指南": os.path.join(BASE_DIR, "01-风格指南.md"),
    "世界观圣经": os.path.join(BASE_DIR, "02-世界观设定圣经.md"),
    "角色声音表": os.path.join(BASE_DIR, "03-角色声音表.md"),
    "场景索引": os.path.join(BASE_DIR, "04-场景类型索引.md"),
    "章节协议": os.path.join(BASE_DIR, "05-章节生成协议.md"),
    "打分表": os.path.join(BASE_DIR, "06-验证打分表.md"),
    "状态台账": os.path.join(BASE_DIR, "07-动态状态台账.md"),
    "期待账本": os.path.join(BASE_DIR, "08-期待账本.md"),
    "故事核": os.path.join(BASE_DIR, "09-故事核.md"),
    "卷纲": os.path.join(BASE_DIR, "10-卷纲.md"),
    "负空间": os.path.join(BASE_DIR, "11-负空间.md"),
    "AI腔黑名单": os.path.join(BASE_DIR, "12-AI腔黑名单.md"),
}

def estimate_tokens(text):
    """估算中文token数（1个汉字≈1.5个token）"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return int(chinese_chars * 1.5)

def split_by_section(content, section_pattern=r'^## '):
    """按二级标题拆分"""
    sections = re.split(f'(?={section_pattern})', content, flags=re.MULTILINE)
    return [s.strip() for s in sections if s.strip()]

def split_by_character(content):
    """按角色拆分角色声音表"""
    chunks = {}
    
    # 匹配"## 角色名"格式
    pattern = r'^## (.+?)(?:\（.*?\）)?\s*\n'
    matches = list(re.finditer(pattern, content, re.MULTILINE))
    
    for i, match in enumerate(matches):
        char_name = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        chunk_content = content[start:end].strip()
        chunks[f"chunk_{char_name}.md"] = chunk_content
    
    return chunks

def split_by_scene(content):
    """按场景类型拆分场景索引"""
    chunks = {}
    
    # 匹配"## N. 场景名"格式
    pattern = r'^## \d+\. (.+?)$'
    matches = list(re.finditer(pattern, content, re.MULTILINE))
    
    for i, match in enumerate(matches):
        scene_name = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        chunk_content = content[start:end].strip()
        chunks[f"chunk_{scene_name}.md"] = chunk_content
    
    return chunks

def extract_cross_character_rules(role_voice_content):
    """从角色声音表提取跨角色总则（通用规则/禁止事项），并进黄金法则每章必读。"""
    if not role_voice_content:
        return ""
    # 抓 "## 通用规则" 这一节（含其下所有内容到文件尾或下一个 ## ）
    m = re.search(r'(^##\s*通用规则[\s\S]*?)(?=^##\s|\Z)', role_voice_content, re.MULTILINE)
    if not m:
        return ""
    block = m.group(1).strip()
    return "\n\n## 角色声音总则（写多角色时必须遵守）\n" + block


def create_golden_rules(style_guide_content, role_voice_content=""):
    """从风格指南中提取黄金法则，并合入角色声音表的跨角色总则。"""
    # 提取核心规则部分
    lines = style_guide_content.split('\n')
    golden_rules = []
    in_core_section = False

    for line in lines:
        if '核心原则' in line or '句式规则' in line:
            in_core_section = True
        if in_core_section:
            golden_rules.append(line)
        if len(golden_rules) > 50:  # 限制长度
            break

    if not golden_rules:
        # 如果没有找到核心部分，取前800字
        golden_rules = style_guide_content[:800].split('\n')

    result = '\n'.join(golden_rules)
    result += extract_cross_character_rules(role_voice_content)
    return result

def main():
    """主函数"""
    print("确保chunks目录存在...")
    os.makedirs(CHUNKS_DIR, exist_ok=True)
    for filename in os.listdir(CHUNKS_DIR):
        if filename.startswith("chunk_") and filename.endswith(".md"):
            os.remove(os.path.join(CHUNKS_DIR, filename))
    
    index = {}
    
    print("\n=== 处理风格指南 ===")
    if os.path.exists(SOURCE_DOCS["风格指南"]):
        with open(SOURCE_DOCS["风格指南"], 'r', encoding='utf-8') as f:
            content = f.read()

        # 读取角色声音表，把跨角色总则并进黄金法则
        role_voice_content = ""
        if os.path.exists(SOURCE_DOCS["角色声音表"]):
            with open(SOURCE_DOCS["角色声音表"], 'r', encoding='utf-8') as rf:
                role_voice_content = rf.read()

        # 黄金法则
        golden_rules = create_golden_rules(content, role_voice_content)
        chunk_path = os.path.join(CHUNKS_DIR, "chunk_黄金法则.md")
        with open(chunk_path, 'w', encoding='utf-8') as f:
            f.write(golden_rules)
        index["黄金法则"] = {
            "file": "chunk_黄金法则.md",
            "tokens": estimate_tokens(golden_rules),
            "category": "必选"
        }
        print(f"  chunk_黄金法则.md ({estimate_tokens(golden_rules)} tokens)")
    
    print("\n=== 处理角色声音表 ===")
    if os.path.exists(SOURCE_DOCS["角色声音表"]):
        with open(SOURCE_DOCS["角色声音表"], 'r', encoding='utf-8') as f:
            content = f.read()
        
        char_chunks = split_by_character(content)
        for filename, chunk_content in char_chunks.items():
            chunk_path = os.path.join(CHUNKS_DIR, filename)
            with open(chunk_path, 'w', encoding='utf-8') as f:
                f.write(chunk_content)
            char_name = filename.replace("chunk_", "").replace(".md", "")
            index[char_name] = {
                "file": filename,
                "tokens": estimate_tokens(chunk_content),
                "category": "角色"
            }
            print(f"  {filename} ({estimate_tokens(chunk_content)} tokens)")
    
    print("\n=== 处理场景索引 ===")
    if os.path.exists(SOURCE_DOCS["场景索引"]):
        with open(SOURCE_DOCS["场景索引"], 'r', encoding='utf-8') as f:
            content = f.read()
        
        scene_chunks = split_by_scene(content)
        for filename, chunk_content in scene_chunks.items():
            chunk_path = os.path.join(CHUNKS_DIR, filename)
            with open(chunk_path, 'w', encoding='utf-8') as f:
                f.write(chunk_content)
            scene_name = filename.replace("chunk_", "").replace(".md", "")
            index[scene_name] = {
                "file": filename,
                "tokens": estimate_tokens(chunk_content),
                "category": "场景"
            }
            print(f"  {filename} ({estimate_tokens(chunk_content)} tokens)")
    
    print("\n=== 处理负空间 ===")
    if os.path.exists(SOURCE_DOCS["负空间"]):
        with open(SOURCE_DOCS["负空间"], 'r', encoding='utf-8') as f:
            content = f.read()
        chunk_path = os.path.join(CHUNKS_DIR, "chunk_负空间.md")
        with open(chunk_path, 'w', encoding='utf-8') as f:
            f.write(content)
        index["负空间"] = {
            "file": "chunk_负空间.md",
            "tokens": estimate_tokens(content),
            "category": "必选"
        }
        print(f"  chunk_负空间.md ({estimate_tokens(content)} tokens)")
    
    print("\n=== 处理AI腔黑名单 ===")
    if os.path.exists(SOURCE_DOCS["AI腔黑名单"]):
        with open(SOURCE_DOCS["AI腔黑名单"], 'r', encoding='utf-8') as f:
            content = f.read()
        chunk_path = os.path.join(CHUNKS_DIR, "chunk_AI腔黑名单.md")
        with open(chunk_path, 'w', encoding='utf-8') as f:
            f.write(content)
        index["AI腔黑名单"] = {
            "file": "chunk_AI腔黑名单.md",
            "tokens": estimate_tokens(content),
            "category": "必选"
        }
        print(f"  chunk_AI腔黑名单.md ({estimate_tokens(content)} tokens)")
    
    print("\n=== 处理其他文档 ===")
    for doc_name, doc_path in SOURCE_DOCS.items():
        if doc_name in ["风格指南", "角色声音表", "场景索引", "负空间", "AI腔黑名单"]:
            continue  # 已处理
        
        if os.path.exists(doc_path):
            with open(doc_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 按二级标题拆分
            sections = split_by_section(content)
            for i, section in enumerate(sections):
                # 提取标题
                title_match = re.match(r'^## (.+)', section)
                if title_match:
                    section_name = title_match.group(1).strip()
                    filename = f"chunk_{doc_name}_{section_name}.md"
                else:
                    filename = f"chunk_{doc_name}_{i}.md"
                
                chunk_path = os.path.join(CHUNKS_DIR, filename)
                with open(chunk_path, 'w', encoding='utf-8') as f:
                    f.write(section)
                
                index[f"{doc_name}_{section_name if title_match else i}"] = {
                    "file": filename,
                    "tokens": estimate_tokens(section),
                    "category": doc_name
                }
                print(f"  {filename} ({estimate_tokens(section)} tokens)")
    
    # 保存索引
    index_path = os.path.join(CHUNKS_DIR, "index.json")
    with open(index_path, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 完成 ===")
    print(f"共生成 {len(index)} 个chunk文件")
    print(f"索引保存到: {index_path}")
    
    # 打印统计
    total_tokens = sum(item["tokens"] for item in index.values())
    print(f"总token数: {total_tokens}")
    
    categories = {}
    for item in index.values():
        cat = item["category"]
        categories[cat] = categories.get(cat, 0) + item["tokens"]
    
    print("\n按类别统计:")
    for cat, tokens in categories.items():
        print(f"  {cat}: {tokens} tokens")

if __name__ == "__main__":
    main()
