# Data Art Galleries

A gallery of animated, sonified visualizations of public data. If `HANDOFF.md` exists, read it first. It is a local session note with the current state and the open tasks. Git ignores it.

## Conventions

- Each room is one public data set in `rooms/<slug>/` with `index.html`, `preview.svg`, `README.md`, and `data/`. The pipeline for the room is in `pipelines/<slug>/`. `rooms.json` is the registry that the hub reads.
- Each room has its own visual language and its own sound design. Do not reuse one template with different data.
- Use real data only. Each room README documents the source, the sampling rule, and the sound mapping.
- Run Python with the venv: `.venv/bin/python3 -I <script>`. Raw downloads go to `data/raw/`, which git ignores.
- Take screenshots with `tools/shot.py <slug>` to check a room before you commit it.
- Commit small, focused changes. Stage files by name. Commit messages are one imperative sentence.

## Publishing

- Personal website: run `tools/sync_site.sh`, then commit and push `~/Github/wanxinwanxin.github.io`. The website keeps its own `gallery/index.html`.
- claude.ai artifact: run `tools/artifact/build.sh`, then publish `build/artifact/index.html` with the other files in `build/artifact/` as the `files` map (`root` = `build/artifact`). The hub source is `tools/artifact/hub.html`.
