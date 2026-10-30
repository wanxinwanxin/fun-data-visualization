# Data Art Galleries

A gallery of animated and sonified visualizations. Each room uses one public data set. Each room has its own visual style and its own sound design.

## Layout

- `index.html` is the gallery hub. It reads `rooms.json`.
- `rooms/<slug>/` holds one room: `index.html`, `preview.svg`, `README.md`, and `data/` with processed files.
- `pipelines/<slug>/` holds the Python scripts that fetch and process the data for that room.
- `shared/room.js` gives each room the entry overlay, the navigation chip, and the sound toggle.
- `tools/shot.py` opens a room in headless Chromium and saves a screenshot.
- `data/raw/` holds raw downloads. Git ignores this directory.
- Room 14 (`treasury-machine`) rebuilds two scanned Census tables with OCR. Its README lists the extra steps and the manual corrections.

## Run

Start a local server from the repository root and open the hub:

```
.venv/bin/python3 -m http.server 8000
```

Then open `http://localhost:8000/`.

## Rebuild a room's data

```
.venv/bin/python3 -I pipelines/<slug>/fetch.py
.venv/bin/python3 -I pipelines/<slug>/process.py
```

Each room README documents the source, the sampling, and the sound mapping.

## Hosting

The gallery is published as a private claude.ai artifact at https://claude.ai/artifact/PhnrPsSkxyjrD1pvvCXGrd . That host serves only standard web file types, so the publish sends each binary data file as a base64 text copy named `<file>.b64.txt`. The shared helper in `shared/room.js` loads that copy when the raw binary file is not available. Local serving uses the raw binary files.
