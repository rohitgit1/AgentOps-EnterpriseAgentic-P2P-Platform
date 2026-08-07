#!/usr/bin/env bash
# Rebuild the developer walkthrough (PDF + PPTX) from a live capture.
#
# The screenshots are taken from the running application, so the deliverables
# are only as current as the demo they were captured from. Re-run this after a
# UI change and the documents update with it.
#
#   ./scripts/walkthrough/build.sh                 # capture, then build both
#   ./scripts/walkthrough/build.sh --no-capture    # rebuild from existing shots
#
# Requires the application running on :8000 and `playwright` + `pptxgenjs`
# resolvable by node. On a machine with a system Chromium, point
# CHROMIUM_PATH at it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUILD="$ROOT/build/walkthrough"
OUT="$ROOT/docs/walkthrough"
PY="${PY:-$ROOT/.venv/bin/python}"

mkdir -p "$BUILD/shots" "$BUILD/img" "$OUT"
export WALKTHROUGH_SHOTS="$BUILD/shots" WALKTHROUGH_IMG="$BUILD/img"
export WALKTHROUGH_BUILD="$BUILD" WALKTHROUGH_OUT="$OUT"

if [[ "${1:-}" != "--no-capture" ]]; then
  echo "▸ staging demo data (runs agents, approves as the qualified persona)"
  "$PY" "$ROOT/scripts/walkthrough/populate.py"

  echo "▸ capturing screens"
  node "$ROOT/scripts/walkthrough/capture.mjs"
fi

echo "▸ optimising screenshots"
"$PY" - <<PYEOF
from PIL import Image
from pathlib import Path
src, dst = Path("$BUILD/shots"), Path("$BUILD/img")
for f in dst.glob("*.jpg"): f.unlink()
total = 0
for f in sorted(src.glob("*.png")):
    im = Image.open(f).convert("RGB")
    im = im.resize((1800, round(im.height * 1800 / im.width)), Image.LANCZOS)
    out = dst / (f.stem + ".jpg")
    im.save(out, quality=88, optimize=True, progressive=True)
    total += out.stat().st_size
print(f"  {len(list(dst.glob('*.jpg')))} images, {total/1e6:.1f} MB")
PYEOF

echo "▸ building the deck"
node "$ROOT/scripts/walkthrough/deck.js" "$OUT/AgentOps-Developer-Walkthrough.pptx"

echo "▸ building the PDF"
node "$ROOT/scripts/walkthrough/pdf.js" "$BUILD/walkthrough.html" >/dev/null
node "$ROOT/scripts/walkthrough/print.mjs"

echo "▸ QA"
"$PY" "$ROOT/scripts/walkthrough/qa.py" "$OUT/AgentOps-Developer-Walkthrough.pptx"

ls -lh "$OUT"
