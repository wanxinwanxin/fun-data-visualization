#!/usr/bin/env bash
# Copy the rooms, the shared helper, and the registry into the personal website.
# The website keeps its own gallery/index.html, so this script does not touch it.
set -euo pipefail
SRC="$(cd "$(dirname "$0")/.." && pwd)"
DST="${1:-$HOME/Github/wanxinwanxin.github.io/gallery}"
mkdir -p "$DST"
rsync -a --delete --exclude '.DS_Store' "$SRC/rooms/" "$DST/rooms/"
rsync -a "$SRC/shared/" "$DST/shared/"
cp "$SRC/rooms.json" "$DST/rooms.json"
echo "synced to $DST"
du -sh "$DST"
