#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_scan.py —— 内容审查的机械扫描（P4.5 第一步）。

只查"能用程序判定的错误"，把需要判断的留给盲解。检查项：

  ① LaTeX 结构（硬失败）：`$$` 成对、行内 `$` 成对、\\left/\\right 配对、
     数学环境里花括号配对、\\begin{env}/\\end{env} 配对
  ② 详解每题是否给出「答案」（默认提示，--strict 时硬失败）
  ③ 禁词：显然 / 易得 / 不难看出 / 由已知可得（默认提示）
  ④ 「同型」引用是否含年份与题号（默认提示）
  ⑤ 是否存在 审查报告.md（默认提示，--strict 时硬失败）

用法：
  python3 audit_scan.py [目录]          # 默认当前目录（通常是 <工作区>/ai_study）
  python3 audit_scan.py [目录] --strict  # 交付用：②③④⑤ 全部升级为硬失败
  python3 audit_scan.py [目录] --json

退出码：有硬失败 → 1；无 → 0；目录不存在 → 2
"""
import argparse
import json
import re
import sys
from pathlib import Path

TARGETS = ["知识点讲解*.md", "习题集*.md", "*详解*.md", "复习路线*.md", "审查报告*.md"]
BANNED = ["显然", "易得", "不难看出", "由已知可得", "综上易知"]
ANSWER_HINT = re.compile(r"答案[：:]|得证|证毕|结论[：:]")

# \left 家族里属于箭头/箭头的，不算配对符
LEFT = re.compile(r"\\left(?!arrow|rightarrow|leftrightarrow|rightharpoonup|rightharpoondown)")
RIGHT = re.compile(r"\\right(?!arrow|rightarrow|leftrightarrow|leftharpoonup|rightharpoondown)")
ENV = re.compile(r"\\(begin|end)\{([^}]*)\}")


def mask_code(text):
    """屏蔽围栏代码块与行内代码（保留行号与长度），避免 $VAR 之类被当成公式。"""
    out, fence = [], None
    for line in text.split("\n"):
        s = line.strip()
        if fence is None and (s.startswith("```") or s.startswith("~~~")):
            fence = s[:3]; out.append(""); continue
        if fence is not None:
            if s.startswith(fence):
                fence = None
            out.append(""); continue
        out.append(line)
    joined = "\n".join(out)
    # 行内代码 `...` 同样屏蔽（保留长度，行号与位置不变）
    return re.sub(r"`[^`\n]*`", lambda m: " " * len(m.group(0)), joined)


def strip_block_math(text):
    """去掉 $$...$$ 块，便于单独数行内 $。"""
    return re.sub(r"\$\$.*?\$\$", "", text, flags=re.S)


def math_spans(text):
    """→ 所有数学片段（块级 + 行内），用于查括号与 left/right。"""
    spans = [(m.start(), m.group(0)) for m in re.finditer(r"\$\$.*?\$\$", text, re.S)]
    rest = strip_block_math(text)
    spans += [(m.start(), m.group(0)) for m in re.finditer(r"(?<!\$)\$(?!\$)[^$\n]+\$(?!\$)", rest)]
    return spans


def brace_balance(span):
    """数学片段里的花括号差（忽略 \\{ \\}）。"""
    s = re.sub(r"\\[{}]", "", span)
    return s.count("{") - s.count("}")


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


def scan_file(p):
    text = mask_code(p.read_text(encoding="utf-8", errors="replace"))
    hard, soft = [], []

    # ① LaTeX 结构
    if text.count("$$") % 2:
        hard.append(f"第 {text.count(chr(10), 0, text.rfind('$$')) + 1} 行附近 `$$` 未成对"
                    f"（全文 {text.count('$$')} 个）")
    inline = strip_block_math(text).count("$")
    if inline % 2:
        soft.append(f"行内 `$` 未成对（去掉块级公式后 {inline} 个）")
    n_left, n_right = len(LEFT.findall(text)), len(RIGHT.findall(text))
    if n_left != n_right:
        hard.append(f"\\left {n_left} 个 / \\right {n_right} 个，不配对")
    for pos, span in math_spans(text):
        d = brace_balance(span)
        if d:
            hard.append(f"第 {line_of(text, pos)} 行公式花括号{'多' if d > 0 else '少'} {abs(d)} 个：{span[:40]}")
            break
    envs = {}
    for kind, name in ENV.findall(text):
        envs.setdefault(name, {"begin": 0, "end": 0})[kind] += 1
    for name, c in envs.items():
        if c["begin"] != c["end"]:
            hard.append(f"环境 {name}：begin {c['begin']} / end {c['end']} 不配对")

    # ③ 禁词
    for w in BANNED:
        for m in re.finditer(w, text):
            soft.append(f"第 {line_of(text, m.start())} 行出现禁词「{w}」")

    # ④ 同型引用格式
    for m in re.finditer(r"同型[：:]\s*([^\n）)；;]{1,40})", text):
        ref = m.group(1)
        has_year = bool(re.search(r"\d{2}\s*[-–—]\s*\d{2}|\d{4}|\b(19|20)\d{2}\b", ref))
        has_num = bool(re.search(r"选择|填空|解答|综合|证明|判断|第\s*\d+|\d+\s*题|[一二三四五六七八九十]+\s*[.．、]?\s*\d+", ref))
        if not (has_year and has_num):
            soft.append(f"第 {line_of(text, m.start())} 行「同型：{ref.strip()}」缺年份或题号")

    return hard, soft


def scan_solutions(files):
    """② 详解每题是否有答案。题号形如 **1.**；题号每天重新编号，按最近的 Day 标题归属。"""
    hard, soft, total, missing = [], [], 0, []
    for p in files:
        text = mask_code(p.read_text(encoding="utf-8", errors="replace"))
        heads = [(m.start(), int(m.group(1) or m.group(2)))
                 for m in re.finditer(r"^#{1,4}\s*.*?(?:Day\s*(\d+)|第\s*(\d+)\s*天)", text, re.M)]
        marks = [(m.start(), m.group(1)) for m in re.finditer(r"^\s*\*\*(\d+)[.．]\*\*", text, re.M)]
        total += len(marks)
        miss_here = []
        for i, (pos, num) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            if ANSWER_HINT.search(text[pos:end]):
                continue
            day = next((d for hp, d in reversed(heads) if hp < pos), None)
            miss_here.append(f"Day{day} #{num}" if day else f"#{num}")
        if miss_here:
            missing += [f"{p.name} {x}" for x in miss_here]
            soft.append(f"{p.name}：{len(miss_here)}/{len(marks)} 道题没有「答案/结论」")
    return hard, soft, total, missing


def main():
    ap = argparse.ArgumentParser(description="内容审查机械扫描：LaTeX 结构、答案完整、禁词、同型引用、审查报告。")
    ap.add_argument("dir", nargs="?", default=".", help="工作区目录（通常 ai_study），默认当前目录")
    ap.add_argument("--strict", action="store_true", help="交付用：提示项一律升级为硬失败")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.dir).resolve()
    if not root.is_dir():
        print(f"❌ 目录不存在：{root}", file=sys.stderr)
        return 2
    files = sorted({p for pat in TARGETS for p in root.glob(pat) if p.is_file()})
    sols = [p for p in files if "详解" in p.name]
    if not files:
        hint = ""
        if list(root.glob("*.md")):
            hint = ("\n   这个目录里有 .md 但没有讲解/习题/详解/路线——看起来是 markdown/ 转写稿目录。\n"
                    "   转写稿请用 pdf_prepare.py 处理；audit_scan.py 审的是 ai_study/ 下的产出。")
        print(f"❌ 在 {root} 里找不到任何待审产物（{'、'.join(TARGETS)}）{hint}", file=sys.stderr)
        return 2

    res = {"dir": str(root), "files": [str(p) for p in files], "hard": [], "soft": [], "strict": args.strict}

    for p in files:
        h, s = scan_file(p)
        res["hard"] += [f"{p.name}: {x}" for x in h]
        res["soft"] += [f"{p.name}: {x}" for x in s]

    total, missing = 0, []
    if sols:
        h, s, total, missing = scan_solutions(sols)
        res["soft"] += s
        res["solutions_total"], res["solutions_missing"] = total, len(missing)
    report = next((p for p in root.glob("审查报告*.md")), None)
    if report is None:
        res["soft"].append("缺少 审查报告.md（内容未审，或报告没落盘）")

    res["ok"] = not res["hard"] and (not args.strict or not res["soft"])
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"\n🔍 内容机械扫描：{root}")
        print(f"   待审文件 {len(files)} 个" + (f"｜详解题 {total} 道" if total else ""))
        if res["hard"]:
            print("\n❌ 硬错误（必须修）：")
            for x in res["hard"]:
                print(f"   - {x}")
        else:
            print("\n✅ LaTeX 结构无硬错误")
        if res["soft"]:
            print(f"\n💡 提示（{len(res['soft'])} 条{'，--strict 下算失败' if not args.strict else ''}）：")
            for x in res["soft"][:40]:
                print(f"   - {x}")
            if len(res["soft"]) > 40:
                print(f"   … 还有 {len(res['soft']) - 40} 条")
        if missing:
            print(f"\n   无答案的题：{'、'.join(missing[:15])}" + ("…" if len(missing) > 15 else ""))
        print()
        print("✅ 机械扫描通过" if res["ok"] else "❌ 未通过：修完再进入盲解审查")
        if res["ok"]:
            print("   ↳ 下一步：按 references/audit.md 做盲解复核（机械扫描不能替代盲解）")
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
