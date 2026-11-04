#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdf_prepare.py —— 真题 PDF 入库（P1）。
  probe   体检：页数 / 文本层 / 每页字符数 / 推荐路线（text | vision）
  extract 入库：有文本层 → <out>/<stem>.md；扫描件 → <out>/_pages/<stem>-pNN.png
  例：python3 pdf_prepare.py probe 卷子.pdf --json
      python3 pdf_prepare.py extract 卷子.pdf --out markdown
依赖 python3 标准库 + markitdown（抽文本）+ swift（Xcode CLT 自带，逐页渲染）。
不需要 pdftotext/pdftoppm/mutool/qpdf/tesseract/libreoffice；sips/qlmanage 只能出第 1 页。
"""
import argparse, hashlib, json, os, re, shutil, subprocess, sys, tempfile
from pathlib import Path

MIN_TEXT_TOTAL = 200   # 全文少于该字符数：无可用文本层
MIN_TEXT_AVG = 40      # 页均低于该值：判为扫描件
SPARSE_PAGE = 15       # 单页低于该值：该页无文字层，需视觉补读
DENSE_PAGE = 400       # 单页低于该值：公式/图密集，须加 --with-pages 校对公式（与 delivery.md 同口径）
DEFAULT_DPI = 160      # 落在 150–200 之间
SWIFT_SRC = r'''// Swift 助手：info 报每页字符数，render 逐页渲染 PNG（CoreGraphics/PDFKit）
import Foundation
import CoreGraphics
import ImageIO
import PDFKit
let a = CommandLine.arguments
guard let doc = PDFDocument(url: URL(fileURLWithPath: a[2])) else { exit(3) }
if a[1] == "info" {
    var c: [Int] = []; for i in 0..<doc.pageCount { c.append((doc.page(at: i)?.string ?? "").count) }
    print("{\"pages\":\(doc.pageCount),\"chars\":[\(c.map { String($0) }.joined(separator: ","))]}")
} else {
    let dir = URL(fileURLWithPath: a[3]), pre = a[4], s = (Double(a[5]) ?? 160.0) / 72.0
    guard let cg = CGPDFDocument(URL(fileURLWithPath: a[2]) as CFURL) else { exit(3) }
    for i in 1...cg.numberOfPages {
        guard let pg = cg.page(at: i) else { continue }
        let b = pg.getBoxRect(.mediaBox), w = Int((b.width * s).rounded()), h = Int((b.height * s).rounded())
        guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { continue }
        ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1)); ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
        ctx.saveGState()
        ctx.scaleBy(x: s, y: s)
        ctx.translateBy(x: -b.origin.x, y: -b.origin.y)
        ctx.drawPDFPage(pg)
        ctx.restoreGState()
        let out = dir.appendingPathComponent(String(format: "%@-p%02d.png", pre, i))
        guard let img = ctx.makeImage(), let d = CGImageDestinationCreateWithURL(out as CFURL, "public.png" as CFString, 1, nil) else { continue }
        CGImageDestinationAddImage(d, img, nil); CGImageDestinationFinalize(d); print("\(out.path)\t\(w)x\(h)")
    }
}
'''

class PdfError(Exception): pass  # 可直接展示给用户的硬错误

_swift = None  # 已落盘的 Swift 源码路径

def swift_run(*args):
    """调用 Swift 助手（源码首次使用时落到临时文件）。返回 (成功?, 输出)。"""
    global _swift
    if not shutil.which("swift"):
        return False, "缺少 swift 命令（逐页渲染需 Xcode Command Line Tools：xcode-select --install）"
    if _swift is None:
        fd, _swift = tempfile.mkstemp(suffix=".swift", prefix="pdfprep_")
        os.write(fd, SWIFT_SRC.encode()); os.close(fd)
    r = subprocess.run(["swift", _swift, *args], capture_output=True, text=True, timeout=300)
    return r.returncode == 0, (r.stdout if r.returncode == 0 else (r.stderr.strip() or "swift 执行失败"))

def page_info(pdf):
    """→ (页数, 每页字符数 或 None, 引擎名)。Swift 不可用时退回读 PDF 结构拿页数。"""
    ok, out = swift_run("info", str(pdf))
    if ok:
        try:
            d = json.loads(out.strip().splitlines()[-1]); return d["pages"], d["chars"], "pdfkit"
        except Exception:
            pass
    raw = Path(pdf).read_bytes()                                   # 兜底：扫结构
    m = re.search(rb"/Type\s*/Pages[^>]*?/Count\s+(\d+)", raw) or re.search(rb"/Count\s+(\d+)", raw)
    return (int(m.group(1)) if m else (len(re.findall(rb"/Type\s*/Page[^s]", raw)) or None)), None, "regex"

def markitdown_text(pdf):
    if not shutil.which("markitdown"):
        raise PdfError("找不到 markitdown 命令；它是本 skill 抽取文本层的唯一依赖，请先安装。")
    r = subprocess.run(["markitdown", str(pdf)], capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise PdfError(f"markitdown 抽取失败：{(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout

# Adobe Symbol 字体私有区（PUA）字形解码：标记位 → 真实字符
SYMBOL = dict(zip(range(0x20, 0x7F), map(chr, range(0x20, 0x7F))))   # Symbol 的 ASCII 段原样
# 高位：Symbol 字体的数学符号表（码位 → 字符）
_HI = (0xA2,0xA3,0xA4,0xA5,0xAB,0xAC,0xAD,0xAE,0xAF,0xB0,0xB1,0xB2,0xB3,0xB4,0xB5,0xB6,0xB7,0xB8,0xB9,0xBA,0xBB,0xBC,0xBE,
       0xC6,0xC7,0xC8,0xC9,0xCA,0xCB,0xCC,0xCD,0xCE,0xCF,0xD0,0xD1,0xD5,0xD6,0xD7,0xD8,0xDB,0xDE,0xE6,0xE7,0xE8,
       0xE9,0xEA,0xEB,0xEC,0xED,0xEE,0xEF,0xF2,0xF5,0xF6,0xF7,0xF8,0xF9,0xFA,0xFB,0xFC,0xFD,0xFE)
_CH = "′≤⁄∞↔←↑→↓°±″≥×∝∂•÷≠≡≈…—∅∩∪⊃⊇⊄⊂⊆∈∉∠∇∏√⋅¬⇔⇒⎛⎜⎝⎡⎢⎣⎧⎨⎩⎪∫∫⎞⎟⎠⎤⎥⎦⎫⎬⎭"
SYMBOL.update(dict(zip(_HI, _CH)))

MATH_FUNC = r"(?:lim|sin|cos|tan|cot|sec|csc|arcsin|arccos|arctan|ln|log|exp|max|min)"
SIDEBAR = "姓名学号班级学院专业线订装得分密封题"

def decode_pua(text):
    """PUA 字形 → 真实符号；返回 (文本, 未解码个数)。"""
    out, unknown = [], 0
    for ch in text:
        cp = ord(ch)
        if 0xF020 <= cp <= 0xF0FF:
            v = SYMBOL.get(cp - 0xF000)
            out.append(v) if v else None
            unknown += 0 if v else 1
        elif 0xE000 <= cp <= 0xF8FF:
            unknown += 1
        else:
            out.append(ch)
    return "".join(out), unknown

def clean_markdown(raw):
    """markitdown 输出 → 可读正文：拆退化表格、解字形、归一空白、剔除装订线栏字。"""
    lines = []
    for ln in raw.split("\n"):
        s = ln.strip()
        if not s:
            lines.append("") if lines and lines[-1] else None
            continue
        if s.startswith("|"):                       # markitdown 把版式识别成了逐行表格
            s = " ".join(c.strip() for c in s.strip("|").split("|") if c.strip() and not re.fullmatch(r"[-: ]+", c.strip()))
            if not s:
                continue
        s = re.sub(r"^[%s]\s+" % SIDEBAR, "", s)    # 竖排装订线单字（"姓 f(x)" → "f(x)"）
        if not s or re.fullmatch(r"[%s：:（）()。、,，]" % SIDEBAR, s) or re.fullmatch(r"\d+", s):
            continue
        lines.append(s)
    t, unknown = decode_pua("\n".join(lines))
    t = re.sub(r"[ \t\u3000]{2,}", " ", t)
    t = re.sub(r"(?<=[\u4e00-\u9fff]) (?=[\u4e00-\u9fff])", "", t)  # 中文之间不留空格
    t = re.sub(r" +([\)\]\}])", r"\1", re.sub(r"([\(\[\{]) +", r"\1", t))     # ( x ) → (x)
    t = re.sub(r" +(?=[，。；：、！？])", "", t)
    t = re.sub(r"\b(?:[A-Za-z] ){2,}[A-Za-z]\b", lambda m: m.group(0).replace(" ", ""), t)
    t = re.sub(r"\b" + MATH_FUNC + r"(?=[a-z(])", lambda m: m.group(0) + " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return re.sub(r"[ \t]+$", "", t, flags=re.M).strip(), unknown

def render_pages(pdf, outdir, prefix, dpi):
    """逐页渲染 PNG，返回 [(绝对路径, 尺寸)]。"""
    outdir.mkdir(parents=True, exist_ok=True)
    ok, out = swift_run("render", str(Path(pdf).resolve()), str(outdir.resolve()), prefix, str(dpi))
    if not ok:
        raise PdfError(f"逐页渲染失败：{out[-400:]}")
    got = [(str(Path(p).resolve()), s) for ln in out.splitlines() if "\t" in ln for p, s in [ln.rsplit("\t", 1)]]
    if not got:
        raise PdfError("渲染没有产出任何页面图：请确认该 PDF 未加密、未损坏。")
    # 防呆：渲染器静默出空白页时，所有页面图会完全同哈希。宁可报错，也不要让视觉转写去读白纸。
    if len(got) > 1:
        hs = {hashlib.md5(Path(p).read_bytes()).hexdigest() for p, _ in got}
        if len(hs) == 1:
            raise PdfError(f"{len(got)} 页渲染结果完全相同（疑似空白页）：请检查 PDF 是否为纯图形/加密文件，"
                           "或改用 sips/qlmanage 单页导出后人工核对。")
    return got

def probe_one(pdf):
    """单份 PDF 体检 → dict。"""
    pdf = Path(pdf)
    if not pdf.is_file(): raise PdfError(f"文件不存在：{pdf}")
    pages, chars, engine = page_info(pdf)
    if not pages:
        raise PdfError(f"读不出页数（PDF 可能加密或损坏）：{pdf.name}")
    warn = []
    if chars is None:                               # swift 不可用：只能按 markdown 全文估
        total, sparse = len(markitdown_text(pdf)), []
        warn.append("swift 不可用：每页字符数无法测量，总量按 markdown 全文字符估算。")
    else:
        total, sparse = sum(chars), [i + 1 for i, c in enumerate(chars) if c < SPARSE_PAGE]
    avg = round(total / pages, 1)
    if total < MIN_TEXT_TOTAL or avg < MIN_TEXT_AVG:
        route, scanned, sparse = "vision", True, list(range(1, pages + 1))
        verdict = "无文本层（疑似扫描件）：必须走视觉转写，extract 会逐页渲染 PNG。"
        warn.append("文本层字符数过低，markitdown 会产出近乎空文件——不要走 text 路线。")
    else:
        route, scanned = "text", False
        dense = [i + 1 for i, c in enumerate(chars) if c < DENSE_PAGE] if chars else []
        verdict = "文本层可用；公式/图为主的科目仍须加 --with-pages，公式以页面图为准。"
        if dense:
            warn.append(f"第 {'、'.join(map(str, dense))} 页每页字符数 <{DENSE_PAGE}（多为公式/图）："
                        f"不加 --with-pages 会把公式抽成散架文本，数学/物理/化学卷必踩。")
        if sparse:
            warn.append(f"第 {'、'.join(map(str, sparse))} 页几乎无文字：extract 会额外渲染这几页供视觉补读。")
        if not dense and not sparse:
            warn.append("本卷字符密度正常；若题干公式多，仍建议加 --with-pages 抽查一页。")
    return {"file": str(pdf.resolve()), "name": pdf.name, "ok": True, "pages": pages,
            "has_text_layer": route == "text", "chars_per_page": chars, "total_chars": total, "avg_chars_per_page": avg,
            "scanned_suspect": scanned, "sparse_pages": sparse, "route": route, "engine": engine,
            "verdict": verdict, "warnings": warn}

def cmd_probe(args):
    results, failed = [], False
    for f in args.files:
        try:
            results.append(probe_one(f))
        except PdfError as e:
            failed = True; results.append({"file": str(f), "ok": False, "error": str(e)})
    if args.json:
        print(json.dumps({"ok": not failed, "files": results}, ensure_ascii=False, indent=2))
        return 1 if failed else 0
    for r in results:
        print(f"\n📄 {r.get('name', r['file'])}")
        if not r.get("ok"):
            print(f"   ❌ {r['error']}"); continue
        per = ("   每页字符：" + "  ".join(f"p{i+1}={c}" for i, c in enumerate(r["chars_per_page"]))) if r["chars_per_page"] else "   每页字符：未测出（swift 不可用）"
        print(f"   页数 {r['pages']}｜文本层 {'有' if r['has_text_layer'] else '无'}"
              f"｜总字符 {r['total_chars']}｜页均 {r['avg_chars_per_page']}\n{per}")
        print(f"   疑似扫描件：{'是' if r['scanned_suspect'] else '否'}｜推荐路线：{r['route']}")
        print(f"   结论：{r['verdict']}")
        print("".join(f"   ⚠️  {w}\n" for w in r["warnings"]), end="")
    return 1 if failed else 0

def _report(out, args):
    """打印人读结果或 JSON；返回退出码。"""
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=2)); return 0
    if out["route"] == "vision":
        print(f"🖼  {out['stem']}：无文本层，已渲染 {len(out['images'])} 页（{out['dpi']}dpi），请用视觉逐页转写：")
        print("\n".join(f"   {i['path']}  ({i['size']})" for i in out["images"]))
        print(f"\n👉 转写结果写到：{out['md_target']}\n   公式拿不准就保留原文并标「⚠️公式降级」，禁止凭猜测写 LaTeX。"); return 0
    print(f"✅ {out['markdown']}  （{out['chars']} 字，{out['pages']} 页，路线 text）")
    print("".join(f"   ⚠️  {w}\n" for w in out["warnings"]), end="")
    print(*[f"   补充页面图：{i['path']}  ({i['size']})" for i in out["images"]], sep="\n", end=""); return 0

def cmd_extract(args):
    pdf = Path(args.file)
    if not pdf.is_file():
        raise PdfError(f"文件不存在：{pdf}")
    outdir, stem = Path(args.out).resolve(), pdf.stem
    info = probe_one(pdf)
    out = {"file": str(pdf.resolve()), "route": info["route"], "pages": info["pages"], "stem": stem,
           "dpi": args.dpi, "markdown": None, "images": [], "md_target": str(outdir / f"{stem}.md"), "warnings": info["warnings"]}
    if info["route"] == "vision":
        out["images"] = [{"path": p, "size": z} for p, z in render_pages(pdf, outdir / "_pages", stem, args.dpi)]
        return _report(out, args)
    text, unknown = clean_markdown(markitdown_text(pdf))
    if len(text) < MIN_TEXT_TOTAL:
        raise PdfError(f"{pdf.name}：清洗后只剩 {len(text)} 字，疑似扫描件却判成了文本层；"
                       "请确认 PDF 是否被截断，或直接按扫描件走视觉转写。")
    outdir.mkdir(parents=True, exist_ok=True); md = outdir / f"{stem}.md"
    head = [f"<!-- source: {pdf.resolve()} | pages: {info['pages']} | extractor: markitdown -->", f"# {stem}", "",
            "> 提取自 PDF 文本层，已做空白归一与符号解码，**未重排为 LaTeX**；公式若跨行错位，以原文为准。"]
    if unknown:
        head.append(f"> ⚠️ 有 {unknown} 个字形无法解码（已丢弃），该处公式请核对页图。")
    md.write_text("\n".join(head) + "\n\n" + text + "\n", encoding="utf-8")
    out.update(markdown=str(md), chars=len(text))
    if info["sparse_pages"] or getattr(args, "with_pages", False):
        out["images"] = [{"path": p, "size": z} for p, z in render_pages(pdf, outdir / "_pages", stem, args.dpi)]
        if info["sparse_pages"]:
            out["warnings"].append(f"第 {info['sparse_pages']} 页无文本层，已附带页面图。")
        else:
            out["warnings"].append("已按 --with-pages 渲染全部页面图：公式以页面图为准，文本层只用于核对题号与文字。")
    return _report(out, args)

def main():
    ap = argparse.ArgumentParser(description="真题 PDF 入库：判定文本层/扫描件，抽 markdown 或渲染逐页 PNG。")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="体检：页数/文本层/每页字符数/推荐路线")
    p.add_argument("files", nargs="+", help="一个或多个 PDF")
    p.add_argument("--json", action="store_true", help="输出机读 JSON")
    e = sub.add_parser("extract", help="入库：有文本层→markdown；扫描件→逐页 PNG")
    e.add_argument("file", help="PDF 路径")
    e.add_argument("--out", required=True, help="输出目录（通常为工作区的 markdown/）")
    e.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"渲染分辨率，默认 {DEFAULT_DPI}")
    e.add_argument("--with-pages", action="store_true",
                   help="text 路线也渲染全部页面图；公式密集卷（数学/物理）必须加，用来校对公式")
    e.add_argument("--json", action="store_true", help="输出机读 JSON")
    args = ap.parse_args()
    try:
        sys.exit(cmd_probe(args) if args.cmd == "probe" else cmd_extract(args))
    except PdfError as exc:
        print(f"❌ {exc}", file=sys.stderr); sys.exit(2)

if __name__ == "__main__":
    main()  # 入口
