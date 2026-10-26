"""Screenshot helper for rooms. Stdlib plus Playwright only.

Usage:
  .venv/bin/python3 tools/shot.py <slug> [seconds] [width] [height]

The script starts a local HTTP server on the repository root, opens the room,
clicks the entry overlay, waits, and saves a PNG to tools/screenshots/<slug>.png.
It also prints every console error that the page emits.
"""
import os, subprocess, sys, time, socket
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
slug = sys.argv[1]
wait = float(sys.argv[2]) if len(sys.argv) > 2 else 6
width = int(sys.argv[3]) if len(sys.argv) > 3 else 1400
height = int(sys.argv[4]) if len(sys.argv) > 4 else 900

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

port = free_port()
srv = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(0.8)
try:
    from playwright.sync_api import sync_playwright
    out = ROOT / "tools" / "screenshots"; out.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": width, "height": height})
        errors = []
        pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text}") if m.type in ("error", "warning") else None)
        pg.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))
        url = f"http://127.0.0.1:{port}/rooms/{slug}/index.html" if slug != "index" else f"http://127.0.0.1:{port}/index.html"
        pg.goto(url, wait_until="load", timeout=60000)
        pg.wait_for_timeout(1500)
        btn = pg.query_selector(".g-overlay")
        if btn:
            btn.click()
        pg.wait_for_timeout(int(wait * 1000))
        pg.screenshot(path=str(out / f"{slug}.png"))
        print("saved", out / f"{slug}.png")
        for e in errors: print(e)
        b.close()
finally:
    srv.terminate()
