# -*- coding: utf-8 -*-
"""
流水线脚本 - 串联6道工序，生成一章的完整流程
用法:
  python pipeline.py --chapter <章号> --beat <beat文件路径>
  python pipeline.py --chapter <章号> --beat <beat文件路径> --text <正文文件路径>

说明:
  不直接调用模型，只生成写手/评审 prompt，并对已有正文做脚本能可靠完成的硬检查。
  端到端 API 自动写作由 run_pipeline.py 承担。
"""

import os
import sys
import json
import argparse
import re
from datetime import datetime

# 配置。默认取脚本上级目录，也可用 NOVEL_WORKSPACE 覆盖。
BASE_DIR = os.path.abspath(os.environ.get("NOVEL_WORKSPACE") or os.path.join(os.path.dirname(__file__), ".."))
CHUNKS_DIR = os.path.join(BASE_DIR, "chunks")
OUTPUT_DIR = os.path.join(BASE_DIR, "输出")
VERSION_DIR = os.path.join(BASE_DIR, "台账版本")
ROLE_DIRS = {
    "article": os.path.join(OUTPUT_DIR, "文章"),
    "writer": os.path.join(OUTPUT_DIR, "写手"),
    "gate": os.path.join(OUTPUT_DIR, "门禁"),
    "review": os.path.join(OUTPUT_DIR, "评审"),
    "edit": os.path.join(OUTPUT_DIR, "修稿"),
    "archive": os.path.join(OUTPUT_DIR, "记录员"),
    "beat": os.path.join(OUTPUT_DIR, "章纲"),
    "context": os.path.join(OUTPUT_DIR, "上下文"),
}

# Token预算
MAX_TOKENS = 6000
GOLDEN_RULES_BUDGET = 800
NEGATIVE_SPACE_BUDGET = 500
AI_BLACKLIST_BUDGET = 500
SCENE_CARD_BUDGET = 400
CHARACTER_VOICE_BUDGET = 500
STATUS_LEDGER_BUDGET = 500
FORESHADOWING_BUDGET = 400
BEAT_BUDGET = 300

def ensure_dirs():
    """确保目录存在"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(VERSION_DIR, exist_ok=True)
    for path in ROLE_DIRS.values():
        os.makedirs(path, exist_ok=True)

def chapter_file(role, chapter_num, suffix):
    """按新输出结构生成章节产物路径"""
    return os.path.join(ROLE_DIRS[role], f"第{chapter_num:03d}章_{suffix}")

def article_file(chapter_num):
    """最终正文路径，只放给用户阅读的正文"""
    return os.path.join(ROLE_DIRS["article"], f"第{chapter_num:03d}章.md")

def load_chunk(chunk_name):
    """加载chunk文件"""
    chunk_path = os.path.join(CHUNKS_DIR, f"chunk_{chunk_name}.md")
    if os.path.exists(chunk_path):
        with open(chunk_path, 'r', encoding='utf-8') as f:
            return f.read()
    else:
        print(f"警告: chunk文件不存在: {chunk_path}")
        return ""

def load_index():
    """加载chunk索引"""
    index_path = os.path.join(CHUNKS_DIR, "index.json")
    if os.path.exists(index_path):
        with open(index_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    else:
        print("警告: index.json不存在，请先运行split_docs.py")
        return {}

def estimate_tokens(text):
    """估算token数"""
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    return int(chinese_chars * 1.5)

def select_chunks(beat, index):
    """根据beat选择需要的chunks"""
    selected = {}
    
    # 必选项
    for item in ["黄金法则", "负空间", "AI腔黑名单"]:
        if item in index:
            content = load_chunk(item)
            selected[item] = content
    
    # 按场景类型选
    scene_type = beat.get("场景类型", "日常对话")
    if scene_type in index:
        content = load_chunk(scene_type)
        selected[f"场景_{scene_type}"] = content
    
    # 按出场角色选
    characters = beat.get("出场角色", ["沈安"])
    for char in characters[:3]:  # 最多3个角色
        if char in index:
            content = load_chunk(char)
            selected[f"角色_{char}"] = content
    
    return selected

def build_context(selected_chunks, beat, status_ledger, foreshadowing):
    """构建写作上下文"""
    context_parts = []
    
    # 黄金法则
    if "黄金法则" in selected_chunks:
        context_parts.append(f"===== 风格规则 =====\n{selected_chunks['黄金法则']}")
    
    # 负空间
    if "负空间" in selected_chunks:
        context_parts.append(f"===== 负空间（作者不写什么）=====\n{selected_chunks['负空间']}")
    
    # AI腔黑名单
    if "AI腔黑名单" in selected_chunks:
        context_parts.append(f"===== AI腔黑名单（绝对不能出现）=====\n{selected_chunks['AI腔黑名单']}")
    
    # 场景卡
    for key, content in selected_chunks.items():
        if key.startswith("场景_"):
            context_parts.append(f"===== 本章场景规则 =====\n{content}")
    
    # 角色声音
    char_parts = []
    for key, content in selected_chunks.items():
        if key.startswith("角色_"):
            char_parts.append(content)
    if char_parts:
        context_parts.append(f"===== 出场角色声音 =====\n" + "\n".join(char_parts))
    
    # 状态台账
    if status_ledger:
        context_parts.append(f"===== 当前剧情状态 =====\n{status_ledger}")
    
    # 期待账本
    if foreshadowing:
        context_parts.append(f"===== 活跃普通伏笔（短中期债务，不含长线LF）=====\n{foreshadowing}")
    
    # 本章beat
    beat_text = f"""章节编号: 第{beat.get('章节编号', '?')}章
章节标题: {beat.get('标题', '?')}
期待循环位置: {beat.get('期待循环位置', '?')}
场景类型: {beat.get('场景类型', '?')}
本章冲突: {beat.get('本章冲突', '?')}
转折: {beat.get('转折', '?')}
本章爽点: {beat.get('本章爽点', '无')}
章末钩子: {beat.get('章末钩子', '?')}
推进的线: {beat.get('推进的线', '主线')}
伏笔操作: {beat.get('伏笔操作', '无')}
出场角色: {', '.join(beat.get('出场角色', ['沈安']))}"""
    
    context_parts.append(f"===== 本章任务 =====\n{beat_text}")
    
    # 注意事项
    notes = """===== 注意事项 =====
- 不要出现AI腔黑名单中的任何问题
- 不要复用原文的独特比喻（见负空间）
- 对话要符合角色声音表
- 章末必须有钩子
- 长线伏笔没有写进 beat 时不要主动外显；不要在正文出现 LF-XXX 编号
- 段落要短（平均17字），大量单句成段
- 句子要短（平均13字），40%在10字以内"""
    
    context_parts.append(notes)
    
    return "\n\n".join(context_parts)

def load_status_ledger():
    """加载最新状态台账"""
    ledger_path = os.path.join(BASE_DIR, "07-动态状态台账.md")
    if os.path.exists(ledger_path):
        with open(ledger_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 只取最后500行（最新状态）
        lines = content.split('\n')
        if len(lines) > 500:
            return '\n'.join(lines[-500:])
        return content
    return ""

def load_foreshadowing():
    """加载未回收伏笔"""
    foreshadow_path = os.path.join(BASE_DIR, "08-期待账本.md")
    if os.path.exists(foreshadow_path):
        with open(foreshadow_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # 提取未回收条目
        lines = content.split('\n')
        active = [l for l in lines if '未回收' in l]
        if active:
            return "未回收伏笔:\n" + '\n'.join(active[:20])  # 最多20条
    return ""

def generate_writer_prompt(context, chapter_num):
    """生成写手prompt"""
    return f"""你现在是一个网文写手。以下是你的写作规则和当前状态。

{context}

现在开始写第{chapter_num}章。输出格式：

# 第{chapter_num}章 {{标题}}

（正文内容）

注意：
- 正文约2500-3500字
- 段落要短，大量单句成段
- 句子要短，40%在10字以内
- 对话要符合角色声音
- 章末必须有钩子
- 不要出现AI腔
"""

def run_continuity_check(text, chapter_num):
    """第2道：连续性校验"""
    issues = []
    
    # 简单检查：是否有明显的矛盾词
    contradiction_patterns = [
        (r'白天.*晚上', '时间矛盾'),
        (r'死了.*又活', '人物状态矛盾'),
    ]
    
    for pattern, desc in contradiction_patterns:
        if re.search(pattern, text):
            issues.append(f"可能的{desc}")
    
    return {
        "passed": len(issues) == 0,
        "issues": issues
    }

def run_tone_check(text, chapter_num):
    """第3道：口吻打磨"""
    # 简单检查：是否符合角色声音
    issues = []
    
    # 检查是否有不符合角色的用词
    forbidden_words = ["臣妾", "陛下", "喳"]  # 不应该出现在修仙小说中的词
    for word in forbidden_words:
        if word in text:
            issues.append(f"发现不适合的用词: {word}")
    
    return {
        "passed": len(issues) == 0,
        "issues": issues
    }

def run_ai_detector(text):
    """第4道：去AI腔"""
    issues = []
    
    # AI腔检测模式
    ai_patterns = [
        (r'仿佛.*仿佛', '仿佛重复'),
        (r'似乎.*似乎', '似乎重复'),
        (r'他感到.*他感到', '情绪总结重复'),
        (r'说道，.*说道，', '对话后动作小尾巴'),
        (r'不禁.*不禁', '不禁重复'),
    ]
    
    for pattern, desc in ai_patterns:
        if re.search(pattern, text):
            issues.append(f"AI腔: {desc}")
    
    # 检查句子是否太工整
    sentences = re.split(r'[。！？]', text)
    long_sentences = [s for s in sentences if len(s.strip()) > 30]
    if len(long_sentences) > len(sentences) * 0.3:
        issues.append("长句过多，节奏可能偏慢")
    
    return {
        "passed": len(issues) == 0,
        "issues": issues
    }

def run_plagiarism_check(text):
    """第5道：反抄袭门禁"""
    # 简化版：检查是否有原文标志性短语
    signature_phrases = [
        "海到无边天作岸",
        "山登绝顶我为峰",
        "装你麻痹",
        "他强由他强，清风拂山岗",
    ]
    
    issues = []
    for phrase in signature_phrases:
        if phrase in text:
            issues.append(f"发现原文标志性短语: {phrase}")
    
    return {
        "passed": len(issues) == 0,
        "issues": issues
    }

def run_long_foreshadowing_leak_check(text):
    """检查长线伏笔内部编号是否泄露到正文"""
    issues = []
    if re.search(r"LF-\d{3}", text):
        issues.append("正文出现长线伏笔内部编号 LF-XXX")
    return {
        "passed": len(issues) == 0,
        "issues": issues
    }

def generate_reviewer_prompt(text, chapter_num):
    """生成评审prompt"""
    return f"""你是小说写作系统的评审。请审核以下第{chapter_num}章的正文。

评分维度（每项1-5分）：
1. 叙事视角一致性
2. 句式节奏
3. 对话口吻
4. 情绪推进
5. 场景调度
6. 原文复写风险（负向指标）
7. AI腔检测（负向指标）

评分标准：
- 25-30分：优秀
- 20-24分：良好
- 15-19分：一般
- 10-14分：较差
- 10分以下：不合格

请输出评分报告：

# 评分报告 - 第{chapter_num}章

| 评分项 | 分数 | 备注 |
|-------|------|------|
| 叙事视角一致性 | /5 | |
| 句式节奏 | /5 | |
| 对话口吻 | /5 | |
| 情绪推进 | /5 | |
| 场景调度 | /5 | |
| 原文复写风险 | /5 | 负向指标 |
| AI腔检测 | /5 | 负向指标 |
| **总分** | /30 | |

## 修改建议
（如有）

---

待审核的正文：

{text}
"""

def save_version_snapshot(chapter_num, text, context):
    """保存版本快照"""
    snapshot_dir = os.path.join(VERSION_DIR, f"chapter_{chapter_num}")
    os.makedirs(snapshot_dir, exist_ok=True)
    
    # 保存正文
    with open(os.path.join(snapshot_dir, "text.md"), 'w', encoding='utf-8') as f:
        f.write(text)
    
    # 保存上下文
    with open(os.path.join(snapshot_dir, "context.md"), 'w', encoding='utf-8') as f:
        f.write(context)
    
    # 保存时间戳
    with open(os.path.join(snapshot_dir, "timestamp.txt"), 'w', encoding='utf-8') as f:
        f.write(datetime.now().isoformat())
    
    print(f"版本快照已保存到: {snapshot_dir}")

def main():
    parser = argparse.ArgumentParser(description='小说写作流水线')
    parser.add_argument('--chapter', required=True, type=int, help='章号')
    parser.add_argument('--beat', required=True, help='beat描述（JSON格式或文件路径）')
    parser.add_argument('--text', help='已生成正文文件路径；提供后会执行硬检查、保存正文和生成评审prompt')
    parser.add_argument('--skip-checks', action='store_true', help='跳过检查步骤')
    
    args = parser.parse_args()
    
    ensure_dirs()
    
    chapter_num = args.chapter
    
    # 加载beat
    if os.path.exists(args.beat):
        with open(args.beat, 'r', encoding='utf-8') as f:
            beat = json.load(f)
    else:
        # 尝试解析JSON字符串
        try:
            beat = json.loads(args.beat)
        except:
            print("错误: 无法解析beat参数")
            sys.exit(1)
    
    print(f"\n=== 流水线开始: 第{chapter_num}章 ===")
    
    # 加载索引
    index = load_index()
    if not index:
        print("错误: 无法加载chunk索引，请先运行split_docs.py")
        sys.exit(1)
    
    # 选择chunks
    print("\n[Step 1] 选择需要的chunks...")
    selected_chunks = select_chunks(beat, index)
    for name, content in selected_chunks.items():
        tokens = estimate_tokens(content)
        print(f"  {name}: {tokens} tokens")
    
    # 构建上下文
    print("\n[Step 1] 构建写作上下文...")
    status_ledger = load_status_ledger()
    foreshadowing = load_foreshadowing()
    context = build_context(selected_chunks, beat, status_ledger, foreshadowing)
    context_tokens = estimate_tokens(context)
    print(f"  上下文总token数: {context_tokens}")
    
    if context_tokens > MAX_TOKENS:
        print(f"  警告: 上下文超过预算 ({MAX_TOKENS} tokens)")
    
    # 生成写手prompt
    writer_prompt = generate_writer_prompt(context, chapter_num)
    
    # 保存写手prompt（供用户使用）
    prompt_path = chapter_file("writer", chapter_num, "writer_prompt.md")
    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(writer_prompt)
    print(f"\n写手prompt已保存到: {prompt_path}")
    
    print("\n=== 流水线准备完成 ===")
    print("请将写手prompt发送给AI写手，等待正文输出。")
    print("正文生成后，运行以下命令进行后续处理：")
    print(f"  python pipeline.py --chapter {chapter_num} --beat {args.beat} --text <正文文件路径>")
    
    # 如果提供了正文，继续后续处理
    if args.text:
        text_path = args.text
        with open(text_path, 'r', encoding='utf-8') as f:
            text = f.read()
        
        if not args.skip_checks:
            # 第2道：连续性校验
            print("\n[Step 2] 连续性校验...")
            result = run_continuity_check(text, chapter_num)
            print(f"  结果: {'通过' if result['passed'] else '不通过'}")
            if result['issues']:
                for issue in result['issues']:
                    print(f"  - {issue}")
            
            # 第3道：口吻打磨
            print("\n[Step 3] 口吻打磨...")
            result = run_tone_check(text, chapter_num)
            print(f"  结果: {'通过' if result['passed'] else '不通过'}")
            if result['issues']:
                for issue in result['issues']:
                    print(f"  - {issue}")
            
            # 第4道：去AI腔
            print("\n[Step 4] 去AI腔...")
            result = run_ai_detector(text)
            print(f"  结果: {'通过' if result['passed'] else '不通过'}")
            if result['issues']:
                for issue in result['issues']:
                    print(f"  - {issue}")
            
            # 第5道：反抄袭门禁
            print("\n[Step 5] 反抄袭门禁...")
            result = run_plagiarism_check(text)
            print(f"  结果: {'通过' if result['passed'] else '不通过'}")
            if result['issues']:
                for issue in result['issues']:
                    print(f"  - {issue}")

            # 第6道：长线伏笔编号泄露
            print("\n[Step 6] 长线伏笔编号泄露检查...")
            result = run_long_foreshadowing_leak_check(text)
            print(f"  结果: {'通过' if result['passed'] else '不通过'}")
            if result['issues']:
                for issue in result['issues']:
                    print(f"  - {issue}")
        
        # 保存正文
        text_output_path = article_file(chapter_num)
        with open(text_output_path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f"\n正文已保存到: {text_output_path}")
        
        # 生成评审prompt
        reviewer_prompt = generate_reviewer_prompt(text, chapter_num)
        reviewer_prompt_path = chapter_file("review", chapter_num, "reviewer_prompt.md")
        with open(reviewer_prompt_path, 'w', encoding='utf-8') as f:
            f.write(reviewer_prompt)
        print(f"评审prompt已保存到: {reviewer_prompt_path}")
        
        # 保存版本快照
        save_version_snapshot(chapter_num, text, context)
        
        print("\n=== 流水线完成 ===")

if __name__ == "__main__":
    main()
