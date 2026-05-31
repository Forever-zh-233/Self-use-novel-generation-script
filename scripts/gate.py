# -*- coding: utf-8 -*-
"""
反抄袭门禁脚本 - 检测AI生成文本与原文的相似度
用法: python gate.py --input <AI生成的正文文件>
输入: AI生成的正文
输出: 检测报告（通过/不通过）
"""

import re
import sys
import argparse
import os
from collections import Counter

# 配置。默认取脚本上级目录，也可用 NOVEL_WORKSPACE 覆盖。
BASE_DIR = os.path.abspath(os.environ.get("NOVEL_WORKSPACE") or os.path.join(os.path.dirname(__file__), ".."))
SOURCE_FILE = os.path.join(BASE_DIR, "271824.txt")
NGRAM_SIZE = 5  # 与打分表保持一致：5 字连续片段命中即标红
MAX_OVERLAP_COUNT = 0  # 原创模式下命中即需要人工检查

def load_source_ngrams(filepath, n=7):
    """加载原文的n-gram集合"""
    print("加载原文...")
    with open(filepath, 'r', encoding='utf-8') as f:
        text = f.read()
    
    # 提取中文字符
    chinese_text = re.sub(r'[^\u4e00-\u9fff]', '', text)
    
    # 生成n-gram
    ngrams = set()
    for i in range(len(chinese_text) - n + 1):
        ngrams.add(chinese_text[i:i+n])
    
    print(f"原文n-gram数量: {len(ngrams)}")
    return ngrams

def extract_chinese(text):
    """提取中文字符"""
    return re.sub(r'[^\u4e00-\u9fff]', '', text)

def check_ngram_overlap(ai_text, source_ngrams, n=7):
    """检查n-gram重叠"""
    chinese_text = extract_chinese(ai_text)
    
    if len(chinese_text) < n:
        return {
            "passed": True,
            "overlap_count": 0,
            "total_ngrams": 0,
            "overlap_ratio": 0,
            "overlapping_ngrams": []
        }
    
    # 生成AI文本的n-gram
    ai_ngrams = []
    for i in range(len(chinese_text) - n + 1):
        ai_ngrams.append(chinese_text[i:i+n])
    
    # 检查重叠
    overlapping = []
    for ng in ai_ngrams:
        if ng in source_ngrams:
            overlapping.append(ng)
    
    overlap_ratio = len(overlapping) / len(ai_ngrams) if ai_ngrams else 0
    
    return {
        "passed": len(overlapping) <= MAX_OVERLAP_COUNT,
        "overlap_count": len(overlapping),
        "total_ngrams": len(ai_ngrams),
        "overlap_ratio": round(overlap_ratio * 100, 2),
        "overlapping_ngrams": list(set(overlapping))[:20]  # 只显示前20个
    }

def check_phrase_reuse(ai_text, source_file):
    """检查标志性短语复用"""
    # 常见的标志性比喻和台词
    signature_phrases = [
        "像是一片雪花在空中飞舞",
        "装你麻痹",
        "海到无边天作岸",
        "山登绝顶我为峰",
        "他强由他强",
        "清风拂山岗",
        "明月照大江",
        # 可以从原文中提取更多
    ]
    
    found = []
    for phrase in signature_phrases:
        if phrase in ai_text:
            found.append(phrase)
    
    return {
        "passed": len(found) == 0,
        "found_phrases": found
    }

def check_unique_metaphors(ai_text, source_file):
    """检查独特比喻复用"""
    with open(source_file, 'r', encoding='utf-8') as f:
        source_text = f.read()
    
    # 提取比喻句（简单模式）
    metaphor_pattern = r'像[^。，！？]{5,30}[。，！？]'
    source_metaphors = set(re.findall(metaphor_pattern, source_text))
    ai_metaphors = set(re.findall(metaphor_pattern, ai_text))
    
    # 检查重叠
    overlap = source_metaphors & ai_metaphors
    
    return {
        "passed": len(overlap) == 0,
        "source_metaphor_count": len(source_metaphors),
        "ai_metaphor_count": len(ai_metaphors),
        "overlap_count": len(overlap),
        "overlapping_metaphors": list(overlap)[:10]
    }

def generate_report(ai_text_path):
    """生成检测报告"""
    # 加载AI文本
    with open(ai_text_path, 'r', encoding='utf-8') as f:
        ai_text = f.read()
    
    # 加载原文n-gram（缓存机制）
    ngram_cache_path = os.path.join(BASE_DIR, "分析草稿", f"source_{NGRAM_SIZE}grams.json")
    if os.path.exists(ngram_cache_path):
        import json
        with open(ngram_cache_path, 'r', encoding='utf-8') as f:
            source_ngrams = set(json.load(f))
    else:
        source_ngrams = load_source_ngrams(SOURCE_FILE, NGRAM_SIZE)
        # 缓存n-gram
        os.makedirs(os.path.dirname(ngram_cache_path), exist_ok=True)
        with open(ngram_cache_path, 'w', encoding='utf-8') as f:
            json.dump(list(source_ngrams), f)
    
    # 执行检测
    print("\n执行反抄袭检测...")
    
    ngram_result = check_ngram_overlap(ai_text, source_ngrams, NGRAM_SIZE)
    phrase_result = check_phrase_reuse(ai_text, SOURCE_FILE)
    metaphor_result = check_unique_metaphors(ai_text, SOURCE_FILE)
    
    # 综合判定
    all_passed = ngram_result["passed"] and phrase_result["passed"] and metaphor_result["passed"]
    
    # 生成报告
    report = f"""
=== 反抄袭检测报告 ===

1. N-gram重叠检测 (N={NGRAM_SIZE})
   状态: {"通过" if ngram_result["passed"] else "不通过"}
   AI文本n-gram数: {ngram_result["total_ngrams"]}
   重叠数: {ngram_result["overlap_count"]}
   重叠率: {ngram_result["overlap_ratio"]}%
   阈值: 命中数 <= {MAX_OVERLAP_COUNT}
   重叠的n-gram: {', '.join(ngram_result["overlapping_ngrams"][:5])}

2. 标志性短语复用检测
   状态: {"通过" if phrase_result["passed"] else "不通过"}
   找到的短语: {', '.join(phrase_result["found_phrases"]) if phrase_result["found_phrases"] else "无"}

3. 独特比喻复用检测
   状态: {"通过" if metaphor_result["passed"] else "不通过"}
   原文比喻数: {metaphor_result["source_metaphor_count"]}
   AI比喻数: {metaphor_result["ai_metaphor_count"]}
   重叠数: {metaphor_result["overlap_count"]}
   重叠的比喻: {', '.join(metaphor_result["overlapping_metaphors"][:5]) if metaphor_result["overlapping_metaphors"] else "无"}

=== 综合判定 ===
总体状态: {"通过" if all_passed else "不通过"}

{"所有检测通过，文本可以使用。" if all_passed else "检测未通过，需要修改后重新检测。"}
"""
    
    return report, all_passed

def main():
    parser = argparse.ArgumentParser(description='反抄袭门禁检测')
    parser.add_argument('--input', required=True, help='AI生成的正文文件路径')
    parser.add_argument('--output', help='报告输出文件路径')
    
    args = parser.parse_args()
    
    # 执行检测
    report, passed = generate_report(args.input)
    
    # 输出报告
    print(report)
    
    # 保存报告
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"报告已保存到: {args.output}")
    
    # 返回退出码
    sys.exit(0 if passed else 1)

if __name__ == "__main__":
    main()
