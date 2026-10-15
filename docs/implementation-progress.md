# Hushlight implementation progress

Compact evidence and rulings for the approved MVP. No commits, staging,
pushes, installs, dependency changes, desktop edits, or live capture were
performed.

## Environment

- Python 3.14.7 (`/usr/bin/python3`), stdlib only. `pytest`, `ruff`, and
  `coverage` are not installed, so tests use `unittest` and coverage uses the
  stdlib `trace` module.
- Read-only tools used: `pw-dump`, `inotifywait`, `fuser`, `qmllint`,
  `qmlformat`, `omarchy plugin validate`.
- Installed Omarchy APIs inspected: `Commons/Color.qml` (`Color.bar.text`,
  `Color.bar.active`), `Ui/BarWidget.qml`, `Ui/BarIconButton.qml`,
  `Ui/WidgetButton.qml`, `services/PluginRegistry.qml` (manifest validation),
  and existing bar widgets (`SystemUpdate`, `Microphone`).

## Rulings

- Followed `HANDOFF.md`: no proof-of-privacy claims, no settings/popup, theme
  roles over a hardcoded palette, conservative unknown handling.
- Added `backend/status.py` beyond the plan's file list: a tiny shared status
  constructor and layering helper used by all three classifiers. Keeps the
  "positive wins over a gap, limitations preserved" rule in one place.
- `qmlformat --normalize` from the plan does not exist in this build and
  reformats to four spaces; kept the house two-space style used by installed
  widgets instead (tooling consistency). `qmlformat` still parsed the file.
- No orchestration subagents: the plan's `executing-plans` wrappers require
  commits, which are forbidden on the unborn/feature branch. Evidence is
  recorded here instead.
- Camera device-holder identity is an opaque internal token and is never
  emitted, satisfying "no PID or raw device metadata".
- Debounce is leading-edge bounded (at most one reconcile per second, plus a
  5 s discovery fallback), not trailing-only, so a reconcile is not starved by
  a continuous event storm.

## Task evidence

Task 1 (classifier): `tests/test_pipewire.py`. Covers playback-only,
suspended hardware, ALSA microphone, sink/`.monitor` capture, portal screen
capture, `v4l2` camera capture, ambiguous virtual routing, concurrent streams,
positive-wins-over-gap, no mutation, removals, id reuse, split/multiple arrays,
brackets in strings, malformed/oversized decoding, numeric-string `client.id`
owner resolution, and info-level link endpoint fields.

Task 2 (camera + lifecycle): `tests/test_camera.py` and
`tests/test_runtime.py`. Covers sustained-holder activation, short-probe
suppression, last-holder clearing, unavailable lookups as unknown, missing-tool
handling, PipeWire disconnect/malformed-output reset with bounded backoff,
watcher loss and hotplug recovery, event-storm rate limiting, fixed argv
without a shell, process-group cleanup and reap escalation, parent-death signal
setup (unit and real-subprocess), startup-exception cleanup, partial-batch
unknown handling, non-default debounce propagation, and the `fuser`/glob
adapters.

Task 3 (widget + delivery): `tests/test_runtime.py` schema/merge tests cover
output shape, startup unknown, backend failure, and direct-access wording.
`manifest.json` validates; `Widget.qml` passes `qmllint`.

77 tests total.

## Correction pass (review findings)

1. `client.id` routing now normalizes through `_as_int`, so int, numeric-string,
   or missing values all resolve safely; regressions added for numeric-string
   owners and info-level link fields. Real local `pw-dump` shows `client.id` as
   `int`.
2. Owned children set `PR_SET_PDEATHSIG` (SIGTERM) with a fork/ppid race check,
   including the short-lived `fuser` lookup. A real-subprocess test SIGKILLs an
   isolated backend parent and proves its owned child exits (zombie-aware
   liveness via `/proc/<pid>/stat`). Startup writes/reconcile moved inside the
   `try/finally`, with a failing startup test proving children are closed.
3. Icons use `String.fromCodePoint` for supplementary-plane codepoints; a
   `Grid` sizes one row horizontally and one column vertically for up to three
   simultaneous icons; `validSnapshot` accepts only the three known states.
4. Tooltip now shows per-indicator evidence (e.g. "Camera device accessed"),
   renders `unobserved` as "not observed", and appends deduplicated
   limitations, so it never reduces a device backend to "PipeWire only".
5. README coverage matrix limits camera attribution to `device.api: v4l2` and
   the installed Hyprland portal, and lists libcamera as unknown.
6. `Backend` passes its injected debounce to `camera_status`; regression added
   with a non-default value.
7. Documented the one-backend-per-widget (per-monitor) process model in the
   README instead of adding singleton complexity.
8. `graph_bytes` only marks the graph available once a complete array arrives;
   a partial-initial-bytes regression keeps the state `unknown`.

## Checks run

```text
python3 -m unittest discover -s tests -v
  Ran 77 tests ... OK
  (includes a real-subprocess PR_SET_PDEATHSIG test: SIGKILL the backend
   parent, its owned child exits)

python3 -m compileall -q backend tests
  clean

python3 -m trace --count --summary --missing \
  --coverdir /tmp/opencode/hushlight-coverage --ignore-dir /usr/lib \
  --module unittest discover -s tests
  camera   100.0%
  pipewire  91.5%
  runtime   94.9%
  status    97.8%
  backend total 94%    (main.py is the entry point; exercised by the live smoke run)

omarchy plugin validate .
  exit 0

qmllint -I <qs-import-dir> -I /usr/lib/qt6/qml Widget.qml
  exit 0, no diagnostics

qmlformat Widget.qml
  exit 0 (parses); output discarded, house two-space style kept

python3 backend/main.py (4 s, read-only), then SIGTERM
  emitted unknown -> unobserved; no pw-dump/inotifywait children left behind
```

## Explicitly unverified (needs a live shell and separate approval)

- Camera probe false positives under real browser previews.
- System-audio loopback classification and camera `v4l2` capture.
- Concurrent sessions and crashed-application behavior.
- Theme switching and plugin unload in the running bar.
