"""Geometric QA on the deck: bounds, overlap, and text-fit estimation.

LibreOffice cannot render in this sandbox, so instead of eyeballing slide
images this measures the actual shape geometry the file contains and estimates
text fit from font metrics. It catches the defects a visual pass looks for —
off-slide shapes, colliding boxes, text that cannot fit its container.
"""
import sys
from pptx import Presentation
from pptx.util import Emu
from PIL import ImageFont

DECK = sys.argv[1]
W, H = 13.3, 7.5
MARGIN = 0.4

# DejaVu is metrically wider than Calibri/Cambria, so an estimate that fits
# here comfortably fits there — a conservative direction for a warning.
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

def inches(v): return 0 if v is None else Emu(v).inches

def est_lines(text, pt, width_in):
    """Rough wrapped-line count at this point size in this width."""
    if not text.strip(): return 0
    f = ImageFont.truetype(FONT, max(6, int(pt * 4)))   # 4x for resolution
    px_per_in = 96.0 * 4 * (pt / 72.0) / (pt / 72.0)     # measure in font px
    avail = width_in * 96 * 4                            # same scale
    lines = 0
    for para in text.split("\n"):
        if not para.strip(): lines += 1; continue
        words, cur = para.split(), ""
        for w in words:
            trial = (cur + " " + w).strip()
            if f.getlength(trial) <= avail or not cur: cur = trial
            else: lines += 1; cur = w
        lines += 1
    return lines

prs = Presentation(DECK)
problems = []
for i, slide in enumerate(prs.slides, start=1):
    boxes = []
    for sh in slide.shapes:
        x, y = inches(sh.left), inches(sh.top)
        w, h = inches(sh.width), inches(sh.height)

        if x < -0.01 or y < -0.01 or x + w > W + 0.01 or y + h > H + 0.01:
            # Text-free decoration is allowed to bleed off the canvas.
            decorative = not (sh.has_text_frame and sh.text_frame.text.strip())
            if not decorative:
                problems.append(f"slide {i}: '{(sh.name or '')[:28]}' out of bounds "
                                f"({x:.2f},{y:.2f} {w:.2f}x{h:.2f})")

        if sh.has_text_frame and sh.text_frame.text.strip():
            txt = sh.text_frame.text
            sizes = [r.font.size.pt for p in sh.text_frame.paragraphs
                     for r in p.runs if r.font.size]
            pt = max(sizes) if sizes else 12
            n = est_lines(txt, pt, max(0.3, w - 0.1))
            need = n * pt * 1.35 / 72.0        # line height in inches
            if need > h + 0.06:
                problems.append(f"slide {i}: text may overflow — {n} lines @ {pt}pt "
                                f"needs {need:.2f}\" in {h:.2f}\"  «{txt[:52]}…»")
            boxes.append((x, y, w, h, txt[:34]))

    # Overlap between text-bearing boxes (cards are allowed to sit behind them).
    for a in range(len(boxes)):
        for b in range(a + 1, len(boxes)):
            ax, ay, aw, ah, at = boxes[a]
            bx, by, bw, bh, bt = boxes[b]
            ox = min(ax + aw, bx + bw) - max(ax, bx)
            oy = min(ay + ah, by + bh) - max(ay, by)
            if ox > 0.06 and oy > 0.06:
                problems.append(f"slide {i}: text overlap {ox:.2f}x{oy:.2f}\"  "
                                f"«{at}» / «{bt}»")

print(f"{len(prs.slides)} slides checked")
if problems:
    print(f"\n{len(problems)} issue(s):")
    for p in problems: print("  -", p)
else:
    print("no geometry or fit problems found")
