"""Screenshot a room while the server refuses raw binary files.

This simulates a host that serves only text and standard web types. Requests for
.bin, .i16, .i8, .u8 and .u16 files get a 404. Requests for the matching
".b64.txt" copies are served from a directory given as the second argument.

Usage:
  .venv/bin/python3 tools/shot_nobin.py <slug> <b64_dir> [seconds]
"""
import re, subprocess, sys, time, socket
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
slug = sys.argv[1]
b64_dir = Path(sys.argv[2])
wait = float(sys.argv[3]) if len(sys.argv) > 3 else 8
BIN = re.compile(r"\.(bin|i16|i8|u8|u16|f32)$", re.I)

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
        b = p.chromium.launch(args=["--use-gl=swiftshader", "--enable-webgl", "--ignore-gpu-blocklist"])
        pg = b.new_page(viewport={"width": 1400, "height": 900})
        errors, served = [], []
        pg.on("console", lambda m: errors.append(f"[{m.type}] {m.text}") if m.type in ("error",) else None)
        pg.on("pageerror", lambda e: errors.append(f"[pageerror] {e}"))

        def handle(route):
            path = route.request.url.split(f":{port}/", 1)[1].split("?")[0]
            if BIN.search(path):
                route.fulfill(status=404, body="not served")
            elif path.endswith(".b64.txt"):
                f = b64_dir / path
                served.append(path)
                route.fulfill(status=200, body=f.read_text(), content_type="text/plain")
            else:
                route.continue_()
        pg.route(f"http://127.0.0.1:{port}/**", handle)
        pg.goto(f"http://127.0.0.1:{port}/rooms/{slug}/index.html", wait_until="load", timeout=60000)
        pg.wait_for_timeout(1500)
        btn = pg.query_selector(".g-overlay")
        if btn: btn.click()
        pg.wait_for_timeout(int(wait * 1000))
        pg.screenshot(path=str(out / f"{slug}_nobin.png"))
        print("saved", out / f"{slug}_nobin.png")
        print("b64 served:", served)
        for e in errors: print(e)
        b.close()
finally:
    srv.terminate()
