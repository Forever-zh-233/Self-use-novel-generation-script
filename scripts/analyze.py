# -*- coding: utf-8 -*-
"""
量化分析脚本 - 分析源文本的风格特征
用法: python analyze.py
输入: 工作台根目录下的 271824.txt
输出: 工作台 分析草稿/style_metrics.json
"""

import re
import json
import os
from collections import Counter

def load_text(filepath):
    """加载文本文件"""
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()

def analyze_sentence_length(text):
    """分析句长分布"""
    sentences = re.split(r'[。！？\n]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 0]
    lengths = [len(s) for s in sentences]
    
    if not lengths:
        return {}
    
    lengths.sort()
    n = len(lengths)
    
    return {
        "count": n,
        "mean": round(sum(lengths) / n, 1),
        "median": lengths[n // 2],
        "std": round((sum((x - sum(lengths)/n)**2 for x in lengths) / n) ** 0.5, 1),
        "p10": lengths[int(n * 0.1)],
        "p90": lengths[int(n * 0.9)],
        "max": max(lengths),
        "min": min(lengths),
        "distribution": {
            "1-5": sum(1 for l in lengths if l <= 5),
            "6-10": sum(1 for l in lengths if 6 <= l <= 10),
            "11-15": sum(1 for l in lengths if 11 <= l <= 15),
            "16-20": sum(1 for l in lengths if 16 <= l <= 20),
            "21-30": sum(1 for l in lengths if 21 <= l <= 30),
            "31-50": sum(1 for l in lengths if 31 <= l <= 50),
            "50+": sum(1 for l in lengths if l > 50)
        }
    }

def analyze_paragraph_length(text):
    """分析段落长度分布"""
    lines = text.split('\n')
    non_empty = [l.strip() for l in lines if l.strip()]
    lengths = [len(l) for l in non_empty]
    
    if not lengths:
        return {}
    
    n = len(lengths)
    
    return {
        "count": n,
        "mean": round(sum(lengths) / n, 1),
        "median": sorted(lengths)[n // 2],
        "single_sentence_paragraphs": sum(1 for l in lengths if l <= 20),
        "single_sentence_ratio": round(sum(1 for l in lengths if l <= 20) / n * 100, 1),
        "distribution": {
            "1-5": sum(1 for l in lengths if l <= 5),
            "6-10": sum(1 for l in lengths if 6 <= l <= 10),
            "11-20": sum(1 for l in lengths if 11 <= l <= 20),
            "21-30": sum(1 for l in lengths if 21 <= l <= 30),
            "31-50": sum(1 for l in lengths if 31 <= l <= 50),
            "51-100": sum(1 for l in lengths if 51 <= l <= 100),
            "100+": sum(1 for l in lengths if l > 100)
        }
    }

def analyze_punctuation(text):
    """分析标点符号指纹"""
    total_chars = len(text)
    
    puncts = {
        "comma": text.count("，"),
        "period": text.count("。"),
        "exclaim": text.count("！"),
        "question": text.count("？"),
        "dun": text.count("、"),
        "ellipsis": text.count("……"),
        "dash": text.count("——"),
        "quote": text.count('"') + text.count('"'),
        "paren": text.count("（") + text.count("）"),
        "colon": text.count("："),
        "semi": text.count("；"),
    }
    
    result = {}
    for k, v in puncts.items():
        result[k] = {
            "count": v,
            "per_10k": round(v / total_chars * 10000, 1) if total_chars > 0 else 0
        }
    
    # 逗号句号比
    if puncts["period"] > 0:
        result["comma_period_ratio"] = round(puncts["comma"] / puncts["period"], 2)
    else:
        result["comma_period_ratio"] = 0
    
    return result

def analyze_dialogue_ratio(text):
    """分析对话占比"""
    lines = text.split('\n')
    non_empty = [l for l in lines if l.strip()]
    
    dialogue_lines = [l for l in non_empty if '"' in l or '"' in l or '「' in l]
    
    total_chars = len(text)
    dialogue_chars = sum(len(l) for l in dialogue_lines)
    
    return {
        "dialogue_lines": len(dialogue_lines),
        "total_lines": len(non_empty),
        "line_ratio": round(len(dialogue_lines) / len(non_empty) * 100, 1) if non_empty else 0,
        "char_ratio": round(dialogue_chars / total_chars * 100, 1) if total_chars > 0 else 0
    }

def analyze_high_freq_words(text, top_n=50):
    """分析高频词。注意：中文未分词，2-4字滑窗有噪声，仅作粗参考。"""
    words = re.findall(r'[\u4e00-\u9fff]{2,4}', text)
    freq = Counter(words)
    return freq.most_common(top_n)

def analyze_chapter_structure(text):
    """分析章节结构"""
    chapter_pattern = re.compile(r'第(\d+)章')
    chapters = []
    for m in chapter_pattern.finditer(text):
        chapters.append({
            "number": int(m.group(1)),
            "position": m.start()
        })
    
    # 计算章节间距
    if len(chapters) > 1:
        gaps = [chapters[i+1]["position"] - chapters[i]["position"] for i in range(len(chapters)-1)]
        avg_chapter_length = round(sum(gaps) / len(gaps)) if gaps else 0
    else:
        avg_chapter_length = 0
    
    return {
        "total_chapters": len(chapters),
        "avg_chapter_length": avg_chapter_length,
        "first_5": [f"Ch{c['number']}" for c in chapters[:5]],
        "last_5": [f"Ch{c['number']}" for c in chapters[-5:]]
    }

def analyze_system_panels(text):
    """分析系统面板"""
    panels = re.findall(r'【[^】]+】', text)
    return {
        "count": len(panels),
        "first_5": panels[:5]
    }

def analyze_author_notes(text):
    """分析作者旁白（括号内容）"""
    notes = re.findall(r'(?<!【)（[^）]{10,}）', text)
    return {
        "count": len(notes),
        "first_5": [n[:60] + "..." if len(n) > 60 else n for n in notes[:5]]
    }

def analyze_ellipsis(text):
    """分析省略号使用"""
    long_ellipsis = re.findall(r'\.{4,}', text)
    return {
        "long_ellipsis_count": len(long_ellipsis)
    }


def analyze_lexical_fingerprint(text):
    """词汇质感指纹：高频动词偏好、语气词、感官词分布、文白倾向。
    决定遣词习惯像不像，是模仿文风的关键维度。"""
    verb_pairs = {
        "看类": ["看", "瞧", "望", "瞅", "盯", "瞥"],
        "说类": ["说", "道", "问", "答", "喊", "叫"],
        "放类": ["放", "搁", "撂", "摆"],
        "走类": ["走", "跑", "迈", "踱", "蹭", "挪"],
        "拿类": ["拿", "抓", "握", "攥", "捏", "提", "拎"],
    }
    verb_stats = {g: {v: text.count(v) for v in vs} for g, vs in verb_pairs.items()}

    tone_words = ["嘿", "呦", "啧", "唉", "哼", "嗯", "哦", "呃", "诶", "嘛", "呗", "罢了", "得嘞"]
    tone_stats = {w: text.count(w) for w in tone_words if text.count(w) > 0}

    sense_words = {
        "视觉": ["看", "瞧", "望", "盯", "瞥", "色", "光", "亮", "暗", "影"],
        "听觉": ["听", "声", "响", "音", "喊", "叫", "吵", "静"],
        "触觉": ["摸", "碰", "触", "握", "烫", "凉", "冷", "热", "疼", "痛", "软", "硬"],
        "嗅觉": ["闻", "味", "香", "臭", "腥", "气"],
    }
    sense_stats = {s: sum(text.count(w) for w in ws) for s, ws in sense_words.items()}
    sense_total = sum(sense_stats.values()) or 1
    sense_ratio = {k: round(v / sense_total * 100, 1) for k, v in sense_stats.items()}

    classical = ["之", "乎", "者", "也", "矣", "焉", "其", "故", "然则", "是以"]
    total = len(text) or 1
    classical_per_10k = round(sum(text.count(w) for w in classical) / total * 10000, 1)

    return {
        "verb_preference": verb_stats,
        "tone_words": dict(sorted(tone_stats.items(), key=lambda x: -x[1])),
        "sense_distribution": sense_stats,
        "sense_ratio_percent": sense_ratio,
        "classical_particles_per_10k": classical_per_10k,
    }


def analyze_single_sentence_paragraph(text):
    """单句成段比例——这类网文的灵魂。"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    if not lines:
        return {}
    single = 0
    for l in lines:
        enders = sum(l.count(p) for p in "。！？")
        commas = sum(l.count(p) for p in "，；")
        if enders <= 1 and commas == 0:
            single += 1
    return {
        "total_paragraphs": len(lines),
        "single_sentence_paragraphs": single,
        "single_sentence_ratio_percent": round(single / len(lines) * 100, 1),
    }


def analyze_dialogue_style(text):
    """对话风格：说话人标识习惯、对话后动作小尾巴频率、纯对话占比。"""
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    dialogue_lines = [l for l in lines if '"' in l or '“' in l or '”' in l]
    n = len(dialogue_lines) or 1
    pure_quote = with_speaker = with_action_tail = 0
    speaker_pat = re.compile(r'[一-鿿]{1,4}(说|道|问|答|喊|叫|笑)')
    for l in dialogue_lines:
        if speaker_pat.search(l):
            with_speaker += 1
        m = re.search(r'[”"][^”"]*$', l)
        tail = l[m.start() + 1:] if m else ""
        if len(tail.strip()) > 2:
            with_action_tail += 1
        if re.match(r'^[“"][^”"]*[”"]$', l):
            pure_quote += 1
    return {
        "dialogue_line_count": len(dialogue_lines),
        "pure_quote_ratio_percent": round(pure_quote / n * 100, 1),
        "with_speaker_tag_ratio_percent": round(with_speaker / n * 100, 1),
        "with_action_tail_ratio_percent": round(with_action_tail / n * 100, 1),
    }


def analyze_sentence_openings(text):
    """句子开头模式：连词/转折开头占比。"""
    sentences = [s.strip() for s in re.split(r'[。！？\n]+', text) if s.strip()]
    if not sentences:
        return {}
    conjunctions = ["但", "可", "然后", "于是", "因为", "所以", "不过", "而", "却", "只是"]
    sample = sentences[:50000]
    conj_start = sum(1 for s in sample if any(s.startswith(c) for c in conjunctions))
    return {
        "sample_size": len(sample),
        "conjunction_start_ratio_percent": round(conj_start / len(sample) * 100, 1),
    }


def analyze_chapter_endings(text):
    """章末钩子画像：每章末句长度与悬念词倾向。"""
    parts = re.split(r'第\d+章', text)
    tails = []
    for p in parts[1:]:
        lines = [l.strip() for l in p.split('\n') if l.strip()]
        if lines:
            tails.append(lines[-1])
    if not tails:
        return {}
    tail_lengths = [len(t) for t in tails]
    hook_words = ["突然", "忽然", "竟", "却", "没想到", "下一刻", "就在这时"]
    hook_hits = sum(1 for t in tails if any(w in t for w in hook_words))
    return {
        "chapters_sampled": len(tails),
        "avg_last_line_length": round(sum(tail_lengths) / len(tail_lengths), 1),
        "short_ending_ratio_percent": round(sum(1 for l in tail_lengths if l <= 12) / len(tail_lengths) * 100, 1),
        "suspense_word_ending_ratio_percent": round(hook_hits / len(tails) * 100, 1),
    }


def _dist_table(dist, total, header="长度区间"):
    """把一个 {区间: 数量} 字典渲染成带占比的 markdown 表格。"""
    total = total or sum(dist.values()) or 1
    rows = ["| {} | 数量 | 占比 |".format(header), "|---|---|---|"]
    for k, v in dist.items():
        rows.append("| {} | {:,} | {}% |".format(k, v, round(v / total * 100, 1)))
    return "\n".join(rows)


def render_report_md(m):
    """从 style_metrics 字典渲染人能读的《全量统计报告.md》。
    一劳永逸：每次 analyze.py 跑完自动覆盖,永远反映最新维度。"""
    L = []
    basic = m.get("basic", {})
    chap = m.get("chapters", {})
    sent = m.get("sentence", {})
    para = m.get("paragraph", {})
    ssp = m.get("single_sentence_paragraph", {})

    L.append("# 源文本量化统计报告")
    L.append("")
    L.append("> 本报告由 `scripts/analyze.py` 自动生成,数据源 `分析草稿/style_metrics.json`。")
    L.append("> 改了分析维度后重跑脚本即可刷新,不要手改本文件。")
    L.append("")

    L.append("## 基本信息")
    L.append("- 总字符数: {:,} (约{}万字)".format(basic.get("total_chars", 0), round(basic.get("total_chars", 0) / 10000)))
    L.append("- 总行数: {:,}".format(basic.get("total_lines", 0)))
    L.append("- 章节数: {} 章".format(chap.get("total_chapters", "N/A")))
    L.append("- 平均每章字数: {:,} 字".format(chap.get("avg_chapter_length", 0)))
    L.append("")

    L.append("## 句子分析")
    L.append("- 句子总数: {:,}".format(sent.get("count", 0)))
    L.append("- 平均句长: {} 字 | 中位 {} | 标准差 {} | p10 {} | p90 {} | 最长 {}".format(
        sent.get("mean", "?"), sent.get("median", "?"), sent.get("std", "?"),
        sent.get("p10", "?"), sent.get("p90", "?"), sent.get("max", "?")))
    L.append("")
    L.append(_dist_table(sent.get("distribution", {}), sent.get("count", 0)))
    L.append("")
    L.append("**结论: 句长极短,短句主导节奏。**")
    L.append("")

    L.append("## 段落分析")
    L.append("- 段落总数: {:,} | 平均段长 {} 字 | 中位 {}".format(
        para.get("count", 0), para.get("mean", "?"), para.get("median", "?")))
    L.append("- 单句成段(严格): {:,} / {:,} = **{}%**".format(
        ssp.get("single_sentence_paragraphs", 0), ssp.get("total_paragraphs", 0),
        ssp.get("single_sentence_ratio_percent", "?")))
    L.append("")
    L.append(_dist_table(para.get("distribution", {}), para.get("count", 0)))
    L.append("")
    L.append("**结论: 大量单句成段,留白多,阅读极快。**")
    L.append("")

    # === PLACEHOLDER_REPORT_REST ===
    punc = m.get("punctuation", {})
    L.append("## 标点符号 (每万字)")
    L.append("| 标点 | 总数 | 每万字 |")
    L.append("|---|---|---|")
    punc_names = {"comma": "逗号 ，", "period": "句号 。", "exclaim": "感叹号 ！",
                  "question": "问号 ？", "colon": "冒号 ：", "paren": "括号 ()",
                  "dun": "顿号 、", "dash": "破折号 ——", "ellipsis": "省略号 ……",
                  "quote": "引号", "semi": "分号 ；"}
    for key, label in punc_names.items():
        if key in punc and isinstance(punc[key], dict):
            L.append("| {} | {:,} | {} |".format(label, punc[key].get("count", 0), punc[key].get("per_10k", 0)))
    L.append("")
    L.append("- 逗号/句号比: {}".format(punc.get("comma_period_ratio", "?")))
    L.append("**结论: 逗号句号接近 1:1,印证短句为主。**")
    L.append("")

    ds = m.get("dialogue_style", {})
    L.append("## 对话风格")
    L.append("- 含引号对话行: {:,}".format(ds.get("dialogue_line_count", 0)))
    L.append("- 纯引号(无标识无动作): **{}%**".format(ds.get("pure_quote_ratio_percent", "?")))
    L.append("- 带说话人标识(X道/X问): {}%".format(ds.get("with_speaker_tag_ratio_percent", "?")))
    L.append("- 带动作小尾巴(引号后接动作): {}%".format(ds.get("with_action_tail_ratio_percent", "?")))
    L.append("")
    L.append("**结论: 过半对话是纯引号裸对话,动作尾巴克制。模仿时别给每句对话都缀动作。**")
    L.append("")

    lex = m.get("lexical_fingerprint", {})
    L.append("## 词汇质感指纹")
    L.append("")
    L.append("### 高频动词偏好 (同义动词里作者的真实选择)")
    for group, verbs in lex.get("verb_preference", {}).items():
        if verbs:
            top = sorted(verbs.items(), key=lambda x: -x[1])
            inline = "、".join("{}×{:,}".format(v, c) for v, c in top if c > 0)
            L.append("- **{}**: {}".format(group, inline))
    L.append("")
    L.append("### 语气词频率")
    tw = lex.get("tone_words", {})
    if tw:
        L.append("、".join("{}×{}".format(w, c) for w, c in tw.items()))
    L.append("")
    L.append("### 感官分布 (描写时调动哪种感官)")
    sr = lex.get("sense_ratio_percent", {})
    L.append("| 感官 | 占比 |")
    L.append("|---|---|")
    for k in ["视觉", "听觉", "触觉", "嗅觉"]:
        if k in sr:
            L.append("| {} | {}% |".format(k, sr[k]))
    L.append("")
    L.append("- 文白倾向(文言虚词每万字): {}".format(lex.get("classical_particles_per_10k", "?")))
    L.append("")
    L.append("**结论: 视觉主导但听/嗅占比可观,描写不堆视觉。**")
    L.append("")

    ce = m.get("chapter_endings", {})
    so = m.get("sentence_openings", {})
    L.append("## 章末钩子画像")
    L.append("- 采样章数: {}".format(ce.get("chapters_sampled", "?")))
    L.append("- 平均末句长度: {} 字".format(ce.get("avg_last_line_length", "?")))
    L.append("- 短句收尾占比(≤12字): **{}%**".format(ce.get("short_ending_ratio_percent", "?")))
    L.append("- 悬念词收尾占比(突然/竟/没想到等): **{}%**".format(ce.get("suspense_word_ending_ratio_percent", "?")))
    L.append("- 连词/转折开头句占比: {}%".format(so.get("conjunction_start_ratio_percent", "?")))
    L.append("")
    L.append("**结论: 章末几乎全用短句收尾,几乎不靠廉价悬念词制造钩子。模仿时靠留白,别用'突然''竟然'。**")
    L.append("")

    sp = m.get("system_panels", {})
    an = m.get("author_notes", {})
    el = m.get("ellipsis", {})
    L.append("## 其他元素 (设定相关,模仿文风时注意区分)")
    L.append("- 系统面板【…】: {} 个 — 是核心设定,换书未必有".format(sp.get("count", 0)))
    L.append("- 作者旁白/括号注释: {} 条 — 作者与读者互动,**不模仿**".format(an.get("count", 0)))
    L.append("- 长省略号: {} 处".format(el.get("long_ellipsis_count", 0)))
    L.append("")

    L.append("## 风格特征总结")
    L.append("1. **极短段落**: 平均 {} 字,单句成段 {}%".format(para.get("mean", "?"), ssp.get("single_sentence_ratio_percent", "?")))
    L.append("2. **极短句子**: 平均 {} 字".format(sent.get("mean", "?")))
    L.append("3. **裸对话为主**: 纯引号 {}%,少缀动作尾巴".format(ds.get("pure_quote_ratio_percent", "?")))
    L.append("4. **多感官**: 视觉 {}% / 听觉 {}% / 嗅觉 {}% / 触觉 {}%".format(
        sr.get("视觉", "?"), sr.get("听觉", "?"), sr.get("嗅觉", "?"), sr.get("触觉", "?")))
    L.append("5. **章末靠留白收尾**: 短句收尾 {}%,悬念词收尾仅 {}%".format(
        ce.get("short_ending_ratio_percent", "?"), ce.get("suspense_word_ending_ratio_percent", "?")))
    L.append("")
    return "\n".join(L)


def main():
    """主函数"""
    base_dir = os.path.abspath(os.environ.get("NOVEL_WORKSPACE") or os.path.join(os.path.dirname(__file__), ".."))
    filepath = os.path.join(base_dir, "271824.txt")
    output_dir = os.path.join(base_dir, "分析草稿")
    
    # 确保输出目录存在
    os.makedirs(output_dir, exist_ok=True)
    
    print("加载文本...")
    text = load_text(filepath)
    print(f"总字符数: {len(text)}")
    
    print("分析句长分布...")
    sentence_metrics = analyze_sentence_length(text)
    
    print("分析段落长度...")
    paragraph_metrics = analyze_paragraph_length(text)
    
    print("分析标点符号...")
    punctuation_metrics = analyze_punctuation(text)
    
    print("分析对话占比...")
    dialogue_metrics = analyze_dialogue_ratio(text)
    
    print("分析高频词...")
    high_freq_words = analyze_high_freq_words(text)
    
    print("分析章节结构...")
    chapter_metrics = analyze_chapter_structure(text)
    
    print("分析系统面板...")
    panel_metrics = analyze_system_panels(text)
    
    print("分析作者旁白...")
    author_notes = analyze_author_notes(text)
    
    print("分析省略号...")
    ellipsis_metrics = analyze_ellipsis(text)

    print("分析词汇质感指纹...")
    lexical_metrics = analyze_lexical_fingerprint(text)

    print("分析单句成段比例...")
    single_para_metrics = analyze_single_sentence_paragraph(text)

    print("分析对话风格...")
    dialogue_style_metrics = analyze_dialogue_style(text)

    print("分析句子开头模式...")
    opening_metrics = analyze_sentence_openings(text)

    print("分析章末钩子画像...")
    ending_metrics = analyze_chapter_endings(text)

    # 合并所有指标
    all_metrics = {
        "basic": {
            "total_chars": len(text),
            "total_lines": len(text.split('\n'))
        },
        "sentence": sentence_metrics,
        "paragraph": paragraph_metrics,
        "single_sentence_paragraph": single_para_metrics,
        "punctuation": punctuation_metrics,
        "dialogue": dialogue_metrics,
        "dialogue_style": dialogue_style_metrics,
        "lexical_fingerprint": lexical_metrics,
        "sentence_openings": opening_metrics,
        "high_freq_words": high_freq_words,
        "chapters": chapter_metrics,
        "chapter_endings": ending_metrics,
        "system_panels": panel_metrics,
        "author_notes": author_notes,
        "ellipsis": ellipsis_metrics
    }
    
    # 输出到文件
    output_path = os.path.join(output_dir, "style_metrics.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_metrics, f, ensure_ascii=False, indent=2)
    
    print(f"分析完成，结果保存到: {output_path}")

    # 顺手生成人能读的报告 md(一劳永逸:覆盖旧的手写版)
    report_md = render_report_md(all_metrics)
    report_path = os.path.join(output_dir, "全量统计报告.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_md)
    print(f"报告已生成: {report_path}")
    
    # 打印关键指标摘要
    print("\n=== 关键指标摘要 ===")
    print(f"句长: mean={sentence_metrics.get('mean', 'N/A')}, std={sentence_metrics.get('std', 'N/A')}, p90={sentence_metrics.get('p90', 'N/A')}")
    print(f"段落: mean={paragraph_metrics.get('mean', 'N/A')}, 单句成段占比={paragraph_metrics.get('single_sentence_ratio', 'N/A')}%")
    print(f"对话占比: {dialogue_metrics.get('char_ratio', 'N/A')}%")
    print(f"章节数: {chapter_metrics.get('total_chapters', 'N/A')}")
    print(f"系统面板数: {panel_metrics.get('count', 'N/A')}")
    print(f"作者旁白数: {author_notes.get('count', 'N/A')}")
    print(f"单句成段占比: {single_para_metrics.get('single_sentence_ratio_percent', 'N/A')}%")
    print(f"感官分布: {lexical_metrics.get('sense_ratio_percent', {})}")
    print(f"看类动词偏好: {lexical_metrics.get('verb_preference', {}).get('看类', {})}")
    print(f"对话纯引号占比: {dialogue_style_metrics.get('pure_quote_ratio_percent','N/A')}%, 带动作尾巴: {dialogue_style_metrics.get('with_action_tail_ratio_percent','N/A')}%")
    print(f"章末短句收尾占比: {ending_metrics.get('short_ending_ratio_percent','N/A')}%, 悬念词收尾: {ending_metrics.get('suspense_word_ending_ratio_percent','N/A')}%")

if __name__ == "__main__":
    main()
