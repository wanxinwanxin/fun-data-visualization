#!/usr/bin/env bash
# Build the publish directory for the claude.ai artifact.
# The artifact host serves only standard web file types, so each binary data file
# also gets a base64 text copy named <file>.b64.txt. shared/room.js decodes it.
# Usage: tools/artifact/build.sh [out_dir]   (default: build/artifact)
set -euo pipefail
SRC="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$SRC/build/artifact}"
rm -rf "$OUT"; mkdir -p "$OUT"
rsync -a --exclude '.DS_Store' "$SRC/rooms/" "$OUT/rooms/"
rsync -a "$SRC/shared/" "$OUT/shared/"
cp "$SRC/rooms.json" "$OUT/rooms.json"
cp "$SRC/tools/artifact/hub.html" "$OUT/index.html"
# Text types stay as they are. Everything else gets a .b64.txt copy.
find "$OUT/rooms" -type f ! \( -name '*.json' -o -name '*.csv' -o -name '*.tsv' -o -name '*.txt' \
  -o -name '*.svg' -o -name '*.html' -o -name '*.js' -o -name '*.css' -o -name '*.md' -o -name '*.geojson' \) \
  -print0 | while IFS= read -r -d '' f; do base64 -w0 "$f" > "$f.b64.txt"; echo "b64 $f"; done
echo "built $OUT"; du -sh "$OUT"
