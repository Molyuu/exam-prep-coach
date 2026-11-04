#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_coverage.py —— 学习工作区交付自检（P5）。

  python3 check_coverage.py [目录]            # 默认当前目录（通常是 <工作区>/ai_study）
  python3 check_coverage.py --dir <目录> --json

五项检查（①–④ 硬失败，⑤ 只告警）：
  ① 习题集每个 **N.** 在详解里有对应 **N.**（反向孤儿详解只告警）
  ② 复习路线 S/A 级每个编号条目，其关键词能在知识点讲解与习题集里找到；**S/A 级小节存在但 0 条目 = 硬失败**
  ③ 知识点讲解 / 习题集 / 详解 的 Day 分节一一对应
  ④ markdown/ 原始卷子存在且非空（目录不存在则跳过）
  ⑤ 五件产物齐全：错题表.md、AGENTS.md（缺了只提示，不判失败）
硬失败 exit 1，全通过 exit 0；有提示但硬项全过也 exit 0，只是收工语会变成"需人工确认"。
  加 --strict：② 之外的提示项（含 ⑤ 三件产物与审查报告）全部升级为硬失败，交付前建议用它跑一遍。
"""
import argparse
import json
import re
import sys
from pathlib import Path

GENERIC = {"极限", "求导", "证明", "公式", "计算", "函数", "分类", "定理", "方法", "系数", "题型",
           "技巧", "步骤", "性质", "概念", "应用", "与", "和", "型", "类"}


def find(root, patterns, exclude=()):
    """按通配找唯一产物文件；多个命中时取名字最短（最具体）的那个并提示。"""
    hits = sorted({p for pat in patterns for p in root.glob(pat)
                   if p.is_file() and not any(re.search(e, p.name) for e in exclude)},
                  key=lambda p: (len(p.name), p.name))
    return hits


def parse_days(text):
    """→ {day_number}，识别 "## Day 3：..." 与 "# 第 3 天：..."。"""
    days = set()
    for m in re.finditer(r"^#{1,4}\s*.*?(?:Day\s*(\d+)|第\s*(\d+)\s*天)", text, re.M):
        days.add(int(m.group(1) or m.group(2)))
    return days


def parse_numbers(text):
    """→ {(day, num)}：题号每天重新从 1 编号，必须连 Day 一起比对。"""
    cur, out = None, set()
    for line in text.split("\n"):
        m = re.match(r"^#{1,4}\s*.*?(?:Day\s*(\d+)|第\s*(\d+)\s*天)", line)
        if m:
            cur = int(m.group(1) or m.group(2)); continue
        m = re.match(r"^\s*\*\*(\d+)[.．、]\*\*", line)
        if m:
            out.add((cur, int(m.group(1))))
    return out


def fmt_nums(items):
    """{(day,num)} → 可读清单。"""
    return "、".join(f"Day{d} #{n}" if d else f"未分节 #{n}" for d, n in sorted(items, key=lambda x: (x[0] or 0, x[1])))


def sa_entries(route):
    """→ [(级别, 编号, 标题)]，只取 S 级 / A 级小节下的编号条目。"""
    entries = []
    for sec in re.finditer(r"^#{2,4}\s*([SA])\s*级.*?$(.*?)(?=^#{1,4}\s|\Z)", route, re.M | re.S):
        grade, body = sec.group(1), sec.group(2)
        found = re.findall(r"^\s*(\d+)[.．]\s*\*\*(.+?)\*\*", body, re.M)   # 条目必须带 **标题**
        found = found or re.findall(r"^(\d+)[.．]\s*(\S.*)$", body, re.M)      # 无加粗时退回顶格条目
        entries += [(grade, int(n), t.strip()) for n, t in found]
    return entries


def sa_section_counts(route):
    """→ {级别: (可解析条目数, 是否有正文)}。

    区分两种"没内容"：
      - 空壳小节（只有标题、正文也没有）→ 硬失败，多半是照模板复制后忘了填；
      - 有正文但解析不到编号条目（比如改成了无序列表）→ 只提示，属格式问题。
    """
    out = {}
    for sec in re.finditer(r"^#{2,4}\s*([SAB])\s*级.*?$(.*?)(?=^#{1,4}\s|\Z)", route, re.M | re.S):
        body = sec.group(2)
        found = (re.findall(r"^\s*(\d+)[.．]\s*\*\*(.+?)\*\*", body, re.M)
                 or re.findall(r"^(\d+)[.．]\s*(\S.*)$", body, re.M))
        has_text = any(ln.strip() and not ln.lstrip().startswith("#") for ln in body.split("\n"))
        g = sec.group(1)
        n, txt = out.get(g, (0, False))
        out[g] = (n + len(found), txt or has_text)
    return out


def terms_of(title):
    """标题 → 核心词表；去括注、去引号、拆并列、剔通用词。"""
    t = re.sub(r"[（(][^）)]*[）)]|[“”\"'「」]", "", title)
    terms = []
    for part in re.split(r"[与和、，,：:/\s]+", t):
        part = part.strip(" 　*·-—")
        if len(part) >= 2 and part not in GENERIC:
            terms.append(part)
    return terms or [t]


def loose_hit(title, text):
    """宽松匹配：先整词，再逐级缩短前缀（最短 2 字），返回命中的词。"""
    for term in terms_of(title):
        if term in text:
            return term
        for n in range(len(term) - 1, 1, -1):
            if term[:n] in text:
                return term[:n]
    return None


def check(root):
    res = {"dir": str(root), "artifacts": {}, "checks": [], "missing": [], "warnings": []}
    route_f = find(root, ["复习路线*.md", "*路线*.md"])
    lecture_f = find(root, ["知识点讲解*.md", "*讲解*.md"])
    exer_f = find(root, ["习题集*.md", "*习题*.md"], exclude=[r"详解"])
    sol_f = find(root, ["*详解*.md", "*详解*.markdown"])
    for key, hits, name in (("route", route_f, "复习路线"), ("lecture", lecture_f, "知识点讲解"),
                            ("exercise", exer_f, "习题集"), ("solution", sol_f, "详解")):
        if not hits:
            res["artifacts"][key] = None
            res["missing"].append(f"缺少产物：{name}（匹配模式见 README）")
        else:
            res["artifacts"][key] = str(hits[0])
            if len(hits) > 1:
                res["warnings"].append(f"{name} 有 {len(hits)} 个候选，已取 {hits[0].name}")
    texts = {k: Path(v).read_text(encoding="utf-8", errors="replace") if v else ""
             for k, v in res["artifacts"].items()}

    def add(name, ok, detail, hard=True):
        res["checks"].append({"name": name, "ok": ok, "detail": detail, "hard": hard})

    # ① 题号 ↔ 详解
    ex_nums, sol_nums = parse_numbers(texts["exercise"]), parse_numbers(texts["solution"])
    if not ex_nums:
        add("① 习题集→详解 编号对应", False, "习题集里找不到 **N.** 题号（格式应为 **1.** 独占一行）")
    elif not sol_nums:
        add("① 习题集→详解 编号对应", False, "详解里找不到 **N.** 题号")
    else:
        lost, orphan = sorted(ex_nums - sol_nums), sorted(sol_nums - ex_nums)
        add("① 习题集→详解 编号对应", not lost,
            f"{len(ex_nums & sol_nums)}/{len(ex_nums)} 题号在详解中有对应（题号按 Day 归属比对）"
            + (f"；缺详解：{fmt_nums(lost)}" if lost else "")
            + (f"；孤儿详解：{fmt_nums(orphan)}" if orphan else ""))
        if lost:
            res["missing"].append(f"详解缺失题号：{fmt_nums(lost)}")
        if orphan:
            res["warnings"].append(f"孤儿详解（习题集无此题）：{fmt_nums(orphan)}")

    # ② S/A 级考点覆盖（含「小节写了却一条没填」检测）
    counts = sa_section_counts(texts["route"])
    empty = [g for g in ("S", "A") if g in counts and counts[g][0] == 0 and not counts[g][1]]
    unparsed = [g for g in ("S", "A") if g in counts and counts[g][0] == 0 and counts[g][1]]
    entries = sa_entries(texts["route"])
    if empty:
        add("② S/A 考点覆盖（讲解/习题）", False,
            f"{'、'.join(g + ' 级' for g in empty)} 小节只有标题、一条都没填（多半是照模板复制后忘了填）")
        res["missing"].append(f"S/A 级空壳小节：{'、'.join(g + ' 级' for g in empty)}")
    elif not entries:
        if unparsed:
            add("② S/A 考点覆盖（讲解/习题）", True,
                f"{'、'.join(g + ' 级' for g in unparsed)} 小节有内容但解析不到编号条目，"
                f"无法核对覆盖（格式建议用 `1. **考点名**`）", hard=False)
            res["warnings"].append(f"S/A 小节格式无法解析：{'、'.join(g + ' 级' for g in unparsed)}")
        else:
            add("② S/A 考点覆盖（讲解/习题）", False, "复习路线里找不到 S 级/A 级小节及其编号条目")
    else:
        miss_lec, miss_ex, miss_sol, only_one = [], [], [], []
        for grade, num, title in entries:
            hl, he, hs = (loose_hit(title, texts["lecture"]), loose_hit(title, texts["exercise"]),
                          loose_hit(title, texts["solution"]))
            rec = {"grade": grade, "num": num, "title": title,
                   "lecture": hl, "exercise": he, "solution": hs}
            res.setdefault("entries", []).append(rec)
            if not hl:
                miss_lec.append(f"{grade}{num} {title}")
            if not he:
                miss_ex.append(f"{grade}{num} {title}")
            if not hs:
                miss_sol.append(f"{grade}{num} {title}")
            if hl and not he or he and not hl:
                only_one.append(f"{grade}{num} {title}")
        bad = miss_lec + miss_ex
        add("② S/A 考点覆盖（讲解/习题）", not bad,
            f"{len(entries) - len(set(miss_lec) | set(miss_ex))}/{len(entries)} 个 S/A 条目在讲解与习题集均有命中")
        if bad:
            res["missing"].append("讲解缺：" + "、".join(miss_lec) if miss_lec else "")
            res["missing"].append("习题集缺：" + "、".join(miss_ex) if miss_ex else "")
        if miss_sol:
            res["warnings"].append(
                f"详解正文里没直接出现这些考点名（由 ① 的题号对应保证覆盖，仅提示）：{'、'.join(miss_sol)}")
        if only_one:
            res["warnings"].append(f"只在讲解或只在习题集出现：{'、'.join(only_one)}")
        if unparsed:
            res["warnings"].append(
                f"{'、'.join(g + ' 级' for g in unparsed)} 小节有内容但解析不到编号条目，未参与覆盖核对"
                f"（建议统一写成 `1. **考点名**`）")

    # ③ Day 分节一一对应
    d_lec, d_ex, d_sol = (parse_days(texts["lecture"]), parse_days(texts["exercise"]),
                          parse_days(texts["solution"]))
    sets = {"讲解": d_lec, "习题集": d_ex, "详解": d_sol}
    if not any(sets.values()):
        add("③ Day 分节一一对应", False, "三份产物的标题里都没有 Day N / 第 N 天 分节")
    else:
        same = d_lec == d_ex == d_sol
        fmt = lambda s: "{" + ",".join(map(str, sorted(s))) + "}"
        add("③ Day 分节一一对应", same,
            " ".join(f"{k}{fmt(v)}" for k, v in sets.items()))
        if not same:
            res["missing"].append("三份产物的 Day 集合不一致：" +
                                  " ".join(f"{k}{fmt(v)}" for k, v in sets.items()))
    plan = parse_days(texts["route"])
    res["warnings"].append(f"复习路线含 {len(plan)} 个日程分节（第 N 天），作为计划文件不参与 ③ 的强一致比较"
                           if plan else "复习路线里没找到「第 N 天」日程分节")

    # ④ markdown/ 原始卷子
    cands = [root / "markdown", root.parent / "markdown"]
    md_dir = next((c for c in cands if c.is_dir()), None)
    if md_dir is None:
        add("④ markdown/ 原始卷子", True, "未发现 markdown/ 目录，跳过", hard=False)
    else:
        papers = [p for p in md_dir.glob("*.md") if p.is_file()]
        empty = [p.name for p in papers if p.stat().st_size < 50]
        ok = bool(papers) and not empty
        add("④ markdown/ 原始卷子", ok,
            f"{md_dir}：{len(papers)} 份" + (f"；空/过短：{empty}" if empty else "，均非空"))
        if not papers:
            res["missing"].append(f"{md_dir} 里没有任何 .md 转写稿")
        if empty:
            res["missing"].append(f"markdown 转写稿为空或过短：{empty}")

    # ⑤ 五件产物齐全（只提示，不判失败：老工作区常常没建错题表）
    for pat, label in (("错题表.md", "错题表"), ("AGENTS.md", "AGENTS.md 写作约定"),
                       ("审查报告*.md", "审查报告（内容审查结论）")):
        cands = [p for p in list(root.glob(pat)) + list(root.parent.glob(pat)) if p.is_file()]
        add(f"⑤ {label}", bool(cands), str(cands[0]) if cands else
            f"未找到 {pat}（建议补齐；交付前应存在，--strict 下判失败）", hard=False)

    res["ok"] = all(c["ok"] for c in res["checks"] if c["hard"])
    return res


def render(res):
    w = max(len(c["name"]) for c in res["checks"]) + 2
    print(f"\n📂 交付自检：{res['dir']}")
    for c in res["checks"]:
        print(f"  [{'PASS' if c['ok'] else ('FAIL' if c['hard'] else 'WARN')}] "
              f"{c['name']:<{w}}{c['detail']}")
    if res["missing"]:
        print("\n❌ 缺失清单：")
        for m in [m for m in res["missing"] if m]:
            print(f"   - {m}")
    if res["warnings"]:
        print("\n💡 提示：")
        for w_ in res["warnings"]:
            print(f"   - {w_}")
    if not res["ok"]:
        print("\n❌ 有硬性缺失，补齐后重跑。")
    elif res["warnings"]:
        print(f"\n✅ 硬项全过，但还有 {len(res['warnings'])} 条提示：请人工确认后再交付（别直接宣布收工）。")
    else:
        print("\n✅ 全部通过：交付完整，可以收工。")


def main():
    ap = argparse.ArgumentParser(description="学习工作区交付自检：产物齐全、题号对应、考点覆盖、Day 对齐。")
    ap.add_argument("dir", nargs="?", help="工作区目录，默认当前目录（通常是 ai_study）")
    ap.add_argument("--dir", dest="dir_opt", help="同上（等价写法）")
    ap.add_argument("--strict", action="store_true", help="交付用：提示项（含审查报告）全部升级为硬失败")
    ap.add_argument("--json", action="store_true", help="输出机读 JSON")
    args = ap.parse_args()
    root = Path(args.dir_opt or args.dir or ".").resolve()
    if not root.is_dir():
        print(f"❌ 目录不存在：{root}", file=sys.stderr)
        return 2
    res = check(root)
    if args.strict:
        for c in res["checks"]:
            c["hard"] = True
        res["ok"] = all(c["ok"] for c in res["checks"])
        res["strict"] = True
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        render(res)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
