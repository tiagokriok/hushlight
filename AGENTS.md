# AGENTS.md

## What this is

Hushlight is an Omarchy bar-widget plugin: `Widget.qml` (QML) + `backend/` (Python, stdlib only). Installed by cloning into `~/.config/omarchy/plugins/hushlight.privacy/` and enabling it. No build step, no install hooks, no network, no root.

## Verification commands

```bash
python3 -m unittest discover -s tests -v    # 77 tests, fakes only, no real capture
python3 -m compileall -q backend tests
omarchy plugin validate .
qmllint -I <qs-import-dir> -I /usr/lib/qt6/qml Widget.qml
```

- No `ruff`, `pytest`, or `coverage` installed. Use stdlib `unittest` and `trace` (`--ignore-dir /usr/lib`); backend line coverage should stay ≥80%.
- `qmlformat` on this system has no `--normalize` flag and reformats to 4-space indent; the repo uses 2-space. Run it parse-only (exit code) and discard its output.
- QML 2-space style matches installed `/usr/share/omarchy/shell` widgets.

## Landmines

- **Privacy semantics are the contract.** `unobserved` never means "nothing is recording" — only "nothing observed on supported paths". Direct camera access is "Camera device accessed", never "recording"/"streaming". See `docs/capture-research.md` for verified-vs-unverified paths.
- **Never edit `/usr/share/omarchy/`** — read-only, owned by the omarchy package. Work in this repo; copy into `~/.config/omarchy/plugins/hushlight.privacy/` only with explicit user approval, and never run `omarchy plugin clone` for reference (it switches the user's active widget).
- **Never commit, push, install, enable, or modify desktop config without explicit user authorization.** User asked for live testing only after review.
- **Child process cleanup matters.** `pw-dump`/`inotifywait` children must be killed via process group + `PR_SET_PDEATHSIG`; abrupt unload (QProcess kill → SIGKILL) otherwise orphans them. Keep the real-subprocess pdeathsig regression test green.
- **Omarchy already shows recording in the bar.** The widget marks microphone and camera only. Do not re-add a recording icon without user request.
- `pw-dump -m` emits successive JSON arrays, including `{id, info:null}` removals. Decoder must be string-aware, bounded, and treat partial arrays as unknown until complete. `client.id` may be int or numeric string depending on path.

## Layout

- `Widget.qml` — bar widget, theme colors from `Color.bar.*`, launches backend
- `backend/` — `pipewire.py` (graph classify), `camera.py` (fuser debounce), `runtime.py` (subprocess lifecycle), `status.py` (merge semantics), `main.py` (entry)
- `tests/` — stdlib unittest, fake subprocesses; no real capture in tests
- `docs/capture-research.md` — what was actually verified live on this machine
