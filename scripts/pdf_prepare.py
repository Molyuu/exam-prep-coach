#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pdf_prepare.py —— 真题 PDF 入库（P1）：逐页渲染 PNG，交给 agent 读图转写。

  python3 pdf_prepare.py <PDF...> --out markdown/ [--dpi 160] [--json]

  → <out>/_pages/<stem>-pNN.png（每页一张），并打印转写目标 <out>/<stem>.md。
  不抽文本层：PDF 文本层的公式、上下标、分式基本必错，Symbol 字体还会把希腊字母解成拉丁字母。
  一律以页面图为准，由 agent 逐页看图转写。

依赖：python3 标准库 + macOS 自带的 swiftc/swift（Xcode Command Line Tools）。
退出码：0 全部成功；1 部分 PDF 失败；2 参数/环境错误。
"""
import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_DPI = 160      # A4 → 约 1323×1871，够看清上下标；更大 agent 读图时也会被缩回去
MAX_SIDE = 4000        # 单边像素上限，防止 A3/海报类大页面渲染出巨图
TIMEOUT = 600

SWIFT_SRC = r'''// 逐页渲染 PDF → PNG（CoreGraphics），正确处理 /Rotate 与 cropBox。
// 用法：render <pdf> <outdir> <prefix> <dpi> <maxSide>
// 输出：每页一行 "<路径>\t<宽>x<高>"；退出码 3=打不开 4=加密
import Foundation
import CoreGraphics
import ImageIO

let a = CommandLine.arguments
guard a.count == 6, let cg = CGPDFDocument(URL(fileURLWithPath: a[1]) as CFURL) else { exit(3) }
if cg.isEncrypted && !cg.unlockWithPassword("") { exit(4) }
let dir = URL(fileURLWithPath: a[2]), pre = a[3]
let dpi = Double(a[4]) ?? 160.0, maxSide = Double(a[5]) ?? 4000.0
for i in 1...max(cg.numberOfPages, 1) {
    guard i <= cg.numberOfPages, let pg = cg.page(at: i) else { continue }
    let b = pg.getBoxRect(.cropBox)
    let rot = ((Int(pg.rotationAngle) % 360) + 360) % 360
    let pw = (rot == 90 || rot == 270) ? b.height : b.width
    let ph = (rot == 90 || rot == 270) ? b.width : b.height
    let s = min(dpi / 72.0, maxSide / max(pw, ph))
    let w = Int((pw * s).rounded()), h = Int((ph * s).rounded())
    guard w > 0, h > 0, let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8, bytesPerRow: 0,
        space: CGColorSpaceCreateDeviceRGB(), bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue) else { continue }
    ctx.setFillColor(CGColor(red: 1, green: 1, blue: 1, alpha: 1))
    ctx.fill(CGRect(x: 0, y: 0, width: w, height: h))
    ctx.scaleBy(x: s, y: s)
    switch rot {   // /Rotate 是显示时顺时针旋转
    case 90:  ctx.translateBy(x: 0, y: b.width);        ctx.rotate(by: -.pi / 2)
    case 180: ctx.translateBy(x: b.width, y: b.height); ctx.rotate(by: .pi)
    case 270: ctx.translateBy(x: b.height, y: 0);       ctx.rotate(by: .pi / 2)
    default: break
    }
    ctx.translateBy(x: -b.origin.x, y: -b.origin.y)
    ctx.clip(to: b)
    ctx.drawPDFPage(pg)
    let out = dir.appendingPathComponent(String(format: "%@-p%02d.png", pre, i))
    guard let img = ctx.makeImage(),
          let d = CGImageDestinationCreateWithURL(out as CFURL, "public.png" as CFString, 1, nil) else { continue }
    CGImageDestinationAddImage(d, img, nil)
    if CGImageDestinationFinalize(d) { print("\(out.path)\t\(w)x\(h)") }
}
'''


class PdfError(Exception):
    """可直接展示给用户的错误。"""


def renderer():
    """→ 调用渲染器的命令前缀。优先用 swiftc 编译一次并缓存，失败再退回 swift 解释执行。"""
    tag = hashlib.sha1(SWIFT_SRC.encode()).hexdigest()[:12]
    cache = Path.home() / "Library" / "Caches" / "exam-prep-coach"
    binary = cache / f"pdfrender-{tag}"
    if binary.is_file():
        return [str(binary)]
    src = Path(tempfile.gettempdir()) / f"pdfrender-{tag}.swift"
    src.write_text(SWIFT_SRC, encoding="utf-8")
    if shutil.which("swiftc"):
        cache.mkdir(parents=True, exist_ok=True)
        tmp = binary.with_suffix(".tmp")
        r = subprocess.run(["swiftc", "-O", str(src), "-o", str(tmp)], capture_output=True, text=True)
        if r.returncode == 0:
            tmp.replace(binary)
            return [str(binary)]
    if shutil.which("swift"):
        return ["swift", str(src)]
    raise PdfError("缺少 swiftc/swift：逐页渲染需要 Xcode Command Line Tools（xcode-select --install）")


def render(pdf, outdir, dpi):
    """单份 PDF → {file, stem, pages, images:[{path,size}], md_target}。"""
    pdf = Path(pdf)
    if not pdf.is_file():
        raise PdfError(f"文件不存在：{pdf}")
    if pdf.suffix.lower() != ".pdf":
        raise PdfError(f"不是 PDF：{pdf.name}（图片可以直接读图转写，不需要本脚本）")
    stem, pages_dir = pdf.stem, outdir / "_pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    for old in pages_dir.glob(f"{stem}-p*.png"):      # 清掉旧渲染，避免页数变少后残留
        old.unlink()
    cmd = renderer() + [str(pdf.resolve()), str(pages_dir.resolve()), stem, str(dpi), str(MAX_SIDE)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT)
    except subprocess.TimeoutExpired:
        raise PdfError(f"{pdf.name}：渲染超时（>{TIMEOUT}s），试试降低 --dpi")
    if r.returncode == 3:
        raise PdfError(f"{pdf.name}：打不开，PDF 可能已损坏")
    if r.returncode == 4:
        raise PdfError(f"{pdf.name}：PDF 有打开密码，请先解密")
    if r.returncode:
        raise PdfError(f"{pdf.name}：渲染失败：{(r.stderr or r.stdout).strip()[-400:]}")
    images = [{"path": p, "size": s} for ln in r.stdout.splitlines() if "\t" in ln
              for p, s in [ln.rsplit("\t", 1)]]
    if not images:
        raise PdfError(f"{pdf.name}：没有渲染出任何页面")
    # 防呆：渲染器静默出白纸时所有页面完全同哈希；宁可报错，也别让 agent 去"转写"白纸。
    if len(images) > 1 and len({hashlib.md5(Path(i["path"]).read_bytes()).hexdigest() for i in images}) == 1:
        raise PdfError(f"{pdf.name}：{len(images)} 页渲染结果完全相同（疑似空白），请人工打开 PDF 核对")
    return {"file": str(pdf.resolve()), "stem": stem, "pages": len(images), "images": images,
            "md_target": str(outdir / f"{stem}.md")}


def main():
    ap = argparse.ArgumentParser(description="真题 PDF 入库：逐页渲染 PNG，供 agent 读图转写。")
    ap.add_argument("files", nargs="+", help="一个或多个 PDF")
    ap.add_argument("--out", required=True, help="输出目录（通常为工作区的 markdown/）")
    ap.add_argument("--dpi", type=int, default=DEFAULT_DPI, help=f"渲染分辨率，默认 {DEFAULT_DPI}（建议 150–200）")
    ap.add_argument("--json", action="store_true", help="输出机读 JSON")
    args = ap.parse_args()
    if not 50 <= args.dpi <= 600:
        print("❌ --dpi 应在 50–600 之间", file=sys.stderr)
        return 2
    outdir = Path(args.out).resolve()

    results, failed = [], False
    for f in args.files:
        try:
            results.append({"ok": True, **render(f, outdir, args.dpi)})
        except PdfError as e:
            if "swift" in str(e):                       # 环境问题，后面的也必然失败
                print(f"❌ {e}", file=sys.stderr)
                return 2
            failed = True
            results.append({"ok": False, "file": str(f), "error": str(e)})

    if args.json:
        print(json.dumps({"ok": not failed, "dpi": args.dpi, "files": results}, ensure_ascii=False, indent=2))
        return 1 if failed else 0
    for r in results:
        if not r["ok"]:
            print(f"\n❌ {r['error']}")
            continue
        print(f"\n🖼  {r['stem']}：{r['pages']} 页（{args.dpi}dpi）")
        for i in r["images"]:
            print(f"   {i['path']}  ({i['size']})")
        print(f"   👉 逐页读图转写到：{r['md_target']}")
    if any(r["ok"] for r in results):
        print("\n转写要求见 references/delivery.md §4：先转 1 页核对质量再批量；"
              "公式看不清就标「（?）」，禁止猜写。")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
